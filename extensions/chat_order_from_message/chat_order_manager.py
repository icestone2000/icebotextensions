"""
聊天建单服务管理器：全局单例 + 懒加载 Session。
"""
from typing import Optional

from sqlalchemy.orm import Session

from config.logging import app_logger
from database.base import SessionLocal

from .chat_order_service import ChatOrderFromMessageService

_service: Optional[ChatOrderFromMessageService] = None


def get_chat_order_from_message_service() -> ChatOrderFromMessageService:
    """获取全局实例；首次调用时创建 Session 并构造 Service。"""
    global _service
    if _service is None:
        app_logger.info("ChatOrderFromMessageService 未初始化，正在自动初始化...")
        db = SessionLocal()
        try:
            _service = ChatOrderFromMessageService(db)
            app_logger.info("ChatOrderFromMessageService 自动初始化成功")
        except Exception as e:
            app_logger.error("ChatOrderFromMessageService 自动初始化失败: %s", e, exc_info=True)
            db.close()
            raise RuntimeError(f"ChatOrderFromMessageService 初始化失败: {e}") from e
    return _service


def initialize_chat_order_from_message_service(db: Session) -> bool:
    global _service
    try:
        app_logger.info("初始化 ChatOrderFromMessageService...")
        _service = ChatOrderFromMessageService(db)
        app_logger.info("ChatOrderFromMessageService 初始化成功")
        return True
    except Exception as e:
        app_logger.error("ChatOrderFromMessageService 初始化失败: %s", e, exc_info=True)
        _service = None
        return False


def cleanup_chat_order_from_message_service() -> None:
    global _service
    if _service is None:
        return
    try:
        app_logger.info("清理 ChatOrderFromMessageService...")
        if hasattr(_service, "db") and _service.db:
            _service.db.close()
    except Exception as e:
        app_logger.warning("清理 ChatOrderFromMessageService 失败: %s", e)
    finally:
        _service = None
        app_logger.info("ChatOrderFromMessageService 资源清理完成")


def is_chat_order_from_message_service_initialized() -> bool:
    return _service is not None
