# logistics_price_quote — 物流装卸报价

物流群里客户用自然语言描述装卸货需求，本扩展把需求提交到外部 AI 报价接口，拿到价格后以「@发送人 + 报价」形式发回群里。

## 类型

B 类 · 关键词插件型（由关键词回复的「执行 Python 代码」动作触发，见 [docs/关键词回复-执行Python代码.md](../../docs/关键词回复-执行Python代码.md)）

## 功能

- 从消息中剥掉触发关键词，把剩余正文 POST 到报价接口（body：`{content, title=群名}`，30 秒超时）
- 解析接口返回的报价（如「价格1238.7」），@发送人 发回群里
- 报价失败时把失败原因发回群，便于人工跟进
- 接口地址可用 `url` 参数覆盖，方便对接自己的报价服务

## 调用方式

在关键词回复的 Python 代码动作里：

```python
from extensions.logistics_price_quote import get_logistics_price_quote_service

service = get_logistics_price_quote_service()
service.handleCommand(
    context,
    url="https://your-server/apis/ai/price",  # 你的报价接口
    keyword="报价",                             # 触发关键词，会从正文中剥除
)
```

| 参数 | 说明 |
|------|------|
| `context` | 消息上下文（message_content、group_name、sender_name） |
| `url` | 报价接口地址，覆盖 `service.py` 中的默认值 |
| `keyword` | 触发关键词 |

## 注意

- `service.py` 中的 `DEFAULT_PRICE_API_URL` 为示例默认值，**部署时请替换为自己的报价接口地址**
- 请求默认跳过 TLS 证书校验（`verify=False`），对接正式服务时建议开启校验

## 数据文件

无。
