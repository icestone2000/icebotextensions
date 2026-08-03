"""
快递单转发服务管理器
"""
from typing import Optional

from config.logging import app_logger

from .waybill_forward_service import WaybillForwardService

_waybill_forward_service: Optional[WaybillForwardService] = None


def get_waybill_forward_service() -> WaybillForwardService:
    """获取全局WaybillForwardService实例，第一次调用时自动初始化"""
    global _waybill_forward_service
    if _waybill_forward_service is None:
        app_logger.info("WaybillForwardService未初始化，正在自动初始化...")
        _waybill_forward_service = WaybillForwardService()
        app_logger.info("WaybillForwardService自动初始化成功")
    return _waybill_forward_service


def initialize_waybill_forward_service() -> bool:
    """显式初始化全局WaybillForwardService实例"""
    global _waybill_forward_service
    try:
        app_logger.info("初始化WaybillForwardService...")
        _waybill_forward_service = WaybillForwardService()
        app_logger.info("WaybillForwardService初始化成功")
        return True
    except Exception as e:
        _waybill_forward_service = None
        app_logger.error(f"WaybillForwardService初始化失败: {e}", exc_info=True)
        return False


def cleanup_waybill_forward_service():
    """清理全局WaybillForwardService实例"""
    global _waybill_forward_service
    if _waybill_forward_service is None:
        return
    try:
        app_logger.info("清理WaybillForwardService资源...")
        _waybill_forward_service.stop()
    except Exception as e:
        app_logger.warning(f"WaybillForwardService资源清理失败: {e}", exc_info=True)
    finally:
        _waybill_forward_service = None
        app_logger.info("WaybillForwardService资源清理完成")


def is_waybill_forward_service_initialized() -> bool:
    """检查WaybillForwardService是否已初始化"""
    return _waybill_forward_service is not None
