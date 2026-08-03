from .service import KingHonorBoostPriceCalcService
from .tool import KingHonorBoostPriceCalcTool


_service = KingHonorBoostPriceCalcService()
_tool = KingHonorBoostPriceCalcTool(_service)


def register(ctx):
    try:
        ctx.tool_registry.register_tool(_tool)
        ctx.logger.info("[king_honor_boost_price_calc] registered king_honor_boost_price_calc")
    except Exception as e:
        ctx.logger.warning(f"[king_honor_boost_price_calc] failed to register king_honor_boost_price_calc: {e}")


def unregister(ctx):
    ctx.logger.info("[king_honor_boost_price_calc] unregister called")
