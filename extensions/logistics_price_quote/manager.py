"""全局单例（无数据库会话）。"""
from typing import Optional

from config.logging import app_logger

from .service import LogisticsPriceQuoteService

_service: Optional[LogisticsPriceQuoteService] = None


def get_logistics_price_quote_service() -> LogisticsPriceQuoteService:
    global _service
    if _service is None:
        app_logger.info("LogisticsPriceQuoteService 懒加载初始化")
        _service = LogisticsPriceQuoteService()
    return _service


def cleanup_logistics_price_quote_service() -> None:
    global _service
    _service = None
