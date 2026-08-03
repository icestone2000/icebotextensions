from __future__ import annotations

import asyncio
import json
import re
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

from config.logging import app_logger
from core.llm_manager import get_llm_service

from .prompts import CALC_SYSTEM_PROMPT, build_calc_user_prompt


QUERY_CACHE_CAPACITY = 200
TOOL_LLM_TIMEOUT_SECONDS = 90


class KingHonorBoostPriceCalcService:
    def __init__(self) -> None:
        self._query_cache: "OrderedDict[str, Dict[str, str]]" = OrderedDict()
        self._query_lock = threading.Lock()
        self._last_price_table_text = ""

    async def calculate_price(
        self,
        price_table_text: str,
        star_level_input: str,
        llm_config_id: Optional[int] = None,
    ) -> Dict[str, str]:
        price_table_norm = str(price_table_text or "").strip()
        star_level_norm = str(star_level_input or "").strip()
        cache_key = f"{price_table_norm}||{star_level_norm}"

        with self._query_lock:
            # 按需求：当价格表变化时，清空全部缓存。
            if self._last_price_table_text and self._last_price_table_text != price_table_norm:
                app_logger.info(
                    "[king_honor_boost_price_calc] price table changed, clear all cache: size=%s",
                    len(self._query_cache),
                )
                self._query_cache.clear()
            self._last_price_table_text = price_table_norm

            cached = self._query_cache.get(cache_key)
            if cached is not None:
                self._query_cache.move_to_end(cache_key)
                app_logger.info(
                    "[king_honor_boost_price_calc] cache hit: stars=%s, cache_size=%s",
                    star_level_norm,
                    len(self._query_cache),
                )
                return dict(cached)
            app_logger.info(
                "[king_honor_boost_price_calc] cache miss: stars=%s, cache_size=%s",
                star_level_norm,
                len(self._query_cache),
            )

        llm_service = get_llm_service()
        app_logger.info(
            "[king_honor_boost_price_calc] invoke llm for calc: stars=%s, llm_config_id=%s, timeout=%ss",
            star_level_norm,
            llm_config_id,
            TOOL_LLM_TIMEOUT_SECONDS,
        )
        try:
            response = await asyncio.wait_for(
                llm_service.generate_response_with_messages(
                    system_message=CALC_SYSTEM_PROMPT,
                    user_message=build_calc_user_prompt(price_table_norm, star_level_norm),
                    config_id=llm_config_id,
                ),
                timeout=TOOL_LLM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"王者代练报价工具调用LLM超时（{TOOL_LLM_TIMEOUT_SECONDS}s）"
            ) from exc
        if not response.get("success"):
            raise RuntimeError(str(response.get("error") or "LLM 调用失败"))

        content = str(response.get("content") or "").strip()
        data = self._parse_json_object(content)

        calc_process = str(data.get("calc_process") or "").strip()
        calc_result_raw = str(data.get("calc_result") or "").strip()
        if not re.fullmatch(r"\d+", calc_result_raw):
            raise ValueError("calc_result 必须是整数数字字符串")

        result = {
            "calc_process": calc_process,
            "calc_result": calc_result_raw,
        }
        with self._query_lock:
            self._query_cache[cache_key] = result
            app_logger.info(
                "[king_honor_boost_price_calc] cache store: stars=%s, cache_size=%s",
                star_level_norm,
                len(self._query_cache),
            )
            while len(self._query_cache) > QUERY_CACHE_CAPACITY:
                self._query_cache.popitem(last=False)
                app_logger.info(
                    "[king_honor_boost_price_calc] cache evict oldest: cache_size=%s",
                    len(self._query_cache),
                )
        return result

    def _parse_json_object(self, text: str) -> Dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else {}
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            raise ValueError("未解析到 JSON 对象")
        data = json.loads(match.group(0))
        if not isinstance(data, dict):
            raise ValueError("LLM 返回的 JSON 不是对象")
        return data
