from __future__ import annotations

import math
import os
import re
import threading
import json
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import pandas as pd

from config.logging import app_logger
from core.extension_manager import get_extensions_base_dir

# 与《快递价格表.xlsx》Sheet1 表头一致
PRICE_TABLE_FILENAME = "快递价格表.xlsx"
SHEET_NAME = "Sheet1"
REQUIRED_COLUMNS = ("快递公司", "始发地", "目的地", "首重", "续重")

# 表中「首重」为金额；续重按超出首重 1kg 的部分，每整千克计费（行业常见口径）
FIRST_WEIGHT_KG = 1.0
# 未传、无法解析或非正数的重量，按 1kg 计价
DEFAULT_WEIGHT_KG = 1.0
# 体积重（kg）= 长(cm)*宽(cm)*高(cm) / VOLUMETRIC_DIVISOR（快递常见抛比）
VOLUMETRIC_DIVISOR = 8000.0

# 后台轮询文件 mtime 的间隔（秒）
MTIME_POLL_INTERVAL_SEC = 30.0

_ADMIN_SUFFIXES = (
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "自治区",
    "特别行政区",
    "省",
    "市",
)


def get_default_price_table_path() -> str:
    return os.path.join(get_extensions_base_dir(), PRICE_TABLE_FILENAME)


def _cache_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))


def _normalize_courier_token(name: str) -> str:
    """去除首尾空白并压缩中间空白，便于与表中名称宽松匹配。"""
    return "".join(str(name or "").strip().split())


def _courier_row_matches(row_courier: str, wanted: str) -> bool:
    a = str(row_courier or "").strip()
    b = str(wanted or "").strip()
    if not b:
        return True
    if a == b:
        return True
    return _normalize_courier_token(a) == _normalize_courier_token(b)


def normalize_province(name: str) -> str:
    """与表中「安徽」「广东」等短名称对齐。"""
    s = str(name or "").strip()
    if not s:
        return ""
    for suf in _ADMIN_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
            break
    return s


def _billable_extra_kg(weight_kg: float) -> int:
    """超出首重 1kg 的部分，按千克向上取整计续重次数。"""
    if weight_kg <= FIRST_WEIGHT_KG:
        return 0
    return int(math.ceil(weight_kg - FIRST_WEIGHT_KG))


def _row_price(first_yuan: float, cont_yuan: float, weight_kg: float) -> float:
    extra = _billable_extra_kg(weight_kg)
    return round(float(first_yuan) + extra * float(cont_yuan), 2)


PLACEHOLDER_MAX_INDEX = 15

_INDEXED_PLACEHOLDER_RE = re.compile(r"\[(?:价格|快递名|续重价)(\d{1,2})\]")


def _drop_unused_quote_lines(text: str, quote_count: int) -> str:
    """删除编号占位符全部超出实际报价条数的整行，避免留下空的「(续/kg)」壳。"""
    kept: List[str] = []
    for line in text.split("\n"):
        idxs = [
            int(m)
            for m in _INDEXED_PLACEHOLDER_RE.findall(line)
            if 1 <= int(m) <= PLACEHOLDER_MAX_INDEX
        ]
        if idxs and all(i > quote_count for i in idxs):
            continue
        kept.append(line)
    return "\n".join(kept)


def _fmt_display_num(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if math.isfinite(x) and abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s or "0"


def _fmt_weight_display(w: float) -> str:
    if abs(w - round(w)) < 1e-9:
        return str(int(round(w)))
    return f"{w:.2f}".rstrip("0").rstrip(".")


def format_quote_message(template: str, quote_result: Dict[str, Any]) -> str:
    """
    替换 message_template 中的占位符。
    [出发省份][目的省份][重量][最便宜的快递名][补差值]；
    [价格i][快递名i][续重价i]（i 为 1..15），报价按总价升序编号。
    若某一行的编号占位符全部超出实际报价条数，则整行删除（而非替换为空后留下模板里的字面装饰文字）。
    """
    text = str(template or "")
    origin = str(quote_result.get("origin_province") or "")
    dest = str(quote_result.get("dest_province") or "")
    cw_raw = quote_result.get("chargeable_weight_kg")
    if cw_raw is None:
        cw_raw = quote_result.get("weight_kg")
    try:
        wf = float(cw_raw)
    except (TypeError, ValueError):
        wf = DEFAULT_WEIGHT_KG
    weight_str = _fmt_weight_display(wf)

    text = text.replace("[出发省份]", origin)
    text = text.replace("[目的省份]", dest)
    text = text.replace("[重量]", weight_str)
    text = text.replace("[补差值]", _fmt_display_num(quote_result.get("compensation_value")))

    quotes = list(quote_result.get("quotes") or [])
    sorted_q = sorted(
        quotes,
        key=lambda x: (float(x.get("price") or 0), str(x.get("courier") or "")),
    )
    cheapest = str(sorted_q[0].get("courier") or "") if sorted_q else ""
    text = text.replace("[最便宜的快递名]", cheapest)

    text = _drop_unused_quote_lines(text, len(sorted_q))
    for i in range(1, PLACEHOLDER_MAX_INDEX + 1):
        if i <= len(sorted_q):
            q = sorted_q[i - 1]
            ps = _fmt_display_num(q.get("price"))
            courier = str(q.get("courier") or "")
            cs = _fmt_display_num(q.get("continuation_price_per_kg"))
        else:
            ps = courier = cs = ""
        text = text.replace(f"[价格{i}]", ps)
        text = text.replace(f"[快递名{i}]", courier)
        text = text.replace(f"[续重价{i}]", cs)
    return text


def resolve_weight_kg(weight_raw: Any) -> Tuple[float, bool]:
    """
    解析重量（千克）。未传入、无法解析、<=0、非有限数时按 DEFAULT_WEIGHT_KG。
    返回 (weight_kg, defaulted)。
    """
    if weight_raw is None:
        return DEFAULT_WEIGHT_KG, True
    if isinstance(weight_raw, str) and not str(weight_raw).strip():
        return DEFAULT_WEIGHT_KG, True
    try:
        w = float(weight_raw)
    except (TypeError, ValueError):
        return DEFAULT_WEIGHT_KG, True
    if not math.isfinite(w) or w <= 0:
        return DEFAULT_WEIGHT_KG, True
    return w, False


def resolve_compensation_base(base_raw: Any) -> Tuple[float, bool]:
    """
    解析补差基数。未传入、无法解析、非有限数时按 0。
    若小于 0 按 0 处理。
    返回 (compensation_base, defaulted)。
    """
    if base_raw is None:
        return 0.0, True
    if isinstance(base_raw, str) and not str(base_raw).strip():
        return 0.0, True
    try:
        v = float(base_raw)
    except (TypeError, ValueError):
        return 0.0, True
    if not math.isfinite(v):
        return 0.0, True
    if v < 0:
        return 0.0, False
    return round(v, 2), False


def _parse_positive_cm(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, str) and not str(raw).strip():
        return None
    try:
        x = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x <= 0:
        return None
    return x


def resolve_dimensions_cm(
    length_raw: Any,
    width_raw: Any,
    height_raw: Any,
) -> Optional[Tuple[float, float, float]]:
    """三者均传入且均为有限正数时返回 (长,宽,高) 厘米；否则视为未提供体积信息。"""
    if length_raw is None or width_raw is None or height_raw is None:
        return None
    L = _parse_positive_cm(length_raw)
    W = _parse_positive_cm(width_raw)
    H = _parse_positive_cm(height_raw)
    if L is None or W is None or H is None:
        return None
    return (L, W, H)


def compute_chargeable_weight(
    declared_kg: float,
    dims_cm: Optional[Tuple[float, float, float]],
) -> Tuple[float, Optional[float], str]:
    """
    计费重量 = max(向上取整实重, 向上取整体积重)；体积重 = L*W*H/8000。
    返回 (chargeable_kg, volume_weight_kg 或 None, billing_weight_source)。
    """
    declared_ceil = float(math.ceil(declared_kg))
    if dims_cm is None:
        return declared_ceil, None, "no_dimensions"
    L, W, H = dims_cm
    volume_raw_kg = (L * W * H) / VOLUMETRIC_DIVISOR
    volume_ceil_kg = float(math.ceil(volume_raw_kg))
    chargeable = declared_ceil if declared_ceil >= volume_ceil_kg else volume_ceil_kg
    if volume_ceil_kg > declared_ceil:
        return chargeable, volume_ceil_kg, "volumetric"
    return chargeable, volume_ceil_kg, "actual"


def _billing_extras(
    declared_kg: float,
    chargeable_kg: float,
    dims_cm: Optional[Tuple[float, float, float]],
    volume_weight_kg: Optional[float],
    billing_weight_source: str,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "declared_weight_kg": declared_kg,
        "chargeable_weight_kg": chargeable_kg,
        "billing_weight_source": billing_weight_source,
    }
    if dims_cm is not None:
        out["dimensions_cm"] = {"length": dims_cm[0], "width": dims_cm[1], "height": dims_cm[2]}
    if volume_weight_kg is not None:
        out["volume_weight_kg"] = volume_weight_kg
    return out


class ExpressPriceCalcService:
    """读入快递价格表，按始发/目的/重量报价；带 mtime 缓存与可选后台轮询。"""

    def __init__(self, price_table_path: Optional[str] = None) -> None:
        self._path = price_table_path
        self._lock = threading.Lock()
        self._caches: Dict[str, Dict[str, Any]] = {}
        self._stop_poll = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None

    def _resolve_quote_path(self, price_table_filename: Optional[Any]) -> str:
        if self._path is not None:
            return _cache_key(str(self._path))
        base = get_extensions_base_dir()
        if price_table_filename is None:
            return _cache_key(os.path.join(base, PRICE_TABLE_FILENAME))
        s = str(price_table_filename).strip()
        if not s:
            return _cache_key(os.path.join(base, PRICE_TABLE_FILENAME))
        bn = os.path.basename(s)
        if not bn or bn in (".", ".."):
            raise ValueError("无效的价格表文件名")
        return _cache_key(os.path.join(base, bn))

    def start_mtime_poller(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop_poll.clear()

        def _run() -> None:
            while not self._stop_poll.wait(timeout=MTIME_POLL_INTERVAL_SEC):
                try:
                    self._invalidate_if_file_changed()
                except Exception as e:
                    app_logger.warning("[express_price_calc] mtime poll error: %s", e)

        t = threading.Thread(target=_run, name="express_price_calc_mtime", daemon=True)
        t.start()
        self._poll_thread = t
        app_logger.info("[express_price_calc] mtime poller started (interval=%ss)", MTIME_POLL_INTERVAL_SEC)

    def stop_mtime_poller(self) -> None:
        self._stop_poll.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=3.0)
            self._poll_thread = None
        app_logger.info("[express_price_calc] mtime poller stopped")

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
                app_logger.info("[express_price_calc] price file missing, clearing cache: %s", key)
                continue
            st = os.stat(key)
            if c.get("mtime") != st.st_mtime or c.get("size") != st.st_size:
                with self._lock:
                    if self._caches.get(key) is c:
                        self._caches.pop(key, None)
                app_logger.info("[express_price_calc] price file changed, clearing cache: %s", key)

    def _load_locked(self, path: str) -> Dict[str, Any]:
        df = pd.read_excel(path, sheet_name=SHEET_NAME, engine="openpyxl")
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"价格表缺少列: {missing}")
        df = df[list(REQUIRED_COLUMNS)].copy()
        df["快递公司"] = df["快递公司"].astype(str).str.strip()
        df["始发地"] = df["始发地"].astype(str).str.strip()
        df["目的地"] = df["目的地"].astype(str).str.strip()
        df["首重"] = pd.to_numeric(df["首重"], errors="coerce")
        df["续重"] = pd.to_numeric(df["续重"], errors="coerce")
        df = df.dropna(subset=["快递公司", "始发地", "目的地", "首重", "续重"])

        index: DefaultDict[Tuple[str, str], List[Tuple[str, float, float]]] = defaultdict(list)
        for _, row in df.iterrows():
            o = str(row["始发地"]).strip()
            d = str(row["目的地"]).strip()
            courier = str(row["快递公司"]).strip()
            if not o or not d or not courier:
                continue
            index[(o, d)].append((courier, float(row["首重"]), float(row["续重"])))

        st = os.stat(path)
        return {
            "mtime": st.st_mtime,
            "size": st.st_size,
            "index": index,
            "row_count": int(len(df)),
        }

    def _ensure_cache(self, path: str) -> Dict[str, Any]:
        key = _cache_key(path)
        if not os.path.isfile(key):
            raise FileNotFoundError(f"未找到快递价格表: {key}")

        with self._lock:
            st = os.stat(key)
            c = self._caches.get(key)
            if c is not None and c.get("mtime") == st.st_mtime and c.get("size") == st.st_size:
                return c
            app_logger.info("[express_price_calc] loading price table: %s", key)
            c = self._load_locked(key)
            self._caches[key] = c
            app_logger.info(
                "[express_price_calc] loaded rows=%s keys=%s",
                c["row_count"],
                len(c["index"]),
            )
            return c

    def quote(
        self,
        origin_province: str,
        dest_province: str,
        weight_kg: Any = None,
        courier_name: Optional[str] = None,
        compensation_base: Any = None,
        length_cm: Any = None,
        width_cm: Any = None,
        height_cm: Any = None,
        price_table_filename: Optional[Any] = None,
    ) -> Dict[str, Any]:
        origin = normalize_province(origin_province)
        dest = normalize_province(dest_province)
        courier_filter = str(courier_name).strip() if courier_name is not None else ""
        if not origin:
            return {"quotes": [], "error": "起始省份不能为空"}
        if not dest:
            return {"quotes": [], "error": "目的省份不能为空"}
        try:
            table_path = self._resolve_quote_path(price_table_filename)
        except ValueError as exc:
            return {"quotes": [], "error": str(exc)}
        app_logger.info(
            "[express_price_calc] quote start: table_path=%s, origin_raw=%s, dest_raw=%s, origin_norm=%s, dest_norm=%s, weight_raw=%s, compensation_base_raw=%s, courier_name=%s, length_cm=%s, width_cm=%s, height_cm=%s",
            table_path,
            origin_province,
            dest_province,
            origin,
            dest,
            weight_kg,
            compensation_base,
            courier_filter or None,
            length_cm,
            width_cm,
            height_cm,
        )
        w, weight_defaulted = resolve_weight_kg(weight_kg)
        declared_ceil_kg = float(math.ceil(w))
        dims_cm = resolve_dimensions_cm(length_cm, width_cm, height_cm)
        w_bill, vol_kg, bill_src = compute_chargeable_weight(w, dims_cm)
        billing = _billing_extras(declared_ceil_kg, w_bill, dims_cm, vol_kg, bill_src)
        compensation_base_value, compensation_base_defaulted = resolve_compensation_base(
            compensation_base
        )
        app_logger.info(
            "[express_price_calc] quote weight resolved: weight_kg=%s, defaulted=%s, chargeable_kg=%s, billing=%s, compensation_base=%s, compensation_base_defaulted=%s",
            w,
            weight_defaulted,
            w_bill,
            bill_src,
            compensation_base_value,
            compensation_base_defaulted,
        )

        cache = self._ensure_cache(table_path)
        index: DefaultDict[Tuple[str, str], List[Tuple[str, float, float]]] = cache["index"]
        rows = list(index.get((origin, dest), []))
        if not rows:
            result = {
                "quotes": [],
                "origin_province": origin,
                "dest_province": dest,
                "weight_kg": w,
                "weight_defaulted": weight_defaulted,
                **billing,
                "compensation_base": compensation_base_value,
                "compensation_base_defaulted": compensation_base_defaulted,
                "compensation_value": 0.0,
                "message": "未找到该始发地/目的地组合的价格行",
            }
            if courier_filter:
                result["courier_name"] = courier_filter
            app_logger.info(
                "[express_price_calc] quote result(no rows): key=(%s,%s), result=%s",
                origin,
                dest,
                json.dumps(result, ensure_ascii=False),
            )
            return result

        if courier_filter:
            rows = [r for r in rows if _courier_row_matches(r[0], courier_filter)]
            if not rows:
                result = {
                    "quotes": [],
                    "origin_province": origin,
                    "dest_province": dest,
                    "weight_kg": w,
                    "weight_defaulted": weight_defaulted,
                    **billing,
                    "compensation_base": compensation_base_value,
                    "compensation_base_defaulted": compensation_base_defaulted,
                    "compensation_value": 0.0,
                    "courier_name": courier_filter,
                    "message": f'未找到快递公司「{courier_filter}」在该线路的价格，请核对表中「快递公司」名称',
                }
                app_logger.info(
                    "[express_price_calc] quote result(no courier match): key=(%s,%s), courier=%s",
                    origin,
                    dest,
                    courier_filter,
                )
                return result

        # courier -> (best_total_price, continuation_yuan_per_kg from winning row)
        best: Dict[str, Tuple[float, float]] = {}
        for courier, first_y, cont_y in rows:
            p = _row_price(first_y, cont_y, w_bill)
            cont_y = float(cont_y)
            if courier not in best or p < best[courier][0]:
                best[courier] = (p, cont_y)

        quotes = [
            {
                "courier": k,
                "price": v[0],
                "continuation_price_per_kg": round(v[1], 2),
            }
            for k, v in sorted(best.items(), key=lambda x: (x[1][0], x[0]))
        ]
        min_price = round(float(quotes[0]["price"]), 2) if quotes else None
        compensation_value = (
            round(max(float(min_price) - compensation_base_value, 0.0), 2)
            if min_price is not None
            else 0.0
        )
        result = {
            "quotes": quotes,
            "origin_province": origin,
            "dest_province": dest,
            "weight_kg": w,
            "weight_defaulted": weight_defaulted,
            **billing,
            "min_price": min_price,
            "compensation_base": compensation_base_value,
            "compensation_base_defaulted": compensation_base_defaulted,
            "compensation_value": compensation_value,
            "first_weight_kg_rule": FIRST_WEIGHT_KG,
        }
        if courier_filter:
            result["courier_name"] = courier_filter
        app_logger.info(
            "[express_price_calc] quote result(success): key=(%s,%s), rows=%s, quotes=%s, result=%s",
            origin,
            dest,
            len(rows),
            len(quotes),
            json.dumps(result, ensure_ascii=False),
        )
        return result
