from .service import TirePriceQueryService
from .tool import TirePriceQueryTool


_service = TirePriceQueryService()


def register(ctx):
    tool = TirePriceQueryTool(_service, ctx.db_factory)
    try:
        ctx.tool_registry.register_tool(tool)
    except Exception as e:
        ctx.logger.warning(f"[tire_price_query] failed to register tire_price_query: {e}")
        return
    _service.start_mtime_poller()
    ctx.logger.info("[tire_price_query] registered tire_price_query")


def unregister(ctx):
    _service.stop_mtime_poller()
    ctx.logger.info("[tire_price_query] unregister called")
