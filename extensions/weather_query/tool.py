from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from config.logging import app_logger
from database.base import SessionLocal
from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolCall, ToolExecutionRequest, ToolType

from .message_sender import send_text_to_customer
from .service import WeatherQueryService, format_weather_message


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("false", "0", "no", "off"):
        return False
    if s in ("true", "1", "yes", "on"):
        return True
    return default


class WeatherQueryTool(BaseTool):
    def __init__(
        self,
        service: WeatherQueryService,
        db_factory: Optional[Callable[[], Session]] = None,
    ):
        self._service = service
        self._db_factory = db_factory or SessionLocal

    def get_name(self) -> str:
        return "weather_query"

    def get_description(self) -> str:
        return (
            "查询指定城市的实时天气，并将格式化天气信息发送到当前会话。"
            "当用户询问某地天气、气温、是否下雨等时使用。"
            "参数 city 为城市名，如 北京、上海、深圳。"
            "send_to_customer 默认为 true，会主动发消息；仅要 JSON 时传 false。"
            "工具会主动发消息时，编排宜设置 requires_tool_result: false，避免重复回复。"
        )

    def get_tool_type(self) -> ToolType:
        return ToolType.DATA_QUERY

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，如 北京、上海、杭州"},
                "send_to_customer": {
                    "type": "boolean",
                    "description": "是否将天气信息发送到当前会话，默认 true",
                },
                "recipient_id": {
                    "type": "string",
                    "description": "可选，覆盖接收方；默认当前会话",
                },
            },
            "required": ["city"],
        }

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        params = tool_call.parameters or {}
        city = str(params.get("city") or "").strip()
        send_to_customer = _coerce_bool(params.get("send_to_customer"), default=True)
        recipient_override = params.get("recipient_id")

        if not city:
            return {"success": False, "error": "city 不能为空"}

        try:
            weather = await self._service.query(city)
        except Exception as exc:
            app_logger.exception("[weather_query] query failed: %s", exc)
            return {"success": False, "error": str(exc), "city": city}

        if weather.get("error"):
            return {"success": False, **weather, "city": city}

        message = format_weather_message(weather)
        base = {"success": True, "city": city, "weather": weather, "formatted_message": message}

        if not send_to_customer:
            return {**base, "message_sent": False, "send_status": "skipped"}

        db = self._db_factory()
        try:
            send_out = send_text_to_customer(db, request, recipient_override, message)
        finally:
            db.close()

        ok = bool(send_out.get("ok"))
        return {
            **base,
            "message_sent": ok,
            "send_status": "sent" if ok else "failed",
            **({"send_error": send_out.get("detail")} if not ok else {}),
        }
