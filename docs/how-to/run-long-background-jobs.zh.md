# 运行长时间后台任务

> English version: [run-long-background-jobs.md](./run-long-background-jobs.md)

## 适用场景

你需要启动一个构建、测试套件、包安装或数据管道任务，预计耗时数分钟——并且不希望 agent 阻塞等待。对 `Bash` 工具使用 `run_in_background=true`。

## 前置条件

- 主机连接正常（运行 `python -m remote_mcp --host <name> --test`）
- 要运行的命令（必须是非交互式的——无提示、无 TTY）

## 步骤

1. **在后台启动任务**

   以 `run_in_background=true` 调用 `Bash`。工具立即返回，并给出 PID 和日志路径：

   ```
   Bash("make -j4 all", run_in_background=true)
   ```

   响应：

   ```
   [host=prod cwd=/opt/app]
   Started background task.
     PID: 12345
     Log: /tmp/rmcp-bg-abc123def456.log

   To check status:    Bash("kill -0 12345 && echo running || echo done")
   To read new output: Read("/tmp/rmcp-bg-abc123def456.log", offset=<last_line+1>)
   To stop gracefully: Bash("kill -TERM -- -12345")
   To force stop:      Bash("kill -KILL -- -12345")
   ```

   原样复制 PID 和日志路径——不要自行猜测。

2. **检查任务是否仍在运行**

   读取输出前，始终先验证 PID 是否存活。PID 复用虽然罕见，但进程已退出时可能发生：

   ```
   Bash("kill -0 12345 && echo running || echo done")
   ```

   `running` 表示进程组存活。`done` 表示已退出（日志文件仍存在，可供检查）。

3. **增量读取新输出**

   使用带 `offset=` 的 `Read` 只获取上次读取后的新行。记录上次接收到的行号：

   ```
   Read("/tmp/rmcp-bg-abc123def456.log", offset=1)
   ```

   下次轮询时传入 `offset=<已读行数 + 1>`，避免重复读取旧输出。不要使用 `Bash("cat /tmp/rmcp-bg-abc123def456.log")`——每次轮询都会重传整个文件。

4. **按需停止任务**

   命令使用进程组 ID（PGID，用 `setsid` 启动时等于 PID）来终止所有子进程：

   - 优雅停止（SIGTERM，让进程自行清理）：
     ```
     Bash("kill -TERM -- -12345")
     ```
   - 强制停止（SIGKILL，立即终止）：
     ```
     Bash("kill -KILL -- -12345")
     ```

   始终优先使用 SIGTERM，等待片刻后若进程未退出再使用 SIGKILL。

5. **任务完成后清理日志文件**

   `/tmp/rmcp-bg-*.log` 中的日志文件会故意保留以便事后分析。完成后删除：

   ```
   Bash("rm /tmp/rmcp-bg-abc123def456.log")
   ```

   或一次性删除所有后台日志：

   ```
   Bash("rm -f /tmp/rmcp-bg-*.log")
   ```

## 验证

启动任务后：

```
Bash("kill -0 12345 && echo running || echo done")
```

几秒内应返回 `running`。任务完成后，同一命令返回 `done`，对日志路径执行 `Read` 可查看包含最终退出状态的完整输出（前提是你在原始命令末尾追加了 `; echo "Exit: $?"`）。

## 常见问题排查

- **`Error: failed to launch background task`** — 远程主机可能缺少 `setsid` 或 `nohup`。验证：`Bash("which setsid nohup")`。如果缺失，安装它们（`apt install util-linux`）。
- **`kill -0 <pid>` 立即返回 `done`** — 命令在启动时就退出了。读取日志文件查看错误信息。常见原因：命令路径错误，或缺少必要的环境变量（后台环境从头开始——重新导出命令所需的变量，或内联设置：`Bash("MY_VAR=value make all", run_in_background=true)`）。
- **日志文件无限增长** — 在命令中追加 `| head -10000`，或只重定向所需的输出。`/tmp` 在重启时会被清空；对于长时间运行的守护进程，请重定向到持久路径。
