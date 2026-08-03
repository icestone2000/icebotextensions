"""
转账消息：按金额从文本卡密文件取一行发到当前会话，并从文件中删除该行。
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from config.logging import app_logger
from schemas.wechat import MessageSend, MessageType

_AMOUNT_RE = re.compile(r"￥\s*([\d.]+)")

_lock_registry_lock = threading.Lock()
_file_locks: Dict[str, threading.Lock] = {}


def _lock_for_path(path: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(path))
    with _lock_registry_lock:
        if key not in _file_locks:
            _file_locks[key] = threading.Lock()
        return _file_locks[key]


def decimal_to_cents(amount: Decimal) -> int:
    q = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int((q * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cents_to_decimal(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))


def parse_transfer_amount(message_content: str) -> Optional[Decimal]:
    """从含 ``￥`` 的文案中解析金额（如 ``[转账消息]`` / ``[收款消息]`` + 金额）。"""
    if not message_content:
        return None
    m = _AMOUNT_RE.search(message_content)
    if not m:
        return None
    try:
        return Decimal(m.group(1)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None


def _is_wx_self_bubble(context: Dict[str, Any]) -> bool:
    """wxauto 侧本人气泡：``sender_id`` / ``user_id`` / ``wxauto_attr`` 为 self。"""
    if not context:
        return False
    uid = (context.get("sender_id") or context.get("user_id") or "").strip().lower()
    if uid == "self":
        return True
    return (context.get("wxauto_attr") or "").strip().lower() == "self"


def is_transfer_card_secret_eligible(
    context: Dict[str, Any], message_content: str
) -> bool:
    """
    仅当已收款气泡（content 以 ``[收款消息]`` 开头）且为 self 气泡时发卡密。
    ``[转账消息]`` + self 表示本人转出，不适用。
    """
    if not _is_wx_self_bubble(context):
        return False
    s = (message_content or "").strip()
    if s.startswith("[转账消息]"):
        return False
    return s.startswith("[收款消息]")


def _price_file_row_amount(row: Dict[str, Any]) -> Any:
    """优先「金额」，否则 ``amount``（兼容旧配置）。"""
    if "金额" in row:
        v = row["金额"]
        if v is not None and str(v).strip() != "":
            return v
    return row.get("amount")


def _price_file_row_path(row: Dict[str, Any]) -> str:
    """优先「文件」，否则 ``file``。"""
    for key in ("文件", "file"):
        v = row.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _price_file_row_before_secret(row: Dict[str, Any]) -> str:
    """「卡密前置说明」：非空则在弹出并发送该档卡密前先发一条文本。"""
    v = row.get("卡密前置说明")
    if v is None:
        return ""
    return str(v).strip()


def _price_file_row_after_secret(row: Dict[str, Any]) -> str:
    """「卡密后说明」：非空则在发送该档卡密后再发一条文本。"""
    v = row.get("卡密后说明")
    if v is None:
        return ""
    return str(v).strip()


class DenominationRow(NamedTuple):
    """某一金额档位对应的卡密文件与前后说明文案。"""

    file_path: str
    before_secret: str
    after_secret: str


class PendingArm(NamedTuple):
    """会话内对方已发启动命令，在 expires_at_monotonic 之前有效。"""

    expires_at_monotonic: float
    armed_by_id: str
    armed_by_name: str


def chat_key_from_context(context: Dict[str, Any]) -> str:
    """优先 ``group_id``，否则 ``group_name``。"""
    if not context:
        return ""
    gid = (context.get("group_id") or "").strip()
    if gid:
        return gid
    return (context.get("group_name") or "").strip()


def merge_price_file_list(
    price_file_list: List[Dict[str, Any]],
) -> Tuple[Dict[Decimal, DenominationRow], List[str]]:
    """
    面额 -> 配置行；字典键优先「金额」「文件」，兼容 ``amount`` / ``file``。
    可选「卡密前置说明」「卡密后说明」：在每条卡密发送前/后各发一条文本（若有值）。
    同一面额多次出现时后者覆盖前者。
    返回 (映射, 警告列表)。
    """
    merged: Dict[Decimal, DenominationRow] = {}
    warnings: List[str] = []
    for row in price_file_list:
        if not isinstance(row, dict):
            continue
        raw_amt = _price_file_row_amount(row)
        try:
            amt = Decimal(str(raw_amt)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            warnings.append(f"跳过无效金额: {raw_amt!r}")
            continue
        fp = _price_file_row_path(row)
        if not fp:
            warnings.append(f"跳过空文件路径: amount={amt}")
            continue
        if amt in merged:
            warnings.append(f"金额 {amt} 重复配置，已使用后出现的文件")
        merged[amt] = DenominationRow(
            file_path=fp,
            before_secret=_price_file_row_before_secret(row),
            after_secret=_price_file_row_after_secret(row),
        )
    return merged, warnings


def min_coins_combo(target_cents: int, coin_cents: List[int]) -> Optional[List[int]]:
    """
    无穷背包最少张数；返回每张卡的面额（分），顺序为每次在最优路径上取最大面额。
    coin_cents 应为正整数列表。
    """
    coins = sorted({c for c in coin_cents if c > 0})
    if not coins or target_cents < 0:
        return None
    INF = target_cents + 10**9
    dp: List[int] = [INF] * (target_cents + 1)
    dp[0] = 0
    for s in range(1, target_cents + 1):
        best = INF
        for c in coins:
            if s >= c:
                v = dp[s - c] + 1
                if v < best:
                    best = v
        dp[s] = best
    if dp[target_cents] >= INF:
        return None
    result: List[int] = []
    rem = target_cents
    while rem > 0:
        picked = None
        for c in sorted(coins, reverse=True):
            if rem >= c and dp[rem] == dp[rem - c] + 1:
                picked = c
                break
        if picked is None:
            return None
        result.append(picked)
        rem -= picked
    return result


def pop_first_line(path: str) -> str:
    """
    从文本文件中原子弹出第一行非空内容（strip 后），删除该行。
    返回该行文本（strip）。
    """
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path) or "."
    lock = _lock_for_path(abs_path)
    with lock:
        if not os.path.isfile(abs_path):
            raise FileNotFoundError(f"卡密文件不存在: {abs_path}")
        with open(abs_path, "r", encoding="utf-8-sig", newline="") as f:
            lines = f.read().splitlines()
        idx = None
        secret = ""
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped:
                idx = i
                secret = stripped
                break
        if idx is None:
            raise ValueError(f"卡密文件为空或无有效行: {abs_path}")
        rest = lines[:idx] + lines[idx + 1 :]
        new_body = "\n".join(rest)
        if rest:
            new_body += "\n"
        fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as tf:
                tf.write(new_body)
            os.replace(tmp_path, abs_path)
        except Exception:
            if os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise
        return secret


class TransferCardSecretService:
    """转账后发卡密。"""

    def __init__(self) -> None:
        self._pending_lock = threading.Lock()
        self._pending: Dict[str, PendingArm] = {}

    def clear_pending(self) -> None:
        """清空待发货窗口（单测或运维用）。"""
        with self._pending_lock:
            self._pending.clear()

    def _normalize_ttl_minutes(self, command_ttl_minutes: Any) -> int:
        try:
            n = int(command_ttl_minutes)
        except (TypeError, ValueError):
            return 3
        return n if n >= 1 else 3

    def _peek_valid_pending(self, chat_key: str) -> Optional[PendingArm]:
        with self._pending_lock:
            rec = self._pending.get(chat_key)
            if rec is None:
                return None
            if time.monotonic() > rec.expires_at_monotonic:
                del self._pending[chat_key]
                return None
            return rec

    def _arm_pending(
        self,
        chat_key: str,
        armed_by_id: str,
        armed_by_name: str,
        ttl_seconds: int,
    ) -> None:
        with self._pending_lock:
            self._pending[chat_key] = PendingArm(
                expires_at_monotonic=time.monotonic() + float(ttl_seconds),
                armed_by_id=(armed_by_id or "").strip(),
                armed_by_name=(armed_by_name or "").strip(),
            )

    def _clear_pending(self, chat_key: str) -> None:
        with self._pending_lock:
            self._pending.pop(chat_key, None)

    def handleCommand(
        self,
        context: Dict[str, Any],
        price_file_list: List[Dict[str, Any]],
        notify_target: str,
        start_command: str = "",
        command_ttl_minutes: Any = 3,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        group_name = (context or {}).get("group_name") or ""
        message_content = (context or {}).get("message_content") or ""
        notify = (notify_target or "").strip()
        ttl_min = self._normalize_ttl_minutes(command_ttl_minutes)
        ttl_sec = ttl_min * 60
        cmd = (start_command or "").strip()

        def fail(reason: str) -> Dict[str, Any]:
            app_logger.warning("[TransferCardSecret] %s", reason)
            if notify:
                self._send_chat_text(notify, f"[发卡密] {reason}")
            return {"success": False, "message": reason}

        if not group_name:
            return fail("缺少会话 group_name，无法发卡密")
        if not price_file_list:
            return fail("price_file_list 为空")

        chat_key = chat_key_from_context(context or {})
        if not chat_key:
            return fail("缺少会话标识（group_id 或 group_name）")

        # --- 先处理「启动发货命令」（非 self、全等匹配），避免正文含 ￥ 时误走金额分支 ---
        if cmd:
            if (
                (message_content or "").strip() == cmd
                and not _is_wx_self_bubble(context or {})
            ):
                armer_id = (
                    (context or {}).get("sender_id")
                    or (context or {}).get("user_id")
                    or ""
                ).strip()
                armer_name = ((context or {}).get("sender_name") or "").strip()
                self._arm_pending(chat_key, armer_id, armer_name, ttl_sec)
                app_logger.info(
                    "[TransferCardSecret] 已记录启动发货 chat_key=%s armer=%s ttl=%smin",
                    chat_key,
                    armer_id or armer_name,
                    ttl_min,
                )
                return {
                    "success": True,
                    "message": "已记录启动发货",
                    "armed": True,
                    "ttl_minutes": ttl_min,
                    "ttl_seconds": ttl_sec,
                }

        amount = parse_transfer_amount(message_content)
        if amount is None:
            return fail("无法从消息中解析转账金额")

        if not is_transfer_card_secret_eligible(context, message_content):
            app_logger.info(
                "[TransferCardSecret] 非已收款(self) 或未满足发卡密条件，已跳过"
            )
            return {
                "success": False,
                "message": "非已收款(self) 或未满足发卡密条件，已跳过",
                "skipped": True,
            }

        if cmd:
            pending = self._peek_valid_pending(chat_key)
            if pending is None:
                note = (
                    f"会话「{group_name}」收到收款 {amount} 元，但未在 {ttl_min} 分钟内"
                    f"由对方发送启动命令「{cmd}」（或已过期），已跳过发卡密。"
                )
                app_logger.info("[TransferCardSecret] %s", note)
                if notify:
                    self._send_chat_text(notify, f"[发卡密] {note}")
                return {
                    "success": False,
                    "message": note,
                    "skipped": True,
                    "reason": "no_valid_arm",
                }

        merged, warns = merge_price_file_list(price_file_list)
        for w in warns:
            app_logger.info("[TransferCardSecret] %s", w)

        if not merged:
            return fail("没有有效的金额与文件配置")

        target_cents = decimal_to_cents(amount)
        if target_cents <= 0:
            return fail("转账金额无效")

        coin_cents = [decimal_to_cents(a) for a in merged.keys()]
        combo = min_coins_combo(target_cents, coin_cents)
        if combo is None:
            return fail(
                f"金额 {amount} 无法用已配置的面额精确凑齐（支持多种面额之和，条数最少）"
            )

        cents_to_row: Dict[int, DenominationRow] = {}
        for amt, row_cfg in merged.items():
            cents_to_row[decimal_to_cents(amt)] = row_cfg

        try:
            for i, c in enumerate(combo):
                row_cfg = cents_to_row.get(c)
                if not row_cfg:
                    return fail(f"内部错误：缺少面额 {cents_to_decimal(c)} 对应的文件")
                if row_cfg.before_secret:
                    self._send_chat_text(group_name, row_cfg.before_secret)
                    time.sleep(0.5)
                secret = pop_first_line(row_cfg.file_path)
                self._send_chat_text(group_name, secret)
                if row_cfg.after_secret:
                    time.sleep(0.5)
                    self._send_chat_text(group_name, row_cfg.after_secret)
                if i < len(combo) - 1:
                    time.sleep(0.5)
        except FileNotFoundError as e:
            return fail(str(e))
        except ValueError as e:
            return fail(str(e))
        except Exception as e:
            app_logger.error("[TransferCardSecret] 处理异常: %s", e, exc_info=True)
            return fail(str(e))

        if cmd:
            self._clear_pending(chat_key)

        return {
            "success": True,
            "message": "发卡密成功",
            "amount": str(amount),
            "cards_sent": len(combo),
        }

    def _send_chat_text(self, chat_id: str, content: str) -> None:
        if not chat_id or not content:
            return
        try:
            from core.wechat_manager import get_wechat_service

            wechat_service = get_wechat_service()
            send_result = wechat_service.send_message(
                MessageSend(
                    chat_id=chat_id,
                    content=content,
                    message_type=MessageType.TEXT,
                )
            )
            if not send_result.success:
                app_logger.warning(
                    "[TransferCardSecret] 发送失败: %s", send_result.error
                )
        except RuntimeError as e:
            app_logger.warning("[TransferCardSecret] 微信服务不可用: %s", e)
        except Exception as e:
            app_logger.warning("[TransferCardSecret] 发送异常: %s", e, exc_info=True)
