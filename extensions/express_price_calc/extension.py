from .service import ExpressPriceCalcService
from .tool import ExpressPriceQuoteTool


_service = ExpressPriceCalcService()


def register(ctx):
    tool = ExpressPriceQuoteTool(_service, ctx.db_factory)
    try:
        ctx.tool_registry.register_tool(tool)
    except Exception as e:
        ctx.logger.warning(f"[express_price_calc] failed to register express_price_quote: {e}")
        return
    _service.start_mtime_poller()
    ctx.logger.info("[express_price_calc] registered express_price_quote")


def unregister(ctx):
    _service.stop_mtime_poller()
    ctx.logger.info("[express_price_calc] unregister called")
