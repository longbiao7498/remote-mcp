# 为何采用非持久 Bash

> English version: [why-non-persistent-bash.md](./why-non-persistent-bash.md)

> 另见：[v0.2.0 设计规范](../../superpowers/specs/2026-05-27-v0.2.0-non-persistent-bash.md)（权威版本）。

在 v0.1.x 中，Bash 工具通过一个持久 SSH 通道保持单个 bash 进程存活。`cd`、`export`、`source venv/bin/activate` 都能跨工具调用持续存在。这与人类用户在终端上的交互预期相符。

在 v0.2.0 中，我们移除了这一机制。现在每次 Bash 调用都会派生一个全新的 shell，运行命令，然后退出。状态**不会**持续存在。

## 我们为何做出改变

**与 Claude Code 原生对齐。** 直接测试表明，Claude Code 原生 Bash 工具在每次调用之间都会重置 cwd 和环境变量。基于 CC 行为训练的 agent 假设的是非持久性。我们的持久模型是一个无意为之的偏差——agent 会 `cd` 一次并假设自己还在那里，当相对路径失败时（或更糟，对错误的文件成功时）就会感到困惑。

**一类系统性 bug。** 带 PTY 的持久 bash 会导致 `srun`、`cat`（无参数）和其他读取 stdin 的命令永久挂起——持久 PTY 意味着我们的 stdin 监视器从不关闭，远端命令永远看不到 EOF。修复方案是在每个命令上加 `</dev/null`，但与持久性结合后产生了微妙的交互（每个命令单独重定向 stdin，但 PTY 本身持久存在 → 行为偏离了 agent 的心智模型）。

**机制复杂性。** 支撑持久 bash 需要：用于在连续 stdout 流上标记命令边界的 sentinel 协议、防止 paramiko 缓冲区死锁的后台 reader 线程、通过 Ctrl-C 传递 SIGINT 的 PTY 分配、后台命令的 `setsid` 包装，以及脆弱的初始化序列（`set +m`、`stty -echo`、`exec 2>&1`……）。大约 350 行支撑机制代码。非持久模型只需约 50 行，且无边界情况。

## 我们保留了什么

「shell 环境只加载一次而非每次调用都加载」的便利性。我们在 SSH 建立连接时通过 `bash -ic 'declare -p; declare -fp; alias'` 对 bashrc 加载后的环境进行快照，每次 Bash 调用在运行用户命令之前都会 `source` 此快照。PATH、别名、conda init、`module load`——全部得以保留。这与 Claude Code 原生使用的机制相同（`/home/lb/.claude/shell-snapshots/snapshot-bash-*.sh`）。

## Agent 需要适应的是什么

用 `cd dir && cmd` 代替先 `cd dir` 再 `cmd`。用 `FOO=bar cmd` 代替先 `export FOO=bar` 再 `cmd`。用 `venv/bin/python script.py` 代替先 `source venv/bin/activate` 再 `python script.py`。这些都是标准的 CC 原生使用模式。

如果某个工作流确实无法在非持久模式下运行（ssh-agent 链、复杂的有状态 REPL），未来的 `mode: persistent` 可选模式已在路线图上（见规范 §15.2）。
