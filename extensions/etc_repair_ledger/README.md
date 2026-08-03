# etc_repair_ledger — ETC 设备报修台账

面向高速 ETC 收费站运维群：群里有人反馈设备故障（读不到卡、不抬杆、天线异常、语音不播报等），大模型调用本工具把报修信息自动登记到 Excel 台账。

## 类型

A 类 · 大模型工具型

- **工具名**：`etc_repair_ledger_record`
- **工具类型**：`ToolType.FILE_OPERATION`

## 功能

- 把报修记录（收费站、车道、故障描述、报修人、报修时间）写入 Excel 台账（openpyxl）
- **信息补全流程**：必填信息缺失（收费站，或 `lane_required=true` 时的车道）返回 `status=awaiting_info` 暂存，并提示在群里 @报修人补充；**5 分钟超时后按现有信息自动落账**
- **30 分钟去重窗口**：同一故障短时间内重复上报不会产生重复记录
- 写盘走独立队列线程，避免阻塞工具调用；另有待补充记录的超时监控线程；`unregister` 时自动停止全部线程

本扩展是**带后台线程的扩展如何正确清理资源**的参考实现。

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `excel_file` | string | 是 | 台账文件名（相对名落在扩展数据根目录；`.xls` / 无后缀自动归一为 `.xlsx`） |
| `description` | string | 是 | 故障描述 |
| `reporter` | string | 是 | 报修人 |
| `station` | string | 否* | 收费站（缺失时进入待补充流程） |
| `lane` | string | 否 | 车道 |
| `lane_required` | boolean | 否 | 是否要求必须提供车道 |
| `report_time` | string | 否 | 报修时间，默认当前时间 |

## 数据文件

- `报修台账模板.xlsx` — 台账模板，随扩展打包在本目录
- 实际台账文件由 `excel_file` 参数指定，生成在扩展数据根目录（开发环境 `backend/`，打包环境 exe 同目录）
