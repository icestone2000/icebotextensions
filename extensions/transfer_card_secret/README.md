# transfer_card_secret — 收款自动发卡密

虚拟商品自动发货：识别微信「收款消息」及金额后，自动从卡密文件中取卡发给客户。适合点卡、会员激活码、充值卡等虚拟商品销售。

## 类型

B 类 · 关键词插件型（由关键词回复的「执行 Python 代码」动作触发，见 [docs/关键词回复-执行Python代码.md](../../docs/关键词回复-执行Python代码.md)）

## 功能

- 识别 `[收款消息]￥金额`（仅本方收款气泡有效，`[转账消息]` 本人转出会被排除），防止伪造触发
- **最少张数组合算法**：把收款金额拆成最少张数的面额组合（如 35 元 = 30 元卡 + 5 元卡）
- 从各面额对应的卡密 txt 文件中取出首行发给客户，**发出后即从文件中删除该行**（临时文件 + 按路径文件锁，并发安全）
- 每档面额可配置「卡密前置说明」「卡密后说明」文案
- 可选**启动发货命令**模式：客户须先发送指定命令，并在时限内（默认 3 分钟）完成付款才发货
- 异常情况（如卡密文件已空、金额无法组合）自动通知 `notify_target` 指定的对象

## 调用方式

在关键词回复的 Python 代码动作里：

```python
from extensions.transfer_card_secret import get_transfer_card_secret_service

service = get_transfer_card_secret_service()
service.handleCommand(
    context,
    price_file_list=[
        {"金额": 30, "文件": "D:/cards/30.txt", "卡密前置说明": "您的30元卡密：", "卡密后说明": "请及时使用"},
        {"金额": 5,  "文件": "D:/cards/5.txt"},
    ],
    notify_target="运营小助手",   # 异常通知对象
    start_command="发货",         # 可选：启动发货命令
    command_ttl_minutes=3,        # 命令有效期（分钟）
)
```

## 数据文件

卡密 txt 文件（每行一条卡密），路径由 `price_file_list` 配置指定。**请勿把真实卡密文件提交到代码仓库。**
