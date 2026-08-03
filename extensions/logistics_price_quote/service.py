"""物流装/卸货自然语言 → 外部 AI 报价 API。"""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from config.logging import app_logger
from schemas.wechat import MessageSend, MessageType

DEFAULT_PRICE_API_URL = "https://81.70.97.85/apis/ai/price"
REQUEST_TIMEOUT_SECONDS = 30


def extract_content_after_keyword(
    message_content: str,
    keyword: Optional[str] = None,
) -> str:
    """
    从消息中移除命中关键词后返回正文。
    keyword 为空时仅 strip 全文。
    """
    text = (message_content or "").strip()
    kw = (keyword or "").strip()
    if not text:
        return ""
    if not kw:
        return text
    if kw in text:
        text = text.replace(kw, "", 1)
    return text.strip()


def parse_price_quote_msg(api_data: Any) -> tuple[Optional[str], Optional[str]]:
    """
    从报价 API 响应中提取 msg（如「价格1238.7」）。
    返回 (msg, error_reason)；成功时 error_reason 为 None。
    """
    if not isinstance(api_data, dict):
        return None, "接口返回格式异常"
    msg = str(api_data.get("msg") or "").strip()
    success = api_data.get("success")
    if success is False:
        return None, msg or "报价接口返回失败"
    if not msg:
        return None, "接口未返回报价信息"
    return msg, None


def format_quote_reply(sender_name: str, quote_text: str) -> str:
    """格式化为 @{sender} {quote_text}。"""
    text = (quote_text or "").strip()
    sender = (sender_name or "").strip()
    if sender:
        return f"@{sender} {text}"
    return text


class LogisticsPriceQuoteService:
    """调用外部报价 API，并将 JSON 结果回发到当前会话。"""

    def handleCommand(
        self,
        context: Dict[str, Any],
        url: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        group_name = (context or {}).get("group_name") or ""
        sender_name = (context or {}).get("sender_name") or ""
        message_content = (context or {}).get("message_content") or ""
        keyword = kwargs.get("keyword")
        if keyword is None:
            keyword = (context or {}).get("keyword") or ""

        def fail(reason: str) -> Dict[str, Any]:
            app_logger.warning("[LogisticsPriceQuote] %s", reason)
            if group_name:
                body = (
                    f"@{sender_name} 报价失败：{reason}"
                    if sender_name
                    else f"报价失败：{reason}"
                )
                self._send_chat_text(group_name, body)
            return {"success": False, "message": reason}

        if not group_name:
            return {"success": False, "message": "缺少会话 group_name，无法回发报价"}

        extracted = extract_content_after_keyword(message_content, keyword)
        if not extracted:
            return fail("关键词后无有效内容")

        effective_url = (url or "").strip() or DEFAULT_PRICE_API_URL
        app_logger.info(
            "[LogisticsPriceQuote] POST url=%s title=%s content_len=%s",
            effective_url,
            group_name,
            len(extracted),
        )

        try:
            resp = requests.post(
                effective_url,
                json={"content": extracted, "title": group_name},
                timeout=REQUEST_TIMEOUT_SECONDS,
                verify=False,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            app_logger.error("[LogisticsPriceQuote] 请求失败: %s", e, exc_info=True)
            return fail(f"请求报价接口失败: {e}")

        try:
            api_data = resp.json()
        except ValueError as e:
            app_logger.error(
                "[LogisticsPriceQuote] 响应非 JSON: %s, raw=%s",
                e,
                resp.text[:200],
            )
            return fail("接口返回格式异常")

        quote_msg, parse_err = parse_price_quote_msg(api_data)
        if parse_err:
            return fail(parse_err)

        reply_text = format_quote_reply(sender_name, quote_msg or "")
        self._send_chat_text(group_name, reply_text)
        return {
            "success": True,
            "message": "报价成功",
            "content": extracted,
            "quote_msg": quote_msg,
            "api_response": api_data,
        }

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
                    "[LogisticsPriceQuote] 群内回执发送失败: %s", send_result.error
                )
        except RuntimeError as e:
            app_logger.warning(
                "[LogisticsPriceQuote] 微信服务不可用，跳过回执: %s", e
            )
        except Exception as e:
            app_logger.warning(
                "[LogisticsPriceQuote] 群内回执异常: %s", e, exc_info=True
            )
