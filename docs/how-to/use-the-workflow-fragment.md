# Use the CLAUDE.md workflow fragment

> 中文版本：[use-the-workflow-fragment.zh.md](./use-the-workflow-fragment.zh.md)

## When to use this guide

You've installed and registered `remote-mcp`, and you want the agent to use the bandwidth-aware patterns (Grep with context lines, MultiRead, FileStat, background Bash) automatically — without you having to prompt for them every time.

## What you need first

- A working `remote-mcp` registration (see the [tutorial](../tutorial/first-remote-session.md) if not).
- A clear idea of which scope you want the rules applied in — see the three options below.

## Where the file goes — LOCAL, not remote

**The fragment goes into a `CLAUDE.md` on your LOCAL machine — the same machine where Claude Code runs.** It does *not* go onto the remote SSH host. Claude Code reads `CLAUDE.md` from your local filesystem at session startup; the remote host never sees this file.

> A quick mnemonic: `remote-mcp` is the tool; *what it operates on* is remote, but *Claude Code itself* (and everything it reads — including `CLAUDE.md`) lives on your local machine.

## Three patterns — pick one

### Pattern 1 — Per-project (recommended default)

Best when you have a specific local project that you're working on remotely.

```bash
cd /path/to/your-local-project   # the directory you open in Claude Code
cat /path/to/remote-mcp/CLAUDE.md.fragment.md >> CLAUDE.md
```

The `>>` appends — if `CLAUDE.md` doesn't exist yet, it gets created. The rules now apply only when you open Claude Code from inside `/path/to/your-local-project`.

Pros: surgical — rules don't apply where they shouldn't (e.g. local-only projects). Easy to git-track if you want.

### Pattern 2 — User-level (heavy users)

Best when *most* of your Claude Code projects use `remote-mcp`.

```bash
cat /path/to/remote-mcp/CLAUDE.md.fragment.md >> ~/.claude/CLAUDE.md
```

The rules apply to every Claude Code project you open. Trade-off: in local-only projects, the rules don't hurt — they're context the agent ignores — but they do consume tokens on every conversation.

### Pattern 3 — Team-shared via git

Best when multiple people on your team work on the same remote-using project.

Commit the contents into your project's `CLAUDE.md`. Everyone who clones the repo gets the rules automatically.

```bash
cd /path/to/team-project
cat /path/to/remote-mcp/CLAUDE.md.fragment.md >> CLAUDE.md
git add CLAUDE.md
git commit -m "docs: add remote-mcp workflow rules for the agent"
```

Pros: convention is enforced by version control; if a teammate accidentally removes the rules, code review will catch it.

## Verification

After copying, open Claude Code in that project. Ask the agent: *"What do you know about how to use the remote-mcp tools efficiently?"*

A well-loaded fragment will produce a summary that mentions specifics like `Grep -C 5`, `MultiRead`, `FileStat`, `run_in_background=true`. If the agent answers in general terms (or doesn't mention these), the fragment isn't being loaded — check that `CLAUDE.md` is at the expected location and contains the content (`grep -c MultiRead CLAUDE.md` should return ≥ 1).

## Current limitations (and what's coming)

This is a **manual copy-paste workflow**. That has consequences:

- **You have to copy** — there's no auto-install. Forgetting means the agent reverts to less efficient default patterns.
- **No auto-sync** — if `CLAUDE.md.fragment.md` is updated in the `remote-mcp` repo, your already-copied snippet doesn't update automatically. You'd need to manually re-copy (or diff and merge).
- **No safety against deletion** — if you or a teammate accidentally remove the snippet from `CLAUDE.md`, nothing reminds you.

These are exactly what the **M3 Claude Code plugin form** (see spec §15.1) is designed to fix — once a plugin is published, `claude plugin install remote-mcp` would install an always-on skill that delivers the same rules without any file copying. That work is on the roadmap but not done yet.

## When this doesn't work

- **The agent still uses Read instead of FileStat / consecutive Read instead of MultiRead** — verify the fragment is in the right `CLAUDE.md` (Pattern 1 or 3 needs you to be in the project root). Re-check by running `grep "MultiRead" $(claude config get claude_md_path 2>/dev/null || echo CLAUDE.md)` from the project.
- **Multiple `CLAUDE.md` files conflict** — Claude Code merges project-level and user-level `CLAUDE.md`. If you have stale rules in `~/.claude/CLAUDE.md` and updated rules in the project, the project's take precedence for that project. Delete the stale one if it's misleading.
- **You're using a fork of `remote-mcp`** — make sure you're copying from the right repo's fragment (the project rules might differ).
