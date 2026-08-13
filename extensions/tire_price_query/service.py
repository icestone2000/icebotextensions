from __future__ import annotations

import json
import math
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config.logging import app_logger
from core.extension_manager import get_extensions_base_dir

# 与《轮胎型号.xlsx》表头一致；型号列在表里叫「规格」，两种叫法都认
PRICE_TABLE_FILENAME = "轮胎型号.xlsx"
SHEET_NAME = 0  # 取第一个 sheet，避免表名被改后失效
BRAND_COLUMNS = ("品牌",)
MODEL_COLUMNS = ("规格", "型号")
NOTE_COLUMNS = ("备注",)

# 报价类型列完全由表头决定，不在代码里假定任何具体名字（可能是「A类报价」，
# 也可能被运营改成「大客户报价」「小客户报价」「批发价」）
_QUOTE_TYPE_SUFFIXES = ("报价", "价格", "价")

NO_PRICE_TEXT = "暂无报价"
DEFAULT_MAX_ROWS = 30
DEFAULT_FORMAT_TEMPLATE = "[品牌] [型号] [备注] [报价类型]：[价格]"

# 后台轮询文件 mtime 的间隔（秒）
MTIME_POLL_INTERVAL_SEC = 30.0

_PLACEHOLDER_RE = re.compile(r"\[(?:序号|品牌|型号|规格|备注|报价类型|价格)\]")
# 渲染后清理「标点前的空格」：备注等可选字段为空时，模板里的分隔空格会顶到标点前面
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+(?=[：:，,。．、；;！!？?）)】\]}])")


def get_default_price_table_path() -> str:
    return os.path.join(get_extensions_base_dir(), PRICE_TABLE_FILENAME)


def _cache_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def _to_halfwidth(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def normalize_token(value: Any) -> str:
    """归一化：去掉所有空白 → 全角转半角 → 转大写。用于型号/品牌/报价类型的宽松比较。"""
    s = str(value if value is not None else "")
    s = _to_halfwidth(s)
    s = "".join(s.split())
    return s.upper()


def _strip_quote_suffix(norm: str) -> str:
    """去掉报价类型末尾的「报价/价格/价」，让「大客户」「大客户价」都能对上「大客户报价」。"""
    for suf in _QUOTE_TYPE_SUFFIXES:
        suf_norm = normalize_token(suf)
        if norm.endswith(suf_norm) and len(norm) > len(suf_norm):
            return norm[: -len(suf_norm)]
    return norm


def _has_wildcard(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern


def _wildcard_matcher(pattern_norm: str):
    """
    把 * ? 编译成正则。不用 fnmatch.translate：它会把型号里的 [ ] 当字符组解析。
    """
    escaped = re.escape(pattern_norm).replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile(f"^{escaped}$").match


def _parse_price_cell(value: Any) -> Any:
    """
    数字 → float；非空文字（如「面议」）原样保留；空单元格 / NaN → None。
    不用 pd.to_numeric(errors="coerce") 一刀切，那样会把文字价吞掉。
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    try:
        f = float(s.replace(",", ""))
        if math.isfinite(f):
            return f
    except ValueError:
        pass
    return s


def format_price_display(price: Any) -> str:
    if price is None:
        return NO_PRICE_TEXT
    if isinstance(price, str):
        return price
    try:
        x = float(price)
    except (TypeError, ValueError):
        return NO_PRICE_TEXT
    if not math.isfinite(x):
        return NO_PRICE_TEXT
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    s = str(value).strip()
    if s.lower() in ("nan", "none"):
        return ""
    return s


def _pick_column(columns: List[str], aliases: Tuple[str, ...]) -> Optional[str]:
    norm_map = {normalize_token(c): c for c in columns}
    for alias in aliases:
        hit = norm_map.get(normalize_token(alias))
        if hit is not None:
            return hit
    return None


def format_tire_message(
    template: str,
    quotes: List[Dict[str, Any]],
    truncation_note: str = "",
) -> str:
    """
    「格式定义字符串」是**单条记录**的模板，每条报价各渲染一次，用换行拼接。
    占位符：[序号][品牌][型号]（[规格] 同义）[备注][报价类型][价格]。
    某一行若含占位符且渲染后为空（例如备注为空），整行删除，避免留下空壳文字。
    """
    tmpl = str(template or "").strip() or DEFAULT_FORMAT_TEMPLATE
    # 大模型经常把换行传成字面量 \n
    tmpl = tmpl.replace("\\n", "\n")

    blocks: List[str] = []
    for idx, q in enumerate(quotes, start=1):
        values = {
            "[序号]": str(idx),
            "[品牌]": str(q.get("brand") or ""),
            "[型号]": str(q.get("model") or ""),
            "[规格]": str(q.get("model") or ""),
            "[备注]": str(q.get("note") or ""),
            "[报价类型]": str(q.get("quote_type") or ""),
            "[价格]": str(q.get("price_display") or ""),
        }
        lines: List[str] = []
        for line in tmpl.split("\n"):
            had_placeholder = bool(_PLACEHOLDER_RE.search(line))
            rendered = line
            for key, val in values.items():
                rendered = rendered.replace(key, val)
            if had_placeholder and not rendered.strip():
                continue
            # 占位符渲染为空时不留下多余空格，也不在标点前留空
            # （模板常写成「[型号] [备注]：[价格]」，备注为空时不应出现「205/55R16 ：520」）
            rendered = re.sub(r"[ \t]{2,}", " ", rendered)
            rendered = _SPACE_BEFORE_PUNCT_RE.sub("", rendered).rstrip()
            lines.append(rendered)
        if lines:
            blocks.append("\n".join(lines))

    text = "\n".join(blocks)
    note = str(truncation_note or "").strip()
    if note:
        text = f"{text}\n{note}" if text else note
    return text


class TirePriceQueryService:
    """读入《轮胎型号.xlsx》，按品牌/型号/报价类型取价；带 mtime 缓存与后台轮询。"""

    def __init__(self, price_table_path: Optional[str] = None) -> None:
        self._path = price_table_path
        self._lock = threading.Lock()
        self._caches: Dict[str, Dict[str, Any]] = {}
        self._stop_poll = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ 路径

    def _resolve_table_path(self, price_table_filename: Optional[Any] = None) -> str:
        if self._path is not None:
            return _cache_key(str(self._path))
        base = get_extensions_base_dir()
        s = "" if price_table_filename is None else str(price_table_filename).strip()
        if not s:
            return _cache_key(os.path.join(base, PRICE_TABLE_FILENAME))
        bn = os.path.basename(s)
        if not bn or bn in (".", ".."):
            raise ValueError("无效的价格表文件名")
        return _cache_key(os.path.join(base, bn))

    # ------------------------------------------------------------ mtime 轮询

    def start_mtime_poller(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop_poll.clear()

        def _run() -> None:
            while not self._stop_poll.wait(timeout=MTIME_POLL_INTERVAL_SEC):
                try:
                    self._invalidate_if_file_changed()
                except Exception as e:
                    app_logger.warning("[tire_price_query] mtime poll error: %s", e)

        t = threading.Thread(target=_run, name="tire_price_query_mtime", daemon=True)
        t.start()
        self._poll_thread = t
        app_logger.info(
            "[tire_price_query] mtime poller started (interval=%ss)", MTIME_POLL_INTERVAL_SEC
        )

    def stop_mtime_poller(self) -> None:
        self._stop_poll.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=3.0)
            self._poll_thread = None
        app_logger.info("[tire_price_query] mtime poller stopped")

    def _invalidate_if_file_changed(self) -> None:
        with self._lock:
            keys = list(self._caches.keys())
        for key in keys:
            with self._lock:
                c = self._caches.get(key)
            if c is None:
                continue
            if not os.path.isfile(key):
                with self._lock:
                    if self._caches.get(key) is c:
                        self._caches.pop(key, None)
                app_logger.info("[tire_price_query] table missing, clearing cache: %s", key)
                continue
            st = os.stat(key)
            if c.get("mtime") != st.st_mtime or c.get("size") != st.st_size:
                with self._lock:
                    if self._caches.get(key) is c:
                        self._caches.pop(key, None)
                app_logger.info("[tire_price_query] table changed, clearing cache: %s", key)

    # ------------------------------------------------------------------ 加载

    def _load_locked(self, path: str) -> Dict[str, Any]:
        df = pd.read_excel(path, sheet_name=SHEET_NAME, engine="openpyxl")
        columns = [str(c) for c in df.columns]

        brand_col = _pick_column(columns, BRAND_COLUMNS)
        model_col = _pick_column(columns, MODEL_COLUMNS)
        note_col = _pick_column(columns, NOTE_COLUMNS)
        missing = []
        if brand_col is None:
            missing.append("/".join(BRAND_COLUMNS))
        if model_col is None:
            missing.append("/".join(MODEL_COLUMNS))
        if missing:
            raise ValueError(f"价格表缺少列: {missing}")

        # 报价类型 = 除品牌/型号/备注外，所有表头非空且非 Unnamed 的列，按表内从左到右顺序
        fixed = {brand_col, model_col}
        if note_col is not None:
            fixed.add(note_col)
        quote_columns: List[str] = []
        for c in columns:
            if c in fixed:
                continue
            name = c.strip()
            if not name or name.startswith("Unnamed:") or name.lower() == "nan":
                continue
            quote_columns.append(c)

        records: List[Dict[str, Any]] = []
        brand_order: Dict[str, int] = {}
        for pos, (_, row) in enumerate(df.iterrows()):
            model = _cell_text(row.get(model_col))
            if not model:
                continue  # 表尾常有只填品牌的空行
            brand = _cell_text(row.get(brand_col))
            note = _cell_text(row.get(note_col)) if note_col is not None else ""
            if brand not in brand_order:
                brand_order[brand] = len(brand_order)
            records.append(
                {
                    "row_index": pos,
                    "brand": brand,
                    "brand_norm": normalize_token(brand),
                    "model": model,
                    "model_norm": normalize_token(model),
                    "note": note,
                    "prices": {c: _parse_price_cell(row.get(c)) for c in quote_columns},
                }
            )

        st = os.stat(path)
        return {
            "mtime": st.st_mtime,
            "size": st.st_size,
            "records": records,
            "quote_columns": quote_columns,
            "brand_order": brand_order,
            "row_count": len(records),
        }

    def _ensure_cache(self, path: str) -> Dict[str, Any]:
        key = _cache_key(path)
        if not os.path.isfile(key):
            raise FileNotFoundError(f"未找到轮胎价格表: {key}")

        with self._lock:
            st = os.stat(key)
            c = self._caches.get(key)
            if c is not None and c.get("mtime") == st.st_mtime and c.get("size") == st.st_size:
                return c
            app_logger.info("[tire_price_query] loading table: %s", key)
            c = self._load_locked(key)
            self._caches[key] = c
            app_logger.info(
                "[tire_price_query] loaded rows=%s quote_types=%s",
                c["row_count"],
                c["quote_columns"],
            )
            return c

    # ------------------------------------------------------------------ 查询

    def list_quote_types(self, price_table_filename: Optional[Any] = None) -> List[str]:
        """供 get_description 动态列出当前表格里的报价类型（表头原文）。"""
        cache = self._ensure_cache(self._resolve_table_path(price_table_filename))
        return list(cache["quote_columns"])

    def _match_records(
        self, records: List[Dict[str, Any]], field: str, pattern: str
    ) -> Tuple[List[Dict[str, Any]], str]:
        norm = normalize_token(pattern)
        if not norm:
            return list(records), "all"
        if _has_wildcard(norm):
            m = _wildcard_matcher(norm)
            return [r for r in records if m(r[field])], "wildcard"
        hits = [r for r in records if r[field] == norm]
        if hits:
            return hits, "exact"
        return [r for r in records if norm in r[field]], "contains"

    def _match_quote_columns(self, quote_columns: List[str], pattern: str) -> List[str]:
        """输入 → 表头匹配：精确 → 去后缀精确 → 包含 → 通配符。始终按表内列顺序返回。"""
        norm = normalize_token(pattern)
        if not norm:
            return list(quote_columns)

        pairs = [(c, normalize_token(c)) for c in quote_columns]

        hits = [c for c, n in pairs if n == norm]
        if hits:
            return hits

        norm_stripped = _strip_quote_suffix(norm)
        hits = [c for c, n in pairs if _strip_quote_suffix(n) == norm_stripped]
        if hits:
            return hits

        hits = [c for c, n in pairs if norm in n or norm_stripped in _strip_quote_suffix(n)]
        if hits:
            return hits

        if _has_wildcard(norm):
            m = _wildcard_matcher(norm)
            hits = [c for c, n in pairs if m(n)]
            if hits:
                return hits
        return []

    def query(
        self,
        model: Any,
        brand: Any = None,
        quote_type: Any = None,
        max_rows: Any = None,
        price_table_filename: Optional[Any] = None,
    ) -> Dict[str, Any]:
        table_path = self._resolve_table_path(price_table_filename)
        cache = self._ensure_cache(table_path)
        quote_columns: List[str] = cache["quote_columns"]
        available = list(quote_columns)

        model_pattern = str(model or "").strip()
        brand_pattern = str(brand or "").strip()
        quote_pattern = str(quote_type or "").strip()
        limit = self._resolve_max_rows(max_rows)

        app_logger.info(
            "[tire_price_query] query start: table=%s, model=%s, brand=%s, quote_type=%s, max_rows=%s, available=%s",
            table_path,
            model_pattern,
            brand_pattern or None,
            quote_pattern or None,
            limit,
            available,
        )

        base: Dict[str, Any] = {
            "brand": brand_pattern,
            "model": model_pattern,
            "quote_type": quote_pattern,
            "available_quote_types": available,
            "quotes": [],
            "matched_count": 0,
            "returned_count": 0,
            "truncated": False,
            "truncation_note": "",
        }

        if not model_pattern:
            return {**base, "error": "型号不能为空"}
        if not quote_columns:
            return {
                **base,
                "message": "价格表里没有任何报价类型列（除品牌/规格/备注外没有其它表头）",
            }

        records = cache["records"]
        matched, model_mode = self._match_records(records, "model_norm", model_pattern)
        if not matched:
            return {
                **base,
                "match_mode": model_mode,
                "message": f"未找到型号「{model_pattern}」，请核对表格中的「规格」写法",
            }

        brand_mode = "all"
        if brand_pattern:
            matched, brand_mode = self._match_records(matched, "brand_norm", brand_pattern)
            if not matched:
                brands = self._distinct_brands(records)
                return {
                    **base,
                    "match_mode": model_mode,
                    "brand_match_mode": brand_mode,
                    "message": (
                        f"型号「{model_pattern}」下未找到品牌「{brand_pattern}」，"
                        f"当前表格的品牌有：{'、'.join(brands) if brands else '（无）'}"
                    ),
                }

        cols = self._match_quote_columns(quote_columns, quote_pattern)
        if not cols:
            return {
                **base,
                "match_mode": model_mode,
                "brand_match_mode": brand_mode,
                "message": (
                    f"未找到报价类型「{quote_pattern}」，"
                    f"当前表格可选：{'、'.join(available)}"
                ),
            }

        brand_order: Dict[str, int] = cache["brand_order"]
        matched = sorted(
            matched, key=lambda r: (brand_order.get(r["brand"], 1 << 30), r["row_index"])
        )

        quotes: List[Dict[str, Any]] = []
        seen = set()
        for rec in matched:
            for col in cols:
                price = rec["prices"].get(col)
                key = (rec["brand"], rec["model"], rec["note"], col, repr(price))
                if key in seen:
                    continue  # 表里存在完全重复的行
                seen.add(key)
                quotes.append(
                    {
                        "brand": rec["brand"],
                        "model": rec["model"],
                        "note": rec["note"],
                        "quote_type": col,
                        "price": price,
                        "price_display": format_price_display(price),
                    }
                )

        matched_count = len(quotes)
        truncated = matched_count > limit
        truncation_note = ""
        if truncated:
            quotes = quotes[:limit]
            truncation_note = f"（共 {matched_count} 条，此处只显示前 {limit} 条）"
            app_logger.info(
                "[tire_price_query] result truncated: matched=%s, returned=%s, model=%s",
                matched_count,
                limit,
                model_pattern,
            )

        result = {
            **base,
            "quotes": quotes,
            "matched_count": matched_count,
            "returned_count": len(quotes),
            "truncated": truncated,
            "truncation_note": truncation_note,
            "matched_quote_types": list(cols),
            "match_mode": model_mode,
            "brand_match_mode": brand_mode,
        }
        if not any(q["price"] is not None for q in quotes):
            result["message"] = f"型号「{model_pattern}」在表格中存在，但相关报价尚未填写"
        app_logger.info(
            "[tire_price_query] query result: matched=%s, returned=%s, quote_types=%s, result=%s",
            matched_count,
            len(quotes),
            cols,
            json.dumps(result, ensure_ascii=False),
        )
        return result

    @staticmethod
    def _resolve_max_rows(raw: Any) -> int:
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return DEFAULT_MAX_ROWS
        try:
            n = int(float(raw))
        except (TypeError, ValueError):
            return DEFAULT_MAX_ROWS
        if n <= 0:
            return DEFAULT_MAX_ROWS
        return n

    @staticmethod
    def _distinct_brands(records: List[Dict[str, Any]]) -> List[str]:
        out: List[str] = []
        for r in records:
            b = r["brand"]
            if b and b not in out:
                out.append(b)
        return out
