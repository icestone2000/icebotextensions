# 关键词回复「执行 Python 代码」说明文档（客户版）

本文档用于说明：当关键词回复类型选择为“执行 Python 代码”时，系统如何执行代码、可用哪些上下文参数、如何进行复杂功能扩展，以及常见注意事项。

---

## 1. 工作原理

当系统检测到关键词命中后，如果该关键词的回复类型是“执行 Python 代码”，系统会将回复内容当作 Python 代码动态执行。

执行时，系统会传入一个 `context` 对象（字典），其中包含当前消息场景的关键数据；同时会注入同名变量，便于直接使用。

如果代码执行过程中有标准输出（例如使用 `print`），系统会将输出内容回发到当前会话。如果没有标准输出，通常不会有可见回复。

---

## 2. `context` 参数说明

建议写法：统一使用 `context.get("字段名", 默认值)` 读取，避免不同渠道字段差异带来的报错。

| 字段名 | 含义 |
| --- | --- |
| `user_id` | 当前用户 ID（通常与发送者 ID 同源） |
| `group_id` | 当前会话/群 ID |
| `group_name` | 当前会话名称（群名或私聊名称） |
| `message_content` | 当前消息内容 |
| `keyword` | 本次命中的关键词 |
| `message_timestamp` | 消息时间（字符串） |
| `message_type` | 消息类型（如 text/image，部分渠道可能缺失） |
| `sender_id` | 发送者 ID |
| `sender_name` | 发送者名称 |
| `chat_type` | 聊天类型（部分渠道可能缺失） |
| `direction` | 消息方向（部分渠道可能缺失） |
| `context` | 完整上下文字典本身 |
| `is_private` | 是否私聊（仅部分渠道提供） |
| `xianyu_chat_id` | 闲鱼会话 chat ID（仅闲鱼渠道提供） |
| `xianyu_to_id` | 闲鱼消息接收方 ID，通常为买家 ID（仅闲鱼渠道提供） |
| `config_id` | 闲鱼账号配置 ID，用于定位运行中的闲鱼 session（仅闲鱼渠道提供） |

说明：上表中“部分渠道可能缺失”的字段，建议始终使用 `context.get()` 读取并设置默认值。闲鱼渠道还会额外注入 `get_current_chat_orders`、`get_order_detail` 两个订单查询函数，详见第 7 节。

---

## 3. 基础示例

下面是一个可直接用于关键词回复的示例代码：

```python
from core.file_search_manager import get_file_search_service
get_file_search_service().handleCommand(context, r"D:\files")
```

说明：

- 第一个参数传入完整 `context`。
- 第二个参数是要检索的目录路径，请按实际环境修改。

---

## 4. 高级用法：扩展目录

由于关键词中的 Python 代码是“每次命中时动态执行”，如果业务逻辑较复杂，不建议把大量代码直接写在关键词配置里。

推荐做法：

1. 在程序所在目录的 `extensions` 目录中创建扩展模块。
2. 将复杂逻辑（请求封装、数据处理、容错、重试等）写入扩展模块。
3. 在关键词回复中只保留少量“入口调用”代码。

这样做的好处：

- 代码更清晰，便于维护；
- 逻辑可复用，多个关键词可共用同一能力；
- 修改复杂逻辑时，不必反复编辑关键词配置文本。

---

## 5. 业务示例：读取上下文 + 外部请求 + 发送消息

以“车辆商品查询”场景为例，典型流程如下：

1. 从 `context` 读取消息内容、会话名称、发送人、消息类型等参数。
2. 从消息中解析业务关键字（例如车架号）。
3. 发起外部 HTTP 请求获取结果。
4. 调用系统消息接口，把结果发送到指定群或好友。

示例片段（演示结构）：

```python
import requests

group_name = context.get("group_name", "")
sender_name = context.get("sender_name", "")
message_content = context.get("message_content", "")

payload = {
    "sender": sender_name,
    "chat_name": group_name,
    "content": message_content,
}

resp = requests.post("https://example.com/api/query", json=payload, timeout=20)
data = resp.json()

# 这里调用系统消息发送接口，将 data 中结果发送到目标会话
# send_message(chat_id=group_name, content=str(data.get("data", "")))
print(data.get("msg", "执行完成"))
```

### 5.1 通过系统接口发送微信消息（参数说明）

在关键词代码里，你可以按“构造发送对象 -> 调用发送接口 -> 判断结果”的方式发送消息。

示例：

```python
from schemas.wechat import MessageSend, MessageType
from core.wechat_manager import get_wechat_service

target_chat = context.get("group_name", "")  # 也可以替换为你要发送的好友名称
text = "查询结果：xxx"

message_send = MessageSend(
    chat_id=target_chat,
    content=text,
    message_type=MessageType.TEXT,
)

result = get_wechat_service().send_message(message_send)
if result.success:
    print("发送成功")
else:
    print(f"发送失败: {result.error}")
```

消息发送常用参数：

| 参数 | 含义 | 是否必填 | 可用值/说明 |
| --- | --- | --- | --- |
| `chat_id` | 目标会话标识 | 是 | 字符串。常用“群名称”或“好友名称”。建议先从 `context.get("group_name")` 获取当前会话名称。 |
| `content` | 消息内容 | 是 | 字符串，建议简洁明确。文本消息最大长度受系统限制。 |
| `message_type` | 消息类型 | 否 | 默认 `text`。常见可用值：`text`、`image`、`voice`、`video`、`file`、`link`、`card`、`location`、`system`、`revoke`、`transfer`、`red_packet`、`unknown`。关键词自动回复场景建议优先使用 `text`。 |
| `at_users` | @用户列表 | 否 | 字符串数组。用于群聊 @ 指定成员；不需要 @ 时可留空。 |
| `reply_to` | 回复目标消息 ID | 否 | 字符串。需要“回复某条消息”时传入；普通发送可不填。 |

发送结果参数：

| 参数 | 含义 |
| --- | --- |
| `success` | 是否发送成功（`true`/`false`） |
| `message_id` | 发送成功后的消息 ID（可为空） |
| `error` | 失败原因（仅失败时通常有值） |
| `timestamp` | 发送时间 |

实践建议：

- 目标会话建议优先使用 `context` 中当前会话信息，避免发错对象。
- 调用发送接口后务必判断 `success`，并记录 `error` 便于排查。
- 若你需要跨会话发送（发到其他群/好友），建议先在管理配置中核对目标名称。

### 5.2 通过系统接口发送企业微信消息（参数说明）

企业微信渠道需使用第三方实例 API 发送。`context.get("group_id")` 为当前企微会话 ID，可作为 `to_id` 发给当前聊天对象。

示例（发到当前会话）：

```python
from database.base import SessionLocal
from models.wechat_group import WeChatConfig, WeChatGroup
from models.wecom_third_party import WeComThirdPartyInstance
from services.wecom_third_party_service import WeComThirdPartyService
from utils.config_manager import get_config_manager

to_id = context.get("group_id", "")  # 当前企微会话 ID
text = "查询结果：xxx"

db = SessionLocal()
try:
    group = db.query(WeChatGroup).filter(WeChatGroup.group_id == to_id).first()
    if not group:
        print("未找到会话配置")
    else:
        config = db.query(WeChatConfig).filter(WeChatConfig.id == group.config_id).first()
        instance = (
            db.query(WeComThirdPartyInstance)
            .filter(
                WeComThirdPartyInstance.wecom_user_id == config.wxid,
                WeComThirdPartyInstance.status == 2,  # 2 = 已登录
            )
            .first()
        )
        if not instance:
            print("企业微信实例未登录")
        else:
            server_url = get_config_manager(db).get_config("wecom_third_party.server_url", "") or ""
            WeComThirdPartyService(server_url=server_url, db=db).send_text_message(
                guid=instance.guid,
                content=text,
                to_id=to_id,
                license_code=instance.license_code,
            )
            print("发送成功")
finally:
    db.close()
```

`send_text_message` 常用参数：

| 参数 | 含义 | 是否必填 | 可用值/说明 |
| --- | --- | --- | --- |
| `guid` | 企微实例设备 ID | 是 | 从已登录的 `WeComThirdPartyInstance.guid` 获取 |
| `content` | 消息内容 | 是 | 字符串 |
| `to_id` | 接收方会话 ID | 是 | 当前会话用 `context.get("group_id")`；跨会话发送时改为目标会话 ID |
| `license_code` | 实例授权码 | 是 | 从 `WeComThirdPartyInstance.license_code` 获取 |

实践建议：

- 发送前确认企微实例状态为已登录（`status == 2`）。
- 跨会话发送时，`to_id` 需填写目标群或联系人的企微会话 ID，而非显示名称。
- 若需发送图片、链接、@ 消息等，可调用 `WeComThirdPartyService` 的其它方法（如 `send_image_message_by_file_name`、`send_link_message`、`send_hyper_text_message`）。

### 5.3 通过系统接口发送闲鱼消息（参数说明）

闲鱼渠道需通过运行中的 `XianyuService` session 主动发送。`context` 中会注入 `config_id`、`xianyu_chat_id`、`xianyu_to_id`，用于定位 session 与目标买家。

示例（发到当前闲鱼买家）：

```python
from services.xianyu_service import XianyuService

config_id = context.get("config_id")
chat_id = context.get("xianyu_chat_id")
to_id = context.get("xianyu_to_id")
group_id = context.get("group_id", "")
text = "感谢购买！"

session = XianyuService._sessions.get(config_id)
if not session:
    print("闲鱼会话未运行，请先启动该闲鱼账号")
elif not chat_id or not to_id:
    print("缺少闲鱼会话标识（xianyu_chat_id / xianyu_to_id）")
else:
    session.send_message(chat_id, to_id, text)
    if group_id:
        XianyuService.save_outgoing_text_message(config_id, group_id, text)
    print("发送成功")
```

闲鱼文本发送常用参数：

| 参数 | 含义 | 是否必填 | 可用值/说明 |
| --- | --- | --- | --- |
| `config_id` | 闲鱼账号配置 ID | 是 | 从 `context.get("config_id")` 获取，用于 `XianyuService._sessions` |
| `chat_id` | 闲鱼会话 ID | 是 | 从 `context.get("xianyu_chat_id")` 获取 |
| `to_id` | 接收方 ID（买家） | 是 | 从 `context.get("xianyu_to_id")` 获取 |
| `text` | 消息内容 | 是 | 字符串 |

实践建议：

- 闲鱼账号需已在后台启动且 session 在线，否则 `_sessions.get(config_id)` 为空。
- 主动调用 `session.send_message` 会立即发给买家；与 `print()` 不同（`print` 输出也会作为回复发给买家，见第 7.5 节）。
- 建议发送后调用 `XianyuService.save_outgoing_text_message` 落库，便于后台查看聊天记录。

---

## 6. 调试与安全建议

- 调试时可先用 `print()` 输出关键信息，便于快速确认逻辑是否执行。
- 代码建议做好异常处理，避免因单次异常影响用户体验。
- 外部 HTTP 请求请设置超时时间，避免长时间阻塞。
- 仅允许可信管理员维护“执行 Python 代码”内容。
- 该能力权限较高，代码可发起网络请求、调用系统能力，请严格进行变更审核。

---

## 7. 闲鱼场景：获取订单信息并转发到微信

> 本节仅适用于**闲鱼渠道**的关键词回复。微信渠道不提供以下 helper 函数。

### 7.1 背景

买家在闲鱼付款后，会自动发送一条"[我已付款，等待你发货]"消息。可以在关键词回复中匹配该文本，触发 Python 代码，自动获取订单详情（收件地址、商品规格、金额等），并通过微信发送给指定联系人或群。

### 7.2 可用的订单 helper 函数

在闲鱼渠道的关键词回复代码中，系统额外注入了以下两个函数，通过 `context` 调用：

| 函数 | 说明 |
| --- | --- |
| `context['get_current_chat_orders']()` | 查询当前会话买家的**待发货订单列表**（含收件信息、金额，最多扫描前 3 页）。返回 `list[dict]`，字段见下表。 |
| `context['get_order_detail'](order_no)` | 根据订单号查询**完整订单详情**，包含商品规格（skuInfo）。返回 `dict`，字段见下表。 |

**`get_current_chat_orders()` 返回字段：**

| 字段 | 含义 |
| --- | --- |
| `order_no` | 订单号 |
| `status` | 订单状态（如 `pending_ship` 待发货） |
| `item_id` | 商品 ID |
| `placed_at` | 下单时间（字符串） |
| `buyer_id` | 买家 ID |
| `buyer_nick` | 买家昵称 |
| `receiver_name` | 收件人姓名 |
| `receiver_phone` | 收件人手机号 |
| `receiver_address` | 收件地址 |
| `amount` | 付款金额（元，字符串） |
| `quantity` | 购买数量 |

**`get_order_detail(order_no)` 返回字段（在上方基础上增加）：**

| 字段 | 含义 |
| --- | --- |
| `spec_name` | 规格名称（如"颜色"） |
| `spec_value` | 规格值（如"星空黑"） |
| `quantity` | 购买数量（详情接口更准确） |
| `amount` | 付款金额（详情接口更准确） |
| `receiver_name` | 收件人姓名（详情接口更准确） |
| `receiver_phone` | 收件人手机号（详情接口更准确） |
| `receiver_address` | 收件地址（详情接口更准确） |

> 说明：列表接口（`get_current_chat_orders`）返回的地址来自买家信息，通常已够用。若需要最精确的收件信息和商品规格，请调用详情接口（`get_order_detail`）。

### 7.3 完整示例：付款后自动通知微信联系人

以下代码可直接粘贴到关键词配置的"执行 Python 代码"内容中：

```python
from schemas.wechat import MessageSend, MessageType
from core.wechat_manager import get_wechat_service
from services.xianyu_service import XianyuService

# ── 配置项（按需修改） ─────────────────────────────
TARGET_WECHAT = "你的微信好友或群名称"   # 要通知的微信联系人/群
# ─────────────────────────────────────────────────

try:
    # 1. 获取待发货订单列表（当前会话买家）
    orders = context['get_current_chat_orders']()

    if not orders:
        print("暂未查询到待发货订单，请稍后在后台手动确认。")
    else:
        order = orders[0]
        order_no = order['order_no']

        # 2. 获取订单详情（含商品规格）
        detail = context['get_order_detail'](order_no)

        # 3. 拼接规格信息
        if detail.get('spec_name') and detail.get('spec_value'):
            spec_str = f"{detail['spec_name']}：{detail['spec_value']}"
        else:
            spec_str = "无规格"

        # 4. 优先使用详情接口的地址和金额（更精确）
        receiver_name    = detail.get('receiver_name')    or order.get('receiver_name', '')
        receiver_phone   = detail.get('receiver_phone')   or order.get('receiver_phone', '')
        receiver_address = detail.get('receiver_address') or order.get('receiver_address', '')
        amount           = detail.get('amount')           or order.get('amount', '')
        quantity         = detail.get('quantity')         or order.get('quantity', 1)

        # 5. 构造通知消息
        msg = (
            f"📦 新订单待发货\n"
            f"买家：{context.get('sender_name', '')}\n"
            f"订单号：{order_no}\n"
            f"金额：¥{amount}  数量：{quantity}\n"
            f"规格：{spec_str}\n"
            f"收件人：{receiver_name} {receiver_phone}\n"
            f"地址：{receiver_address}"
        )

        # 6. 发送到微信
        result = get_wechat_service().send_message(MessageSend(
            chat_id=TARGET_WECHAT,
            content=msg,
            message_type=MessageType.TEXT,
        ))

        if result.success:
            print("已通知")
        else:
            print(f"微信发送失败：{result.error}")

        # 7. 向当前闲鱼买家发送感谢语
        config_id = context.get("config_id")
        chat_id = context.get("xianyu_chat_id")
        to_id = context.get("xianyu_to_id")
        group_id = context.get("group_id", "")
        thank_text = "感谢购买！"

        session = XianyuService._sessions.get(config_id)
        if session and chat_id and to_id:
            session.send_message(chat_id, to_id, thank_text)
            if group_id:
                XianyuService.save_outgoing_text_message(config_id, group_id, thank_text)

except Exception as e:
    print(f"执行出错：{e}")
```

### 7.4 创建关键词步骤

1. 进入管理后台 → 关键词回复 → 新建。
2. **关键词**填写：`[我已付款，等待你发货]`（完整匹配，含方括号）。
3. **回复类型**选择：`执行 Python 代码`。
4. **回复内容**粘贴上方示例代码，将 `TARGET_WECHAT` 改为实际的微信联系人/群名称。
5. 保存后，买家付款即自动触发。

### 7.5 注意事项

- `get_current_chat_orders` 调用闲鱼 API，依赖当前账号登录状态，若 Cookie 失效会返回空列表。
- 若买家刚付款立即触发，订单可能存在短暂延迟（秒级），极少数情况下列表为空，此时 `print` 的内容会回复给买家，建议消息友好。
- `TARGET_WECHAT` 填写的名称需与微信通讯录显示名称完全一致。
- 该代码发送完通知后会向买家回复 `print` 的内容（如"已通知"）；如果不希望买家看到，可将 `print` 语句删除或改为空字符串输出。

---

## 8. 常见问题

### Q1：为什么关键词命中了，但没有看到回复？

可能原因：

- 代码没有 `print` 任何输出；
- 执行结果为空；
- 代码发生异常但未正确输出错误信息。

建议先在代码中增加：

```python
print("start", context.get("keyword"))
```

### Q2：为什么有些字段有时取不到？

不同消息渠道的上下文字段可能不完全一致。请统一使用：

```python
value = context.get("message_type", "")
```

并为缺失字段设置默认值。
