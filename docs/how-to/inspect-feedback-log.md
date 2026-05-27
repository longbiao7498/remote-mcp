# Inspect the feedback log

> 中文版本：[inspect-feedback-log.zh.md](./inspect-feedback-log.zh.md)

## When to use this guide

You want to read what the agent has filed via the `Feedback` tool — bug reports and enhancement ideas it recorded while working on your remote host. This is the primary input for planning the next iteration of remote-mcp.

## What you need first

- `jq` installed locally (`apt install jq` / `brew install jq`)
- At least one remote-mcp session completed (otherwise the file may not exist yet)

## Steps

1. **Find the log file**

   Default path: `~/.local/share/remote-mcp/feedback.jsonl`

   If you set `feedback_path:` in config, use that path instead.

2. **View all entries**

   ```bash
   cat ~/.local/share/remote-mcp/feedback.jsonl | jq .
   ```

   Each line is one JSON object:

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

3. **Filter by category**

   Bugs only:

   ```bash
   jq 'select(.category == "bug")' ~/.local/share/remote-mcp/feedback.jsonl
   ```

   Enhancements only:

   ```bash
   jq 'select(.category == "enhancement")' ~/.local/share/remote-mcp/feedback.jsonl
   ```

4. **Filter by host**

   ```bash
   jq 'select(.host == "prod")' ~/.local/share/remote-mcp/feedback.jsonl
   ```

5. **Show summaries only (quick triage)**

   ```bash
   jq -r '[.ts, .host, .category, .summary] | @tsv' \
       ~/.local/share/remote-mcp/feedback.jsonl
   ```

   Example output:

   ```
   2026-05-26T14:03:22+00:00	prod	bug	        Bash timeout leaves session in broken state
   2026-05-26T14:11:55+00:00	gpu	 enhancement	Add a Symlink tool for creating soft links
   ```

6. **Act on the entries**

   - `bug` entries: reproduce, then fix or open a GitHub issue.
   - `enhancement` entries: evaluate against the design pillars in `CONTRIBUTING.md` before implementing. If the enhancement requires a new tool, follow [Add a new tool](./add-a-new-tool.md).
   - After triaging, you can archive processed entries:
     ```bash
     mv ~/.local/share/remote-mcp/feedback.jsonl \
        ~/.local/share/remote-mcp/feedback-$(date +%Y%m%d).jsonl
     ```

## Verification

If the file is missing entirely:

```bash
ls ~/.local/share/remote-mcp/
```

The file is created on the first `Feedback` tool call. If no agent has filed feedback yet, the directory may not exist. That is normal — it is created automatically when the first entry is appended.

## When this doesn't work

- **`jq: command not found`** — install jq: `apt install jq` (Debian/Ubuntu) or `brew install jq` (macOS).
- **`No such file or directory`** — the agent has not yet filed any feedback this session. The file is written only when the `Feedback` tool is called.
- **Entries look garbled** — the file is JSONL (one JSON object per line). Do not open it in a text editor that rewraps lines; use `jq` or `cat`.
