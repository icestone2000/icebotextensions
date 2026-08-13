import json
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolType, ToolCall, ToolExecutionRequest
from config.logging import app_logger
from database.base import SessionLocal

from .message_sender import send_tire_quote_to_customer
from .service import (
    DEFAULT_FORMAT_TEMPLATE,
    DEFAULT_MAX_ROWS,
    NO_PRICE_TEXT,
    PRICE_TABLE_FILENAME,
    TirePriceQueryService,
    format_tire_message,
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


def _first_present(params: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = params.get(k)
        if v is not None and not (isinstance(v, str) and not v.strip()):
            return v
    return None


class TirePriceQueryTool(BaseTool):
    def __init__(
        self,
        service: TirePriceQueryService,
        db_factory: Optional[Callable[[], Session]] = None,
    ):
        self._service = service
        self._db_factory = db_factory or SessionLocal

    def get_name(self) -> str:
        return "tire_price_query"

    def _quote_types_hint(self) -> str:
        """报价类型永远以表头为准，这里运行时读一次真实表头；读不到也绝不能抛异常。"""
        try:
            types = self._service.list_quote_types()
        except Exception as e:
            app_logger.warning("[tire_price_query] list_quote_types failed: %s", e)
            return "报价类型取值以价格表表头为准（除品牌/规格/备注外的列名），可能随时被运营改名或增删。"
        if not types:
            return "报价类型取值以价格表表头为准（除品牌/规格/备注外的列名），当前表格未发现报价类型列。"
        return (
            "报价类型取值以价格表表头为准（除品牌/规格/备注外的列名），可能随时被运营改名或增删；"
            "当前表格的报价类型有：" + "、".join(types) + "。"
        )

    def get_description(self) -> str:
        return (
            "从轮胎价格表 Excel（后端根目录下的「" + PRICE_TABLE_FILENAME + "」）按品牌/型号/报价类型查询轮胎报价，"
            "并可按给定的格式模板拼好正文直接发到当前会话。"
            "参数 model（型号）必填；表格里该列的表头是「规格」，「型号」「规格」是同一个东西。"
            "brand（品牌）不传则返回所有品牌的价格；quote_type（报价类型）不传则返回所有报价类型。"
            + self._quote_types_hint()
            + "报价类型可以只写一部分，如「大客户」「大客户价」都能命中「大客户报价」；写「客户」会同时命中"
            "「大客户报价」「小客户报价」等多列。"
            "型号与品牌支持通配符 * 和 ?（如 205/55R16* 可匹配到带 (POR) 后缀的行）；"
            "匹配前会统一去空格、全角转半角、转大写；不带通配符时先精确匹配，无结果再按「包含」匹配。"
            "某条记录的该报价类型没填价格时，价格位显示「" + NO_PRICE_TEXT + "」。"
            "format_template 是**单条记录**的格式模板，每条命中结果各渲染一次、用换行拼接，"
            "占位符：[序号][品牌][型号]（[规格] 同义）[备注][报价类型][价格]；"
            "例如「[品牌] [型号] [报价类型]：[价格]元」。某行占位符渲染后为空则整行删除。"
            "结果默认最多 " + str(DEFAULT_MAX_ROWS) + " 条（max_rows 可调），超出会截断并在文末注明总条数。"
            "send_to_customer 默认为 true（会尝试发消息，此时 format_template 必填）；若仅需 JSON 请传 send_to_customer=false。"
            "未命中任何记录时不会发送消息，只返回提示信息。"
            "返回值始终包含 available_quote_types（当前表格的报价类型原文列表），报价类型写错时可据此重试。"
            "当工具会主动发消息时，建议在编排里设置 requires_tool_result: false，避免与模型二次回复重复。"
        )

    def get_tool_type(self) -> ToolType:
        return ToolType.DATA_QUERY

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "必填，轮胎型号/规格，如 205/55R16、LT265/60R20(POR)；支持通配符 * ?",
                },
                "brand": {
                    "type": "string",
                    "description": "可选，轮胎品牌，如 马牌；不传则返回所有品牌的价格；支持通配符 * ?",
                },
                "quote_type": {
                    "type": "string",
                    "description": (
                        "可选，报价类型，取值以价格表表头为准（如「大客户报价」「小客户报价」）；"
                        "可只写一部分；不传则返回所有报价类型"
                    ),
                },
                "format_template": {
                    "type": "string",
                    "description": (
                        "单条记录的格式模板，每条命中结果各渲染一次并换行拼接。"
                        "占位符：[序号][品牌][型号][规格][备注][报价类型][价格]。"
                        "send_to_customer 为 true 时必填；默认模板为「" + DEFAULT_FORMAT_TEMPLATE + "」"
                    ),
                },
                "max_rows": {
                    "type": "integer",
                    "description": "可选，最多返回多少条报价，默认 " + str(DEFAULT_MAX_ROWS),
                },
                "price_table_filename": {
                    "type": "string",
                    "description": (
                        "可选；轮胎价格表文件名（仅文件名，位于后端根目录）。"
                        "不传则使用「" + PRICE_TABLE_FILENAME + "」。"
                    ),
                },
                "send_to_customer": {
                    "type": "boolean",
                    "description": "是否把渲染后的报价发送到当前会话；默认 true；false 时仅返回 JSON",
                },
                "recipient_id": {
                    "type": "string",
                    "description": "可选，覆盖当前会话接收方（否则用 request.group_id / group_name）",
                },
            },
            "required": ["model"],
        }

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        params = tool_call.parameters or {}
        model = str(_first_present(params, "model", "型号", "规格") or "").strip()
        brand = str(_first_present(params, "brand", "品牌") or "").strip()
        quote_type = str(_first_present(params, "quote_type", "报价类型") or "").strip()
        format_template = _first_present(params, "format_template", "格式定义", "格式")
        max_rows = _first_present(params, "max_rows", "最大条数")
        price_table_filename = _first_present(params, "price_table_filename", "价格表文件名")
        send_to_customer = _coerce_bool(params.get("send_to_customer"), default=True)
        recipient_override = params.get("recipient_id")

        app_logger.info(
            "[tire_price_query] tool execute start: model=%s, brand=%s, quote_type=%s, "
            "max_rows=%s, price_table_filename=%s, send_to_customer=%s",
            model,
            brand or None,
            quote_type or None,
            max_rows,
            price_table_filename,
            send_to_customer,
        )

        if not model:
            return {"success": False, "error": "model（型号/规格）不能为空"}

        try:
            result = self._service.query(
                model,
                brand=brand,
                quote_type=quote_type,
                max_rows=max_rows,
                price_table_filename=price_table_filename,
            )
        except FileNotFoundError as exc:
            app_logger.warning("[tire_price_query] tool execute file not found: %s", exc)
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            app_logger.exception("[tire_price_query] tool execute failed: %s", exc)
            return {"success": False, "error": str(exc)}

        if result.get("error"):
            app_logger.info(
                "[tire_price_query] tool execute result(error): %s",
                json.dumps(result, ensure_ascii=False),
            )
            return {"success": False, **result}

        base: Dict[str, Any] = {"success": True, **result}
        quotes = result.get("quotes") or []

        if not quotes:
            # 没查到就不发消息，交给大模型自己组织话术
            return {
                **base,
                "message_sent": False,
                "formatted_message": "",
                "send_status": "skipped_no_match",
            }

        if not send_to_customer:
            return {
                **base,
                "message_sent": False,
                "formatted_message": format_tire_message(
                    str(format_template or DEFAULT_FORMAT_TEMPLATE),
                    quotes,
                    result.get("truncation_note") or "",
                ),
                "send_status": "skipped",
            }

        tmpl = str(format_template or "").strip()
        if not tmpl:
            out = {
                **base,
                "message_sent": False,
                "formatted_message": "",
                "send_status": "validation_failed",
                "send_error": "send_to_customer 为 true 时需要提供 format_template",
            }
            app_logger.info(
                "[tire_price_query] tool execute missing template: %s",
                json.dumps(out, ensure_ascii=False),
            )
            return out

        formatted = format_tire_message(tmpl, quotes, result.get("truncation_note") or "")
        db = self._db_factory()
        try:
            send_out = send_tire_quote_to_customer(db, request, recipient_override, formatted)
        except Exception as exc:
            app_logger.exception("[tire_price_query] send_tire_quote_to_customer: %s", exc)
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
            "[tire_price_query] tool execute result(success): %s",
            json.dumps(out, ensure_ascii=False),
        )
        return out
