import os
from typing import Any, Dict, Optional

from schemas.tool_calling import ToolCall, ToolExecutionRequest

from .message_sender import send_media_to_customer

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".jfif"}


def _pick_qr_file(directory: str, file_name: Optional[str] = None) -> Optional[str]:
    if not os.path.isdir(directory):
        return None
    if file_name:
        path = os.path.join(directory, file_name)
        if os.path.isfile(path):
            return path
        return None
    try:
        files = sorted(
            f for f in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, f))
            and os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
        )
    except OSError:
        return None
    if not files:
        return None
    return os.path.join(directory, files[0])


async def send_qr_code_service(ctx, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
    if ctx is None or not hasattr(ctx, "db_factory"):
        return {"success": False, "error": "扩展上下文不可用，无法获取数据库连接"}

    db = None
    try:
        params = tool_call.parameters or {}
        directory = (params.get("directory") or "").strip()
        file_name = (params.get("file_name") or "").strip() or None

        if not directory:
            return {"success": False, "error": "缺少必填参数 directory（二维码码库目录）"}
        if not os.path.isdir(directory):
            return {"success": False, "error": f"二维码码库目录不存在: {directory}"}

        qr_path = _pick_qr_file(directory, file_name)
        if not qr_path:
            return {"success": False, "error": f"二维码目录中没有可用图片: {directory}"}

        db = ctx.db_factory()
        if db is None:
            return {"success": False, "error": "数据库连接创建失败"}

        send_result = send_media_to_customer(db, request, None, qr_path, media_type="image")
        if not send_result.get("ok"):
            return {
                "success": False,
                "error": f"发送二维码失败: {send_result.get('detail', '')}",
                "file": os.path.basename(qr_path),
            }

        removed = False
        try:
            os.remove(qr_path)
            removed = True
        except Exception as e:
            if getattr(ctx, "logger", None):
                ctx.logger.warning(f"[send_qr_code] 删除二维码文件失败: {e}")

        return {
            "success": True,
            "message": "二维码已发送" + ("并已从码库删除" if removed else "，发送成功但文件删除失败"),
            "file": os.path.basename(qr_path),
            "channel": send_result.get("channel", ""),
            "detail": send_result.get("detail", ""),
            "removed": removed,
        }
    except Exception as e:
        return {"success": False, "error": f"发送二维码异常: {e}"}
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
