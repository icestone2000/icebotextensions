# mobile_plan_recommender — 手机套餐推荐

手机卡 / 流量卡销售客服场景：客户用自然语言描述需求（「联通 50 左右的」「移动流量多的」），大模型调用本工具从套餐库中挑出最匹配的几个，由大模型组织成自然语言回复。

本扩展是**纯查询、不发消息**类工具的推荐参考实现，也演示了 LLM 失败时的降级策略。

## 类型

A 类 · 大模型工具型

- **工具名**：`mobile_plan_recommend`
- **工具类型**：`ToolType.DATA_QUERY`

## 功能

- 抓取套餐发布页面（httpx）并解析出套餐列表（名称、描述、办理链接、详情）
- 用 LLM 按客户条件挑选并排序 top_k（提示词在 `prompts.py`）
- **LLM 失败自动降级**为本地关键词匹配 `_fallback_recommend()`，工具永不空手而归
- 两级缓存：源数据日级 TTL（1 天，惰性刷新）+ 查询结果 LRU 30 条（`asyncio.Lock` 保护）

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 自然语言筛选条件 |
| `top_k` | integer | 否 | 返回数量，默认 5，范围 1–10 |
| `force_refresh` | boolean | 否 | 强制刷新源数据缓存 |

## 返回示例

```json
{
  "success": true,
  "query": "联通50左右的",
  "cache_hit": false,
  "plans": [
    {
      "name": "【江西省】广电姜黄卡",
      "description": "29元包180G通用+250分钟通话",
      "apply_url": "https://...",
      "reason": "匹配条件:联通 50左右的"
    }
  ]
}
```

## 数据文件

无本地数据文件，数据源为远程网页（地址在 `service.py` 中配置，可改为自己的套餐发布页）。
