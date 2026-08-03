# hello_ext — 扩展入门示例

冰石机器人扩展机制的最小可运行示例。第一次开发扩展时，建议先把它跑通。

## 类型

A 类 · 大模型工具型

- **工具名**：`hello_tool`
- **工具类型**：`ToolType.SYSTEM_ACTION`

## 功能

注册一个最简单的工具：接收 `name` 参数，返回 `hello, {name}!` 问候语。同时提供普通函数 `extensions.hello_ext.greet(name)`，可在关键词回复的「执行 Python 代码」动作里直接调用。

它演示了一个扩展的全部必要组成：

- `__init__.py` — 标记 Python 包
- `extension.py` — `register(ctx)` / `unregister(ctx)` 入口，注册 `BaseTool` 子类
- `BaseTool` 的 5 个必须实现的方法：`get_name` / `get_description` / `get_tool_type` / `get_parameters` / `execute`

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 要问候的名字，默认 `world` |

## 部署

1. 把本目录复制到扩展根目录（开发环境 `backend/extensions/`，打包环境 exe 同目录的 `extensions/`）
2. 重启服务，或调用 `POST /api/v1/extensions/reload`，body: `{"name": "hello_ext"}`
3. 管理后台开启工具调用并勾选 `hello_tool`
4. 启动日志出现 `[hello_ext] registered hello_tool` 即成功
