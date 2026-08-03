from __future__ import annotations

import asyncio
import html
import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

from config.logging import app_logger
from core.llm_manager import get_llm_service

from .prompts import (
    RECOMMEND_SYSTEM_PROMPT,
    build_recommend_user_prompt,
)


SOURCE_URL = "https://hk.txgj.net.cn/index?k=TlgwK3BNNG9PRk09"
SITE_BASE = "https://hk.txgj.net.cn"
SOURCE_TTL = timedelta(days=1)
QUERY_CACHE_CAPACITY = 30


@dataclass
class SourceCache:
    plans: List[Dict[str, Any]]
    fetched_at: datetime
    expires_at: datetime
    raw_html: str


class MobilePlanRecommenderService:
    def __init__(self) -> None:
        self._source_cache: Optional[SourceCache] = None
        self._query_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._source_lock = asyncio.Lock()
        self._query_lock = asyncio.Lock()

    async def get_recommendations(
        self,
        query: str,
        top_k: int = 5,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        query_norm = self._normalize_query(query)
        source_cache, source_updated = await self._get_or_refresh_source(force_refresh=force_refresh)
        cache_key = f"{query_norm}||{top_k}"

        cache_hit = False
        async with self._query_lock:
            cached = self._query_cache.get(cache_key)
            if cached is not None:
                self._query_cache.move_to_end(cache_key)
                plans = cached["plans"]
                cache_hit = True
            else:
                plans = []

        if not cache_hit:
            plans = await self._recommend_with_llm(
                query=query,
                top_k=top_k,
                plans=source_cache.plans,
            )
            if not plans:
                plans = self._fallback_recommend(query, top_k, source_cache.plans)
            async with self._query_lock:
                self._query_cache[cache_key] = {"plans": plans, "created_at": datetime.now()}
                while len(self._query_cache) > QUERY_CACHE_CAPACITY:
                    self._query_cache.popitem(last=False)

        return {
            "query": query,
            "cache_hit": cache_hit,
            "source_updated_at": source_cache.fetched_at.isoformat(),
            "source_refreshed": source_updated,
            "plans": plans[:top_k],
        }

    async def _get_or_refresh_source(self, force_refresh: bool) -> Tuple[SourceCache, bool]:
        now = datetime.now()
        cache = self._source_cache
        if cache and not force_refresh and cache.expires_at > now:
            return cache, False

        async with self._source_lock:
            now = datetime.now()
            cache = self._source_cache
            if cache and not force_refresh and cache.expires_at > now:
                return cache, False
            refreshed = await self._refresh_source()
            return refreshed, True

    async def _refresh_source(self) -> SourceCache:
        t0 = datetime.now()
        raw_html = await self._fetch_html()
        # Source extraction is parser-based to avoid LLM timeout on large HTML pages.
        extracted_plans = self._extract_plans_from_html(raw_html)
        plans = self._normalize_and_filter_plans(extracted_plans)
        if not plans:
            raise RuntimeError("暂时无法解析套餐列表")

        now = datetime.now()
        refreshed = SourceCache(
            plans=plans,
            fetched_at=now,
            expires_at=now + SOURCE_TTL,
            raw_html=raw_html,
        )
        self._source_cache = refreshed
        async with self._query_lock:
            self._query_cache.clear()
        app_logger.info(
            f"[mobile_plan_recommender] source refreshed: plans={len(plans)}, elapsed_ms={(datetime.now()-t0).total_seconds()*1000:.1f}"
        )
        return refreshed

    async def _fetch_html(self) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(SOURCE_URL)
            resp.raise_for_status()
            return resp.text

    async def _recommend_with_llm(self, query: str, top_k: int, plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        try:
            llm_service = get_llm_service()
            resp = await llm_service.generate_response_with_messages(
                system_message=RECOMMEND_SYSTEM_PROMPT,
                user_message=build_recommend_user_prompt(query, top_k, plans),
            )
            if not resp.get("success"):
                app_logger.warning(f"[mobile_plan_recommender] llm recommend failed: {resp.get('error')}")
                return []
            parsed = self._parse_json_array(resp.get("content") or "")
            normalized = []
            for item in parsed:
                plan = self._normalize_plan_item(item)
                if not plan:
                    continue
                plan["reason"] = str(item.get("reason") or "与条件匹配")
                normalized.append(plan)
            return normalized[:top_k]
        except Exception as exc:
            app_logger.warning(f"[mobile_plan_recommender] llm recommend exception: {exc}")
            return []

    def _normalize_and_filter_plans(self, plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        dedup: Dict[str, Dict[str, Any]] = {}
        for item in plans:
            plan = self._normalize_plan_item(item)
            if not plan:
                continue
            if not self._is_mobile_plan(plan):
                continue
            key = self._plan_key(plan)
            if key not in dedup:
                dedup[key] = plan
        return list(dedup.values())

    def _normalize_plan_item(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        name = str(item.get("name") or "").strip()
        description = str(item.get("description") or "").strip()
        apply_url = self._normalize_apply_url(str(item.get("apply_url") or "").strip())
        details = str(item.get("details") or "").strip()
        if not name or not apply_url:
            return None
        if not description:
            description = details[:80] if details else "暂无描述"
        if not details:
            details = "暂无详细说明"
        return {
            "name": name,
            "description": description,
            "apply_url": apply_url,
            "details": details,
        }

    def _normalize_apply_url(self, value: str) -> str:
        if not value:
            return ""
        value = html.unescape(value)
        value = urljoin(SITE_BASE, value)
        parsed = urlparse(value)
        if not parsed.query:
            return value
        q = parse_qs(parsed.query)
        uid = (q.get("uid") or [""])[0]
        pid = (q.get("pid") or [""])[0]
        if uid and pid:
            clean_query = urlencode({"uid": uid, "pid": pid})
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{clean_query}"
        return value

    def _is_mobile_plan(self, plan: Dict[str, Any]) -> bool:
        text = f"{plan.get('name', '')} {plan.get('description', '')} {plan.get('details', '')}".lower()
        reject_words = ["门锁", "摄像头", "路由", "监控", "随身wifi", "设备"]
        if any(word in text for word in reject_words):
            return False
        accept_words = ["卡", "套餐", "流量", "通话", "月租", "移动", "联通", "电信", "广电"]
        return any(word in text for word in accept_words)

    def _plan_key(self, plan: Dict[str, Any]) -> str:
        pid_match = re.search(r"[?&]pid=(\d+)", plan.get("apply_url", ""))
        if pid_match:
            return f"pid:{pid_match.group(1)}"
        return f"{plan.get('name','')}|{plan.get('description','')}"

    def _parse_json_array(self, text: str) -> List[Dict[str, Any]]:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, list) else []
        except Exception:
            match = re.search(r"\[[\s\S]*\]", cleaned)
            if not match:
                return []
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, list) else []
            except Exception:
                return []

    def _normalize_query(self, query: str) -> str:
        return re.sub(r"\s+", " ", (query or "").strip().lower())

    def _fallback_recommend(self, query: str, top_k: int, plans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        keywords = self._normalize_query(query).split(" ")
        scored: List[Tuple[int, Dict[str, Any]]] = []
        for plan in plans:
            text = f"{plan['name']} {plan['description']} {plan['details']}".lower()
            score = sum(3 for kw in keywords if kw and kw in text)
            if re.search(r"\d+", query):
                score += self._numeric_hint_score(query, text)
            scored.append((score, plan))
        scored.sort(key=lambda x: x[0], reverse=True)
        result = []
        for score, plan in scored[:top_k]:
            item = dict(plan)
            item["reason"] = "按关键词和价格流量信息匹配" if score > 0 else "默认候选"
            result.append(item)
        return result

    def _numeric_hint_score(self, query: str, text: str) -> int:
        nums = re.findall(r"\d+", query)
        score = 0
        for n in nums:
            if n in text:
                score += 2
        return score

    def _extract_plans_from_html(self, raw_html: str) -> List[Dict[str, Any]]:
        # The source HTML is often not strictly balanced; slicing by listitem-start is much
        # more robust than relying on strict nested tag closing.
        starts = [
            m.start()
            for m in re.finditer(
                r"<div[^>]*class=['\"][^'\"]*\blistitem\b[^'\"]*['\"][^>]*>",
                raw_html,
                flags=re.IGNORECASE,
            )
        ]
        if not starts:
            return self._extract_plans_from_html_regex_fallback(raw_html)

        results: List[Dict[str, Any]] = []
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(raw_html)
            card = raw_html[start:end]
            name, desc = self._extract_name_desc_from_card(card)
            href = self._extract_apply_url_from_card(card)
            details = self._extract_details_from_card(card)
            if name and href:
                results.append(
                    {
                        "name": name,
                        "description": desc,
                        "apply_url": href,
                        "details": details,
                    }
                )

        if results:
            return results
        return self._extract_plans_from_html_regex_fallback(raw_html)

    def _extract_name_desc_from_card(self, card: str) -> Tuple[str, str]:
        itemtext_match = re.search(
            r"<div[^>]*class=['\"][^'\"]*\bitemtext\b[^'\"]*['\"][^>]*>([\s\S]*?)</div>",
            card,
            flags=re.IGNORECASE,
        )
        target = itemtext_match.group(1) if itemtext_match else card[:3000]
        p_texts = [
            self._normalize_plain_text(x)
            for x in re.findall(r"<p[^>]*>([\s\S]*?)</p>", target, flags=re.IGNORECASE)
        ]
        p_texts = [t for t in p_texts if t and t not in {"分享", "办理"}]
        if not p_texts:
            return "", ""
        name = p_texts[0]
        desc = p_texts[1] if len(p_texts) > 1 else ""
        return name, desc

    def _extract_apply_url_from_card(self, card: str) -> str:
        href_match = re.search(r"href=['\"]([^'\"]*order/index[^'\"]*)['\"]", card, flags=re.IGNORECASE)
        if href_match:
            return href_match.group(1)
        onclick_match = re.search(
            r"toImg\(\s*'[^']*'\s*,\s*'([^']*order/index[^']*)'\s*\)",
            card,
            flags=re.IGNORECASE,
        )
        if onclick_match:
            return onclick_match.group(1)
        return ""

    def _extract_details_from_card(self, card: str) -> str:
        itembot_match = re.search(
            r"<div[^>]*class=['\"][^'\"]*\bitembot\b[^'\"]*['\"][^>]*>([\s\S]*?)</div>",
            card,
            flags=re.IGNORECASE,
        )
        target = itembot_match.group(1) if itembot_match else card
        details_parts = [
            self._normalize_plain_text(x)
            for x in re.findall(r"<span[^>]*>([\s\S]*?)</span>", target, flags=re.IGNORECASE)
        ]
        details_parts = [p for p in details_parts if p and p not in {"分享", "办理"}]
        return " ".join(details_parts)

    def _extract_plans_from_html_regex_fallback(self, raw_html: str) -> List[Dict[str, Any]]:
        list_blocks = re.findall(
            r"<div[^>]*class=['\"][^'\"]*\blistitem\b[^'\"]*['\"][^>]*>([\s\S]*?)</div>\s*</div>",
            raw_html,
            flags=re.IGNORECASE,
        )
        if not list_blocks:
            list_blocks = re.findall(
                r"<div[^>]*class=['\"][^'\"]*\bitemtop\b[^'\"]*['\"][^>]*>([\s\S]*?)<div[^>]*class=['\"][^'\"]*\bitembot\b[^'\"]*['\"][^>]*>([\s\S]*?)</div>",
                raw_html,
                flags=re.IGNORECASE,
            )
        results: List[Dict[str, Any]] = []
        for block in list_blocks:
            if isinstance(block, tuple):
                block = " ".join(block)
            href_match = re.search(r"href=['\"]([^'\"]*order/index[^'\"]*)['\"]", block, flags=re.IGNORECASE)
            p_texts = re.findall(r"<p[^>]*>([\s\S]*?)</p>", block, flags=re.IGNORECASE)
            details_texts = re.findall(r"<span[^>]*>([\s\S]*?)</span>", block, flags=re.IGNORECASE)
            name = self._normalize_plain_text(p_texts[0]) if p_texts else ""
            desc = self._normalize_plain_text(p_texts[1]) if len(p_texts) > 1 else ""
            details = " ".join(self._normalize_plain_text(s) for s in details_texts if self._normalize_plain_text(s))
            href = href_match.group(1) if href_match else ""
            if name and href:
                results.append(
                    {
                        "name": name,
                        "description": desc,
                        "apply_url": href,
                        "details": details,
                    }
                )
        return results

    def _normalize_plain_text(self, s: str) -> str:
        no_tag = re.sub(r"<[^>]+>", " ", s or "")
        return re.sub(r"\s+", " ", html.unescape(no_tag)).strip()


