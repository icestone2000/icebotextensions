import json
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolCall, ToolExecutionRequest, ToolType
from config.logging import app_logger
from database.base import SessionLocal

from .message_sender import send_quote_text_to_customer
from .service import (
    PRICE_TABLE_FILENAME,
    ExpressPriceCalcService,
    PLACEHOLDER_MAX_INDEX,
    format_quote_message,
)


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) and value != 0
    s = str(value).strip().lower()
    if s in ("false", "0", "no", "off", "n"):
        return False
    if s in ("true", "1", "yes", "on", "y"):
        return True
    return default


class ExpressPriceQuoteTool(BaseTool):
    def __init__(
        self,
        service: ExpressPriceCalcService,
        db_factory: Optional[Callable[[], Session]] = None,
    ):
        self._service = service
        self._db_factory = db_factory or SessionLocal

    def get_name(self) -> str:
        return "express_price_quote"

    def get_description(self) -> str:
        return (
            "根据价格表 Excel（默认与后端根目录下同名的「" + PRICE_TABLE_FILENAME + "」）计算各快递公司运费；"
            "可选 price_table_filename（兼容中文键「价格表文件名」）指定同目录下其它文件名，多表分文件缓存。"
            "输入起始省份、目的省份、可选重量（千克）；未传或格式无效时按 1kg 计价。"
            "可选长宽高 length_cm/width_cm/height_cm（厘米），兼容中文键“长(cm)”“宽(cm)”“高(cm)”；"
            "三者齐全且为正时计算体积重=长×宽×高/8000；实重与体积重都会先向上取整，再取 max(实重,体积重) 作为计费重量；缺一或无效则忽略体积、按原重量（向上取整）计费。"
            "可选补差基数 compensation_base（兼容中文键名“补差基数”）；"
            "补差值=当前返回结果最低价-补差基数，若小于0则为0。"
            "可选 courier_name：传入则仅计算并返回该快递公司一条报价（名称需与价格表中「快递公司」一致，首尾空白可忽略）。"
            "返回每条含总价 price、以及每公斤续重单价 continuation_price_per_kg（首重按 1kg，超出部分续重按千克向上取整）。"
            "算价后可按 message_template 拼好正文发到当前会话（依赖 request 的 config_id/group_id/context；闲鱼需 group_info.xianyu_chat_id、xianyu_to_id）。"
            "占位符全文替换：[出发省份][目的省份][重量][最便宜的快递名][补差值]；"
            "按总价升序编号 [价格1]…[价格" + str(PLACEHOLDER_MAX_INDEX) + "]、[快递名i]、[续重价i]"
            "（某行的编号占位符全部超出实际报价条数时整行删除，不会留下空壳文字）。"
            "send_to_customer 默认为 true（会尝试发消息）；若仅需 JSON 请传 send_to_customer=false。"
            "当工具会主动发消息时，建议在编排里设置 requires_tool_result: false，避免与模型二次回复重复。"
        )

    def get_tool_type(self) -> ToolType:
        return ToolType.DATA_QUERY

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "origin_province": {"type": "string", "description": "起始省份，如 安徽、广东省"},
                "dest_province": {"type": "string", "description": "目的省份"},
                "weight_kg": {
                    "type": "number",
                    "description": "重量（千克）；不传或无法解析或非正数时按 1kg",
                },
                "length_cm": {
                    "type": "number",
                    "description": "可选，货物长（厘米）；与 width_cm、height_cm 齐全的生效体积重",
                },
                "width_cm": {
                    "type": "number",
                    "description": "可选，货物宽（厘米）",
                },
                "height_cm": {
                    "type": "number",
                    "description": "可选，货物高（厘米）",
                },
                "compensation_base": {
                    "type": "number",
                    "description": "可选，补差基数；兼容中文参数“补差基数”。补差值=max(最低价-补差基数, 0)",
                },
                "courier_name": {
                    "type": "string",
                    "description": "可选；指定快递公司名称时只返回该公司的报价",
                },
                "price_table_filename": {
                    "type": "string",
                    "description": (
                        "可选；快递价格表文件名（仅文件名，位于后端根目录，与默认表同目录）。"
                        "不传则使用「" + PRICE_TABLE_FILENAME + "」。"
                    ),
                },
                "send_to_customer": {
                    "type": "boolean",
                    "description": "是否在算价后向当前会话发送 message_template；默认 true；false 时仅返回 JSON",
                },
                "message_template": {
                    "type": "string",
                    "description": (
                        "发送正文模板（send_to_customer 为 true 时必填）。占位符见工具说明。"
                    ),
                },
                "recipient_id": {
                    "type": "string",
                    "description": "可选，覆盖当前会话接收方（否则用 request.group_id / group_name）",
                },
            },
            "required": ["origin_province", "dest_province"],
        }

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        params = tool_call.parameters or {}
        origin = str(params.get("origin_province") or "").strip()
        dest = str(params.get("dest_province") or "").strip()
        weight_raw = params.get("weight_kg")
        compensation_base_raw = params.get("compensation_base")
        if compensation_base_raw is None:
            compensation_base_raw = params.get("补差基数")
        length_raw = params.get("length_cm")
        if length_raw is None:
            length_raw = params.get("长(cm)")
        width_raw = params.get("width_cm")
        if width_raw is None:
            width_raw = params.get("宽(cm)")
        height_raw = params.get("height_cm")
        if height_raw is None:
            height_raw = params.get("高(cm)")
        courier_raw = params.get("courier_name")
        price_table_filename = params.get("price_table_filename")
        if price_table_filename is None:
            price_table_filename = params.get("价格表文件名")
        send_to_customer = _coerce_bool(params.get("send_to_customer"), default=True)
        message_template = params.get("message_template")
        recipient_override = params.get("recipient_id")

        app_logger.info(
            "[express_price_calc] tool execute start: origin=%s, dest=%s, price_table_filename=%s, weight_raw=%s, compensation_base_raw=%s, length_cm=%s, width_cm=%s, height_cm=%s, courier_name=%s, send_to_customer=%s",
            origin,
            dest,
            price_table_filename,
            weight_raw,
            compensation_base_raw,
            length_raw,
            width_raw,
            height_raw,
            courier_raw,
            send_to_customer,
        )

        if not origin:
            return {"success": False, "error": "origin_province 不能为空"}
        if not dest:
            return {"success": False, "error": "dest_province 不能为空"}

        try:
            result = self._service.quote(
                origin,
                dest,
                weight_raw,
                courier_name=courier_raw,
                compensation_base=compensation_base_raw,
                length_cm=length_raw,
                width_cm=width_raw,
                height_cm=height_raw,
                price_table_filename=price_table_filename,
            )
        except FileNotFoundError as exc:
            app_logger.warning("[express_price_calc] tool execute file not found: %s", exc)
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            app_logger.exception("[express_price_calc] tool execute failed: %s", exc)
            return {"success": False, "error": str(exc)}

        if result.get("error"):
            app_logger.info(
                "[express_price_calc] tool execute result(error): %s",
                json.dumps(result, ensure_ascii=False),
            )
            return {"success": False, **result}

        base: Dict[str, Any] = {"success": True, **result}

        if not send_to_customer:
            out = {
                **base,
                "message_sent": False,
                "formatted_message": "",
                "send_status": "skipped",
            }
            app_logger.info(
                "[express_price_calc] tool execute result(success, no send): %s",
                json.dumps(out, ensure_ascii=False),
            )
            return out

        tmpl = str(message_template or "").strip()
        if not tmpl:
            out = {
                **base,
                "message_sent": False,
                "formatted_message": "",
                "send_status": "validation_failed",
                "send_error": "send_to_customer 为 true 时需要提供 message_template",
            }
            app_logger.info(
                "[express_price_calc] tool execute missing template: %s",
                json.dumps(out, ensure_ascii=False),
            )
            return out

        formatted = format_quote_message(tmpl, result)
        db = self._db_factory()
        try:
            send_out = send_quote_text_to_customer(
                db, request, recipient_override, formatted
            )
        except Exception as exc:
            app_logger.exception("[express_price_calc] send_quote_text_to_customer: %s", exc)
            send_out = {"ok": False, "channel": "", "detail": str(exc)}
        finally:
            db.close()

        ok = bool(send_out.get("ok"))
        out = {
            **base,
            "message_sent": ok,
            "formatted_message": formatted,
            "send_status": "sent" if ok else "failed",
            **({"send_error": send_out.get("detail")} if not ok else {}),
        }
        app_logger.info(
            "[express_price_calc] tool execute result(success): %s",
            json.dumps(out, ensure_ascii=False),
        )
        return out
