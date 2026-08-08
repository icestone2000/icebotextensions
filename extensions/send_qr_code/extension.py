from .tool import SendQrCodeTool


def register(ctx):
    try:
        ctx.tool_registry.register_tool(SendQrCodeTool(ctx))
        ctx.logger.info("[send_qr_code] 工具注册成功")
    except Exception as e:
        ctx.logger.warning(f"[send_qr_code] 工具注册失败: {e}")


def unregister(ctx):
    try:
        if hasattr(ctx, "tool_registry") and hasattr(ctx.tool_registry, "unregister_tool"):
            ctx.tool_registry.unregister_tool("send_qr_code")
        ctx.logger.info("[send_qr_code] 工具注销成功")
    except Exception as e:
        ctx.logger.warning(f"[send_qr_code] 工具注销失败: {e}")
