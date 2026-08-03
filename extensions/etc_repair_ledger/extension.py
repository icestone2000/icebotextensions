from .service import RepairLedgerService
from .tool import EtcRepairLedgerTool

_service = RepairLedgerService()


def register(ctx):
    tool = EtcRepairLedgerTool(_service)
    try:
        ctx.tool_registry.register_tool(tool)
        ctx.logger.info("[etc_repair_ledger] registered etc_repair_ledger_record")
    except Exception as e:
        ctx.logger.warning(f"[etc_repair_ledger] failed to register: {e}")


def unregister(ctx):
    try:
        _service.stop()
    except Exception as e:
        ctx.logger.warning(f"[etc_repair_ledger] stop service failed: {e}")
    ctx.logger.info("[etc_repair_ledger] unregister called")
