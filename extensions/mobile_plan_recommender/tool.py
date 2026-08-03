from typing import Any, Dict

from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolCall, ToolExecutionRequest, ToolType

from .service import MobilePlanRecommenderService


class MobilePlanRecommendTool(BaseTool):
    def __init__(self, service: MobilePlanRecommenderService):
        self._service = service

    def get_name(self) -> str:
        return "mobile_plan_recommend"

    def get_description(self) -> str:
        return "根据自然语言条件推荐手机套餐，支持日级源缓存与查询结果缓存"

    def get_tool_type(self) -> ToolType:
        return ToolType.DATA_QUERY

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询条件，如：联通50左右的、移动流量多的"},
                "top_k": {"type": "integer", "description": "返回数量，默认5，最大10", "minimum": 1, "maximum": 10},
                "force_refresh": {"type": "boolean", "description": "是否强制刷新源数据缓存"},
            },
            "required": ["query"],
        }

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        params = tool_call.parameters or {}
        query = str(params.get("query") or "").strip()
        if not query:
            return {"success": False, "error": "query 不能为空"}

        top_k = int(params.get("top_k") or 5)
        top_k = max(1, min(10, top_k))
        force_refresh = bool(params.get("force_refresh", False))

        try:
            result = await self._service.get_recommendations(
                query=query,
                top_k=top_k,
                force_refresh=force_refresh,
            )
            return {"success": True, **result}
        except Exception as exc:
            return {"success": False, "error": str(exc), "query": query}

