from typing import Any, Dict

from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolType, ToolCall, ToolExecutionRequest

from .hello import greet


class HelloTool(BaseTool):
    def get_name(self) -> str:
        return "hello_tool"

    def get_description(self) -> str:
        return "Hello 扩展示例工具"

    def get_tool_type(self) -> ToolType:
        return ToolType.SYSTEM_ACTION

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "要问候的名字"},
            },
        }

    def is_enabled(self) -> bool:
        return True

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        name = (tool_call.parameters or {}).get("name") or "world"
        return {"success": True, "result": greet(str(name))}


def register(ctx):
    # Register a tool (optional). This demonstrates tool registration from extensions.
    try:
        ctx.tool_registry.register_tool(HelloTool())
        ctx.logger.info("[hello_ext] registered HelloTool")
    except Exception as e:
        ctx.logger.warning(f"[hello_ext] failed to register HelloTool: {e}")


def unregister(ctx):
    # Optional cleanup hook. Tool removal is handled by ExtensionManager using tracked tool names.
    ctx.logger.info("[hello_ext] unregister called")

