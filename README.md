# 冰石机器人扩展（IceBot Extensions）

本仓库是**冰石机器人**（智能微信客服机器人系统）的官方开源扩展集合，包含 11 个真实业务场景的扩展源码，以及完整的扩展开发文档。你可以直接部署这些扩展，也可以把它们当作模板，为自己的业务开发新扩展。

---

## 一、冰石机器人是什么？

冰石机器人是一个多渠道智能客服机器人系统，让大模型真正接管你的微信 / 企业微信 / 闲鱼客服。

### 多端客服，一套配置

- **个人微信**：连接个人微信，自动回复好友与群消息
- **企业微信**（iPad 协议第三方）：扫码登录，支持消息、群发、自动拉群、好友欢迎语
- **闲鱼**：按账号 + 宝贝配置自动回复，白名单 / 黑名单过滤

关键词、常见问题（FAQ）、大模型提示词、知识库等智能客服配置**三端共用**，一套能力多端复用。

### 智能回复：先本地、后大模型

回复链路为 **关键词匹配 → FAQ 匹配 → 大模型回复**。常规问题本地直接命中，响应快、零调用成本；复杂问题才交给大模型（支持 OpenAI、DeepSeek、通义千问、智谱等多厂商，带 fallback 降级）。

- **多条消息合并**：用户连发多条时先合并再回复，只回一条，更像真人
- **简短口语化**：提示词模板统一控制回复风格，降低"机器人感"
- **群组 / 宝贝知识库**：回复时自动结合商品信息与群知识库

### 大模型会"动手"：工具调用（本仓库的主题）

大模型在对话中可以输出 `tool_calls` 调用工具完成实际操作：发通知、发媒体文件、创建订单、创建定时群发任务、执行 Python 代码……而且**支持在 `extensions/` 目录下开发自定义工具**——这正是本仓库提供的内容。

用户在微信里说一句「查一下北京天气」，大模型识别意图后调用你写的 `weather_query` 工具，工具查完天气自动把结果发回当前会话。

### 人机协同

- **真人客服优先**：可配置真人客服名单与等待秒数，真人回复了机器人就闭嘴
- **一句话接管**：在聊天窗口发送「人工接管」等命令即可随时切换自动回复开 / 关

### 运营与管理

- 定时推送、统一群发、顺序定时群发（滴灌式）
- 客户管理、订单管理（支持拼多多订单导入）
- 从聊天记录 / 任意文本一键抽取 FAQ，沉淀知识库
- Vue 管理后台，移动端适配，**手机浏览器也能配置**

完整功能清单见 [docs/功能列表.md](docs/功能列表.md)，特色功能详解见 [docs/特色功能.md](docs/特色功能.md)。

---

## 二、免费试用

扫描下方二维码，添加企业微信，**获取免费试用激活码**：

![扫码加企业微信获取免费试用激活码](docs/images/企业微信二维码.png)

---

## 三、仓库结构

```
icebotextensions/
├── README.md
├── docs/                 # 扩展开发文档（中文）
└── extensions/           # 11 个扩展源码，每个扩展一个目录
```

本仓库的 `extensions/` 目录对应冰石机器人的扩展根目录：

| 运行方式 | 扩展目录位置 |
|---------|-------------|
| 源码开发运行 | `backend/extensions/<扩展名>/` |
| 打包 exe 运行 | `<exe 同目录>/extensions/<扩展名>/` |

把某个扩展目录整个复制进去，重启服务或调用 `POST /api/v1/extensions/reload`（body: `{"name": "<扩展名>"}`）热重载即可生效。

---

## 四、扩展列表

扩展按接入方式分为两类：

- **A 类 · 大模型工具型**：包含 `extension.py`，在 `register(ctx)` 中把 `BaseTool` 子类注册进工具注册表，由**大模型在对话中自动调用**。需在管理后台开启「工具调用」并勾选对应工具。
- **B 类 · 关键词插件型**：暴露全局服务单例与 `handleCommand()` 入口，由**关键词回复的「执行 Python 代码」动作**触发（详见 [docs/关键词回复-执行Python代码.md](docs/关键词回复-执行Python代码.md)）。

| 扩展 | 类型 | 工具名 / 入口 | 一句话说明 |
|------|------|--------------|-----------|
| [hello_ext](extensions/hello_ext/) | A | `hello_tool` | 最小入门示例，学写扩展从这里开始 |
| [weather_query](extensions/weather_query/) | A | `weather_query` | 查城市实时天气并发回当前会话 |
| [express_price_calc](extensions/express_price_calc/) | A | `express_price_quote` | 读 Excel 价格表算快递运费并报价 |
| [etc_repair_ledger](extensions/etc_repair_ledger/) | A | `etc_repair_ledger_record` | ETC 收费站设备报修自动登记 Excel 台账 |
| [king_honor_boost_price_calc](extensions/king_honor_boost_price_calc/) | A | `king_honor_boost_price_calc` | 王者荣耀代练报价（LLM 计算） |
| [mobile_plan_recommender](extensions/mobile_plan_recommender/) | A | `mobile_plan_recommend` | 手机流量套餐智能推荐（LLM 排序） |
| [send_qr_code](extensions/send_qr_code/) | A | `send_qr_code` | 从码库目录取二维码图片发给对方，发完即删 |
| [chat_order_from_message](extensions/chat_order_from_message/) | B | `handleCommand()` | 从群消息一句话解析并自动创建订单 |
| [logistics_price_quote](extensions/logistics_price_quote/) | B | `handleCommand()` | 物流装卸货自然语言报价（对接外部 AI 接口） |
| [transfer_card_secret](extensions/transfer_card_secret/) | B | `handleCommand()` | 微信收款自动发卡密 |
| [waybill_forwarder](extensions/waybill_forwarder/) | B | 转发入口函数 | 快递单号在代发群与物流群间双向转发 |

### 各扩展详细说明

#### hello_ext — 入门示例

扩展机制的最小可运行示例：注册一个 `hello_tool` 工具，接收 `name` 参数并返回问候语。代码不到 60 行，覆盖了 `register(ctx)`、`BaseTool` 五个必须实现的方法。**建议第一次开发扩展时先跑通它**。

#### weather_query — 天气查询

大模型识别「查一下北京天气」类意图后调用本工具。优先走国内免 API Key 的 itboy 天气接口（内置 `city_codes.py` 城市编码表），失败自动回退 `wttr.in`。返回温度、湿度、空气质量、风力等，并默认把格式化好的天气文本**主动发回当前会话**（支持个人微信 / 企业微信 / 闲鱼三渠道）。配套教程：[docs/如何为冰石机器人扩展大模型工具-天气查询示例.md](docs/如何为冰石机器人扩展大模型工具-天气查询示例.md)。

- 参数：`city`（必填）、`send_to_customer`（默认 true）、`recipient_id`

#### express_price_calc — 快递运费报价

读取放在后端根目录的 `快递价格表.xlsx`（列：快递公司 / 始发地 / 目的地 / 首重 / 续重），按「起始省 → 目的省 + 重量」计算各家快递运费。支持**体积重**（长×宽×高/8000，与实重取大）、**补差基数**、指定快递公司过滤、中文参数别名（如「补差基数」「长(cm)」）。算完可按自定义模板（`[出发省份]`、`[最便宜的快递名]`、`[价格1..15]` 等占位符）拼好报价正文直接发给客户。

后台线程每 30 秒轮询价格表文件变更并自动刷新缓存——改了 Excel 无需重启。这是**带发消息的数据查询工具**的推荐参考实现（`tool.py` + `service.py` + `message_sender.py` 分层）。

- 参数：`origin_province`、`dest_province`（必填）；`weight_kg`、`length_cm/width_cm/height_cm`、`compensation_base`、`courier_name`、`send_to_customer`、`message_template` 等

#### etc_repair_ledger — ETC 设备报修台账

面向高速 ETC 收费站运维群：群里有人反馈「3 号车道读不到卡」，大模型调用本工具把报修信息（收费站、车道、故障描述、报修人、时间）写入 Excel 台账。必填信息缺失时返回 `awaiting_info` 状态并提示 @报修人补充，**5 分钟超时后按现有信息自动落账**；30 分钟去重窗口防止同一故障重复记录。附带 `报修台账模板.xlsx` 模板。

写盘走独立队列线程，展示了**带后台线程的扩展**如何在 `unregister` 时正确清理资源。

- 参数：`excel_file`、`description`、`reporter`（必填）；`station`、`lane`、`lane_required`、`report_time`

#### king_honor_boost_price_calc — 王者荣耀代练报价

游戏代练客服场景：把「代练价格表文本」和客户要打的「星级区间」（如 `70-90`）交给大模型计算总价，要求返回带计算过程与纯数字结果的 JSON 并做校验。演示了**工具内部再调 LLM**（`core.llm_manager.get_llm_service`）的写法，带 LRU 结果缓存（价格表一变即整体失效）。

- 参数：`price_table_text`、`star_level_input`（均必填）

#### mobile_plan_recommender — 手机套餐推荐

抓取运营商套餐页面并解析套餐列表，再用 LLM 按客户的自然语言条件（「联通 50 左右的」「移动流量多的」）挑选排序 top_k；**LLM 失败自动降级**为本地关键词匹配，保证工具永不空手而归。源数据日级缓存 + 查询结果 LRU 缓存。这是**纯查询、不发消息**类工具的推荐参考实现，结果 JSON 交由大模型组织自然语言回复。

- 参数：`query`（必填）、`top_k`（默认 5）、`force_refresh`

#### send_qr_code — 发送二维码图片

从 `directory` 参数指定的二维码码库目录中取一张图片（可用 `file_name` 指定具体文件），通过当前会话渠道主动发送给对方（个人微信 / 企业微信 / 闲鱼），**发送成功后自动删除该图片文件**，保证一张码只发一次。适合收款码、进群码等「一码一发、发完即毁」场景。工具会主动发消息，建议设置 `requires_tool_result: false`。

- 参数：`directory`（必填，码库目录）、`file_name`（可选，指定文件名）

#### chat_order_from_message — 群消息自动建单

接送机 / 高铁站接送类业务群里，客户或调度发一条紧凑消息（`手机号 姓名 次数 项目 站点`），本扩展用正则解析出字段，自动查找或创建客户档案并创建订单，然后把成功回执（含订单号）或失败原因发回原群。项目名支持全称 / 简称映射（默认：酒店 / 高铁 / 机场 / 景区），可通过 `projectList` 参数自定义。

- 入口：`get_chat_order_from_message_service().handleCommand(context, projectList=..., success_reply=..., failure_reply=...)`

#### logistics_price_quote — 物流装卸报价

物流群里客户用自然语言描述装卸货需求，本扩展剥掉触发关键词后把正文提交到外部 AI 报价接口，解析返回价格后以「@发送人 + 报价」形式发回群里。接口地址可通过 `url` 参数覆盖，方便对接自己的报价服务。

- 入口：`get_logistics_price_quote_service().handleCommand(context, url=..., keyword=...)`

#### transfer_card_secret — 收款自动发卡密

虚拟商品自动发货：识别微信「收款消息」及金额后，用**最少张数组合算法**把金额拆成各面额，从对应的卡密 txt 文件中取出首行发给客户并从文件中删除（临时文件 + 文件锁保证并发安全），支持每档面额配置卡密前后说明文案。可选「启动发货命令」模式：客户须先发指定命令、并在时限内（默认 3 分钟）完成付款才发货。异常（如卡密文件空了）自动通知指定对象。

- 入口：`get_transfer_card_secret_service().handleCommand(context, price_file_list=..., notify_target=..., start_command=..., command_ttl_minutes=...)`

#### waybill_forwarder — 快递单号双向转发

打通「代发群」与「物流群」：代发群里出现快递单号（内置圆通 / 极兔 / 邮政 / 中通 / 韵达等单号正则）时原文转发到指定物流群，并记录单号与来源群的映射（默认 60 分钟有效，JSON 文件持久化）；物流群里再次出现同一单号时，自动把消息回传到原代发群。后台线程定期清理过期映射。

- 入口：`get_waybill_forward_service().forward_from_daifa_group(...)` / `forward_from_logistics_group(...)`

---

## 五、扩展开发文档

想为自己的业务开发扩展？按下面顺序阅读：

| 文档 | 内容 |
|------|------|
| [自定义工具开发指南.md](docs/自定义工具开发指南.md) | **核心文档**。目录结构、`BaseTool` 接口、`ExtensionContext`、三渠道发消息 API、工具内调 LLM、开发规范 Checklist，以及可直接投喂大模型的**扩展代码生成提示词** |
| [如何为冰石机器人扩展大模型工具-天气查询示例.md](docs/如何为冰石机器人扩展大模型工具-天气查询示例.md) | 手把手教程：从零写一个天气查询工具，写代码 → 配提示词 → 后台启用 → 看效果 |
| [extensions.md](docs/extensions.md) | 扩展加载机制：目录位置、启动预加载、动态重载 API |
| [机器人大模型与工具配置说明.md](docs/机器人大模型与工具配置说明.md) | 管理后台配置：大模型接入、提示词模板、启用工具调用、内置工具参数（含配置截图） |
| [关键词回复-执行Python代码.md](docs/关键词回复-执行Python代码.md) | B 类扩展的触发方式：在关键词回复中执行 Python 代码调用扩展 |

### 最小扩展长这样

```python
# extensions/my_ext/extension.py
from schemas.base_tool import BaseTool
from schemas.tool_calling import ToolType, ToolCall, ToolExecutionRequest
from typing import Any, Dict

class MyTool(BaseTool):
    def get_name(self) -> str:
        return "my_tool"

    def get_description(self) -> str:
        return "给大模型看的工具说明"

    def get_tool_type(self) -> ToolType:
        return ToolType.DATA_QUERY

    def get_parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询条件"},
            },
            "required": ["query"],
        }

    async def execute(self, tool_call: ToolCall, request: ToolExecutionRequest) -> Dict[str, Any]:
        query = (tool_call.parameters or {}).get("query") or ""
        return {"success": True, "result": f"查询 {query} 的结果"}

def register(ctx):
    try:
        ctx.tool_registry.register_tool(MyTool())
        ctx.logger.info("[my_ext] registered my_tool")
    except Exception as e:
        ctx.logger.warning(f"[my_ext] failed to register: {e}")

def unregister(ctx):
    ctx.logger.info("[my_ext] unregister called")
```

### 部署与启用（A 类工具）

1. 把扩展目录放入 `extensions/`，重启服务或调用 `POST /api/v1/extensions/reload` 热重载
2. 管理后台 → 对应平台（微信 / 企微 / 闲鱼）系统配置 → 开启**启用工具调用功能**
3. 在**选择工具**中勾选新工具（留空表示全部启用）
4. `GET /api/tool-calling/tools/{tool_name}` 验证注册结果，`POST /api/tool-calling/test` 单独调试

---

## 六、许可证

本仓库代码基于 [MIT License](LICENSE) 开源。

冰石机器人主程序为商业软件，扫描上方二维码加企业微信可获取**免费试用激活码**。
