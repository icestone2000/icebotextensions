"""
将快递询价结果文本发到当前会话：个人微信 / 企业微信第三方 / 闲鱼。
逻辑对齐 SendNotificationTool（文本）与 SendMediaTool（闲鱼上下文）。
"""
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


def send_quote_text_to_customer(
    db: Session,
    request: ToolExecutionRequest,
    recipient_id_override: Optional[str],
    text: str,
) -> Dict[str, Any]:
    """
    返回 {\"ok\": bool, \"channel\": str, \"detail\": str}
    """
    recipient_id = (
        str(recipient_id_override).strip()
        if recipient_id_override
        else ""
    )
    if not recipient_id:
        recipient_id = (request.group_id or request.group_name or "").strip()
    if not recipient_id:
        return {"ok": False, "channel": "", "detail": "缺少接收方：请提供 recipient_id 或确保 request 含 group_id/group_name"}

    config = resolve_wechat_config(db, request)

    if not config:
        app_logger.warning("[express_price_calc] 无法解析微信配置，回退个人微信服务")
        return _send_personal_wechat(recipient_id, text)

    account_type = (config.account_type or "").strip()
    app_logger.info(
        "[express_price_calc] send resolved config_id=%s account_type=%s recipient=%s",
        config.id,
        account_type,
        recipient_id,
    )

    if account_type == "xianyu":
        return _send_xianyu(db, config, request, recipient_id, text)

    if account_type == "official":
        instance = _get_wecom_instance(db, config)
        if not instance:
            return {"ok": False, "channel": "wecom", "detail": "企业微信实例不存在或未登录"}
        return _send_wecom(instance, recipient_id, text, db)

    return _send_personal_wechat(recipient_id, text)


def _get_wecom_instance(db: Session, config: WeChatConfig) -> Optional[WeComThirdPartyInstance]:
    try:
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
    except Exception as e:
        app_logger.error("[express_price_calc] _get_wecom_instance: %s", e, exc_info=True)
        return None


def _send_personal_wechat(recipient_id: str, text: str) -> Dict[str, Any]:
    try:
        wechat_service = get_wechat_service()
        send_result = wechat_service.send_message(
            MessageSend(chat_id=recipient_id, content=text, message_type=MessageType.TEXT)
        )
        if send_result.success:
            return {"ok": True, "channel": "wechat_personal", "detail": "已发送"}
        return {"ok": False, "channel": "wechat_personal", "detail": send_result.error or "发送失败"}
    except RuntimeError as e:
        return {"ok": False, "channel": "wechat_personal", "detail": str(e)}
    except Exception as e:
        app_logger.exception("[express_price_calc] personal wechat send: %s", e)
        return {"ok": False, "channel": "wechat_personal", "detail": str(e)}


def _send_wecom(
    instance: WeComThirdPartyInstance,
    recipient_id: str,
    text: str,
    db: Session,
) -> Dict[str, Any]:
    try:
        config_manager = get_config_manager(db)
        server_url = config_manager.get_config("wecom_third_party.server_url", "") or ""
        wecom_service = WeComThirdPartyService(server_url=server_url, db=db)
        send_result = wecom_service.send_text_message(
            guid=instance.guid,
            content=text,
            to_id=recipient_id,
            license_code=instance.license_code,
        )
        if send_result and not send_result.get("pending"):
            return {"ok": True, "channel": "wecom_third_party", "detail": "已发送"}
        return {"ok": True, "channel": "wecom_third_party", "detail": "请求已受理（可能异步）"}
    except Exception as e:
        app_logger.exception("[express_price_calc] wecom send: %s", e)
        return {"ok": False, "channel": "wecom_third_party", "detail": str(e)}


def _send_xianyu(
    _db: Session,
    config: WeChatConfig,
    request: ToolExecutionRequest,
    recipient_id: str,
    text: str,
) -> Dict[str, Any]:
    try:
        from services.xianyu_service import XianyuService

        app_logger.info(
            "[express_price_calc] xianyu session lookup: config_id=%s, sessions_keys=%s",
            config.id,
            list(XianyuService._sessions.keys()),
        )
        session = XianyuService._sessions.get(config.id)
        app_logger.info(
            "[express_price_calc] xianyu session lookup result: config_id=%s, session=%r",
            config.id,
            session,
        )
        if not session:
            return {"ok": False, "channel": "xianyu", "detail": "闲鱼会话未运行，请先启动该闲鱼账号"}

        group_info = (request.context or {}).get("group_info") or {}
        chat_id = group_info.get("xianyu_chat_id") or request.group_id or recipient_id
        to_id = group_info.get("xianyu_to_id") or request.user_id or recipient_id
        if not chat_id or not to_id:
            return {
                "ok": False,
                "channel": "xianyu",
                "detail": "闲鱼发送需要 context.group_info.xianyu_chat_id 与 xianyu_to_id（或 request.user_id）",
            }
        session.send_message(chat_id, to_id, text)
        gi = (request.context or {}).get("group_info") or {}
        db_group_id = (
            str(request.group_id or "").strip()
            or str(gi.get("id") or "").strip()
        )
        if db_group_id:
            XianyuService.save_outgoing_text_message(config.id, db_group_id, text)
        else:
            app_logger.warning(
                "[express_price_calc] 闲鱼消息已发送但未落库：缺少 request.group_id 与 context.group_info.id"
            )
        return {"ok": True, "channel": "xianyu", "detail": "已发送"}
    except Exception as e:
        app_logger.exception("[express_price_calc] xianyu send: %s", e)
        return {"ok": False, "channel": "xianyu", "detail": str(e)}
