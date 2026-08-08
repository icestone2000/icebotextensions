import os
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from schemas.tool_calling import ToolExecutionRequest
from schemas.wechat import MessageSend, MessageType
from core.wechat_manager import get_wechat_service
from models.wecom_third_party import WeComThirdPartyInstance
from services.wecom_third_party_service import WeComThirdPartyService
from utils.config_manager import get_config_manager
from utils.wechat_config_resolver import resolve_wechat_config


def _resolve_media_path(file_path: str) -> str:
    p = (file_path or "").strip()
    if not p:
        return ""
    if os.path.isabs(p) or os.path.exists(p):
        return p
    return os.path.join("uploads", p)


def send_media_to_customer(
    db: Session,
    request: ToolExecutionRequest,
    recipient_id_override: Optional[str],
    file_path: str,
    media_type: str = "image",
) -> Dict[str, Any]:
    """发送图片/视频/文件。返回 {"ok": bool, "channel": str, "detail": str}"""
    media_type = (media_type or "image").strip().lower()
    if media_type not in ("image", "video", "file"):
        return {"ok": False, "channel": "", "detail": f"不支持的 media_type: {media_type}"}

    path = _resolve_media_path(file_path)
    if not path or not os.path.exists(path):
        return {"ok": False, "channel": "", "detail": f"文件不存在: {file_path}"}

    recipient_id = str(recipient_id_override or "").strip()
    if not recipient_id:
        recipient_id = (request.group_name or "").strip()
    if not recipient_id:
        return {"ok": False, "channel": "", "detail": "缺少接收方"}

    msg_type = {
        "image": MessageType.IMAGE,
        "video": MessageType.VIDEO,
        "file": MessageType.FILE,
    }[media_type]

    config = resolve_wechat_config(db, request)
    if not config:
        try:
            r = get_wechat_service().send_message(
                MessageSend(chat_id=recipient_id, content=path, message_type=msg_type)
            )
            return {"ok": r.success, "channel": "wechat_personal", "detail": r.error or "已发送"}
        except Exception as e:
            return {"ok": False, "channel": "wechat_personal", "detail": str(e)}

    account_type = (config.account_type or "").strip()

    if account_type == "xianyu":
        # 闲鱼：图片与视频均用 send_image；不支持普通文件
        if media_type == "file":
            return {"ok": False, "channel": "xianyu", "detail": "闲鱼暂不支持发送文件"}
        from services.xianyu_service import XianyuService
        session = XianyuService._sessions.get(config.id)
        if not session:
            return {"ok": False, "channel": "xianyu", "detail": "闲鱼会话未运行"}
        gi = (request.context or {}).get("group_info") or {}
        chat_id = gi.get("xianyu_chat_id") or request.group_id or recipient_id
        to_id = gi.get("xianyu_to_id") or request.user_id or recipient_id
        session.send_image(chat_id, to_id, path)
        return {"ok": True, "channel": "xianyu", "detail": "已发送"}

    if account_type == "official":
        instance = db.query(WeComThirdPartyInstance).filter(
            WeComThirdPartyInstance.wecom_user_id == config.wxid,
            WeComThirdPartyInstance.status == 2,
        ).first()
        if not instance:
            return {"ok": False, "channel": "wecom", "detail": "企微实例未登录"}
        server_url = get_config_manager(db).get_config("wecom_third_party.server_url", "") or ""
        svc = WeComThirdPartyService(server_url=server_url, db=db)
        if media_type == "image":
            svc.send_image_message_by_file_name(
                guid=instance.guid, filename_or_path=path, to_id=recipient_id,
                license_code=instance.license_code,
            )
        elif media_type == "video":
            svc.send_video_message_by_file_name(
                guid=instance.guid, filename_or_path=path, to_id=recipient_id,
                license_code=instance.license_code,
            )
        else:
            svc.send_file_message_by_file_name(
                guid=instance.guid, filename_or_path=path, to_id=recipient_id,
                license_code=instance.license_code,
            )
        return {"ok": True, "channel": "wecom", "detail": "已发送"}

    try:
        r = get_wechat_service().send_message(
            MessageSend(chat_id=recipient_id, content=path, message_type=msg_type)
        )
        return {"ok": r.success, "channel": "wechat_personal", "detail": r.error or "已发送"}
    except Exception as e:
        return {"ok": False, "channel": "wechat_personal", "detail": str(e)}
