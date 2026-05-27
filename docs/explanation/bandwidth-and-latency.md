# Bandwidth and Latency

> 中文版本：[bandwidth-and-latency.zh.md](./bandwidth-and-latency.zh.md)

The network constraint is not a footnote — it is the design forcing function behind almost every non-obvious choice in remote-mcp. This document explains the assumption, traces how it shaped each major optimization, and gives you a concrete sense of how badly the naive approach performs so you can appreciate why the optimized approach matters.

## The baseline assumption

Remote-mcp is designed for the hardest realistic case: a cellular modem or cross-continental VPN link with roughly 100 KB/s to 1 MB/s of sustained throughput and an RTT (round-trip time) of 200–1000 milliseconds.

These numbers matter in two independent ways:

**Throughput** determines how much data you can move per unit time. A 500 KB source file takes 0.5–5 seconds to transfer over such a link, not milliseconds.

**Latency (RTT)** determines how long each back-and-forth exchange takes, regardless of data size. Even a zero-byte request has a minimum cost of one RTT. At 500 ms RTT, three sequential tool calls (each requiring its own round-trip) cost at least 1.5 seconds of pure waiting before any bytes move. At 200 ms RTT, five sequential Read calls to explore a module cost at least 1 second in overhead alone.

A well-designed remote-mcp session minimizes both: sending as few bytes as possible and batching as many operations as possible into single round-trips.

## Optimization 1: Remote sed-slicing in Read

**The problem without it:** The naive approach to Read is "fetch the whole file via SFTP, slice in Python". For small files this is acceptable. For a 50 MB log file where the agent wants lines 8000–8020, the naive approach transfers 50 MB. At 100 KB/s, that is over 8 minutes. Even at 1 MB/s it is 50 seconds.

**The optimization:** Read uses `sed -n '{offset},{end}p; {end+1}q'` via an exec channel. The `sed` command runs on the remote host, extracts exactly the requested lines, and sends back only those — typically a few kilobytes regardless of the total file size.

**The cost-without vs. cost-with:** A 50 MB file, reading 20 lines: 50 MB vs. ~2 KB. At 100 KB/s, 8 minutes vs. less than a second.

This optimization means the `offset` and `limit` parameters in Read are not just for convenience — on a high-latency link they are essential. An agent that reads the first 2000 lines of a 100,000-line file is sending the right signal; an agent that reads the entire file to search it is doing the wrong thing (use Grep instead).

## Optimization 2: MultiRead — N round-trips collapsed to one

**The problem without it:** Exploring a module often means reading several related files in sequence: the configuration, the model definitions, the utility helpers. Each Read is a separate tool call, which means a separate round-trip. At 500 ms RTT, reading five files takes 2.5 seconds of pure latency overhead before any content arrives.

**The optimization:** MultiRead accepts a list of `{file_path, offset, limit}` entries, constructs a single shell script that applies `sed` slicing to each file and separates results with delimiter markers, sends the whole script in one exec call, and parses the combined output client-side. Five files, one round-trip.

**The cost-without vs. cost-with:** At 500 ms RTT, reading 5 files: 2500 ms of latency overhead vs. 500 ms. The content transfer time is the same either way.

MultiRead is the right default for any exploration pattern. The wrong pattern is: Read file1, think about what to read next, Read file2. The right pattern is: decide what files you need, read them all at once.

## Optimization 3: FileStat — metadata without content

**The problem without it:** The natural way to check "does this file exist and how big is it?" without FileStat is to either Bash a `stat` command or try a Read and check for an error. Bash costs one round-trip. A trial Read costs one round-trip *plus* the full file transfer if the file exists. For a 200 MB file, "does this file exist?" costs 200 MB of data transfer if you try to read it.

**The optimization:** FileStat uses SFTP's `stat()` operation, which returns structured metadata (size, mtime, mode, type) in a single SFTP message. The response is measured in bytes, not kilobytes or megabytes. It accepts a list of paths, so you can check the existence and size of ten files in one call.

**The cost-without vs. cost-with:** Checking metadata of a 200 MB file: 200 MB + 1 RTT vs. ~100 bytes + 1 RTT. FileStat is also strictly faster than Bash because it reuses the existing SFTP channel rather than opening a new exec channel.

## Optimization 4: MultiEdit — one file transfer for N edits

**The problem without it:** Refactoring a file with three independent changes requires three Edit calls. Each Edit call reads the full file, makes one change, and writes the full file back. Three edits = six full file transfers. For a 50 KB source file at 100 KB/s, that is three seconds of transfer time, not counting RTT.

**The optimization:** MultiEdit accepts a list of edits as a single call. It reads the file once, applies all edits in sequence (failing atomically if any edit fails), and writes once. Three edits = two file transfers.

**The cost-without vs. cost-with:** A 50 KB file, three edits: 300 KB total transfer vs. 100 KB total transfer. At 100 KB/s, 3 seconds vs. 1 second. The ratio improves as the number of edits grows.

MultiEdit also provides atomicity: if edit #2 fails (old_string not found, or found multiple times), the file is not written at all. This is better behavior than three sequential Edits, where the first two succeed and the third fails, leaving the file in a partially-modified state.

## Optimization 5: Grep context flags — eliminate follow-up Reads

**The problem without it:** A common workflow is: Grep a pattern to find the relevant location, then Read the surrounding code for context. That is two tool calls, two round-trips, and a partial file transfer for the Read.

**The optimization:** Grep supports `-A` (after), `-B` (before), and `-C` (context) parameters that include surrounding lines in the grep output itself. "Find all uses of `run_migration` and show 5 lines of context" is a single Grep call with `context=5`. The grep runs on the remote host, includes the context lines in its output, and returns everything in one response.

**The cost-without vs. cost-with:** Find + Read-for-context: 2 RTTs + transfer of matched region. Grep with context: 1 RTT + transfer of matched region. At 500 ms RTT, this is consistently a 500 ms saving per search-then-inspect cycle.

## Optimization 6: Bash background mode — unblocking without reducing bytes

**The problem without it:** A `pip install -r requirements.txt` on a slow network can take five minutes. An `npm run build` can take three. During that time, the Bash tool is blocked waiting for the command to complete. The agent is blocked. The user is blocked. Nothing else can happen.

**The optimization:** `Bash(command="...", run_in_background=true)` wraps the command in `setsid nohup bash -c ... > /tmp/rmcp-bg-<uuid>.log 2>&1 </dev/null &`, launches it, captures the PID, and returns immediately — typically within a few seconds. The agent receives the PID, the log path, and template commands for checking status, reading output, stopping the process, and force-stopping it.

**The cost-without vs. cost-with:** This optimization does not reduce bytes transferred. It eliminates the wall-clock blocking time. A five-minute build is still five minutes of remote CPU work — but the agent can do other things while it runs, and the user is not stuck watching a spinner.

The log is read incrementally with Read using `offset=<last_line+1>`, which means you can poll for new output without retransferring the entire log. Combined with the sed-slicing optimization, polling a growing build log is bandwidth-efficient.

## Optimization 7: SSH compression

**The optimization:** The SSH transport runs with `compress=True`. All SSH traffic is compressed using zlib before transmission.

Source code, configuration files, and log output are highly compressible — typically 3–10× compression ratios for ASCII text. This means a 100 KB Python file might transmit as 15–30 KB of compressed SSH payload. The compression happens transparently at the paramiko layer; no tool implementation needs to be aware of it.

**The cost:** A small amount of CPU time on both ends. On modern hardware (including the agent-side laptop and any reasonable server), this cost is unmeasurable in practice compared to the network savings.

## Optimization 8: SFTP mkdir for Write

**The problem without it:** V1's Write tool ran `conn.exec("mkdir -p {parent}")` before the SFTP write. This opened a new exec channel, paid the channel setup RTT, ran the command, got the result, and closed the channel — then opened the SFTP session for the write itself.

**The optimization:** V2 implements `_sftp_mkdirs()` using SFTP's own `mkdir` operation on the already-open SFTP channel. No new exec channel is needed. One round-trip (one SFTP message per directory level to create) instead of exec channel overhead plus SFTP overhead.

**The cost-without vs. cost-with:** One fewer channel open/close cycle per Write to a new directory. At 500 ms RTT, this is 500 ms saved per Write to a new path.

## Output caps: preventing accidental floods

Three output caps apply across the tools:

- Read results: capped at 256 KB
- Bash output: capped at 100 KB  
- Glob results: capped at 1000 entries

These caps are not bandwidth optimizations in the normal sense — they are safety guards against commands that could generate megabytes or gigabytes of output. `find /` would return millions of lines. `grep "e" /` (searching for the letter "e" everywhere) would return gigabytes. An agent that accidentally issues one of these commands should get a truncated result with a clear notice (`... [truncated to N bytes]`), not a 30-minute wait followed by an out-of-memory error.

The caps are per-call, so a well-targeted command that produces reasonable output is never affected by them.

## What still costs what it costs

Some things cannot be optimized away:

- Edit always reads and writes the full file (needed to verify uniqueness of `old_string`). Source files under 100 KB are fine; multi-megabyte files are a known pain point.
- The minimum cost of any tool call is one RTT. On a 1000 ms RTT link, even a trivial FileStat has a 1-second floor.
- Background bash tasks still run for their full duration on the remote host; `run_in_background` only unblocks the agent, it doesn't make the computation faster.

See the [tool reference](../reference/tools/) for exact behavior of each optimization parameter.
