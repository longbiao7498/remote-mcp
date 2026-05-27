# 添加新工具

> English version: [add-a-new-tool.md](./add-a-new-tool.md)

## 适用场景

你想向 Claude Code 暴露一项新的远程能力——例如 `Touch` 工具、`Chmod` 工具或 `Symlink` 工具。本指南逐一讲解从实现到文档的全部五个切入点。

## 前置条件

- 本地开发安装：`pip install -e ".[dev]"`（同时安装 pytest 和包本身）
- 通读完整设计规范：`docs/superpowers/specs/2026-05-26-remote-mcp-design.md`——sentinel 协议、exec 与 bash 会话的选择、SFTP 与 shell 的选择均在其中做出了决策
- 熟悉 `remote_mcp/tools/` 中的现有工具，作为参考实现

## 步骤

以下示例全程以 `Touch` 工具为例——该工具用于创建空文件或更新其 mtime。

---

1. **在 `remote_mcp/tools/touch.py` 中实现工具函数**

   严格遵守签名和返回约定：

   ```python
   from ..connection import SSHConnection
   import shlex

   def touch(conn: SSHConnection, file_path: str) -> str:
       """Create an empty file or update its mtime."""
       result = conn.exec(f"touch {shlex.quote(file_path)}")
       if result.exit_code != 0:
           return f"Error: {result.stderr.strip() or 'touch failed'}"
       return f"Touched: {file_path}"
   ```

   需要遵守的约定：

   - **签名**：`def <name>(conn: SSHConnection, ...args) -> str`
   - **失败时**：返回 `"Error: ..."`——不得抛出异常。
   - **执行路径选择**：
     - `conn.exec(cmd)` — 无状态、一次性。用于 Glob/Grep 风格的操作以及不需要 shell 状态的任何情形。
     - `conn.get_bash_session().execute(cmd)` — 有状态持久 shell。仅在工具需要 `cd` 或 `export` 状态持久化时使用。
     - `conn.get_sftp()` — 用于文件读/写/mkdir。二进制安全，无需 shell 转义。
   - `conn.exec()` 调用在重连时由服务器的 `_with_retry` 包装器自动重试——重连安全性由框架保证，无需自行处理。

2. **在 `remote_mcp/schemas.py` 中注册 schema**

   添加 `TOUCH_SCHEMA` 字典和 `TOUCH_DESC` 字符串，然后将它们追加到文件底部的导出字典中：

   ```python
   TOUCH_SCHEMA = {
       "type": "object",
       "properties": {
           "file_path": {"type": "string", "description": "Absolute path on the remote host"},
       },
       "required": ["file_path"],
   }

   TOUCH_DESC = (
       "Create an empty file or update its modification time on the remote host. "
       "Equivalent to the shell `touch` command. "
       "Bandwidth: negligible (exec channel only)."
   )
   ```

   在 `schemas.py` 末尾的现有导出字典中：

   ```python
   ALL_TOOL_SCHEMAS = {
       ...,
       "Touch": TOUCH_SCHEMA,
   }

   ALL_TOOL_DESCRIPTIONS = {
       ...,
       "Touch": TOUCH_DESC,
   }
   ```

   键名（`"Touch"`）即 Claude Code 调用该工具时使用的工具名。

3. **在 `remote_mcp/server.py` 中接入分发逻辑**

   在导入块顶部添加导入：

   ```python
   from .tools import touch as touch_tool
   ```

   在 `_raw_dispatch` 中添加分支：

   ```python
   if name == "Touch":
       return touch_tool.touch(_conn, **args)
   ```

   按字母顺序插入，与其他分支保持一致，便于阅读。

4. **编写测试**

   单元测试（不需要 SSH）放在 `tests/unit/test_touch_logic.py`。集成测试（需要真实 SSH）放在 `tests/integration/test_file_tools.py`，或使用共享 `conn` fixture 新建文件。

   最简集成测试：

   ```python
   def test_touch_creates_file(conn, remote_tmp):
       path = f"{remote_tmp}/testfile.txt"
       result = touch(conn, path)
       assert result == f"Touched: {path}"
       # verify it exists
       stat_result = conn.exec(f"test -f {shlex.quote(path)} && echo exists")
       assert "exists" in stat_result.stdout

   def test_touch_bad_path_returns_error(conn):
       result = touch(conn, "/root/no-permission-dir/x.txt")
       assert result.startswith("Error:")
   ```

   运行单元测试：`pytest tests/unit/ -v`
   运行集成测试：`pytest tests/integration/ -v`（SSH 主机不可达时自动跳过）

5. **更新文档**

   - `README.md` — 在介绍段落的工具列表中添加 `Touch`。
   - `CHANGELOG.md` — 在 `[Unreleased]` 下添加条目：
     ```
     feat(tools): Touch — create empty file or update mtime
     ```
   - `CLAUDE.md.fragment.md` — 如果新工具改变了 agent 工作流，添加使用提示。
   - 设计规范（`docs/superpowers/specs/2026-05-26-remote-mcp-design.md`）§4 工具总数——如有变化则更新。

---

## 验证

1. 手动启动服务器，确认无导入错误：
   ```bash
   python -m remote_mcp --host prod --test
   ```

2. 在 Claude Code 中（重启后）调用新工具：
   ```
   mcp__remote-prod__Touch(file_path="/tmp/hello.txt")
   ```

   预期结果：`Touched: /tmp/hello.txt`

3. 运行完整测试套件：
   ```bash
   pytest tests/ -v
   ```

## 常见问题排查

- **服务器返回 `Tool name not handled` 错误** — `ALL_TOOL_SCHEMAS`、`ALL_TOOL_DESCRIPTIONS` 和 `_raw_dispatch` 分支中的工具名必须完全一致（包括大小写）。
- **工具出现在 Claude Code 中但始终返回 `Error: ...`** — 通过 `Bash` 手动执行底层 exec 命令，排查错误来自 SSH 命令本身还是 Python 包装逻辑。
- **MCP 层 schema 校验失败** — 检查 schema 的 `required` 列表是否与函数的非默认参数完全对应。多余或缺失的条目会导致 MCP 框架在调用到达你的函数之前就拒绝请求。
