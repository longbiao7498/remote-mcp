# Tutorials

> 中文版本：[`README.zh.md`](./README.zh.md)

Tutorials are **lessons**. They teach a beginner by getting them through a small, complete experience successfully. You follow the steps; you see the same results we describe.

A tutorial is *not* a reference (it doesn't enumerate parameters) and not a how-to (it doesn't assume you know the goal yet — it shows you one).

## Available tutorials

| Tutorial | Duration | Prereqs |
|----------|----------|---------|
| [Your first remote session](./first-remote-session.md) | ~15 min | A Linux host you can `ssh` into; Python 3.8+ locally; Claude Code installed |

If you've never used remote-mcp before, **start here**.

## What goes in a tutorial (for contributors)

- Always end at a successful, visible outcome ("you should now see ...").
- Show expected output after every command, so the reader can confirm at each step.
- Don't explain *why* — that's for `explanation/`. Don't list every option — that's for `reference/`.
- Tutorials should be safe to follow: no risk of damaging the user's setup.
- One tutorial = one journey. Don't add "alternatives" or "you could also try X" — those belong in how-to.
