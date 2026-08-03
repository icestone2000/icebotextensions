from typing import Any, Dict

from config.logging import app_logger
from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolCall, ToolExecutionRequest, ToolType

from .service import RepairLedgerService, RepairRecord, parse_report_time, resolve_excel_path


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    return default


class EtcRepairLedgerTool(BaseTool):
    def __init__(self, service: RepairLedgerService):
        self._service = service

    def get_name(self) -> str:
        return "etc_repair_ledger_record"

    def get_description(self) -> str:
        return (
            "把ETC收费站的设备故障报修信息记录到Excel报修台账。"
            "当群消息中出现收费站/车道的故障报修（如读不到卡、不抬杆、天线异常、"
            "语音不播报、电脑黑屏等）时调用。"
            "收费站信息必需；针对具体车道的故障（lane_required=true）车道信息必需。"
            "必需信息缺失时记录会暂存并返回 status=awaiting_info，此时应在群里@报修人补充信息；"
            "超时后按现有信息自动写入台账。信息完整则异步写入台账并自动去重。"
            "参数 excel_file 为台账文件名或完整路径，无路径时保存在程序目录。"
        )

    def get_tool_type(self) -> ToolType:
        return ToolType.FILE_OPERATION

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "excel_file": {
                    "type": "string",
                    "description": "台账Excel文件名或完整路径，如 报修台账.xlsx；无路径时保存在程序目录",
                },
                "station": {
                    "type": "string",
                    "description": "收费站名称，如 久长站、威宁北；消息和昵称都无法确定时填 未知",
                },
                "lane": {
                    "type": "string",
                    "description": "车道号，如 85、出口84、入口163；消息中没有可不传",
                },
                "lane_required": {
                    "type": "boolean",
                    "description": "该故障是否必须提供车道号：故障针对具体车道（读不到卡、不抬杆、语音不播报等）填 true；全站性/平台性故障填 false",
                },
                "description": {
                    "type": "string",
                    "description": "故障描述，一句话概括故障现象，保留车牌号等关键细节",
                },
                "reporter": {
                    "type": "string",
                    "description": "报修人微信名（发送报修消息的群成员昵称）",
                },
                "report_time": {
                    "type": "string",
                    "description": "报修时间，格式 YYYY-MM-DD HH:MM:SS；不确定时可不传，默认当前时间",
                },
            },
            "required": ["excel_file", "description", "reporter"],
        }

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        params = tool_call.parameters or {}
        excel_file = str(params.get("excel_file") or "").strip()
        station = str(params.get("station") or "").strip()
        lane = str(params.get("lane") or "").strip()
        lane_required = _coerce_bool(params.get("lane_required"), default=False)
        description = str(params.get("description") or "").strip()
        reporter = str(params.get("reporter") or "").strip()

        if not excel_file:
            return {"success": False, "error": "excel_file 不能为空"}
        if not description:
            return {"success": False, "error": "description 不能为空"}
        if not reporter:
            return {"success": False, "error": "reporter 不能为空"}

        try:
            excel_path = resolve_excel_path(excel_file)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        record = RepairRecord(
            station=station,
            lane=lane,
            description=description,
            reporter=reporter,
            report_time=parse_report_time(params.get("report_time")),
        )
        group_key = str(request.group_id or request.group_name or "")

        try:
            result = self._service.submit(
                excel_path, record, lane_required=lane_required, group_key=group_key
            )
        except Exception as exc:
            app_logger.exception("[etc_repair_ledger] 提交报修记录失败: %s", exc)
            return {"success": False, "error": str(exc)}

        status = result["status"]
        if status == "awaiting_info":
            missing = "、".join(result["missing"])
            wait_min = max(1, int(result["wait_seconds"] // 60))
            return {
                "success": True,
                "status": "awaiting_info",
                "missing": result["missing"],
                "already_asked": result["already_asked"],
                "message": (
                    f"报修信息缺少：{missing}，已暂存。"
                    + (
                        f"请在群里@{reporter} 补充{missing}信息，"
                        f"{wait_min}分钟内未补充将按现有信息记录台账。"
                        if not result["already_asked"]
                        else "此前已提醒过报修人，无需再次提醒。"
                    )
                ),
            }
        if status == "duplicate":
            return {
                "success": True,
                "status": "duplicate",
                "duplicate": True,
                "message": "该报修与近期已记录的台账重复，已跳过",
                "excel_file": excel_path,
            }
        return {
            "success": True,
            "status": "recorded",
            "message": "报修记录已提交" + ("（已合并此前待补充的报修）" if result.get("merged") else ""),
            "excel_file": excel_path,
            "pending": result.get("pending"),
        }
