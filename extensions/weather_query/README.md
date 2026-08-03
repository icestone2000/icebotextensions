# weather_query — 天气查询

用户在微信 / 企业微信 / 闲鱼里说「查一下北京天气」，大模型调用本工具查询实时天气，并把格式化好的天气文本主动发回当前会话。

配套手把手教程：[docs/如何为冰石机器人扩展大模型工具-天气查询示例.md](../../docs/如何为冰石机器人扩展大模型工具-天气查询示例.md)

## 类型

A 类 · 大模型工具型

- **工具名**：`weather_query`
- **工具类型**：`ToolType.DATA_QUERY`

## 功能

- 双通道查询：优先国内免 API Key 的 itboy 接口（`t.weather.itboy.net`，经 `city_codes.py` 把城市名解析为城市编码），失败自动回退 `wttr.in`
- 返回温度、湿度、空气质量、天气类型、高低温、风力、生活提示等
- 默认把结果**主动发送**给当前会话客户（个人微信 / 企业微信 / 闲鱼三渠道，见 `message_sender.py`）

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `city` | string | 是 | 城市名，如「北京」「上海」 |
| `send_to_customer` | boolean | 否 | 是否主动发消息给客户，默认 `true` |
| `recipient_id` | string | 否 | 指定接收方，默认当前会话 |

## 文件结构

| 文件 | 职责 |
|------|------|
| `extension.py` | 注册工具 |
| `tool.py` | 工具定义（参数 schema、execute） |
| `service.py` | 查天气业务逻辑（httpx，双通道） |
| `city_codes.py` | 城市名 → 城市编码映射表 |
| `message_sender.py` | 三渠道发消息封装 |

## 注意

- 工具会主动发消息，建议大模型编排时设置 `requires_tool_result: false`，避免重复回复
- 未收录在 `city_codes.py` 中的城市自动走 wttr.in 通道
