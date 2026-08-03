# waybill_forwarder — 快递单号双向转发

打通「代发群」与「物流群」：代发群里出现快递单号时自动转发到物流群；物流群里再次出现同一单号时（如出库回复、异常反馈），自动把消息回传到原代发群。适合电商代发、集运中转场景。

## 类型

B 类 · 关键词插件型（由关键词回复的「执行 Python 代码」动作触发，见 [docs/关键词回复-执行Python代码.md](../../docs/关键词回复-执行Python代码.md)）

## 功能

- 内置多家快递单号正则：圆通 `YT+12/13位数字`、极兔 `JT+13位数字`、邮政 `9开头13位`、中通 `78开头12/13位`、韵达 `3开头13位`、通用 15 位纯数字
- **正向**：代发群消息含单号 → 原文转发到指定物流群，记录「单号 → 来源群」映射（默认 60 分钟有效），并给代发群发送回执
- **反向**：物流群消息含已记录的单号 → 消息回传到原代发群
- 映射持久化到 `waybill_map.json`，服务重启不丢失；后台守护线程每 5 分钟清理过期映射

## 调用方式

在关键词回复的 Python 代码动作里（两个群各配一条规则）：

```python
from extensions.waybill_forwarder import get_waybill_forward_service

service = get_waybill_forward_service()

# 代发群的规则：
service.forward_from_daifa_group(context, target_group="物流对接群", valid_minutes=60)

# 物流群的规则：
service.forward_from_logistics_group(context)
```

| 参数 | 说明 |
|------|------|
| `context` | 消息上下文（message_content、group_name、sender_name） |
| `target_group` | 物流群名称 |
| `valid_minutes` | 单号映射有效期（分钟），默认 60 |

## 数据文件

`waybill_map.json` — 单号映射持久化文件，运行时自动生成在本扩展目录内。
