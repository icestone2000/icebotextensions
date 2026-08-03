"""
从聊天文本解析「手机+姓名+次数+项目+站点」并创建订单。
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from config.logging import app_logger
from schemas.order import CustomerCreate, OrderCreate, OrderItemCreate, OrderStatus, PaymentStatus
from schemas.wechat import MessageSend, MessageType
from services.order_service import OrderService

# 默认项目：全称与简称均映射到规范「商品名」（全称）
DEFAULT_PROJECT_ROWS: List[Tuple[str, str]] = [
    ("酒店", "酒"),
    ("高铁", "高"),
    ("机场", "机"),
    ("景区", "景"),
]

_SOURCE_MAX_LEN = 50
_PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")


def _merge_project_map(project_list: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    """
    token（全称或简称） -> 规范商品名（全称）。
    先加载默认表，再以 projectList 覆盖同名 token，使调用方配置优先生效。
    """
    token_to_full: Dict[str, str] = {}
    for full, abbr in DEFAULT_PROJECT_ROWS:
        token_to_full[full] = full
        token_to_full[abbr] = full
    if not project_list:
        return token_to_full
    for row in project_list:
        if not isinstance(row, dict):
            continue
        full = (row.get("full") or row.get("name") or "").strip()
        abbr = (row.get("abbr") or row.get("short") or "").strip()
        if full:
            token_to_full[full] = full
        if abbr and full:
            token_to_full[abbr] = full
    return token_to_full


def _build_project_regex(token_to_full: Dict[str, str]) -> str:
    tokens = sorted({k for k in token_to_full.keys() if k}, key=len, reverse=True)
    if not tokens:
        return ""
    return "(?:" + "|".join(re.escape(t) for t in tokens) + ")"


def _normalize_compact(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", "", text.strip())


def _truncate_source(name: str, max_len: int = _SOURCE_MAX_LEN) -> str:
    if not name:
        return ""
    if len(name) <= max_len:
        return name
    app_logger.warning("[ChatOrderFromMessage] group_name 超过 source 字段长度，已截断至 %s", max_len)
    return name[:max_len]


def _format_reply(
    template: Optional[str],
    *,
    default: str,
    sender: str,
    order_number: str = "",
    message: str = "",
) -> str:
    """支持占位符 {sender_name}、{order_number}、{message}；{sender} 为 {sender_name} 的兼容别名。"""
    text = (template or "").strip() or default
    placeholders = ("{sender_name}", "{sender}", "{order_number}", "{message}")
    if not any(x in text for x in placeholders):
        return text
    s = sender or ""
    return (
        text.replace("{sender_name}", s)
        .replace("{sender}", s)
        .replace("{order_number}", order_number or "")
        .replace("{message}", message or "")
    )


def parse_order_message(
    message_content: str, token_to_full: Dict[str, str]
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    解析紧凑格式：手机号 + 姓名 + 次数 + 项目 + 站点（站点可为空）。
    返回 (ok, error_message, fields)
    """
    compact = _normalize_compact(message_content)
    if not compact:
        return False, "消息内容为空", None

    m = _PHONE_PATTERN.search(compact)
    if not m:
        return False, "未识别到11位手机号", None

    phone = m.group(0)
    remainder = compact[m.end() :]
    if not remainder:
        return False, "手机号后缺少姓名与订单信息", None

    proj_re = _build_project_regex(token_to_full)
    if not proj_re:
        return False, "项目表为空", None

    body_re = re.compile(r"^(\D+?)(\d+)(" + proj_re + r")(.*)$")
    bm = body_re.match(remainder)
    if not bm:
        return False, "无法解析姓名、次数、项目或站点，请检查格式", None

    raw_name, count_str, project_token, station = bm.group(1), bm.group(2), bm.group(3), bm.group(4)
    name = raw_name.strip() if raw_name else ""
    if not name:
        return False, "姓名为空", None
    try:
        count = int(count_str)
    except ValueError:
        return False, "次数不是有效数字", None
    if count < 1:
        return False, "次数必须大于0", None

    product_name = token_to_full.get(project_token)
    if not product_name:
        return False, f"未识别的项目: {project_token}", None

    return True, "", {
        "phone": phone,
        "customer_name": name,
        "quantity": count,
        "product_name": product_name,
        "station": station or "",
    }


class ChatOrderFromMessageService:
    """聊天消息解析并创建订单。"""

    def __init__(self, db: Session):
        self.db = db
        self.order_service = OrderService(db)

    def handleCommand(
        self,
        context: Dict[str, Any],
        projectList: Optional[List[Dict[str, str]]] = None,
        success_reply: Optional[str] = None,
        failure_reply: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        context: message_content, group_name, sender_name, sender_id / user_id 等。
        success_reply / failure_reply: 可选模板，占位符 {sender_name}、{order_number}、{message}（{sender} 与 {sender_name} 同义）。
        """
        group_name = (context or {}).get("group_name") or ""
        sender_name = (context or {}).get("sender_name") or ""
        message_content = (context or {}).get("message_content") or ""

        token_map = _merge_project_map(projectList)

        def send_fail(reason: str) -> Dict[str, Any]:
            default_f = (
                f"@{sender_name} 订单创建失败：{reason}" if sender_name else f"订单创建失败：{reason}"
            )
            body = _format_reply(
                failure_reply,
                default=default_f,
                sender=sender_name,
                message=reason,
            )
            self._send_chat_text(group_name, body)
            return {"success": False, "message": reason}

        def send_ok(order_number: str) -> None:
            default_s = (
                f"@{sender_name} 订单创建成功！" if sender_name else "订单创建成功！"
            )
            body = _format_reply(
                success_reply,
                default=default_s,
                sender=sender_name,
                order_number=order_number,
                message="",
            )
            self._send_chat_text(group_name, body)

        try:
            ok, err, fields = parse_order_message(message_content, token_map)
            if not ok or not fields:
                return send_fail(err or "解析失败")

            phone = fields["phone"]
            customer_name = fields["customer_name"]
            quantity = fields["quantity"]
            product_name = fields["product_name"]
            station = fields["station"]

            customer = self.order_service.find_or_create_customer(
                {"name": customer_name, "phone": phone},
                user_id=None,
            )

            unit_price = Decimal("1")
            subtotal = unit_price * quantity
            item = OrderItemCreate(
                product_name=product_name,
                quantity=quantity,
                unit_price=unit_price,
                total_price=subtotal,
                notes=station or None,
            )

            source_val = _truncate_source(group_name)
            order_create = OrderCreate(
                customer_id=customer.id,
                order_items=[item],
                subtotal=subtotal,
                tax_amount=Decimal("0"),
                discount_amount=Decimal("0"),
                shipping_cost=Decimal("0"),
                total_amount=subtotal,
                paid_amount=Decimal("0"),
                shipping_name=customer_name,
                shipping_phone=phone,
                notes=sender_name or None,
                source=source_val or "chat",
                status=OrderStatus.PENDING,
                payment_status=PaymentStatus.PENDING,
            )

            order = self.order_service.create_order(order_create)
            send_ok(order.order_number)
            return {
                "success": True,
                "message": "订单创建成功",
                "order_id": order.id,
                "order_number": order.order_number,
                "customer_id": customer.id,
            }
        except Exception as e:
            app_logger.error("[ChatOrderFromMessage] handleCommand 异常: %s", e, exc_info=True)
            try:
                self.db.rollback()
            except Exception:
                pass
            return send_fail(str(e))

    def _send_chat_text(self, group_name: str, content: str) -> None:
        if not group_name or not content:
            return
        try:
            from core.wechat_manager import get_wechat_service

            wechat_service = get_wechat_service()
            send_result = wechat_service.send_message(
                MessageSend(
                    chat_id=group_name,
                    content=content,
                    message_type=MessageType.TEXT,
                )
            )
            if not send_result.success:
                app_logger.warning(
                    "[ChatOrderFromMessage] 群内回执发送失败: %s", send_result.error
                )
        except RuntimeError as e:
            app_logger.warning("[ChatOrderFromMessage] 微信服务不可用，跳过回执: %s", e)
        except Exception as e:
            app_logger.warning("[ChatOrderFromMessage] 群内回执异常: %s", e, exc_info=True)
