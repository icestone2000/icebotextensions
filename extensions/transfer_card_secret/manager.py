"""全局单例（无数据库会话）。"""
from typing import Optional

from config.logging import app_logger

from .service import TransferCardSecretService

_service: Optional[TransferCardSecretService] = None


def get_transfer_card_secret_service() -> TransferCardSecretService:
    global _service
    if _service is None:
        app_logger.info("TransferCardSecretService 懒加载初始化")
        _service = TransferCardSecretService()
    return _service


def cleanup_transfer_card_secret_service() -> None:
    global _service
    _service = None


def clear_transfer_card_secret_pending() -> None:
    """清空全局单例上的待发货窗口（测试或运维）。"""
    if _service is not None:
        _service.clear_pending()
