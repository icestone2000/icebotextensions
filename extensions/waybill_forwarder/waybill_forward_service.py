"""
快递单双向转发服务
"""
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Set

from config.logging import app_logger
from schemas.wechat import MessageSend, MessageType


class WaybillForwardService:
    """快递单双向转发服务"""

    _CLEANUP_INTERVAL_SECONDS = 5 * 60
    _YT_PATTERN = r"YT\d{12,13}"
    _JT_PATTERN = r"(?<![A-Za-z0-9])JT\d{13}(?!\d)"
    _CHINA_POST_PATTERN = r"(?<!\d)9\d{12}(?!\d)"
    _ZTO_PATTERN = r"(?<!\d)78\d{10,11}(?!\d)"
    _YUNDA_PATTERN = r"(?<!\d)3\d{12}(?!\d)"
    _NUMERIC_PATTERN = r"(?<!\d)\d{15}(?!\d)"

    def __init__(self):
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._waybill_map: Dict[str, Dict[str, Any]] = {}
        self._store_file = os.path.join(os.path.dirname(__file__), "waybill_map.json")

        self._load_map_from_json()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="WaybillForwardCleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def forward_from_daifa_group(
        self,
        context: Dict[str, Any],
        target_group: str,
        valid_minutes: int = 60,
    ) -> Dict[str, Any]:
        """处理代发群消息并转发到物流群"""
        try:
            message_content = (context or {}).get("message_content", "")
            source_group_name = (context or {}).get("group_name", "")
            sender_name = (context or {}).get("sender_name", "")

            waybills = self._extract_waybills(message_content)
            if not waybills:
                return {"success": False, "message": "消息中未识别到快递单号"}
            if not source_group_name:
                return {"success": False, "message": "context中缺少group_name"}
            if not target_group:
                return {"success": False, "message": "target_group不能为空"}
            if valid_minutes <= 0:
                return {"success": False, "message": "valid_minutes必须大于0"}

            now_ts = time.time()
            expire_ts = now_ts + valid_minutes * 60
            with self._lock:
                for waybill in waybills:
                    self._waybill_map[waybill] = {
                        "expire_ts": expire_ts,
                        "group_name": source_group_name,
                    }
                self._save_map_to_json_locked()

            from core.wechat_manager import get_wechat_service

            wechat_service = get_wechat_service()
            forward_send = MessageSend(
                chat_id=target_group,
                content=message_content,
                message_type=MessageType.TEXT,
            )
            forward_result = wechat_service.send_message(forward_send)
            if not forward_result.success:
                return {"success": False, "message": f"转发到物流群失败: {forward_result.error}"}

            receipt_text = f"@{sender_name} 消息已转发至{target_group}" if sender_name else f"消息已转发至{target_group}"
            receipt_send = MessageSend(
                chat_id=source_group_name,
                content=receipt_text,
                message_type=MessageType.TEXT,
            )
            receipt_result = wechat_service.send_message(receipt_send)
            if not receipt_result.success:
                app_logger.warning(f"[WaybillForwardService] 回执发送失败: {receipt_result.error}")

            return {
                "success": True,
                "message": "代发群消息转发成功",
                "waybills": waybills,
                "source_group": source_group_name,
                "target_group": target_group,
                "valid_minutes": valid_minutes,
            }
        except Exception as e:
            app_logger.error(f"[WaybillForwardService] forward_from_daifa_group异常: {e}", exc_info=True)
            return {"success": False, "message": f"处理失败: {e}"}

    def forward_from_logistics_group(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """处理物流群消息并回传到代发群"""
        try:
            message_content = (context or {}).get("message_content", "")
            waybills = self._extract_waybills(message_content)
            if not waybills:
                return {"success": False, "message": "消息中未识别到快递单号"}

            target_groups: Set[str] = set()
            matched_waybills: List[str] = []
            with self._lock:
                for waybill in waybills:
                    item = self._waybill_map.get(waybill)
                    if not item:
                        continue
                    target_group = item.get("group_name")
                    if target_group:
                        target_groups.add(target_group)
                        matched_waybills.append(waybill)

            if not target_groups:
                app_logger.warning(
                    f"[WaybillForwardService] 物流群消息未命中任何映射, waybills={waybills}, message={message_content}"
                )
                return {"success": False, "message": "未命中可回传的快递单号映射"}

            from core.wechat_manager import get_wechat_service

            wechat_service = get_wechat_service()
            failed_groups: List[str] = []
            for group in target_groups:
                message_send = MessageSend(
                    chat_id=group,
                    content=message_content,
                    message_type=MessageType.TEXT,
                )
                send_result = wechat_service.send_message(message_send)
                if not send_result.success:
                    failed_groups.append(group)
                    app_logger.warning(
                        f"[WaybillForwardService] 回传失败 group={group}, error={send_result.error}"
                    )

            if failed_groups:
                return {
                    "success": False,
                    "message": f"部分回传失败: {failed_groups}",
                    "matched_waybills": matched_waybills,
                    "target_groups": list(target_groups),
                }

            return {
                "success": True,
                "message": "物流群消息回传成功",
                "matched_waybills": matched_waybills,
                "target_groups": list(target_groups),
            }
        except Exception as e:
            app_logger.error(f"[WaybillForwardService] forward_from_logistics_group异常: {e}", exc_info=True)
            return {"success": False, "message": f"处理失败: {e}"}

    def stop(self):
        """停止后台线程并持久化当前map"""
        self._stop_event.set()
        if hasattr(self, "_cleanup_thread") and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=1)
        with self._lock:
            self._save_map_to_json_locked()

    def _extract_waybills(self, content: str) -> List[str]:
        if not content:
            return []
        yt_waybills = re.findall(self._YT_PATTERN, content)
        jt_waybills = re.findall(self._JT_PATTERN, content, flags=re.IGNORECASE)
        china_post_waybills = re.findall(self._CHINA_POST_PATTERN, content)
        zto_waybills = re.findall(self._ZTO_PATTERN, content)
        yunda_waybills = re.findall(self._YUNDA_PATTERN, content)
        numeric_waybills = re.findall(self._NUMERIC_PATTERN, content)
        merged = (
            yt_waybills
            + jt_waybills
            + china_post_waybills
            + zto_waybills
            + yunda_waybills
            + numeric_waybills
        )

        result: List[str] = []
        seen: Set[str] = set()
        for item in merged:
            if len(item) == 15 and item[:2].upper() == "JT" and item[2:].isdigit():
                key = "JT" + item[2:]
            else:
                key = item
            if key not in seen:
                seen.add(key)
                result.append(key)
        return result

    def _cleanup_loop(self):
        while not self._stop_event.is_set():
            try:
                self._cleanup_expired_and_persist()
            except Exception as e:
                app_logger.error(f"[WaybillForwardService] 清理线程异常: {e}", exc_info=True)

            self._stop_event.wait(self._CLEANUP_INTERVAL_SECONDS)

    def _cleanup_expired_and_persist(self):
        now_ts = time.time()
        removed = 0
        with self._lock:
            expired_keys = [k for k, v in self._waybill_map.items() if float(v.get("expire_ts", 0)) <= now_ts]
            for key in expired_keys:
                self._waybill_map.pop(key, None)
                removed += 1
            self._save_map_to_json_locked()

        if removed:
            app_logger.info(f"[WaybillForwardService] 清理过期单号数量: {removed}")

    def _load_map_from_json(self):
        if not os.path.exists(self._store_file):
            return
        try:
            with open(self._store_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                app_logger.warning("[WaybillForwardService] waybill_map.json格式非法，忽略加载")
                return

            valid_map: Dict[str, Dict[str, Any]] = {}
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                group_name = value.get("group_name")
                expire_ts = value.get("expire_ts")
                if not isinstance(group_name, str):
                    continue
                try:
                    expire_ts_float = float(expire_ts)
                except Exception:
                    continue
                valid_map[str(key)] = {"group_name": group_name, "expire_ts": expire_ts_float}

            with self._lock:
                self._waybill_map = valid_map
            app_logger.info(f"[WaybillForwardService] 已加载单号映射数量: {len(valid_map)}")
        except Exception as e:
            app_logger.warning(f"[WaybillForwardService] 加载waybill_map.json失败: {e}")

    def _save_map_to_json_locked(self):
        temp_file = f"{self._store_file}.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(self._waybill_map, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, self._store_file)
