from typing import Any, Dict

from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolType, ToolCall, ToolExecutionRequest

from .service import send_qr_code_service


class SendQrCodeTool(BaseTool):
    def __init__(self, ctx=None):
        self._ctx = ctx

    def get_name(self) -> str:
        return "send_qr_code"

    def get_description(self) -> str:
        return (
            "从指定的二维码码库目录中取一张二维码图片，通过微信发送给对方，发送成功后自动删除该图片文件。"
            "必须通过参数 directory 指定码库目录。每调用一次发送一张二维码。"
            "注意：本工具会主动向对方发送图片消息，建议 requires_tool_result 设为 false。"
        )

    def get_tool_type(self) -> ToolType:
        return ToolType.NOTIFICATION

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "二维码图片所在目录（必填），例如 D:/qrcodes/",
                },
                "file_name": {
                    "type": "string",
                    "description": "指定要发送的二维码文件名（可选），不指定时自动从目录中选择一张二维码图片",
                },
            },
            "required": ["directory"],
        }

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        return await send_qr_code_service(self._ctx, tool_call, request)
