# express_price_calc — 快递运费报价

读取快递价格表 Excel，按「起始省 → 目的省 + 重量」计算各家快递运费，并可按模板拼好报价正文直接发给客户。适合快递代发、集运类客服场景。

这是**带发消息的数据查询工具**的推荐参考实现（`tool.py` + `service.py` + `message_sender.py` 分层）。

## 类型

A 类 · 大模型工具型

- **工具名**：`express_price_quote`
- **工具类型**：`ToolType.DATA_QUERY`

## 功能

- 读取 `快递价格表.xlsx`（列：快递公司 / 始发地 / 目的地 / 首重 / 续重），计算各家快递报价
- **体积重**：长×宽×高/8000，实重与体积重各自向上取整后取较大值计费
- **补差基数**：补差值 = 最低价 − 基数（下限 0），适合「拍下补差价」场景
- 支持只查指定快递公司、中文参数别名（「补差基数」「长(cm)」等）
- `send_to_customer` 默认 `true`，按 `message_template` 模板拼正文后主动发送（个人微信 / 企业微信 / 闲鱼）
- **后台线程每 30 秒轮询价格表文件变更**，Excel 改动后自动刷新缓存，无需重启；`unregister` 时自动停止轮询

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `origin_province` | string | 是 | 起始省份 |
| `dest_province` | string | 是 | 目的省份 |
| `weight_kg` | number | 否 | 重量（kg） |
| `length_cm` / `width_cm` / `height_cm` | number | 否 | 尺寸，用于体积重 |
| `compensation_base` | number | 否 | 补差基数 |
| `courier_name` | string | 否 | 只查指定快递公司 |
| `price_table_filename` | string | 否 | 价格表文件名，默认 `快递价格表.xlsx` |
| `send_to_customer` | boolean | 否 | 默认 `true` |
| `message_template` | string | 否 | 报价消息模板 |
| `recipient_id` | string | 否 | 指定接收方 |

## 消息模板占位符

- 基础：`[出发省份]` `[目的省份]` `[重量]` `[最便宜的快递名]` `[补差值]`
- 编号版：`[价格1]`…`[价格15]`、`[快递名i]`、`[续重价i]`（该行所有编号越界时整行自动删除）

## 数据文件

`快递价格表.xlsx`（Sheet1）放在扩展数据根目录（开发环境为 `backend/`，打包环境为 exe 同目录），**不在扩展目录内**。

## 注意

工具默认主动发消息，建议大模型编排时设置 `requires_tool_result: false`。
