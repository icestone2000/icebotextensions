# king_honor_boost_price_calc — 王者荣耀代练报价

游戏代练客服场景：客户报出想打的星级区间（如「70 到 90 星」），大模型调用本工具按代练价格表计算总价并回复。

本扩展是**工具内部再调用 LLM** 的参考实现（`core.llm_manager.get_llm_service`）。

## 类型

A 类 · 大模型工具型

- **工具名**：`king_honor_boost_price_calc`
- **工具类型**：`ToolType.DATA_QUERY`

## 功能

- 把「代练价格表文本」和「星级区间」交给大模型计算总价（提示词在 `prompts.py`，LLM 超时 90 秒）
- 要求 LLM 返回 JSON：`calc_process`（计算过程）+ `calc_result`（纯整数字符串），返回前做格式校验
- LRU 结果缓存 200 条（`threading.Lock` 保护并发）；**价格表文本一变即清空全部缓存**，保证报价始终基于最新价目

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `price_table_text` | string | 是 | 代练价格表文本（各星级区间的单价规则） |
| `star_level_input` | string | 是 | 星级区间，如 `70` 或 `70-90` |

LLM 配置取自本轮会话的 `request.llm_config_id`，未指定时使用系统默认启用配置。

## 数据文件

无。价格表以文本参数传入（一般写在群组提示词或知识库中，由大模型带入参数）。
