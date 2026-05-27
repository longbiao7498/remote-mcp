# remote-mcp 设计规范（v2）

**日期**：2026-05-26  
**状态**：✅ **已实施**（v0.1.0，2026-05-26 合并到 master）  
**实施记录**：参见 [`docs/superpowers/plans/2026-05-26-remote-mcp-implementation.md`](../plans/2026-05-26-remote-mcp-implementation.md)（31 个任务，6 阶段，全部完成）  
**前身**：本规范取代仓库根目录的 `软件设计文档.md`（v1.0）。v1 中被验证仍然适用的决定在本规范中重述；v2 增量在第 7、8、10、15 节集中体现。

---

## 1. 目标

让 Claude Code 通过 MCP 操控远程 Linux 服务器，使用体验对齐到 **不会因 schema/输出格式差异导致 agent 用错工具** 的程度。所有计算与文件操作发生在远程，本地仅做协议中继。

明确放弃的目标：让 Claude Code 训练时形成的"工具选择策略"自动偏向我们的远程工具。该问题由用户在自己项目的 CLAUDE.md 里引导，**不是本工具的责任**。

## 2. 硬性约束

- 远程主机：仅 SSH 可达，**不允许安装任何 agent 软件**。
- 本地：Linux + Python 3.8+。
- 协议：stdio MCP，挂接 Claude Code。
- 网络：低带宽、高延迟容忍——典型场景假定 ~100 KB/s 到 1 MB/s 持续带宽、RTT 200-1000 ms。所有设计决策必须经受这个假设的检验。
- 多主机：单次工作流可能同时操控 2-3 台主机（非大规模舰队）。

## 3. 架构总览

```
┌─────────────────────────────────────────────────────┐
│                    本地机器                          │
│                                                     │
│  ┌──────────────┐   stdio MCP   ┌────────────────┐  │
│  │  Claude Code │ ◄───────────► │   remote-mcp   │  │
│  │              │               │  (per host)    │  │
│  └──────────────┘               └───────┬────────┘  │
└────────────────────────────────────────│────────────┘
                                         │  SSH (compress=on, keepalive=30s)
                    ┌────────────────────▼─────────┐
                    │       远程 Linux 主机         │
                    │  ┌──────────────────────┐    │
                    │  │ bash --norc (持久)    │   │
                    │  └──────────────────────┘    │
                    │  原生文件系统（SFTP / sed）   │
                    └──────────────────────────────┘
```

**形态**：v1 = 纯 MCP server。每台远程主机一个 Python 进程，独立 SSH 连接、独立 BashSession。Claude Code plugin 形态见 §15。

**两条执行路径**：
- 无状态单次执行（Glob / Grep / Read 远程切片 / Write 的 mkdir）：`SSHConnection.exec()`，每次新建 channel。
- 持久 shell（Bash）：`BashSession` + sentinel 协议，整个连接生命周期内复用。

**文件操作通道**：SFTP 二进制安全，不经 shell，无转义陷阱。

## 4. 工具集（10 个）

Read、Write、Edit、**MultiEdit**、**MultiRead**、**FileStat**、Bash（含 `run_in_background` 参数）、Glob、Grep（参数扩展）、**Feedback**。所有工具：
- 失败返回以 `Error:` 开头的字符串，不抛异常。
- 工具描述（description）末尾嵌入 1 行带宽感知或使用提示（见 §10 M1）。
- **保真度策略**：Read/Write/Edit/MultiEdit/Bash/Glob/Grep 的名称、参数名、输出格式对齐 Claude Code 原生工具；MultiRead/FileStat/Feedback 是为远程带宽场景或开发反馈循环新增的工具（原生无对应），按"自洽、不易误用"标准设计 schema。

**为什么加这 5 项（v2 相对 v1 工具集）**：

| 增量 | 解决的反模式 / 目的 | 收益 |
|------|------------------|------|
| **MultiEdit** | 同文件 N 次 Edit = 2N 次完整文件传输 | N 次 RTT → 1 次 RTT |
| **MultiRead** | 探索多个相关文件 = N 次独立 Read | N 次 RTT → 1 次 RTT |
| **FileStat** | "检查文件是否存在/多大" 用 Read 试探，可能传几 MB 只为知道大小 | 几字节 vs 完整文件 |
| **Grep 参数扩展**（`-A/-B/-C` 等） | grep 找到匹配后再 Read 周围上下文 | 半数往返消失 |
| **Bash `run_in_background`** | 长操作（build/test/install）阻塞整个对话 | 立即返回，不省带宽但消除阻塞 |
| **Feedback** | agent 使用本工具时遇到的 bug / 灵光一现的功能想法没渠道沉淀 | 自动 dev loop——维护者可基于真实使用反馈迭代 |

## 5. 模块详细设计

### 5.1 `connection.py`

```python
# Fragment
@dataclass
class HostConfig:
    hostname: str
    user: str
    port: int = 22
    key_path: Optional[str] = None
    password: Optional[str] = None
    jump_host: Optional[str] = None
    connect_timeout: float = 10.0
    keepalive_interval: int = 30
    compression: bool = True              # v2 新增，默认 on
    bash_timeout_default: int = 120        # v2 新增，原 60s 偏紧
    glob_output_limit: int = 1000          # v2 新增
    read_size_cap: int = 256 * 1024        # v2 新增
    bash_output_cap: int = 100 * 1024      # v2 新增

@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int

class SSHConnection:
    def connect(self) -> None:
        """建立 SSH，启用 compress=True 和 keepalive。"""

    def exec(self, command: str, timeout: float = 30.0) -> ExecResult: ...
    def get_sftp(self) -> paramiko.SFTPClient: ...
    def get_bash_session(self) -> BashSession: ...
    def close(self) -> None: ...

    # 重连机制
    def _do_reconnect(self) -> None:
        self.connect()
        self._reconnected = True   # 见 §9

    def check_and_clear_reconnect_flag(self) -> bool: ...
```

**ProxyJump**：跳板机用 `open_channel("direct-tcpip", (target_host, target_port), ("localhost", 0))` 拿到 tunnel channel，作为目标 client `connect(sock=tunnel)` 的 socket。

**SSH 压缩**：`SSHClient.connect(..., compress=True)`。对文本传输（源码/配置/日志）通常 3-10× 压缩，CPU 开销可忽略。**这是 v2 相对 v1 的关键改动之一**。

#### 5.1.1 连接生命周期与持久化（重要）

整个设计的"持久"是分层的，理解这一层之前，先理解最底下的**进程模型**：

**进程模型**：每个 `claude mcp add` 注册的 remote-mcp server 是一个**长生命 OS 进程**。Claude Code 启动后 spawn 该进程，进程在**整个 Claude Code 会话期间不退出**——不是 per-tool-call 起一个新进程。Claude Code 关闭 → stdio 关闭 → MCP server 收到 EOF → `main()` 的 `try/finally` 退出 → 调 `conn.close()`。

**SSH 连接持久化**：

`main()` 在进程启动时调一次 `conn.connect()`，建立一个 paramiko `Transport`——本质是一个 TCP socket 上承载的 SSH 会话状态。这个 Transport **在整个进程生命周期内常驻**，所有工具调用复用它。

**Transport 上的多路复用**——单 Transport 叠开多种 channel：

| Channel 用途 | 生命周期 | 实现 |
|------------|---------|------|
| 持久 bash session | 与 Transport 同生命（直到重连） | `BashSession`，§5.2 |
| SFTP client | 懒初始化后复用 | `get_sftp()` 缓存单例 |
| 单次 `exec()` | 每次新开、用完关闭 | Glob/Grep/MultiRead/Read sed 切片各调各的 |

**keepalive**：`transport.set_keepalive(30)` 每 30 秒在 SSH 协议层发心跳——产生少量流量，**防止 VPN / 防火墙因空闲超时切 TCP**。`keepalive_interval` 配置项可调，应小于 VPN 的空闲超时阈值。

**持久化分层一览**：

```
┌─────────────────────────────────────────────────────────┐
│  MCP server OS 进程    （per host，整个 Claude Code 会话）│
│  ┌────────────────────────────────────────────────┐    │
│  │  paramiko Transport（TCP+SSH 会话状态）         │    │
│  │  ┌──────────────┐  ┌─────────────┐ ┌─────────┐ │    │
│  │  │ bash channel │  │ SFTP client │ │ exec ×N │ │    │
│  │  │（常驻）       │  │（懒初始化）  │ │（每次）  │ │    │
│  │  └──────────────┘  └─────────────┘ └─────────┘ │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
   │ disconnect / reconnect → 重建整个 Transport 子树
```

**重连点的"持久边界"**：当网络断、Transport 死掉时，**整个子树（bash session、SFTP、所有 channel）一起失效**。重连后是全新的 Transport + 全新的 bash session（cwd / env 丢失）→ §9 的 WARNING 机制保证 agent 知情。重连失败 → 返回 `Error:`，进程不退出（用户可介入修复后下次工具调用会再触发重连尝试）。

### 5.2 `bash_session.py` — Sentinel 协议（最高风险模块）

**为什么需要 sentinel**：持久 bash 的 stdout 是连续流，没有内建的"命令结束"信号。需要在用户命令后追加一行可识别的 echo，从输出里检测它的出现来判断命令边界。

**协议**：

```
发送到 bash stdin:
    {user_command}
    echo "RMCP_SENTINEL_{uuid}_EXIT_$?_CWD_$(pwd)"

从 bash stdout 读:
    每行检查是否匹配正则 ^RMCP_SENTINEL_{uuid}_EXIT_(\d+)_CWD_(.*)$
    匹配前的所有行 → output
    匹配行 → 提取 exit_code 和 cwd，停止读取
    sentinel 行本身不返回给调用方
```

注：`_EXIT_$?_CWD_$(pwd)` 一次性同时捕获退出码与当前目录，是 §8 P1（多主机 cwd 可见性）的协议层基础。`$(pwd)` 在 echo 求值时展开，其值就是 user_command 执行后的实际 cwd（包括 user_command 里 `cd` 引起的变化）。

`uuid` 每次 `execute()` 独立生成（`uuid4().hex`），防止用户输出意外包含旧的 sentinel。

**bash 进程启动与初始化序列**（**不可省略，缺一会破坏 sentinel 解析**）：

```bash
bash --norc --noprofile

# 启动后立即注入：
set +m              # 关 job control 通知，避免 [1]+ Done ... 污染输出
set +o histexpand   # 关 ! 历史扩展，避免命令中的 ! 触发副作用
export PS1=''       # 清空提示符，避免每行命令前混入提示符字符串
export TERM=dumb    # 关闭终端控制序列
exec 2>&1           # stderr 合并到 stdout
```

**后台读取线程**：paramiko channel 缓冲区有限（默认 64KB 级别）。如果本地不及时 `recv()`，远程 bash 在写满缓冲后会阻塞，进而 sentinel 永远不会到达——死锁。因此必须有一个 daemon 线程持续 `recv()` 并按行入队，`execute()` 从队列消费。

```python
# Fragment
class BashSession:
    def __init__(self, transport): ...
    def start(self) -> None: ...  # 启动 bash + 注入初始化序列

    def execute(self, command: str, timeout: float = 120.0) -> BashResult:
        """
        超时：发送 b'\\x03'（Ctrl-C），抛 TimeoutError。
        bash 进程本身不退出，下次 execute 仍可用。
        """

    def _reader_thread(self) -> None: ...   # 必备 daemon 线程
```

**返回结果元信息（v2 新增 P1）**：sentinel 协议**扩展为同时捕获 exit_code 和 cwd**。具体做法见 §5.3.5——把 sentinel echo 改为 `echo "RMCP_SENTINEL_{uuid}_EXIT_$?_CWD_$(pwd)"`，解析时同时提取两个字段。BashSession 缓存最近一次 cwd，工具层（`tools/bash.py`）将其拼入返回前缀。

### 5.3 `tools/` — 工具实现

#### 5.3.1 Read（v2 改动：默认远程切片）

```python
# Fragment
def read(conn: SSHConnection, sftp: paramiko.SFTPClient,
         file_path: str, offset: int = 1, limit: int = 2000) -> str:
    # 关键改动：默认走远程 sed 切片，只传需要的行
    end = offset + limit - 1
    cmd = f"sed -n '{offset},{end}p; {end+1}q' {shlex.quote(file_path)}"
    result = conn.exec(cmd)
    if result.exit_code != 0:
        if "No such file" in result.stderr:
            return f"Error: File not found: {file_path}"
        return f"Error: {result.stderr.strip()}"

    lines = result.stdout.splitlines(keepends=True)
    out = "".join(f"     {offset + i}\t{line}" for i, line in enumerate(lines))

    # 大小 cap
    if len(out) > conn.config.read_size_cap:
        out = out[:conn.config.read_size_cap]
        out += f"\n... [truncated to {conn.config.read_size_cap} bytes]"
    return out
```

**与 v1 的差异**：v1 是 `SFTP 全文 → Python 切片`；v2 是 `sed 远程切片 → 传几 KB`。100 MB 文件读 20 行的流量从 100 MB 降到几 KB。

**关于换行符与 keepends**：sed 输出保留换行；用 `splitlines(keepends=True)` 重建行号前缀。

#### 5.3.2 Write（v2 改动：SFTP 原生 mkdir）

```python
# Fragment
def write(sftp: paramiko.SFTPClient, file_path: str, content: str) -> str:
    parent = posixpath.dirname(file_path)
    _sftp_mkdirs(sftp, parent)   # 递归 SFTP mkdir，省一次 channel
    with sftp.file(file_path, 'w') as f:
        f.write(content.encode('utf-8'))
    return f"Successfully wrote {len(content)} characters to {file_path}"

def _sftp_mkdirs(sftp, path):
    """逐级 mkdir。每级若 stat 成功跳过，否则 mkdir。"""
```

**与 v1 的差异**：v1 用 `conn.exec("mkdir -p ...")` 多建一次 channel；v2 复用 SFTP 连接，省一个 RTT。

#### 5.3.3 Edit

```python
# Fragment
def edit(sftp: paramiko.SFTPClient, file_path: str,
         old_string: str, new_string: str,
         replace_all: bool = False) -> str:
    try:
        with sftp.file(file_path, 'r') as f:
            content = f.read().decode('utf-8')
    except IOError:   # paramiko raises IOError (not FileNotFoundError) on SFTP ENOENT
        return f"Error: File not found: {file_path}"

    if replace_all:
        if old_string not in content:
            return f"Error: old_string not found in {file_path}"
        new_content = content.replace(old_string, new_string)
    else:
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {file_path}"
        if count > 1:
            return (f"Error: old_string found {count} times in {file_path}. "
                    f"Provide more context to match uniquely, "
                    f"or set replace_all=true to replace all.")
        new_content = content.replace(old_string, new_string, 1)

    with sftp.file(file_path, 'w') as f:
        f.write(new_content.encode('utf-8'))
    return f"Successfully edited {file_path}"
```

Edit 必须读全文（为了正确判定 old_string 唯一性）。这是带宽妥协的极限：源码/配置文件通常 < 100 KB，可接受。

#### 5.3.4 MultiEdit（v2 新增）

```python
# Fragment
def multi_edit(sftp: paramiko.SFTPClient, file_path: str,
               edits: list[dict]) -> str:
    """
    edits: list of {"old_string": str, "new_string": str, "replace_all"?: bool}
    按顺序应用，原子性：任一 edit 失败回滚整体不写。
    """
    try:
        with sftp.file(file_path, 'r') as f:
            content = f.read().decode('utf-8')
    except IOError:   # paramiko raises IOError on SFTP ENOENT
        return f"Error: File not found: {file_path}"

    current = content
    for i, e in enumerate(edits):
        old, new = e["old_string"], e["new_string"]
        replace_all = e.get("replace_all", False)
        if replace_all:
            if old not in current:
                return f"Error: edit #{i+1}: old_string not found"
            current = current.replace(old, new)
        else:
            count = current.count(old)
            if count == 0:
                return f"Error: edit #{i+1}: old_string not found"
            if count > 1:
                return (f"Error: edit #{i+1}: old_string found {count} times. "
                        f"Provide more context or set replace_all=true.")
            current = current.replace(old, new, 1)

    with sftp.file(file_path, 'w') as f:
        f.write(current.encode('utf-8'))
    return f"Successfully applied {len(edits)} edits to {file_path}"
```

**带宽收益**：N 次 Edit = N 次完整 read + N 次完整 write = 2N 次大传输；MultiEdit = 1 次 read + 1 次 write = 2 次大传输。

#### 5.3.5 MultiRead（v2 新增）

**反模式**：agent 探索一个模块时连续读 3-5 个相关文件（config / models / utils），每个文件一次 Read = 一次 SSH RTT。高延迟链路上累计 1-5 秒纯延迟。

```python
# Fragment
def multi_read(conn: SSHConnection,
               reads: list[dict]) -> str:
    """
    reads: list of {"file_path": str, "offset"?: int (1-based), "limit"?: int}
    远程一次性切片所有文件，按文件分块返回带行号的内容。
    """
    if not reads:
        return "Error: reads list is empty"

    # 构造一个远程脚本，对每个 file 跑 sed -n 切片
    script_lines = []
    for r in reads:
        fp = r["file_path"]
        offset = r.get("offset", 1)
        limit = r.get("limit", 2000)
        end = offset + limit - 1
        qfp = shlex.quote(fp)
        script_lines.append(
            f'echo "===RMCP_FILE_BEGIN:{fp}==="; '
            f'if [ -f {qfp} ]; then '
            f'  sed -n \'{offset},{end}p; {end+1}q\' {qfp}; '
            f'  echo "===RMCP_FILE_END:{fp}:OK==="; '
            f'else '
            f'  echo "===RMCP_FILE_END:{fp}:NOT_FOUND==="; '
            f'fi'
        )
    cmd = "; ".join(script_lines)
    result = conn.exec(cmd, timeout=60)

    # 解析分块，给每块加上行号前缀（按各自 offset 起算）
    return _format_multi_read(result.stdout, reads, conn.config.read_size_cap)
```

**返回格式**（agent 易解析）：

```
===FILE: /path/to/file1.py===
     1	import os
     2	import sys
     ...

===FILE: /path/to/file2.py===
NOT_FOUND

===FILE: /path/to/file3.py===
    10	def foo():
    11	    return 42
    ...
```

**带宽收益**：N 个文件 = 1 次 RTT 而非 N 次 RTT。在 RTT 500ms 链路上，5 个文件读取从 2.5 秒降到 0.5 秒。

**关于总大小 cap**：所有文件累计内容若超过 `read_size_cap`，按文件顺序累加截断（保证至少返回前几个文件完整）。返回末尾追加 `... [N more files truncated]`。

#### 5.3.6 FileStat（v2 新增）

**反模式**：agent 想知道"文件存在吗？多大？什么时候改的？"，要么 `Bash("stat file")` 一次往返、要么直接 Read 试探——后者可能传输几十 MB 只为知道文件不该被读。

```python
# Fragment
import stat as _stat

def file_stat(sftp: paramiko.SFTPClient,
              file_paths: Union[str, list[str]]) -> str:
    """
    file_paths: 单个路径或路径列表。
    返回结构化文本（每个文件一行或一段），含 exists/size/mtime/mode/is_dir。
    """
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    lines = []
    for fp in file_paths:
        try:
            st = sftp.stat(fp)
            kind = "dir" if _stat.S_ISDIR(st.st_mode) else \
                   "symlink" if _stat.S_ISLNK(st.st_mode) else \
                   "file"
            mtime_iso = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
            lines.append(
                f"{fp}: exists=true type={kind} size={st.st_size} "
                f"mode={oct(st.st_mode)[-4:]} mtime={mtime_iso}"
            )
        except IOError:   # paramiko's SFTP raises IOError on ENOENT (not FileNotFoundError)
            lines.append(f"{fp}: exists=false")
        except PermissionError:
            lines.append(f"{fp}: error=permission_denied")
        except Exception as e:
            lines.append(f"{fp}: error={type(e).__name__}: {e}")

    return "\n".join(lines)
```

**带宽收益**：单次 stat 调用通常 < 100 bytes（vs. Read 一个文件可能是 MB 级）。对"试探性 Read"反模式是数量级的优化。

**为什么走 SFTP `stat` 而非 `Bash("stat ...")`**：SFTP `stat` 复用已有 SFTP session（无需 channel 建立），且返回结构化数据（无需解析 stat 命令输出）。批量调用也比 shell `for` 循环快——每个 stat 是单 SFTP 消息。

#### 5.3.7 Bash（v2 改动：host+cwd 前缀 + `run_in_background`）

```python
# Fragment
def bash(session: BashSession, conn_name: str, command: str,
         run_in_background: bool = False,
         timeout: float = 120.0,
         description: str = "") -> str:
    if run_in_background:
        return _bash_background(session, conn_name, command)
    return _bash_foreground(session, conn_name, command, timeout)

def _bash_foreground(session, conn_name, command, timeout):
    try:
        result = session.execute(command, timeout=timeout)
    except TimeoutError:
        return f"Error: Command timed out after {timeout}s on {conn_name}"

    cwd = session.current_cwd()
    output = result.output

    # v2 P1：结果加主机+cwd 元信息行
    prefix = f"[host={conn_name} cwd={cwd}]\n"

    if result.exit_code != 0:
        output += f"\n[Exit code: {result.exit_code}]"

    # 输出 cap
    if len(output) > session.config.bash_output_cap:
        output = output[:session.config.bash_output_cap] + \
                 f"\n... [truncated to {session.config.bash_output_cap} bytes]"

    return prefix + output

def _bash_background(session, conn_name, command):
    """
    v2 新增：后台启动命令，立即返回 PID + 日志路径 + 操作命令模板。
    用 setsid 把命令放入独立进程组（PID = PGID），agent 可用
    `kill -- -<pid>` 干净地杀掉整棵进程树。
    """
    bg_uuid = uuid.uuid4().hex[:12]
    log_path = f"/tmp/rmcp-bg-{bg_uuid}.log"
    quoted_cmd = shlex.quote(command)
    quoted_log = shlex.quote(log_path)

    # 关键点：
    #   1. setsid 创建新会话，bash 成为新进程组 leader，PID = PGID
    #   2. nohup 防 SIGHUP（虽然 setsid 已脱离 controlling terminal，加上更稳）
    #   3. </dev/null 切断 stdin，避免后台进程阻塞读输入
    #   4. ( ... ) 子 shell 包裹，确保 $! 在 echo 时刚被赋值
    wrap = (
        f"( setsid nohup bash -c {quoted_cmd} "
        f"> {quoted_log} 2>&1 </dev/null & echo \"BG_PID=$!\" )"
    )
    result = session.execute(wrap, timeout=10)

    # 解析 BG_PID=<n>
    m = re.search(r"BG_PID=(\d+)", result.output)
    if not m:
        return (f"Error: failed to start background task on {conn_name}. "
                f"Output: {result.output[:500]}")
    pid = m.group(1)
    cwd = session.current_cwd()

    return (
        f"[host={conn_name} cwd={cwd}]\n"
        f"Started background task.\n"
        f"  PID: {pid}\n"
        f"  Log: {log_path}\n\n"
        f"To check status:    Bash(\"kill -0 {pid} && echo running || echo done\")\n"
        f"To read new output: Read(\"{log_path}\", offset=<last_line+1>)\n"
        f"To stop gracefully: Bash(\"kill -TERM -- -{pid}\")\n"
        f"To force stop:      Bash(\"kill -KILL -- -{pid}\")\n"
    )
```

`session.current_cwd()` 返回最近一次 `execute()` 捕获并缓存的 cwd 值。捕获机制：sentinel 行格式扩展为 `RMCP_SENTINEL_{uuid}_EXIT_$?_CWD_$(pwd)`（与 §5.2 一致），解析时按 `_EXIT_` 和 `_CWD_` 切分提取两字段。**这是 P1 的具体落地**。

**后台任务的关键设计点**：
- **使用 `setsid` 而非 `&` 自带的后台化**：我们 `set +m` 关了 job control，bash 默认不会把 `cmd &` 放进新进程组——它仍在 BashSession 的进程组里。如果 agent 用 `kill -- -<pid>` 想杀整组，会连 BashSession 一起干掉。必须显式 `setsid` 让后台命令成为独立 session/进程组的 leader。
- **不是新工具**：bg 模式复用现有 Bash 工具，仅是 `run_in_background=true` 参数分支。agent 现有"Bash 经验"无缝迁移。
- **不需要 BashOutput/KillBash 这类配套工具**：日志在远程文件，复用现有 Read 拉取；终止用现有 Bash 执行 `kill` 命令。这是 Claude Code 原生设计（截至当前版本）相同的简洁路径。
- **日志清理**：MCP server 进程退出时不自动清理 `/tmp/rmcp-bg-*.log`——文件留着方便用户事后排查。`/tmp` 重启会清，可接受。

#### 5.3.8 Glob（v2 改动：`**` 修正 + cap）

```python
# Fragment
def glob_tool(conn: SSHConnection, pattern: str, path: str = ".") -> str:
    find_expr = _glob_to_find(pattern)     # "**/*.py" → "-path '*.py'"
                                            # "src/**/*.py" → "-path 'src/*/*.py'" or "-wholename"
    limit = conn.config.glob_output_limit
    # Fetch limit+1 so we can detect overflow precisely; trim to `limit` if so.
    cmd = (f"find {shlex.quote(path)} "
           f"\\( {find_expr} \\) -type f | sort | head -{limit + 1}")
    result = conn.exec(cmd)
    if result.exit_code not in (0, 1):
        return f"Error: {result.stderr.strip()}"
    if not result.stdout.strip():
        return "No files found matching pattern"

    lines = result.stdout.splitlines()
    if len(lines) > limit:
        return "\n".join(lines[:limit]) + f"\n... [truncated to {limit} entries]"
    return result.stdout

def _glob_to_find(pattern: str) -> str:
    """
    转换规则（实施时编单元测试覆盖）：
      *.py           → -name '*.py'
      **/*.py        → -name '*.py'   （等价：递归找文件名匹配）
      src/*.py       → -wholename 'src/*.py'
      src/**/*.py    → -wholename 'src/*/*.py' OR -wholename 'src/*.py'（递归用 -path '*/src/*/*.py'）
    """
```

**与 v1 的差异**：v1 直接 `find -name <basename>`，丢失路径段；v2 把 pattern 拆解为 `-name` 或 `-wholename`/`-path`，保留路径层级语义。**接近**原生 `**` 但不保证 100% 等价（用例驱动验证）。

#### 5.3.9 Grep（v2 改动：参数扩展）

**v2 扩展的参数（与 Claude Code 原生 Grep 对齐 + 直接的带宽收益）**：

| 新增参数 | 等价 grep 选项 | 带宽收益 |
|---------|----------------|---------|
| `before: int = 0` | `-B N` | 显示匹配前 N 行 |
| `after: int = 0` | `-A N` | 显示匹配后 N 行 |
| `context: int = 0` | `-C N` | 同时设前后 N 行（覆盖 before/after） |
| `head_limit: int = 200` | `\| head -N` | 显式指定输出上限 |
| `output_mode: str = "content"` | 默认 / `-l` / `-c` | content/files_with_matches/count |
| `glob: str = ""` | `--include` | 文件名 pattern 过滤（兼容旧 `include` 参数） |

`-A/-B/-C` 是带宽收益最大的单点——它把"grep 找到关键字 → 再 N 次 Read 周围代码"的反模式压成 1 次 RTT。

```python
# Fragment
def grep_tool(conn: SSHConnection, pattern: str, path: str,
              include: str = "",
              case_insensitive: bool = False,
              before: int = 0,
              after: int = 0,
              context: int = 0,
              head_limit: int = 200,
              output_mode: str = "content") -> str:
    # output_mode 映射
    if output_mode == "files_with_matches":
        mode_flag = "-l"
    elif output_mode == "count":
        mode_flag = "-c"
    elif output_mode == "content":
        mode_flag = "-n"
    else:
        return f"Error: invalid output_mode: {output_mode!r}"

    flags = ["-r", mode_flag]
    if case_insensitive:
        flags.append("-i")

    # 上下文行（仅 content 模式有意义）
    if output_mode == "content":
        if context > 0:
            flags.append(f"-C{context}")
        else:
            if before > 0:
                flags.append(f"-B{before}")
            if after > 0:
                flags.append(f"-A{after}")

    include_opt = f"--include={shlex.quote(include)}" if include else ""
    cmd = (f"grep {' '.join(flags)} {include_opt} -E "
           f"{shlex.quote(pattern)} {shlex.quote(path)} "
           f"| head -{head_limit}")
    result = conn.exec(cmd)
    # grep 退出码：0=匹配，1=无匹配，2=错误
    if result.exit_code == 2:
        return f"Error: {result.stderr.strip()}"
    if result.exit_code == 1:
        return "No matches found"
    return result.stdout
```

**`multiline` 参数刻意不支持**：原生 Grep 的 multiline 依赖 ripgrep 的 `-U` 标志，我们的实施基于 POSIX `grep`（远程未必有 ripgrep）。标准 `grep -E` 跨行匹配能力有限。这是已知缺口，进 §14 已知局限。

#### 5.3.10 Feedback（v2 新增，非原生）

**目的**：让 agent 在使用 remote-mcp 工具的过程中持续沉淀两类信息——
1. **bug**：remote-mcp 工具表现不符合预期（schema 错位、错误措辞偏离原生、输出损坏、超时反常等）
2. **enhancement**：agent 在工作中想到的、能让 remote-mcp 工作流更高效的功能（新工具、新参数、新优化）

输出落到本地一份 JSONL 文件，让维护者后续基于真实使用数据迭代。**绝不外传**，纯本地 dev loop。

```python
# Fragment
import json
import os
import pathlib
from datetime import datetime, timezone

def feedback(conn_name: str, feedback_path: str,
             category: str, summary: str, details: str = "") -> str:
    if category not in ("bug", "enhancement"):
        return (f"Error: category must be 'bug' or 'enhancement', "
                f"got {category!r}")
    if not summary.strip():
        return "Error: summary cannot be empty"

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": conn_name,
        "category": category,
        "summary": summary.strip(),
        "details": (details.strip() or None) if details else None,
        "session_pid": os.getpid(),
    }

    path = pathlib.Path(feedback_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    # JSONL append。单次 write 在 POSIX 上对 < PIPE_BUF (通常 4 KB)
    # 的数据是原子的——单条 feedback 远小于此阈值，多进程并发安全。
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)

    return f"Feedback recorded: [{category}] {summary} -> {feedback_path}"
```

**自动捕获 vs. agent 提供**：

| 字段 | 来源 | 备注 |
|------|------|------|
| `ts` | 工具自动 | UTC ISO 8601 |
| `host` | 工具自动 | 当前 MCP server 关联的远程主机名 |
| `session_pid` | 工具自动 | MCP server 进程 PID，便于关联日志 |
| `category` | agent 提供 | `bug` / `enhancement` |
| `summary` | agent 提供 | 一行摘要 |
| `details` | agent 提供（可选） | 详细描述：哪个工具、做了什么、期望/实际 |

**为什么不让 agent 读历史 feedback**：故意只暴露写入接口。读取 = 多一次工具调用、可能干扰任务专注、且无价值（agent 自然记不住既往反馈也无所谓——维护者后续 dedupe）。如果将来 M3 plugin 需要"agent 查询过历史反馈避免重复"，再加。

**为什么独立工具而不是让 agent 自己 Write 文件**：
- Schema 一致性：分类、字段、时间戳格式不依赖 agent 记忆
- 原子性：多进程（多主机）并发写同一文件，shell 走 Write 难保证；工具内 `open(..., 'a')` POSIX 原子
- 触发性：独立工具配合工具 description 能更有效引导 agent 主动反馈

**输出文件示例**：

```
{"ts":"2026-05-26T14:30:00+00:00","host":"prod","category":"bug","summary":"Glob '**' missed nested matches","details":"Tried Glob(pattern='src/**/*.py', path='.'). Expected src/sub/foo.py to appear; only got src/foo.py.","session_pid":12345}
{"ts":"2026-05-26T15:12:33+00:00","host":"gpu","category":"enhancement","summary":"Add MultiWrite tool","details":"Often need to write 3-4 new files in sequence (e.g. scaffolding). Each Write is one round-trip; a MultiWrite([{path,content}, ...]) would compress to 1 RTT — symmetric to MultiRead.","session_pid":54321}
```

**隐私**：`details` 可能含用户代码片段。文件完全本地，由用户自己拥有。M2 文档里写明这点。

### 5.4 `server.py`

```python
# Fragment
app = Server("remote-mcp")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="Read", description=READ_DESC, inputSchema=READ_SCHEMA),
        Tool(name="Write", description=WRITE_DESC, inputSchema=WRITE_SCHEMA),
        Tool(name="Edit", description=EDIT_DESC, inputSchema=EDIT_SCHEMA),
        Tool(name="MultiEdit", description=MULTIEDIT_DESC, inputSchema=MULTIEDIT_SCHEMA),
        Tool(name="MultiRead", description=MULTIREAD_DESC, inputSchema=MULTIREAD_SCHEMA),
        Tool(name="FileStat", description=FILESTAT_DESC, inputSchema=FILESTAT_SCHEMA),
        Tool(name="Bash", description=BASH_DESC, inputSchema=BASH_SCHEMA),
        Tool(name="Feedback", description=FEEDBACK_DESC, inputSchema=FEEDBACK_SCHEMA),
        Tool(name="Glob", description=GLOB_DESC, inputSchema=GLOB_SCHEMA),
        Tool(name="Grep", description=GREP_DESC, inputSchema=GREP_SCHEMA),
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    prefix = ""
    if conn.check_and_clear_reconnect_flag():
        # v2 P2：WARNING 文本带 host 名
        prefix = (
            f"[WARNING] SSH connection to {conn.config.name} was lost and "
            f"has been re-established. The remote bash session has been reset: "
            f"working directory is now $HOME, all environment variables set in "
            f"previous commands are lost. Use absolute paths and re-run any "
            f"necessary setup commands.\n\n"
        )
    result = dispatch(name, arguments, conn)
    return [TextContent(type="text", text=prefix + result)]

# 进程入口 —— SSH 连接的生命周期完全由 main() 的 try/finally 框定
async def main(host_name: str, config_path: str) -> None:
    """
    在 MCP server 进程启动时：
      1. 加载 config.yaml
      2. 建立 SSH 连接（compress=True、keepalive 启用）
      3. 进入 stdio MCP 主循环（永远 await，直到 Claude Code 关闭 stdio）
      4. 收到 EOF → 退出循环 → finally 块清理 SSH 连接
    
    全程只有一个 SSHConnection 实例，所有工具调用复用之。
    """
    global conn
    config = load_config(config_path)
    conn = SSHConnection(config.hosts[host_name])
    conn.connect()              # 一次性建立 Transport
    try:
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream,
                          app.create_initialization_options())
    finally:
        conn.close()            # 进程退出前清理 bash session、SFTP、Transport

# __main__.py 里：
#   import asyncio
#   from .server import main
#   asyncio.run(main(args.host, args.config))
```

每个工具的 description 文本（M1 嵌入）见 §10。

**关于 `global conn`**：单进程单连接，全局变量是最直接的传参方式，避免每个工具签名里都塞一个 `conn`。如果将来扩展（不太可能在 v1），可改为 `ContextVar` 或闭包注入。

## 6. 工具接口规范

参数名、字段顺序、错误措辞需要在实施阶段对照 Claude Code 实际原生工具确认（建议：跑一遍 `mcp__local__list_tools` 抓取原生 schema 比对）。下表列规范要点，schema 完整 JSON 见实施时生成的 `schemas.py`。

| 工具 | 必参 | 选参 | 输出格式要点 |
|------|------|------|--------------|
| Read | `file_path` | `offset=1`, `limit=2000` | `     <lineno>\t<line>` 5 空格 + 数字 + tab |
| Write | `file_path`, `content` | — | `Successfully wrote N characters to <path>` |
| Edit | `file_path`, `old_string`, `new_string` | `replace_all=false` | `Successfully edited <path>` |
| MultiEdit | `file_path`, `edits` (list of {old_string, new_string, replace_all?}) | — | `Successfully applied N edits to <path>` |
| **MultiRead** | `reads` (list of {file_path, offset?, limit?}) | — | 每文件一段，`===FILE: <path>===` 分隔 + 行号前缀 |
| **FileStat** | `file_paths` (string or list) | — | 每文件一行：`<path>: exists=... type=... size=... mode=... mtime=...` |
| Bash | `command` | `run_in_background=false`, `timeout=120`, `description=""` | 前台：`[host=X cwd=Y]\n<output>[\n[Exit code: N]]`；后台：`[host=X cwd=Y]\nStarted background task.\n  PID: <pid>\n  Log: <log_path>\n\n<usage hints>` |
| Glob | `pattern` | `path="."` | 每行一个绝对/相对路径 |
| Grep | `pattern`, `path` | `include`/`glob`, `case_insensitive=false`, `before=0`, `after=0`, `context=0`, `head_limit=200`, `output_mode="content"` | content 模式：`path:lineno:matched_line`；files_with_matches：每行一个路径；count：`path:count` |
| **Feedback** | `category` (`"bug"` 或 `"enhancement"`), `summary` | `details=""` | `Feedback recorded: [<category>] <summary> -> <path>` |

错误文本必须**逐字**对齐原生（"File not found:"、"old_string not found"、"old_string found N times in ..."），否则 agent 的恢复策略可能失效。MultiRead/FileStat/Feedback 因无原生对应，错误措辞按 spec §5.3.5/§5.3.6/§5.3.10 钉死。

## 7. 带宽与延迟优化（v2 核心增量）

| 优化 | 原 v1 行为 | v2 新行为 | 收益 |
|------|------------|-----------|------|
| Read | SFTP 全文 → Python 切片 | `sed -n` 远程切片 | 100MB 文件读 20 行：100MB → 几 KB |
| Write 父目录 | `conn.exec("mkdir -p")` | SFTP 原生 mkdir | 省 1 个 channel RTT |
| SSH 压缩 | 未启用 | `compress=True` 默认 | 文本流量 3-10× 压缩 |
| **MultiEdit** | 不存在 | 1 read + N in-memory + 1 write | N 次 Edit 的 2× 传输 → 2× |
| **MultiRead** | 不存在 | 1 次 RTT 切片所有文件 | N 次 RTT → 1 次 RTT |
| **FileStat** | 不存在（agent 用 Read 试探） | SFTP stat，几字节返回 | 试探巨大文件场景节省整个文件传输 |
| **Grep `-A/-B/-C`** | 不支持上下文 | grep 返回匹配 + N 行上下文 | grep+多次 Read → 1 次 RTT |
| **Bash `run_in_background`** | 阻塞等待 | 立即返回 PID/log | 不省带宽，**消除高延迟链路上的阻塞感** |
| Glob 输出 | 无上限 | `head -1000` | 防止大目录树灌爆 |
| Read 结果 | 无上限 | 256 KB cap | 防止 agent 显式传超大 limit |
| Bash 输出 | 无上限 | 100 KB cap | 防止 `find /` 等失误刷爆带宽 |
| Bash 超时 | 60s 默认 | 120s 默认 | 高延迟链路上 build/test 不被误杀 |

cap 触发时输出末尾追加截断说明（`... [truncated to N bytes]`），让 agent 知道结果不完整。

## 8. 多主机支持

**模型**：一台远程主机一个 Python 进程。用户对每台分别 `claude mcp add`：

```bash
claude mcp add --scope user remote-prod -- python -m remote_mcp --host prod
claude mcp add --scope user remote-gpu  -- python -m remote_mcp --host gpu
```

Claude Code 看到的工具：`mcp__remote-prod__Read`、`mcp__remote-gpu__Bash`、...

**v2 多主机改进**：
- **P1**：Bash 工具结果前缀 `[host=<name> cwd=<pwd>]`，让 agent 在多主机场景下看清当前状态。实现：sentinel 协议同时捕获 exit_code 和 cwd（见 §5.3.5）。
- **P2**：重连 WARNING 文本必须带 `<host_name>`，避免多主机同时重连时 agent 错配恢复操作（见 §5.4）。
- **M2 多主机章节**：CLAUDE.md.fragment.md 加一节"多主机工作模式"——优先把工作集中在单台主机完成；跨主机文件传输用 Bash + scp（用户预先配 SSH 互信）；并行调用多主机时注意输出交错。

**显式不做**：联邦架构（单进程多主机）、跨主机原语（Copy(from_host, to_host)）。理由：使用场景为 2-3 台主机，per-host 进程的资源成本可接受；跨主机文件传输可用 Bash + scp 兜底。

## 9. 错误处理与重连

**错误返回约定**：所有工具失败返回 `Error: ...` 字符串，从不抛异常。具体错误措辞表见 §6。

**重连策略**：SSH 断连时自动重连一次。重连成功 → 设 `_reconnected=True`；下次工具调用前 `call_tool` 拿到此标志 → 前置 WARNING（带 host 名，三要素齐全：发生了什么 / 状态丢失了什么 / 应对指示）→ 清除标志。重连失败 → 直接返回 `Error: SSH connection to <host> lost and reconnect failed: <reason>`，**不发 WARNING**（agent 需用户介入）。

**bash session 重建后状态**：cwd 回到 `$HOME`，所有 `export` 的环境变量丢失，已 `source` 的文件需重 source。WARNING 必须明确告诉 agent 这些。

**命令超时**：发送 Ctrl-C（`b'\x03'`），抛 TimeoutError → 工具返回 `Error: Command timed out after Ns on <host>`。**bash 进程本身存活**，下次调用仍可用。

## 10. 工作流引导

### 10.1 M1 — Tool description 内嵌带宽提示

每个工具的 description 字符串末尾追加一行"远程感知"指引。措辞要精炼（单主机 ~2KB 总开销，多主机线性叠加）。示例：

| 工具 | 嵌入提示 |
|------|----------|
| Read | `Transfers file content over SSH. To check existence/size only, use FileStat. To search for specific text, use Grep with -A/-B/-C for context. To read multiple related files at once, use MultiRead.` |
| Write | `Bytes are transferred over SSH. Compose the full file content locally before calling, not incrementally.` |
| Edit | `Reads and writes the full file over SSH. For multiple changes to the same file, use MultiEdit in a single call.` |
| MultiEdit | `Reads and writes the file once for any number of edits. Always prefer this over multiple Edit calls on the same file.` |
| MultiRead | `Batch reads multiple files in one network round-trip. Always prefer this over consecutive Read calls when inspecting 2+ files.` |
| FileStat | `Returns metadata (existence, size, mtime, mode) without transferring file content. Use this before Read to avoid accidentally downloading huge files. Accepts a path or a list of paths.` |
| Bash | `Command output is transferred over SSH. Batch related commands with '&&'; pipe large outputs through head/tail. For long-running commands (build/test/install) set run_in_background=true — returns immediately with PID and log path; poll output via Read on the log; clean up with the printed kill command. Shell state persists across foreground calls.` |
| Glob | `Runs server-side and returns only paths. Output is capped — narrow the path argument when searching large trees.` |
| Grep | `Filters server-side and returns only matching lines. Use context/before/after to include surrounding lines in the same call instead of following up with Read. Use output_mode='files_with_matches' or 'count' when you don't need the matched lines themselves.` |
| Feedback | `Record a bug or enhancement idea about the remote-mcp tools themselves (NOT about the user's code or remote system). Use 'bug' when a remote-mcp tool behaves wrong; 'enhancement' for tool improvements you imagine while working. Brief, non-blocking — file and continue your task.` |

### 10.2 M2 — `CLAUDE.md.fragment.md`

仓库内交付一份 markdown 文件，用户复制内容到**本地**项目的 CLAUDE.md（即 Claude Code 启动时读的那个本地文件，**不是**远程主机上的文件；或追加）。结构：

```markdown
## 在远程主机上工作（remote-mcp 工具使用指南）

本项目通过 `mcp__remote-<host>__` 系列工具操控远程服务器。SSH 链路带宽有限、延迟较高。
请遵循以下工作流：

### 单主机模式

**查代码 / 探索仓库**
- 查代码先用 Grep 定位关键字。如果需要看上下文，**直接用 Grep 的 `context=5`（或 before/after）一次拿到匹配 + 周围代码**，不要 Grep 后再 Read 跟进。
- 只想知道某个文件存在吗、多大、什么时候改的？**用 FileStat**，不要 Read 试探（可能传输 50MB 只为知道文件不该读）。
- 探索多个相关文件（如 config / models / utils 一组）**一次 MultiRead 调用**，不要连续 Read。

**编辑文件**
- 同一文件多处修改，**一律用 MultiEdit**，禁止连续 Edit。

**Shell 操作**
- 多步骤操作优先组合命令：`cmd1 && cmd2 && cmd3` 一次 Bash 调用。更复杂的逻辑写脚本（Write 上传 → Bash 执行）。
- 长耗时操作（build / 测试 / install / 大下载）**用 `Bash(command="...", run_in_background=true)`**，agent 不会被阻塞，可以同时做别的事。
  - 工具返回会打印 PID、日志路径、4 条操作命令模板（status / read output / stop / force-stop）——**照抄即可**，不需要记忆。
  - 用 `Read(log_path, offset=<last_line+1>)` 增量拉日志，不要 `Bash("cat log")`。
  - 任务做完或确定不要了，**务必用 `Bash("kill -TERM -- -<pid>")` 收尾**，否则远程会留僵尸进程。
- 前台 Bash 长操作显式设大 timeout（如 600s），但如果可能拖到几分钟以上，直接用 `run_in_background`。
- 大输出命令要谨慎：`find /`、`ls -R /`、`grep -r 通用词 /` 会刷爆带宽，先想清楚再发。

### 多主机模式（2-3 台同时操作时）
- 工具调用结果会有 `[host=X cwd=Y]` 前缀，注意辨认当前操作的是哪台主机。
- 尽量把工作集中在单台主机上完成；跨主机协调需求增加错误率。
- 跨主机文件传输：用 Bash 调 `scp <local>:<path> <remote>:<path>`（需用户预先在主机间配好 SSH 互信）。**禁止** Read-本地中转-Write 的"双跳"模式，这会双倍消耗带宽。
- 看到 `[WARNING] SSH connection to <host> was lost` 时，状态丢失仅限那台主机。其他主机不受影响。

### 持续反馈（Continuous improvement feedback）

remote-mcp 提供 `Feedback` 工具，让你（agent）把使用过程中遇到的问题或灵感沉淀下来。维护者会读这些反馈来迭代工具。

**何时调用 Feedback**：

✅ **DO** —— 这些场景请主动反馈：
- 某个 remote-mcp 工具的行为不符合 Claude Code 原生工具的预期（schema 不一致、错误措辞偏离、输出格式错位等）
- 某个工具有 bug：超时反常、输出损坏、参数无效却没报错、结果与文档不符
- 你在工作中想到："如果有一个 X 工具，或者 Y 工具加一个 Z 参数，会让这件事简单很多"——具体到能描述 API 的程度
- 工作流摩擦：某个常见场景需要 3+ 次工具调用才能完成，明显有合并空间

❌ **DON'T** —— 这些场景不要用 Feedback：
- 用户代码里的 bug（应该改用户代码 / 写到用户项目的 issue 跟踪里）
- 远程系统问题（磁盘满、权限错、服务挂等运维问题）
- 你不确定的猜测（"也许 Read 应该 X？我没试过"）—— 反馈一定基于实际遇到的情况

**调用规范**：
- `category="bug"` 配实际复现描述（哪个工具、什么参数、期望什么、实际什么）
- `category="enhancement"` 配具体到能 mock API 的程度（不要"希望更好用"这种模糊话）
- **不打断当前任务**：file 完一条 feedback 就继续手头的事，不要因为反馈而中断主流程
- summary 一行能说清；details 写背景上下文

**隐私**：Feedback 写入本地文件 `~/.local/share/remote-mcp/feedback.jsonl`，不上传任何地方。`details` 可包含代码片段——你自己决定要不要分享给上游维护者。

**示例**：

```
✅ Feedback(category="bug", summary="Glob '**' missed nested matches",
            details="Tried Glob(pattern='src/**/*.py'). Files in src/sub/foo.py didn't appear; only src/foo.py did. Re-ran with find -wholename manually — files exist. Looks like the ** → -wholename conversion missed nested cases.")

✅ Feedback(category="enhancement", summary="Add MultiWrite tool",
            details="Often need to write 3-4 scaffolding files in sequence. Currently each Write is one RTT. A MultiWrite([{path, content}, ...]) symmetric to MultiRead would compress to 1 RTT.")

❌ Feedback(category="bug", summary="my code crashed")
   ← 这是用户代码问题，不是 remote-mcp 工具问题
```
```

### 10.3 M3 — Plugin 形态（future work，详见 §15）

## 11. 配置

默认路径 `~/.config/remote-mcp/config.yaml`，`--config` 可覆盖。schema：

```yaml
hosts:
  prod:
    hostname: 192.168.1.100
    user: ubuntu
    port: 22
    key_path: ~/.ssh/id_ed25519
    keepalive_interval: 30
    compression: true              # v2 新增
    bash_timeout_default: 120       # v2 新增
    glob_output_limit: 1000         # v2 新增
    read_size_cap: 262144           # 256 KB
    bash_output_cap: 102400         # 100 KB

  internal:
    hostname: 10.0.0.50
    user: admin
    key_path: ~/.ssh/id_ed25519
    jump_host: prod

default_host: prod

# 顶层字段（不属于任何 host），v2 新增
feedback_path: ~/.local/share/remote-mcp/feedback.jsonl
```

所有 v2 新增字段都有默认值，已有 config.yaml 升级无须改动即可工作。

**`feedback_path`** 是顶层字段（非 per-host），因为多个 per-host server 进程应该写入同一份反馈文件——维护者读一份就能看到所有反馈。默认值用 XDG `~/.local/share/remote-mcp/feedback.jsonl`。父目录不存在时 Feedback 工具自动 `mkdir -p`。

## 12. 测试策略

v1 设计文档未规定测试框架，v2 补全。

### 12.1 unit tests（pytest）

mock paramiko，覆盖：
- Sentinel 协议解析：正常输出、输出包含 sentinel-like 文本、bash 自定义 PS1 残留等边界。
- 错误分支与措辞：每条 `Error:` 字符串都有单元测试钉住，防止改坏对齐原生措辞。
- Reconnect flag 生命周期：set → 工具读取 → 清除 → 第二次工具不再带 WARNING。
- Glob pattern 转换：`*.py`、`**/*.py`、`src/*.c`、`src/**/*.c` 等 case。
- MultiEdit 原子性：中间 edit 失败时整体不写。
- 截断 cap：触发后输出末尾有 `[truncated to ...]`。

### 12.2 integration tests

在 CI 跑一个 sshd container（如 `linuxserver/openssh-server`），端到端验证：
- Bash cwd 与 env 跨调用持久。
- Read 远程切片返回行号正确（对照 SFTP 全文切片的 oracle）。
- Write 含 `'`/`"`/`\\`/`$VAR`/换行的内容，Read 回完全一致。
- MultiEdit 多个 edit 顺序应用，与等价的多次 Edit 结果一致。
- 模拟断连（kill sshd 容器再起）：第一次工具返回带 WARNING，第二次不带。
- 超时（`sleep 100`, timeout=2）后 session 仍可用。
- ProxyJump：跑两个 sshd 容器，一台作为跳板。

### 12.3 CI

GitHub Actions，python 3.8 / 3.10 / 3.12 矩阵 + sshd container service。

## 13. 实施顺序与验收

严格自底向上，每阶段必须满足全部验收点才能进入下一阶段。

### 阶段 1：`connection.py`
- `exec("echo hello")` → `stdout="hello\n"`, `exit_code=0`
- `exec("cat /nonexistent")` → `exit_code != 0`, stderr 含 "No such file"
- `get_sftp()` 返回可用 `SFTPClient`
- 启用 `compress=True`，`transport.local_compression` 非 None
- `transport.get_keepalive()` 返回配置值
- ProxyJump 配置下连接成功
- 模拟断连 → 重连成功 → `check_and_clear_reconnect_flag()` 第一次 True、第二次 False

### 阶段 2：`bash_session.py`（最高风险，建议独立测试脚本先行）
- `execute("cd /tmp && pwd")` → 输出 `/tmp`
- 紧接 `execute("pwd")` → 仍输出 `/tmp`（cwd 持久）
- `execute("export FOO=bar")` 后 `execute("echo $FOO")` → `bar`（env 持久）
- `execute(r"echo 'it'\''s a $test'")` → 字符串原样返回（特殊字符）
- `execute("sleep 100", timeout=2)` 约 2s 后 TimeoutError，且**下次** `execute("pwd")` 正常工作
- sentinel 协议同时捕获 cwd：`execute` 返回结构含 `exit_code` 和 `cwd`（P1 落地的核心机制）

### 阶段 3：文件类工具 — Read / Write / Edit / MultiEdit / MultiRead / FileStat
- Read 远程切片：传 offset=10, limit=5 → 只返回 10-14 行，且 sed 命令命中 `-n '10,15p; 16q'`
- Read 文件不存在 → `Error: File not found: <path>`
- Read 大于 cap → 截断 + `[truncated ...]`
- Write 写入含 `'"\\$VAR\n` 的内容 → Read 回完全一致（SFTP 二进制安全）
- Edit old_string 不存在 → 措辞精确为 `Error: old_string not found in <path>`
- Edit old_string 出现 2 次 → 措辞含 `found 2 times`
- MultiEdit 3 个 edit 全成功 → 文件内容等价于顺序 3 次 Edit
- MultiEdit 第 2 个失败 → 文件未被修改（原子性）
- **MultiRead** 3 个文件 → 单次 `conn.exec`（用 mock 验证只发了一条命令），返回分块带各自行号前缀
- **MultiRead** 中某个文件不存在 → 该块标记 `NOT_FOUND`，其他文件正常返回
- **FileStat** 单文件存在 → 输出含 `exists=true type=file size=... mtime=...`
- **FileStat** 单文件不存在 → 输出 `<path>: exists=false`
- **FileStat** 列表参数 → 每文件一行，顺序与输入一致

### 阶段 4：搜索类工具 — Glob / Grep（含扩展参数）
- Glob `"*.py"` 在含 Python 文件的目录 → 正确列表
- Glob `"src/**/*.py"` → 路径含 `src/` 的 py 文件（重点：路径段保留，非仅文件名）
- Glob 大目录 → cap 触发，结果末尾有截断说明
- Grep 在 1 GB 文件搜关键词 → 响应时间显著少于全文传输时间（验证服务端过滤）
- Grep 路径不存在 → `Error: <stderr>`
- **Grep `context=3`** → 输出含匹配行 + 前后 3 行（带 `--` 分隔符或 `path-lineno-line` 格式）
- **Grep `output_mode="files_with_matches"`** → 每行一个文件路径，无行内容
- **Grep `output_mode="count"`** → 每行 `<path>:<count>`
- **Grep `head_limit=10`** → 输出不超过 10 行

### 阶段 5：`server.py` + `__main__.py` + Bash 工具（含 `run_in_background`）+ Feedback
- `python -m remote_mcp --host prod` 启动后保持运行（stdio 不退出）
- `claude mcp add` 注册后，Claude Code 工具列表出现 **10 个** `mcp__remote-prod__*` 工具
- 前台 Bash 调用 → 返回带 `[host=prod cwd=...]` 前缀
- **Bash `run_in_background=true` 启动 `sleep 100`** → **5 秒内返回**，输出含 `PID: <数字>`、`Log: /tmp/rmcp-bg-...`、4 行操作命令模板
- 后台启动后 `Bash("kill -0 <pid> && echo running")` → 输出 `running`
- 后台启动后 `Bash("kill -- -<pid>")` → 5 秒内进程消失（`kill -0` 返回非零）
- 后台任务 spawn 子进程的场景（如 `sleep 200 & sleep 300 & wait`）→ `kill -- -<pid>` 同时干掉父进程和所有子 sleep
- 模拟主动断连 → 下次工具调用结果以 `[WARNING] ... to prod ...` 开头，再下一次不再带
- **Feedback(category="bug", summary="x", details="y")** → 文件 `~/.local/share/remote-mcp/feedback.jsonl` 末尾新增一行 JSON，包含 ts/host/category/summary/details/session_pid 全部字段
- **Feedback(category="invalid", ...)** → 返回 `Error: category must be 'bug' or 'enhancement'`，文件**不写入**
- **Feedback(summary="")** → 返回 `Error: summary cannot be empty`，文件**不写入**
- **并发 Feedback**：两个进程同时调 Feedback 各 100 次 → 文件总行数严格 200，每行有效 JSON（验证 POSIX append 原子性）
- feedback_path 父目录不存在 → 自动 `mkdir -p`，写入成功

### 阶段 6：交付文档与打包
- `pip install -e .` 可装
- README：安装、配置、`claude mcp add` 步骤、常见故障排查
- `CLAUDE.md.fragment.md` 单独文件，包含 §10.2 所述内容（含多主机段落与后台 Bash 用法）
- pyproject.toml：依赖 paramiko、mcp、pyyaml；声明 `entry_points` 或 `console_scripts`

## 14. 已知局限（v1 不解决）

- **不支持交互式 / TTY 命令**：vim、top、Python REPL 等。Bash 工具调用前 description 中可提示用 `tmux send-keys` 的迂回办法，但本版本不内置。
- **二进制 Write/Edit 不支持**：仅 UTF-8 文本。需要二进制时用 Bash 调 `scp` / `base64`。
- **Edit / MultiEdit 非原子（跨进程）**：同一 agent 串行调用没问题；多 agent 并发写同文件可能竞争。本版本不处理。
- **Read 不支持单行超大场景**：即使切片，单行超过 cap 时仍会截断中间。
- **Glob `**` 接近但不保证 100% 等价原生**：路径段层级用 `-wholename` 模拟，对某些 case（如 brace expansion）不展开。验收测试中列具体 case 集，发现差异时补丁修正。
- **Grep 不支持 `multiline`**：原生 Grep 的多行匹配依赖 ripgrep `-U`，远程不能假定有 ripgrep；POSIX `grep -E` 跨行匹配能力有限。需要多行匹配时 agent 应改用 Bash 跑 `awk` / `perl -0`。
- **Background Bash 日志不自动清理**：MCP server 退出时不删 `/tmp/rmcp-bg-*.log`，方便事后排查。靠 `/tmp` 重启清理。
- **Background Bash PID 复用风险**：若后台进程已死、PID 被系统复用、agent 仍发 `kill <pid>`，会误杀新进程。低概率但存在；agent 应先 `kill -0 <pid>` 探活。
- **Feedback 文件不自动轮转**：v1 简单 append，靠维护者定期归档。极端情况下（数月不读）文件可能数 MB——仍能 `tail` 查看最新条目，不影响功能。
- **Feedback 不主动转交上游**：纯本地文件，维护者手动收集。无 telemetry pipeline。
- **2-3 台以上主机性能未优化**：进程数、SSH 连接数随主机数线性。10+ 主机场景请等 future work。

## 15. 未来工作

### 15.1 M3 — Claude Code Plugin 形态

**目标**：把 v1 的 MCP server 包装进 Claude Code plugin，一键 `claude plugin install` 拿到 server + 工作流 skill + 便捷 slash command，免去手工 `claude mcp add` 和复制 `CLAUDE.md.fragment.md`。

**前置条件**：
- Claude Code plugin 规范进入稳定版本（截至 v2 编写时仍在演进）。
- 确认 plugin manifest 是否支持声明并启动 stdio MCP 子进程（或需要 plugin 自带 server 注册逻辑）。

**plugin 内容拆解**：

1. **bundled MCP server**：完全复用 v1 代码，零改动。
2. **always-on skill**（暂定名 `remote-workflow-aware`）：
   - 触发条件：工具调用涉及 `mcp__remote-*__` 前缀，或项目已注册任一 remote-mcp server。
   - 内容：把 `CLAUDE.md.fragment.md` 重新组织为带正例/反例的 skill 文档。例如：
     - 正例：`grep "import torch" → 找到 file:line → Read offset=line-5 limit=15`
     - 反例：`Read whole_repo/main.py → 在结果里 ctrl-f`
   - 结构化字段：场景、推荐工具序列、要避免的工具序列、网络成本对比。
3. **slash commands**：
   - `/remote-add <name> <user@host[:port]> [--jump <name>] [--key <path>]`  
     交互式向 `~/.config/remote-mcp/config.yaml` 追加主机配置，并自动调用 `claude mcp add`。
   - `/remote-cd <name> <path>`  
     在指定主机的 bash session 里执行 `cd` 并展示新 cwd，避免 agent 用相对路径出错。
   - `/remote-status`  
     列出所有已注册的 remote-mcp server、当前连接状态、bash session 的 cwd、reconnect 计数。
   - `/remote-script <name>`  
     把当前 Claude Code 编辑区或剪贴板的内容作为脚本上传到指定主机执行，省去 agent "多次 Write + 多次 Bash" 的来回。
4. **PreToolUse hook**（可选）：
   - 检测 agent 是否在远程项目上下文里调用了**本地原生** Read/Write/Edit。若是，给出温和提示"看起来您在远程项目上工作，是否要用 `mcp__remote-<host>__` 工具？"
   - hook 触发需要可靠的"项目是否为远程项目"判断逻辑（如检查项目 CLAUDE.md 是否包含 remote-mcp 指引语）。

**分发与升级**：
- 通过 Claude Code plugin marketplace 发布。
- 版本与底层 MCP server 同步。
- 兼容性：v1 用户已有的 `~/.config/remote-mcp/config.yaml` 在 plugin 安装后无须重新配置——plugin 优先读取此文件。

**工作量估算**：
- plugin manifest + skill 内容：1-2 天
- slash command（`/remote-add`、`/remote-status` 简单；`/remote-cd` 中等；`/remote-script` 最复杂，需要捕获编辑区内容）：合计 3-5 天
- hook（可选）：1-2 天
- 测试与 dogfood：2-3 天
- **总计 < v1 server 本身**

**启动条件**：
- v1 跑通且至少 2 周用户实际使用反馈
- Claude Code plugin 规范进入稳定版本
- 没有阻塞性 v1 bug

### 15.2 其他可能的未来增量

- **Read 流式输出**：对单个非常大的文件，按页传输并允许 agent 拉取下一页。
- **远程命令的进度反馈**：长操作（build/test）期间分批传输 stdout，而非等命令结束。需要修改 sentinel 协议或并行用第二个 channel 反向心跳。
- **配置中支持密钥短语 / SSH agent**：当前 paramiko `connect()` 调用已能接受 `pkey` 或 `passphrase`，配置文件 schema 可扩展支持 `key_passphrase_env`。

- **MCP 流式输出支持（streaming response）**：当前 MCP 协议是同步请求-响应——agent 调 Bash 等到完整结果才能处理。"流式"指 agent 在命令运行**期间**就能看到 stdout 一行行涌出，并据此实时反应（提前 kill、注入 stdin、根据中间日志决定下一步）。Claude Code 内置的 `Monitor` 工具是本地实现的类似思路，但 MCP spec 本身还没把这套协议化。
  - **为什么记录**：v0.2.0 改成非持久 bash 后，我们的 Bash 工具底层用 `recv_ready` + `recv` 流式读 stdout 是自然实现，**一旦 MCP 协议层支持流式响应，几乎不需要重写**就能支持流式 Bash。持久模式因为 sentinel 协议本质上要等命令结束才能切分，反而难升级。这是非持久路线对未来的隐性收益。
  - **触发条件**：MCP 规范官方 publish 流式响应协议，且 Claude Code 客户端实现。
  - **可能形态**：`Bash(command="long_build", stream=true)` → 工具返回的 TextContent 分块到达；或新增 `BashStream` 工具与 foreground/background 并列。

- **可选 `mode: persistent` 配置项**（v0.2.0 切非持久之后的反向出口）：如果有用户因为慢共享存储或高延迟链路对每次 channel-open + bash startup 的 ~300-500ms 开销不可接受，提供一个 opt-in 的持久模式配置（复用 v0.1.x 的 sentinel/PTY/setsid 那套代码作为可选模块）。**前提是真有人抱怨**——不提前实现。

---

## 附录：术语

- **sentinel**：在 bash stdout 中插入的唯一标识字符串（含 uuid 与 exit code），用来检测命令边界。
- **持久 bash session**：跨工具调用复用的远程 bash 进程，保证 cwd 与环境变量在调用间持久。
- **fidelity（保真度）**：工具的参数名、输出格式、错误措辞与 Claude Code 原生工具的一致程度。
- **M1/M2/M3**：三档工作流引导强度——M1 嵌在 tool description，M2 用户 opt-in 的 CLAUDE.md 片段，M3 plugin 形态自动加载。
