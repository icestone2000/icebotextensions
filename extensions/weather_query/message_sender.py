"""将天气文本发到当前会话（个人微信 / 企微 / 闲鱼）。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from config.logging import app_logger
from core.wechat_manager import get_wechat_service
from models.wechat_group import WeChatConfig
from models.wecom_third_party import WeComThirdPartyInstance
from schemas.tool_calling import ToolExecutionRequest
from schemas.wechat import MessageSend, MessageType
from services.wecom_third_party_service import WeComThirdPartyService
from utils.config_manager import get_config_manager
from utils.wechat_config_resolver import resolve_wechat_config


def send_text_to_customer(
    db: Session,
    request: ToolExecutionRequest,
    recipient_id_override: Optional[str],
    text: str,
) -> Dict[str, Any]:
    recipient_id = str(recipient_id_override or "").strip()
    if not recipient_id:
        recipient_id = (request.group_id or request.group_name or "").strip()
    if not recipient_id:
        return {"ok": False, "channel": "", "detail": "缺少接收方"}

    config = resolve_wechat_config(db, request)
    if not config:
        return _send_personal_wechat(request.group_name, text)

    account_type = (config.account_type or "").strip()
    if account_type == "xianyu":
        return _send_xianyu(config, request, recipient_id, text)
    if account_type == "official":
        instance = _get_wecom_instance(db, config)
        if not instance:
            return {"ok": False, "channel": "wecom", "detail": "企业微信实例未登录"}
        return _send_wecom(instance, recipient_id, text, db)
    return _send_personal_wechat(request.group_name, text)


def _get_wecom_instance(db: Session, config: WeChatConfig) -> Optional[WeComThirdPartyInstance]:
    if not config.wxid:
        return None
    return (
        db.query(WeComThirdPartyInstance)
        .filter(
            WeComThirdPartyInstance.wecom_user_id == config.wxid,
            WeComThirdPartyInstance.status == 2,
        )
        .first()
    )


def _send_personal_wechat(recipient_id: str, text: str) -> Dict[str, Any]:
    try:
        result = get_wechat_service().send_message(
            MessageSend(chat_id=recipient_id, content=text, message_type=MessageType.TEXT)
        )
        if result.success:
            return {"ok": True, "channel": "wechat_personal", "detail": "已发送"}
        return {"ok": False, "channel": "wechat_personal", "detail": result.error or "发送失败"}
    except Exception as exc:
        return {"ok": False, "channel": "wechat_personal", "detail": str(exc)}


def _send_wecom(instance, recipient_id: str, text: str, db: Session) -> Dict[str, Any]:
    try:
        server_url = get_config_manager(db).get_config("wecom_third_party.server_url", "") or ""
        svc = WeComThirdPartyService(server_url=server_url, db=db)
        svc.send_text_message(
            guid=instance.guid,
            content=text,
            to_id=recipient_id,
            license_code=instance.license_code,
        )
        return {"ok": True, "channel": "wecom", "detail": "已发送"}
    except Exception as exc:
        app_logger.exception("[weather_query] wecom send: %s", exc)
        return {"ok": False, "channel": "wecom", "detail": str(exc)}


def _send_xianyu(config, request: ToolExecutionRequest, recipient_id: str, text: str) -> Dict[str, Any]:
    try:
        from services.xianyu_service import XianyuService

        session = XianyuService._sessions.get(config.id)
        if not session:
            return {"ok": False, "channel": "xianyu", "detail": "闲鱼会话未运行"}
        gi = (request.context or {}).get("group_info") or {}
        chat_id = gi.get("xianyu_chat_id") or request.group_id or recipient_id
        to_id = gi.get("xianyu_to_id") or request.user_id or recipient_id
        session.send_message(chat_id, to_id, text)
        db_group_id = str(request.group_id or gi.get("id") or "").strip()
        if db_group_id:
            XianyuService.save_outgoing_text_message(config.id, db_group_id, text)
        return {"ok": True, "channel": "xianyu", "detail": "已发送"}
    except Exception as exc:
        return {"ok": False, "channel": "xianyu", "detail": str(exc)}
