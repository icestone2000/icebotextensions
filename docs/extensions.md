## Extensions（扩展源码）机制说明

> 定制 LLM 工具的完整开发说明（接口、发消息 API、示例与 LLM 代码生成提示词）见 **[自定义工具开发指南.md](自定义工具开发指南.md)**。

本项目支持在**启动时预加载** `extensions/` 目录下的扩展源码，并提供管理接口用于**按目录动态重载**扩展。

### 目录位置（非常重要）

- **开发运行（非 frozen）**：扩展目录在 `backend/extensions/`
- **打包 exe 运行（frozen）**：扩展目录在 `exe 同目录/extensions/`

> 系统会在启动时把 `base_dir` 加入 `sys.path`，因此 action 代码可以直接 `import extensions.xxx`。

### 扩展目录结构

每个扩展一个子目录，至少包含：

- `extensions/<ext_name>/__init__.py`

推荐包含入口文件（用于注册 tools/初始化资源）：

- `extensions/<ext_name>/extension.py`
  - `register(ctx)`（可选）
  - `unregister(ctx)`（可选）

### 在 action（执行 Python 代码）里调用扩展

示例 action 代码（关键词回复类型仍使用 `action`）：

```python
from extensions.hello_ext import greet
print(greet("Alice"))
```

### 扩展注册自定义 Tool（可选）

如果希望扩展提供 Tool（供 LLM 工具调用/系统调用），在 `extensions/<ext_name>/extension.py` 中实现 `register(ctx)`：

- `ctx.tool_registry.register_tool(tool_instance)`

其中 `tool_instance` 需要继承 `BaseTool`，并实现 `get_name()/execute()` 等接口。

### 动态重载 API

- `GET /api/v1/extensions/list`：查看扩展加载状态
- `POST /api/v1/extensions/reload`：重载指定扩展
  - body: `{ "name": "hello_ext" }`
- `POST /api/v1/extensions/reload-all`：重载全部扩展

这些接口需要管理员权限（`require_admin`）。

### 示例扩展

仓库内置了示例：`backend/extensions/hello_ext/`

- 提供函数：`extensions.hello_ext.greet(name)`
- 提供可选工具：`hello_tool`（在 `register(ctx)` 中注册）

