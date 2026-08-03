from .service import WeatherQueryService
from .tool import WeatherQueryTool

_service = WeatherQueryService()


def register(ctx):
    tool = WeatherQueryTool(_service, ctx.db_factory)
    try:
        ctx.tool_registry.register_tool(tool)
        ctx.logger.info("[weather_query] registered weather_query")
    except Exception as e:
        ctx.logger.warning(f"[weather_query] failed to register: {e}")


def unregister(ctx):
    ctx.logger.info("[weather_query] unregister called")
