from typing import Any, Dict

from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolCall, ToolExecutionRequest, ToolType

from .service import KingHonorBoostPriceCalcService


class KingHonorBoostPriceCalcTool(BaseTool):
    def __init__(self, service: KingHonorBoostPriceCalcService):
        self._service = service

    def get_name(self) -> str:
        return "king_honor_boost_price_calc"

    def get_description(self) -> str:
        return "根据王者荣耀代练价格表和星级区间，计算总代练报价"

    def get_tool_type(self) -> ToolType:
        return ToolType.DATA_QUERY

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "price_table_text": {"type": "string", "description": "代练价格表文本"},
                "star_level_input": {"type": "string", "description": "星级输入，如 70 或 70-90"},
            },
            "required": ["price_table_text", "star_level_input"],
        }

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        params = tool_call.parameters or {}
        price_table_text = str(params.get("price_table_text") or "").strip()
        star_level_input = str(params.get("star_level_input") or "").strip()

        if not price_table_text:
            return {"success": False, "error": "price_table_text 不能为空"}
        if not star_level_input:
            return {"success": False, "error": "star_level_input 不能为空"}

        try:
            result = await self._service.calculate_price(
                price_table_text=price_table_text,
                star_level_input=star_level_input,
                llm_config_id=request.llm_config_id,
            )
            return {"success": True, **result}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
