# remote-mcp 设计规范（v2）

**日期**：2026-05-26  
**状态**：待实施  
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

## 4. 工具集（7 个）

Read、Write、Edit、**MultiEdit**、Bash、Glob、Grep。所有工具：
- 名称、参数名、输出格式对齐 Claude Code 原生工具。
- 失败返回以 `Error:` 开头的字符串，不抛异常。
- 工具描述（description）末尾嵌入 1 行带宽感知提示（见 §10 M1）。

MultiEdit 加入 v1 的理由：它把"同文件多次编辑"压成 1 次完整文件传输，是带宽优化里收益最大的单点；又完全保持原生保真（Claude Code 原生有此工具）。

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
         old_string: str, new_string: str) -> str:
    try:
        with sftp.file(file_path, 'r') as f:
            content = f.read().decode('utf-8')
    except FileNotFoundError:
        return f"Error: File not found: {file_path}"

    count = content.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {file_path}"
    if count > 1:
        return (f"Error: old_string found {count} times in {file_path}. "
                f"Provide more context to match uniquely.")

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
    except FileNotFoundError:
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

#### 5.3.5 Bash（v2 改动：结果加 host+cwd 前缀）

```python
# Fragment
def bash(session: BashSession, conn_name: str,
         command: str, timeout: float = 120.0) -> str:
    try:
        result = session.execute(command, timeout=timeout)
    except TimeoutError:
        return f"Error: Command timed out after {timeout}s on {conn_name}"

    cwd = session.current_cwd()   # 缓存值或 sentinel 协议探测
    output = result.output

    # v2 P1：结果加主机+cwd 元信息行（agent 在多主机场景下能看清当前状态）
    prefix = f"[host={conn_name} cwd={cwd}]\n"

    if result.exit_code != 0:
        output += f"\n[Exit code: {result.exit_code}]"

    # 输出 cap
    if len(output) > session.config.bash_output_cap:
        output = output[:session.config.bash_output_cap] + \
                 f"\n... [truncated to {session.config.bash_output_cap} bytes]"

    return prefix + output
```

`session.current_cwd()` 返回最近一次 `execute()` 捕获并缓存的 cwd 值。捕获机制：sentinel 行格式扩展为 `RMCP_SENTINEL_{uuid}_EXIT_$?_CWD_$(pwd)`（与 §5.2 一致），解析时按 `_EXIT_` 和 `_CWD_` 切分提取两字段。**这是 P1 的具体落地**。

#### 5.3.6 Glob（v2 改动：`**` 修正 + cap）

```python
# Fragment
def glob_tool(conn: SSHConnection, pattern: str, path: str = ".") -> str:
    find_expr = _glob_to_find(pattern)     # "**/*.py" → "-path '*.py'"
                                            # "src/**/*.py" → "-path 'src/*/*.py'" or "-wholename"
    cmd = (f"find {shlex.quote(path)} "
           f"\\( {find_expr} \\) -type f | sort | head -{conn.config.glob_output_limit}")
    result = conn.exec(cmd)
    if result.exit_code not in (0, 1):
        return f"Error: {result.stderr.strip()}"
    if not result.stdout.strip():
        return "No files found matching pattern"

    lines = result.stdout.splitlines()
    if len(lines) >= conn.config.glob_output_limit:
        return result.stdout + f"\n... [truncated to {conn.config.glob_output_limit} entries]"
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

#### 5.3.7 Grep

```python
# Fragment
def grep_tool(conn: SSHConnection, pattern: str, path: str,
              include: str = "", case_insensitive: bool = False) -> str:
    flags = "-rn"
    if case_insensitive:
        flags += "i"
    include_opt = f"--include={shlex.quote(include)}" if include else ""
    cmd = (f"grep {flags} {include_opt} -E {shlex.quote(pattern)} "
           f"{shlex.quote(path)} | head -200")
    result = conn.exec(cmd)
    # grep 退出码：0=匹配，1=无匹配，2=错误
    if result.exit_code == 2:
        return f"Error: {result.stderr.strip()}"
    if result.exit_code == 1:
        return "No matches found"
    return result.stdout
```

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
        Tool(name="Bash", description=BASH_DESC, inputSchema=BASH_SCHEMA),
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
```

每个工具的 description 文本（M1 嵌入）见 §10。

## 6. 工具接口规范

参数名、字段顺序、错误措辞需要在实施阶段对照 Claude Code 实际原生工具确认（建议：跑一遍 `mcp__local__list_tools` 抓取原生 schema 比对）。下表列规范要点，schema 完整 JSON 见实施时生成的 `schemas.py`。

| 工具 | 必参 | 选参 | 输出格式要点 |
|------|------|------|--------------|
| Read | `file_path` | `offset=1`, `limit=2000` | `     <lineno>\t<line>` 5 空格 + 数字 + tab |
| Write | `file_path`, `content` | — | `Successfully wrote N characters to <path>` |
| Edit | `file_path`, `old_string`, `new_string` | `replace_all=false` | `Successfully edited <path>` |
| MultiEdit | `file_path`, `edits` (list) | — | `Successfully applied N edits to <path>` |
| Bash | `command` | `description=""`, `timeout=120` | `[host=X cwd=Y]\n<output>[\n[Exit code: N]]` |
| Glob | `pattern` | `path="."` | 每行一个绝对/相对路径 |
| Grep | `pattern`, `path` | `include=""`, `case_insensitive=false` | `path:lineno:matched_line` |

错误文本必须**逐字**对齐原生（"File not found:"、"old_string not found"、"old_string found N times in ..."），否则 agent 的恢复策略可能失效。

## 7. 带宽与延迟优化（v2 核心增量）

| 优化 | 原 v1 行为 | v2 新行为 | 收益 |
|------|------------|-----------|------|
| Read | SFTP 全文 → Python 切片 | `sed -n` 远程切片 | 100MB 文件读 20 行：100MB → 几 KB |
| Write 父目录 | `conn.exec("mkdir -p")` | SFTP 原生 mkdir | 省 1 个 channel RTT |
| SSH 压缩 | 未启用 | `compress=True` 默认 | 文本流量 3-10× 压缩 |
| MultiEdit | 不存在 | 1 read + N in-memory + 1 write | N 次 Edit 的 2× 减为 2× |
| Glob 输出 | 无上限 | `head -1000` | 防止大目录树灌爆 |
| Read 结果 | 无上限 | 256 KB cap | 防止 agent 显式传超大 limit |
| Bash 输出 | 无上限 | 100 KB cap | 防止 `find /` 等失误刷爆带宽 |
| Bash 超时 | 60s 默认 | 120s 默认 | 高延迟链路上 build/test 不被误杀 |

cap 触发时输出末尾追加截断说明（`... [truncated to N bytes]`），让 agent 知道结果不完整。

## 8. 多主机支持

**模型**：一台远程主机一个 Python 进程。用户对每台分别 `claude mcp add`：

```bash
claude mcp add --global remote-prod -- python -m remote_mcp --host prod
claude mcp add --global remote-gpu  -- python -m remote_mcp --host gpu
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
| Read | `This tool transfers file content over SSH. To search for specific text, prefer Grep — it filters server-side.` |
| Write | `Bytes are transferred over SSH. Compose the full file content locally before calling, not incrementally.` |
| Edit | `Reads and writes the full file over SSH. For multiple changes to the same file, use MultiEdit in a single call.` |
| MultiEdit | `Reads and writes the file once for any number of edits. Always prefer this over multiple Edit calls on the same file.` |
| Bash | `Command output is transferred over SSH. Batch related commands with '&&'; pipe large outputs through head/tail. Shell state persists across calls.` |
| Glob | `Runs server-side and returns only paths. Output is capped — narrow the path argument when searching large trees.` |
| Grep | `Filters server-side and returns only matching lines (capped at 200). Always prefer this over Read for searches.` |

### 10.2 M2 — `CLAUDE.md.fragment.md`

仓库内交付一份 markdown 文件，用户复制内容到自己远程项目的 CLAUDE.md（或追加）。结构：

```markdown
## 在远程主机上工作（remote-mcp 工具使用指南）

本项目通过 `mcp__remote-<host>__` 系列工具操控远程服务器。SSH 链路带宽有限、延迟较高。
请遵循以下工作流：

### 单主机模式
- 查代码先用 Grep 定位关键字，再用 Read 配合 offset/limit 精读相关段落，不要全文 Read。
- 同一文件多处修改，**一律用 MultiEdit**，禁止连续 Edit。
- 多步骤操作优先组合命令：`cmd1 && cmd2 && cmd3` 一次 Bash 调用；
  更复杂的逻辑写脚本（Write 上传 → Bash 执行），不要拆成几十次 Bash。
- 长耗时操作（build、测试、下载）显式设大 timeout（如 600s），不要默认 120s 跑一半被杀。
- 大输出命令要谨慎：`find /`、`ls -R /`、`grep -r 通用词 /` 会刷爆带宽，先想清楚再发。

### 多主机模式（2-3 台同时操作时）
- 工具调用结果会有 `[host=X cwd=Y]` 前缀，注意辨认当前操作的是哪台主机。
- 尽量把工作集中在单台主机上完成；跨主机协调需求增加错误率。
- 跨主机文件传输：用 Bash 调 `scp <local>:<path> <remote>:<path>`（需用户预先在主机间配好 SSH 互信）。**禁止** Read-本地中转-Write 的"双跳"模式，这会双倍消耗带宽。
- 看到 `[WARNING] SSH connection to <host> was lost` 时，状态丢失仅限那台主机。其他主机不受影响。
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
```

所有 v2 新增字段都有默认值，已有 config.yaml 升级无须改动即可工作。

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

### 阶段 3：Read / Write / Edit / MultiEdit
- Read 远程切片：传 offset=10, limit=5 → 只返回 10-14 行，且 sed 命令命中 `-n '10,15p; 16q'`
- Read 文件不存在 → `Error: File not found: <path>`
- Read 大于 cap → 截断 + `[truncated ...]`
- Write 写入含 `'"\\$VAR\n` 的内容 → Read 回完全一致（SFTP 二进制安全）
- Edit old_string 不存在 → 措辞精确为 `Error: old_string not found in <path>`
- Edit old_string 出现 2 次 → 措辞含 `found 2 times`
- MultiEdit 3 个 edit 全成功 → 文件内容等价于顺序 3 次 Edit
- MultiEdit 第 2 个失败 → 文件未被修改（原子性）

### 阶段 4：Glob / Grep
- Glob `"*.py"` 在含 Python 文件的目录 → 正确列表
- Glob `"src/**/*.py"` → 路径含 `src/` 的 py 文件（重点：路径段保留，非仅文件名）
- Glob 大目录 → cap 触发，结果末尾有截断说明
- Grep 在 1 GB 文件搜关键词 → 响应时间显著少于全文传输时间（验证服务端过滤）
- Grep 路径不存在 → `Error: <stderr>`

### 阶段 5：`server.py` + `__main__.py`
- `python -m remote_mcp --host prod` 启动后保持运行（stdio 不退出）
- `claude mcp add` 注册后，Claude Code 工具列表出现 7 个 `mcp__remote-prod__*` 工具
- 实际在 Claude Code 中调用 Bash → 返回带 `[host=prod cwd=...]` 前缀
- 模拟主动断连 → 下次工具调用结果以 `[WARNING] ... to prod ...` 开头，再下一次不再带

### 阶段 6：交付文档与打包
- `pip install -e .` 可装
- README：安装、配置、`claude mcp add` 步骤、常见故障排查
- `CLAUDE.md.fragment.md` 单独文件，包含 §10.2 所述内容
- pyproject.toml：依赖 paramiko、mcp、pyyaml；声明 `entry_points` 或 `console_scripts`

## 14. 已知局限（v1 不解决）

- **不支持交互式 / TTY 命令**：vim、top、Python REPL 等。Bash 工具调用前 description 中可提示用 `tmux send-keys` 的迂回办法，但本版本不内置。
- **二进制 Write/Edit 不支持**：仅 UTF-8 文本。需要二进制时用 Bash 调 `scp` / `base64`。
- **Edit / MultiEdit 非原子（跨进程）**：同一 agent 串行调用没问题；多 agent 并发写同文件可能竞争。本版本不处理。
- **Read 不支持单行超大场景**：即使切片，单行超过 cap 时仍会截断中间。
- **Glob `**` 接近但不保证 100% 等价原生**：路径段层级用 `-wholename` 模拟，对某些 case（如 brace expansion）不展开。验收测试中列具体 case 集，发现差异时补丁修正。
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

---

## 附录：术语

- **sentinel**：在 bash stdout 中插入的唯一标识字符串（含 uuid 与 exit code），用来检测命令边界。
- **持久 bash session**：跨工具调用复用的远程 bash 进程，保证 cwd 与环境变量在调用间持久。
- **fidelity（保真度）**：工具的参数名、输出格式、错误措辞与 Claude Code 原生工具的一致程度。
- **M1/M2/M3**：三档工作流引导强度——M1 嵌在 tool description，M2 用户 opt-in 的 CLAUDE.md 片段，M3 plugin 形态自动加载。
