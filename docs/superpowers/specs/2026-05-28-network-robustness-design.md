# remote-mcp v0.2.2 设计规范：网络鲁棒性

**日期**：2026-05-28
**状态**：待审核 → 待实施
**前身**：增量于 [`2026-05-26-remote-mcp-design.md`](./2026-05-26-remote-mcp-design.md)（v1，已实施为 v0.1.x）与 [`2026-05-27-v0.2.0-non-persistent-bash.md`](./2026-05-27-v0.2.0-non-persistent-bash.md)（v0.2.0/v0.2.1，已实施）。本规范覆盖 v0.2.2 的网络异常行为契约统一与四个具体修复，其他设计（连接生命周期、SFTP 工具、非持久 Bash、cwd 配置等）继续以前述 spec 为准。

---

## 1. 概述与目标

v0.2.0 与 v0.2.1 在架构层面解决了一批 SSH 层暴露给 agent 的失败模式，但仍残留四个网络鲁棒性问题：

- Edit / MultiEdit 在自动重试时给出与远端实际状态相反的反馈（虚假失败）
- SFTP 操作在静默丢包场景下可能长时间不返回
- Background Bash 在响应丢失时返回"启动失败"，但远端进程已实际启动，agent 无法管理
- Snapshot 重建失败时 WARNING 文本仍声称重建成功，agent 无法感知后续 Bash 调用环境已退化

四个问题的共同根源是：原始设计未把"网络异常下的工具行为"作为一等公民来约束，每个工具自行处理网络相关失败，缺乏统一的行为契约。本规范的目标是建立这套契约，并按契约修复四个已知 bug。

## 2. 与前序 spec 的关系

| 前序 spec 段 | v0.2.2 对其影响 |
|------------|---------------|
| v1 §9 错误处理与重连 | 本规范替代——`_with_retry` 的"重试所有工具"行为收窄为白名单/黑名单分发 |
| v0.2.0 §5.1 Snapshot 机制 | 本规范替代——snapshot 改为"MCP 启动时本地捕获 + 本地内存缓存 + 远端持久化"，不在每次 reconnect 时重新跑 `bash -ic`，存放位置从 `/tmp` 迁到 `~/.cache/remote-mcp/` |
| v0.2.0 §5.6 Reconnect WARNING 简化 | 本规范扩展——WARNING 文本根据 snapshot 是否需要重传、重传是否成功分三种文案 |
| v0.2.1 Bash channel-death 处理 | **不变**，本规范在其基础上增加对 SFTP 路径的等价保护 |
| v0.2.0 §5.3.7 Bash 工具背景启动 | 本规范微调——背景启动命令增加 pidfile 写入，启动失败响应文本增加 pidfile 找回提示 |

## 3. 动机

把已暴露的四个 bug 与其对 agent 的影响汇总如下：

| Bug | 触发场景 | 当前行为 | 对 agent 的影响 |
|-----|---------|---------|----------------|
| #1 | Edit / MultiEdit 通过 SFTP 完成 read-modify-write 后，响应包路上链路断开 | `_with_retry` 自动重连后再次执行整个 Edit。重试时 `old_string` 已被替换为 `new_string`，返回 `Error: old_string not found` | agent 收到的失败结果与远端实际状态相反；据此重新执行 Edit 会破坏已经正确的文件内容 |
| #2 | 静默丢包（笔记本休眠、VPN 失效），TCP socket 未关闭，paramiko Transport 未被标记失效 | SFTP 操作发出请求后等待响应，但响应永远不到达。当前代码未为 SFTP 操作设置整体超时 | 工具调用既不返回成功也不返回错误；Claude Code 界面长时间无响应；实践中需用户手动结束 MCP 进程 |
| #3 | `_bash_background` 在 `setsid nohup bash -c ... &` 成功启动远端进程后，channel 在 `echo BG_PID=$!` 响应到达之前断开 | `_bash_background` 返回 `failed to start background task`，但远端进程仍在运行；agent 未收到 PID 与日志路径 | agent 以为没启动，所以不知道有孤儿进程要清理；清理需用户登录远端手动操作 |
| #4 | `_do_reconnect` 之后 `_create_snapshot()` 执行失败（远端 `/tmp` 不可写、bashrc 报错等） | `_snapshot_path` 设为 None，仅向 stderr 打印警告；`call_tool` 仍向 agent 输出固定 WARNING `Snapshot was rebuilt` | 后续 Bash 调用走降级路径（不加载 snapshot、不切到配置 cwd），命令静默失败；agent 无法从 WARNING 文本判断根本原因 |

四者各自的根源不同，但都属于"网络异常下工具行为契约缺失"的具体表现。本规范在通过契约统一这类行为的同时，分别修复四个 bug。

## 4. 行为契约

为全部 13 个工具建立以下三条行为约束，作为本次设计与未来工具开发的共同基线：

### 4.1 有限时间返回（不卡死）

任何工具调用必须在有限时间内返回结果。**该约束通过框架层超时管理实现**，单个工具的实现代码不需要包含超时检查或超时处理逻辑。

具体实现见 §5.2。

### 4.2 成功与失败可区分（不混淆）

工具的返回内容必须让 agent 能区分"任务完成"与"任务未完成"。继续沿用既有约定：

- 成功：返回正常输出字符串
- 失败：返回以 `Error:` 开头的字符串

不引入新的结构化字段或前缀类别，agent 仍通过文本判断。**本规范不对错误消息内容施加字段级清单**——只要措辞清晰、不与远端实际状态冲突即可。

### 4.3 失败信息不撒谎（且足以让 agent 察觉）

工具在返回 `Error:` 时不得给出与远端实际状态相反的判断。具体表现为下列禁止行为：

- 远端任务已完成，返回"未完成"
- 远端任务未启动，返回"已启动"
- 远端任务状态未知，返回"已失败"或"已成功"这类确定性结论
- 框架层的 WARNING 文本与实际状态不符

错误消息应当让 agent 大致理解发生了什么（什么动作、在哪台 host、影响哪个资源），但**不强制**包含建议动作——工具不掌握 agent 的上下文，无法可靠判断 agent 应该做什么。

### 4.4 契约的实现位置

三条契约全部通过**框架层机制**满足，包括：

- `server.py::call_tool` 的分发分流（决定哪些工具走自动重试）
- `connection.py` 的 SFTP/exec 通道超时设置
- `connection.py` 的 snapshot 生命周期管理与本地缓存
- `server.py` 的 WARNING 文本选择

per-tool 代码改动最小化，新工具加入时只需遵循"返回成功或 `Error: ...` 字符串"的既有约定即可。

## 5. 修复设计

### 5.1 bug #1 修复：自动重试黑名单

#### 5.1.1 问题描述

`_with_retry` 当前对所有工具一视同仁地"重连一次 + 重跑一次"。对 Edit / MultiEdit 这类 SFTP read-modify-write 工具而言，第一次"写"成功但响应丢失的情况下，重跑会基于已被修改的文件状态执行，导致 `old_string` 不再存在，错误地返回失败。

Bash 同样不适合自动重跑（命令是否幂等只有 agent 知道）。v0.2.1 已经让 Bash 在 channel 中途死亡时自行返回明确错误，但 Bash 在 `_with_retry` 路径上的其他失败模式仍会被自动重跑（例如 `exec_command` 自身抛 SSHException）。

#### 5.1.2 设计

`server.py` 引入不参与自动重试的工具集合：

```python
NO_RETRY_TOOLS: frozenset[str] = frozenset({"Edit", "MultiEdit", "Bash"})
```

`call_tool` 根据集合分流：

```python
if name in NO_RETRY_TOOLS:
    result = _with_reconnect_only(lambda: _raw_dispatch(name, arguments))
else:
    result = _with_retry(lambda: _raw_dispatch(name, arguments))
```

`_with_reconnect_only` 与 `_with_retry` 的区别仅在于：捕获到 SSH 层异常时**只触发 reconnect 让下次调用可用**，不再重跑当前调用。捕获到的异常被转成 `Error:` 字符串返回 agent：

```python
def _with_reconnect_only(call):
    try:
        return call()
    except (paramiko.SSHException, EOFError, OSError) as e:
        try:
            _conn._do_reconnect()
        except Exception:
            pass  # reconnect 即使失败，本次仍以原始错误返回 agent
        return f"Error: {type(e).__name__}: {e}"
```

`_with_retry` 自身保持现有行为不变。

#### 5.1.3 影响范围

- `server.py`：新增 `NO_RETRY_TOOLS` 常量、`_with_reconnect_only` 函数、`call_tool` 的分支
- per-tool 代码：完全不动

#### 5.1.4 agent-visible 行为差异

- Edit / MultiEdit 在网络抖动后**不再**透明返回"成功"，而是返回一次 SSH 层错误字符串，agent 自行判断是否查证后重试
- Bash 在 `exec_command` 自身抛异常时同样直接返回 SSH 层错误字符串
- 8 个走 SSH 的幂等读类与全量覆盖写工具（Read / Glob / Grep / FileStat / MultiRead / Write / Upload / Download）行为不变

### 5.2 bug #2 修复：SFTP / exec 通道超时

#### 5.2.1 问题描述

paramiko 的 SFTP 与 exec channel 在 v0.2.x 当前实现下没有设置整体超时上限。静默丢包场景下，操作可能等待远端响应长达数分钟（取决于 paramiko keepalive 与 TCP RTO），违反 §4.1 的"有限时间返回"。

#### 5.2.2 设计

在 `connection.py` 中为所有 SFTP 与 exec 通道调用 `channel.settimeout(X)`，语义为"X 秒内没有任何字节往返就抛 `socket.timeout`"。具体实施点：

- **新增 HostConfig 字段** `op_timeout_default: int = 60`，单位秒
- **`conn.exec()`**：将 `timeout=30.0` 默认值改为读取 `self.config.op_timeout_default`，并显式通过 `exec_command(timeout=...)` 传入（paramiko 在该值上调用 channel.settimeout）
- **`conn.get_sftp()`**：在首次返回 SFTPClient 前调用 `sftp.get_channel().settimeout(self.config.op_timeout_default)`。由于 SFTPClient 单例复用，超时设置一次即可
- **Bash 前台 drain 循环**：保持现有的 `channel.settimeout(0.2)` 短轮询不变（与 `bash_timeout_default` 整体上限协同）
- **Bash 后台 exec_command**：传入 `timeout=10.0` 不变（10 秒足以让 setsid 启动完成）

超时被触发后，paramiko 抛出的 `socket.timeout` 继承自 `OSError`，自然被 `_with_retry` 或 `_with_reconnect_only` 捕获，转换为 Error 字符串或触发 reconnect。

#### 5.2.3 影响范围

- `config.py`：`HostConfig` 新增 `op_timeout_default` 字段
- `connection.py`：`exec()` 与 `get_sftp()` 中应用超时
- per-tool 代码：完全不动

#### 5.2.4 与现有 `bash_timeout_default` 的关系

两个超时面向不同语义：

- `op_timeout_default`（默认 60s）：**单次通道 I/O 静默等待上限**。任何 SFTP / exec 操作只要在 60s 内没有任何字节往返就会被超时。正常进行中的长传输（每秒钟有数据流动的大文件传输）不受影响
- `bash_timeout_default`（默认 120s）：**Bash 前台命令整体执行时长上限**。即使命令持续输出数据也会在 120s 后被强制超时

两者在 Bash 前台调用中协同：drain 循环以 200ms 周期检查整体 deadline，单次 `recv` 走 `op_timeout_default`（实际上 drain 循环里设的是 0.2s 轮询超时，所以 `op_timeout_default` 在 Bash 前台路径上不会生效——它只对 SFTP 与一次性 exec 生效）。

#### 5.2.5 配置示例

```yaml
hosts:
  prod:
    hostname: prod.example.com
    user: deploy
    op_timeout_default: 60       # 单次 I/O 静默上限
    bash_timeout_default: 120    # Bash 前台整体上限
```

### 5.3 bug #3 修复：Background Bash 增加 pidfile

#### 5.3.1 问题描述

`_bash_background` 在远端启动 `( setsid nohup bash -c ... & echo "BG_PID=$!" )` 后等待 `BG_PID=` 响应。如果响应到达前 channel 中断：

- 远端进程**已实际启动**（`setsid + nohup` 让它独立于 channel 存在）
- 本地返回 `Error: failed to start background task on <host>`，与实际状态相反
- agent 不持有 PID 与日志路径，无法管理该进程
- 远端孤儿进程持续运行直到结束、被 OOM 杀掉，或用户登录手动 kill

#### 5.3.2 设计

修改远端启动命令，在 `echo BG_PID=$!` **之前**将 PID 写入远端文件：

```bash
( setsid nohup bash --noprofile --norc -c "<inner>" \
    > /tmp/rmcp-bg-<uuid>.log 2>&1 </dev/null & \
  PID=$!; \
  echo $PID > /tmp/rmcp-bg-<uuid>.pid; \
  echo "BG_PID=$PID" )
```

`<uuid>` 是 `_bash_background` 已经生成的 12 位 hex，与日志文件命名 `/tmp/rmcp-bg-<uuid>.log` 配对。

#### 5.3.3 失效窗口

| 阶段 | 进程状态 | 本地观察 | agent 恢复手段 |
|------|---------|---------|--------------|
| 进程未 fork 就失败 | 未启动 | 收到非零退出或错误响应 | 无需恢复 |
| 进程已 fork、pidfile 未写就 channel 死 | 已启动 | 收到错误或无响应 | 无（毫秒级窗口） |
| 进程已 fork、pidfile 已写、`echo BG_PID` 响应在路上丢失 | 已启动 | 收到错误或无响应 | `Bash("cat /tmp/rmcp-bg-*.pid")` 找回 PID |
| 进程已 fork、pidfile 已写、响应正常到达 | 已启动 | 收到含 BG_PID 的正常响应 | 直接管理 |

第二种窗口（fork 后到 file write 之间）在毫秒量级，可接受。

#### 5.3.4 pidfile 文件约定

- 路径：`/tmp/rmcp-bg-<uuid>.pid`（与对应日志 `/tmp/rmcp-bg-<uuid>.log` 共享 uuid）
- 内容：单行 PID 数字，不含其他字段
- 清理：**不**主动清理，由远端重启或 `/tmp` 清理任务回收
- agent 通过 `kill -0 <pid>` 过滤已死进程对应的 stale pidfile

#### 5.3.5 错误消息

`_bash_background` 在异常路径上的返回字符串调整为：

```
Error: background launch on <host> may have started but the response was lost.
Inspect /tmp/rmcp-bg-*.pid on remote to recover PIDs of any orphan processes
(use `cat /tmp/rmcp-bg-*.pid` then `kill -0 <pid>` to filter live ones).
```

这一条文案是 per-tool 改动中唯一明显增量的部分，但它**不**包含错误分析逻辑——只是在异常处理路径上返回固定文本。

#### 5.3.6 与 bug #1 的协同

bug #1 修复后 Bash 在 `NO_RETRY_TOOLS` 中，因此 `_bash_background` 抛异常时**不会**被框架自动重跑——避免出现"中途失败 + 自动重试 = 两个孤儿进程"的二次破坏。两个修复必须**同时**生效；如果只修 bug #3 不修 bug #1，pidfile 机制反而会让孤儿数量翻倍。

#### 5.3.7 影响范围

- `remote_mcp/tools/bash.py::_bash_background`：远端命令字符串调整、异常路径返回文本调整
- per-tool 其他代码：完全不动
- `CLAUDE.md.fragment.md`：增加 pidfile 找回指引

### 5.4 bug #4 修复：Snapshot 本地缓存 + ~/.cache 持久化

#### 5.4.1 问题描述

v0.2.0 的 snapshot 在每次 `_do_reconnect()` 都重新执行 `bash -ic 'declare -p; ...'`。这带来两个问题：

- **行为不对齐 Claude Code 原生**：CC 原生 bash 工具在 session 开始时锁定环境一次，期间用户即使改动 bashrc 也不影响。我们当前实现把"用户登录后改的东西"偷偷拾取进来，与原生不一致
- **重建失败时 WARNING 撒谎**：snapshot 重建失败时 `_snapshot_path` 设为 None，但 WARNING 仍说 `Snapshot was rebuilt`。agent 看不到环境已退化的事实

#### 5.4.2 设计

把 snapshot 改为 **MCP server 启动时捕获一次、本地内存缓存、远端持久化在 `~/.cache/`**：

- **捕获在 MCP 启动时进行一次**：`_capture_snapshot()` 跑 `bash -ic 'declare -p; declare -fp; alias'`，结果存到 `self._snapshot_content`（本地内存），然后上传到远端 `~/.cache/remote-mcp/snapshot-<pid>.sh`
- **Reconnect 不重新捕获**：`_do_reconnect()` 不再调 `_capture_snapshot()`。改为 SFTP `stat` 检查远端文件是否还在，缺失则从本地内存缓存重新上传
- **远端文件位置改为 `~/.cache/remote-mcp/`**：避免被 `/tmp` 清理任务回收。`.cache` 目录在 XDG 约定中不自动清理
- **`close()` 不删除远端 snapshot 文件**：文件长期保留在 `~/.cache/`，下次 MCP 启动时新 PID 对应新文件名（多个 MCP 实例并发也不冲突）

#### 5.4.3 SSHConnection 新字段

```python
self._snapshot_content: Optional[bytes] = None   # MCP 启动时捕获，session 期间不变
self._snapshot_path: Optional[str] = None        # 远端文件绝对路径
self._snapshot_error: Optional[str] = None       # 失败原因（启动时捕获失败、或 reconnect 重传失败）
self._remote_home: Optional[str] = None          # 远端 $HOME，连接时一次性查到，用于拼 ~/.cache/ 路径
```

`_remote_home` 在 v0.2.0 `_resolve_remote_home()` 中已经会查询，本次只是把结果显式保存。

#### 5.4.4 关键方法

**`_capture_snapshot()`**（仅 MCP 启动时调用一次）：

```python
def _capture_snapshot(self) -> None:
    """Run bash -ic once, cache content locally, upload to remote ~/.cache/."""
    self._snapshot_error = None
    self._snapshot_content = None
    self._snapshot_path = None
    try:
        cmd = "bash -ic 'declare -p 2>/dev/null; declare -fp 2>/dev/null; alias 2>/dev/null'"
        result = self.exec(cmd, timeout=30.0)
        content = result.stdout
        if self.config.cwd:
            content += f"\ncd {shlex.quote(self.config.cwd)} || exit 1\n"
        self._snapshot_content = content.encode("utf-8")
    except Exception as e:
        self._snapshot_error = f"snapshot capture failed: {e}"
        return
    # Capture 成功，尝试上传
    self._upload_snapshot_to_remote()
```

**`_upload_snapshot_to_remote()`**（初始上传 + reconnect 后检测到丢失时重传）：

```python
def _upload_snapshot_to_remote(self) -> None:
    """Upload cached snapshot content to remote ~/.cache/remote-mcp/. Idempotent."""
    if self._snapshot_content is None:
        return
    if self._remote_home is None:
        self._snapshot_error = "snapshot upload failed: remote home unresolved"
        self._snapshot_path = None
        return
    cache_dir = f"{self._remote_home}/.cache/remote-mcp"
    pid = os.getpid()
    path = f"{cache_dir}/snapshot-{pid}.sh"
    try:
        sftp = self.get_sftp()
        from .tools.write import _sftp_mkdirs  # 复用现有的 SFTP mkdir -p helper
        _sftp_mkdirs(sftp, cache_dir)
        with sftp.file(path, "w") as f:
            f.write(self._snapshot_content)
        self._snapshot_path = path
        self._snapshot_error = None
    except Exception as e:
        self._snapshot_error = f"snapshot upload failed: {e}"
        self._snapshot_path = None
```

mkdir -p 与文件写入失败、权限不足、磁盘满都走统一异常分支。

**`_do_reconnect()` 调整**：

```python
def _do_reconnect(self) -> None:
    self.close()
    self.connect()                       # connect() 不再调 _capture_snapshot
    if self._snapshot_content is not None:
        # 已有本地缓存，检查远端是否还在
        if not self._snapshot_exists_on_remote():
            self._upload_snapshot_to_remote()
    self._reconnected = True
```

**`_snapshot_exists_on_remote()`**：

```python
def _snapshot_exists_on_remote(self) -> bool:
    if self._snapshot_path is None:
        return False
    try:
        sftp = self.get_sftp()
        sftp.stat(self._snapshot_path)
        return True
    except IOError:
        return False
```

**`connect()` 改动**：

去掉末尾的 `self._create_snapshot()` 调用（重命名为 `_capture_snapshot()` 后也不在此处调用）。`_capture_snapshot()` 仅在 `server.py::main` 启动时显式调用一次。

**`close()` 改动**：

去掉 `_snapshot_path` 文件的 `rm -f` 清理逻辑。文件保留在远端 `~/.cache/`。

#### 5.4.5 启动流程

`server.py::main` 启动时：

```python
_conn = SSHConnection(host_cfg, jump_config=jump_cfg)
_conn.connect()
_conn._capture_snapshot()      # 仅启动时调用一次
```

#### 5.4.6 WARNING 文本三种情况

`call_tool` 在 `_reconnected` flag 为 True 时根据状态选择文案：

**情况 A：远端文件依然存在（绝大多数 reconnect 走此路径）**：

```
[WARNING] SSH connection to <host> was lost and has been re-established.
```

不再提 snapshot——它没动过。

**情况 B：远端文件之前丢失，已从本地缓存重新上传**：

```
[WARNING] SSH connection to <host> was lost and has been re-established. The remote snapshot file was missing (likely cleaned externally) and has been re-uploaded from the local cache; the environment captured at session start has been preserved.
```

**情况 C：本地缓存上传失败**：

```
[WARNING] SSH connection to <host> was lost and has been re-established, but the remote snapshot file was missing AND re-upload failed (<reason>). Subsequent Bash calls will run without the user's PATH/aliases, and will start in $HOME instead of the configured cwd (<configured cwd>).
```

文案选择逻辑：

```python
if not _conn.check_and_clear_reconnect_flag():
    pass  # 无 WARNING
elif _conn._snapshot_error is None:
    prefix = "情况 A 文案"
elif <重传刚刚发生过且成功>:
    prefix = "情况 B 文案"
else:
    prefix = "情况 C 文案"
```

为了区分 B 与 A，需要在 `_do_reconnect()` 检测到远端文件缺失并触发重传时设置一个**待显示一次**的标志 `_snapshot_reuploaded: bool`，由 `call_tool` 消费后清零。该字段与三个 WARNING 状态字段的统一汇总见 §5.4.8。

#### 5.4.7 启动时 snapshot 捕获失败

`_capture_snapshot()` 在初始启动时失败的概率不高，但要处理。设计：

- MCP server **继续启动**（不 fail-fast）。理由：snapshot 失败比 cwd 失败影响小（agent 仍可用绝对路径），且失败原因往往是用户 bashrc 临时问题，下次重试可能就好了
- `_snapshot_error` 被设置
- `call_tool` 在第一次工具调用时通过独立的"启动 WARNING 待显示一次"机制，向 agent 输出：

```
[WARNING] Session-start snapshot capture failed (<reason>). Bash calls will run without the user's PATH/aliases, and will start in $HOME instead of the configured cwd (<configured cwd>).
```

显示一次后清零。后续调用不重复提示。

#### 5.4.8 三类 WARNING 状态字段汇总

§5.4.6 与 §5.4.7 共涉及三个独立的 SSHConnection 状态字段，三者职责互不重叠：

| 字段 | 类型 | 设置时机 | `call_tool` 消费 |
|------|------|---------|------------------|
| `_reconnected` | `bool` | `_do_reconnect()` 成功结束时设为 True（v0.1.x 既有） | `check_and_clear_reconnect_flag()` 读取并清零；触发 §5.4.6 三选一的 reconnect 文案 |
| `_snapshot_reuploaded` | `bool`（新增） | `_do_reconnect()` 检测到远端文件缺失并尝试重传后设为 True（无论重传成功还是失败） | reconnect 文案分支用它区分情况 A（False=文件还在没动过）与情况 B/C（True=发生过重传尝试，再看 `_snapshot_error` 区分 B/C）；读取后清零 |
| `_startup_warning_pending` | `bool`（新增） | `_capture_snapshot()` 在 MCP 启动时失败后设为 True | `call_tool` 在第一次工具调用前若为 True 则插入启动 WARNING 并清零 |

`call_tool` 的 WARNING 拼装顺序：

```python
prefix = ""
# 启动 snapshot 失败的一次性 WARNING（独立于 reconnect）
if _conn._startup_warning_pending:
    prefix += <启动 WARNING 文案>
    _conn._startup_warning_pending = False
# Reconnect WARNING（三选一）
if _conn.check_and_clear_reconnect_flag():
    if not _conn._snapshot_reuploaded:
        prefix += <情况 A 文案>
    elif _conn._snapshot_error is None:
        prefix += <情况 B 文案>
    else:
        prefix += <情况 C 文案>
    _conn._snapshot_reuploaded = False
return [TextContent(type="text", text=prefix + result + suffix)]
```

边界情形："启动失败的 agent 从未调过工具 → 网络断 → reconnect → 第一次调用"时，两段 WARNING 都会出现（启动 WARNING 在前、reconnect WARNING 在后），都只显示一次。这是预期行为，不需要特殊合并。

#### 5.4.9 影响范围

- `connection.py`：
  - 新增字段 `_snapshot_content` / `_snapshot_error` / `_remote_home` / `_snapshot_reuploaded` / `_startup_warning_pending`
  - 新增 `_capture_snapshot()` / `_upload_snapshot_to_remote()` / `_snapshot_exists_on_remote()`
  - 删除原 `_create_snapshot()`（功能拆到上述两个新方法）
  - `connect()` 不再无条件调用 snapshot 创建
  - `close()` 不再删除远端 snapshot 文件
  - `_do_reconnect()` 加入"检查 + 必要时重传 + 设置 `_snapshot_reuploaded` 标志"逻辑
  - `_resolve_remote_home()` 把结果存到 `_remote_home` 字段
- `server.py`：
  - `main()` 启动时显式调用 `_capture_snapshot()`；若 `_snapshot_error` 非空则设 `_startup_warning_pending = True`
  - `call_tool()` 的 WARNING 文案三套选择逻辑，按 §5.4.8 描述的拼装顺序
- per-tool 代码：完全不动

## 6. 文档配套

### 6.1 CLAUDE.md.fragment.md（en + zh）增补

新增"网络异常 agent 处理指引"段落，含决策树：

1. **收到 `Error: SSH channel ... closed unexpectedly` 时**：远端命令的执行状态不可确定。按命令幂等性分类：
   - 幂等读类（如 `cat`、`ls`、`pwd`、`grep`）：可直接重发
   - 副作用类（如 `rm`、`mv`、`git push`、迁移脚本）：先通过其他工具查证状态，再决定是否重发
   - 长任务（如 `sleep`、训练脚本）：通过 `Bash("pgrep -af ...")` 查证是否还在远端运行

2. **收到 `Error: SSH connection ... reconnect failed` 时**：网络真的不通。等待若干秒后再发任何调用；或先调一次 `RemoteInfo`（不走网络）作为最低成本探测后再决定。

3. **收到含 `snapshot ... missing AND re-upload failed` 的 WARNING 时**：后续 Bash 调用不加载用户 PATH/aliases、工作目录回退至 `$HOME`。对依赖用户环境的命令（conda、venv、自定义 alias）应改用绝对路径或显式设置环境。

4. **后台任务启动失败（响应丢失）时**：可能存在孤儿进程。通过：
   ```bash
   Bash("for pf in /tmp/rmcp-bg-*.pid 2>/dev/null; do pid=$(cat $pf 2>/dev/null); kill -0 $pid 2>/dev/null && echo \"$pid alive ($pf)\"; done")
   ```
   找回所有存活的后台 PID。

### 6.2 docs/reference 配套更新

- `docs/reference/config-schema.md` / `.zh.md`：新增 `op_timeout_default` 字段说明
- `docs/reference/errors.md` / `.zh.md`：新增三类错误条目（channel-death、reconnect-failed、background-launch-may-have-started）；snapshot 相关 WARNING 三套文案说明
- `docs/reference/tools/bash.md` / `.zh.md`：补充 `_bash_background` 启动失败响应的 pidfile 恢复提示
- `docs/reference/tools/edit.md` / `.zh.md`、`multi-edit.md` / `.zh.md`：补充"网络异常不自动重试"的说明

### 6.3 docs/explanation 新增

- `docs/explanation/network-failure-contract.md` / `.zh.md`：本规范的精简版，讲清三条契约与四个 bug 的处理思路，供长期参考

## 7. 测试与验证策略

### 7.1 单元测试

- `tests/unit/test_warning_text_selection.py`（新建）：模拟 `_conn._snapshot_error` 与 `_reconnected` 的不同组合，验证 `call_tool` 选择正确的 WARNING 文案
- `tests/unit/test_no_retry_tools.py`（新建）：模拟工具调用抛 SSHException，验证 `Edit` / `MultiEdit` / `Bash` 走 `_with_reconnect_only` 路径，其他工具走 `_with_retry`

### 7.2 集成测试

复用现有 `sshd_kill_and_restart` fixture：

- `tests/integration/test_no_retry_for_edit.py`：模拟 Edit 调用中途链路断开。验证 agent 收到 `Error:` 字符串而**非**被框架自动重跑后的 `old_string not found`
- `tests/integration/test_sftp_op_timeout.py`：将 `op_timeout_default` 配为短值（5s），人为阻塞 SFTP（通过减速服务端或强行 hang），验证 SFTP 操作在该时间内返回错误
- `tests/integration/test_background_pidfile.py`：
  - 验证正常路径下 `/tmp/rmcp-bg-<uuid>.pid` 与 `/tmp/rmcp-bg-<uuid>.log` 文件存在且 uuid 一致
  - 模拟启动响应丢失，验证远端 pidfile 已存在、agent 可通过 `cat /tmp/rmcp-bg-*.pid` 找回 PID
- `tests/integration/test_snapshot_persistence.py`：
  - 验证 `_capture_snapshot()` 仅在 MCP 启动时调用一次
  - 模拟 reconnect，验证 snapshot 文件仍在 `~/.cache/remote-mcp/` 且未被重新捕获（`bash -ic` 未被再次调用）
  - 模拟远端 snapshot 文件被删除后 reconnect，验证从本地内存缓存重新上传成功
- `tests/integration/test_warning_three_cases.py`：覆盖三种 WARNING 文案的实际触发条件

## 8. 明确不在本次范围内

下列问题不违反三条契约，留待后续版本：

- `_with_retry` 单次重试且无指数退避——失败已通过错误信息返回，agent 可再次调用
- 缺少专用的链路探测工具——agent 可通过其他工具间接探测（例如 `RemoteInfo` 不走网络）
- 多次连续 reconnect 合并为单次 WARNING——实践中极少触发
- reconnect 失败原因以非结构化文本返回——agent 可解析文本

## 9. 影响面汇总

### 9.1 代码改动

| 文件 | 改动类别 |
|------|---------|
| `remote_mcp/config.py` | HostConfig 新增 `op_timeout_default` 字段 |
| `remote_mcp/connection.py` | 较大重构：snapshot 拆分、close 简化、reconnect 流程调整、settimeout 应用 |
| `remote_mcp/server.py` | `call_tool` 增加 `NO_RETRY_TOOLS` 分支、WARNING 文案三套选择、启动时调用 `_capture_snapshot` |
| `remote_mcp/tools/bash.py` | 仅 `_bash_background` 启动命令字符串与异常路径返回文本调整 |
| 其他 12 个 tool 文件 | **完全不动** |

### 9.2 测试改动

| 文件 | 改动 |
|------|------|
| `tests/unit/test_warning_text_selection.py` | 新建 |
| `tests/unit/test_no_retry_tools.py` | 新建 |
| `tests/integration/test_no_retry_for_edit.py` | 新建 |
| `tests/integration/test_sftp_op_timeout.py` | 新建 |
| `tests/integration/test_background_pidfile.py` | 新建 |
| `tests/integration/test_snapshot_persistence.py` | 新建 |
| `tests/integration/test_warning_three_cases.py` | 新建 |
| `tests/integration/test_bash_tool.py` | 现有 background 测试需要适配 pidfile 写入（验证 PID 与文件内容） |
| `tests/integration/test_connection.py` | snapshot 相关测试调整（不再每次 reconnect 都 capture） |

### 9.3 文档改动

| 文件 | 改动 |
|------|------|
| `CLAUDE.md.fragment.md` / `.zh.md` | 新增网络异常处理指引段 |
| `docs/reference/config-schema.md` / `.zh.md` | 新增 `op_timeout_default` 字段 |
| `docs/reference/errors.md` / `.zh.md` | 新增错误条目 |
| `docs/reference/tools/bash.md` / `.zh.md` | 补充 pidfile 恢复提示 |
| `docs/reference/tools/edit.md` / `.zh.md` | 补充不自动重试说明 |
| `docs/reference/tools/multi-edit.md` / `.zh.md` | 补充不自动重试说明 |
| `docs/explanation/network-failure-contract.md` / `.zh.md` | 新建 |
| `CHANGELOG.md` / `.zh.md` | v0.2.2 段 |
| 父 spec v1 / v0.2.0 | 增加超链接指向本规范 |

## 10. 接受的取舍

### 10.1 Edit / MultiEdit 在网络抖动后不再透明重试

agent 会比 v0.2.1 看到更多次"链路抖动 → 调用失败"事件。为它们做正确的 `_with_retry` 替代是不可能的——因为无法在框架层判断重试是否安全。把决定权交回 agent 是正确的取舍。

### 10.2 Background pidfile 在远端 `/tmp` 长期累积

每个 background 任务留下一个小文件，按典型使用频率每天约 10-100 个，单文件几字节。`/tmp` 系统重启或定期清理会自然回收。本规范不引入自动清理机制以保持简单。

### 10.3 Snapshot 文件长期累积在远端 `~/.cache/remote-mcp/`

每次 MCP 启动留下一个文件，按典型使用频率每天约 1-5 个，单文件几 KB 到几十 KB。`~/.cache/` 在 XDG 约定中不自动清理，但用户预期此目录可任意删除。本规范不引入自动清理机制。

### 10.4 多 MCP 实例并发对同一远端写 snapshot 不冲突，但都跑了一遍 `bash -ic`

`snapshot-<pid>.sh` 文件名按本地 PID 区分，互不覆盖；每个实例独立捕获自己的环境。这是 v0.2.0 已有的设计取舍，本规范不改变。

## 11. 实施提示

按依赖顺序：

1. `config.py` 加 `op_timeout_default` 字段
2. `connection.py` 应用 `channel.settimeout` 到 exec 与 SFTP（bug #2 修复）
3. `connection.py` 重构 snapshot 流程（bug #4 修复）
4. `server.py` 增加 `NO_RETRY_TOOLS` 分支与 `_with_reconnect_only`（bug #1 修复）
5. `server.py` 增加三套 WARNING 文案选择与启动 snapshot 失败的"待显示一次"机制（bug #4 收尾）
6. `tools/bash.py` `_bash_background` 启动命令与失败文本调整（bug #3 修复）
7. 集成测试覆盖
8. 文档级联
9. CHANGELOG v0.2.2 段

每步独立可测。

## 附录：术语

- **行为契约**：本规范在 §4 定义的三条"工具在网络异常下的行为约束"
- **`_with_retry`**：现有的 server.py 包装函数，捕获 SSH 层异常后 reconnect 并重跑工具调用一次
- **`_with_reconnect_only`**（v0.2.2 新增）：捕获 SSH 层异常后 reconnect 但**不**重跑当前调用，直接返回 `Error: ...`
- **`NO_RETRY_TOOLS`**（v0.2.2 新增）：不参与自动重试的工具集合，当前为 `{Edit, MultiEdit, Bash}`
- **`op_timeout_default`**（v0.2.2 新增）：单次通道 I/O 静默等待上限，默认 60s
- **本地内存 snapshot 缓存**：v0.2.2 后 snapshot 内容在 MCP 启动时捕获并保存到 `SSHConnection._snapshot_content`，session 期间不变，作为远端文件丢失时重传的来源
- **pidfile**：v0.2.2 后 background bash 启动时写入远端 `/tmp/rmcp-bg-<uuid>.pid` 的单行 PID 文件，用于响应丢失时 agent 找回 PID
