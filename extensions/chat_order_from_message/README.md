# chat_order_from_message — 群消息自动建单

接送机 / 高铁站接送类业务群：客户或调度在群里发一条紧凑消息（`手机号 姓名 次数 项目 站点`），本扩展自动解析、建档、下单，并把回执发回原群。

## 类型

B 类 · 关键词插件型（由关键词回复的「执行 Python 代码」动作触发，见 [docs/关键词回复-执行Python代码.md](../../docs/关键词回复-执行Python代码.md)）

## 功能

- 正则解析消息中的「11 位手机号 + 姓名 + 次数 + 项目 + 站点」
- 项目名支持全称 / 简称映射（默认：酒店 / 高铁 / 机场 / 景区，简称 酒 / 高 / 机 / 景），可用 `projectList` 参数覆盖或扩充
- 按手机号自动查找或创建客户档案，然后创建订单（订单来源记录群名）
- 成功回执（含订单号）或失败原因**主动发回原群**，回执文案支持模板占位符

## 调用方式

在关键词回复的 Python 代码动作里：

```python
from extensions.chat_order_from_message import get_chat_order_from_message_service

service = get_chat_order_from_message_service()
service.handleCommand(
    context,
    projectList=[("酒店", "酒"), ("高铁", "高"), ("机场", "机"), ("景区", "景")],
    success_reply="{sender_name} 下单成功，订单号 {order_number}",
    failure_reply="{sender_name} 下单失败：{message}",
)
```

| 参数 | 说明 |
|------|------|
| `context` | 消息上下文（message_content、group_name、sender_name、sender_id） |
| `projectList` | 项目全称 / 简称映射，覆盖默认表 |
| `success_reply` / `failure_reply` | 回执模板，占位符：`{sender_name}` `{order_number}` `{message}` |

## 数据文件

无。订单与客户数据写入系统数据库（复用系统 `OrderService`）。
