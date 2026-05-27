# 查看反馈日志

> English version: [inspect-feedback-log.md](./inspect-feedback-log.md)

## 适用场景

你想读取 agent 通过 `Feedback` 工具提交的内容——它在操作远程主机过程中记录的 bug 报告和功能增强建议。这是规划 remote-mcp 下一次迭代的主要输入来源。

## 前置条件

- 本地已安装 `jq`（`apt install jq` / `brew install jq`）
- 至少完成过一次 remote-mcp 会话（否则日志文件可能尚不存在）

## 步骤

1. **找到日志文件**

   默认路径：`~/.local/share/remote-mcp/feedback.jsonl`

   如果你在配置中设置了 `feedback_path:`，则使用该路径。

2. **查看所有条目**

   ```bash
   cat ~/.local/share/remote-mcp/feedback.jsonl | jq .
   ```

   每行是一个 JSON 对象：

   ```json
   {
     "ts": "2026-05-26T14:03:22+00:00",
     "host": "prod",
     "category": "bug",
     "summary": "Bash timeout leaves session in broken state",
     "details": "After a timeout, the next Bash call returns empty output until reconnect.",
     "session_pid": 98123
   }
   ```

3. **按类别筛选**

   仅查看 bug：

   ```bash
   jq 'select(.category == "bug")' ~/.local/share/remote-mcp/feedback.jsonl
   ```

   仅查看功能增强：

   ```bash
   jq 'select(.category == "enhancement")' ~/.local/share/remote-mcp/feedback.jsonl
   ```

4. **按主机筛选**

   ```bash
   jq 'select(.host == "prod")' ~/.local/share/remote-mcp/feedback.jsonl
   ```

5. **只显示摘要（快速分流）**

   ```bash
   jq -r '[.ts, .host, .category, .summary] | @tsv' \
       ~/.local/share/remote-mcp/feedback.jsonl
   ```

   示例输出：

   ```
   2026-05-26T14:03:22+00:00	prod	bug	        Bash timeout leaves session in broken state
   2026-05-26T14:11:55+00:00	gpu	 enhancement	Add a Symlink tool for creating soft links
   ```

6. **处理各条目**

   - `bug` 条目：复现问题，然后修复或提 GitHub issue。
   - `enhancement` 条目：在实现前对照 `CONTRIBUTING.md` 中的设计原则进行评估。如果增强需要新工具，按照[添加新工具](./add-a-new-tool.md)操作。
   - 分流完成后，可以归档已处理的条目：
     ```bash
     mv ~/.local/share/remote-mcp/feedback.jsonl \
        ~/.local/share/remote-mcp/feedback-$(date +%Y%m%d).jsonl
     ```

## 验证

如果文件完全不存在：

```bash
ls ~/.local/share/remote-mcp/
```

文件在首次调用 `Feedback` 工具时创建。如果 agent 尚未提交任何反馈，目录可能也不存在。这是正常现象——第一条条目写入时会自动创建目录。

## 常见问题排查

- **`jq: command not found`** — 安装 jq：`apt install jq`（Debian/Ubuntu）或 `brew install jq`（macOS）。
- **`No such file or directory`** — agent 在当前会话中尚未提交任何反馈。文件仅在调用 `Feedback` 工具时才会写入。
- **条目显示乱码** — 文件是 JSONL 格式（每行一个 JSON 对象）。不要用会自动换行的文本编辑器打开；请使用 `jq` 或 `cat`。
