# docs/superpowers/

This directory holds the **design and implementation history** of remote-mcp,
maintained via the [superpowers](https://github.com/anthropics/claude-code/tree/main/plugins/superpowers)
workflow (brainstorming → writing-plans → subagent-driven-development).

## Layout

```
specs/    Design specifications (the "what" and "why")
plans/    Implementation plans (the "how" and "in what order")
```

## Current artifacts

| File | Purpose | Status |
|------|---------|--------|
| `specs/2026-05-26-remote-mcp-design.md` | v2 design — the authoritative blueprint for what remote-mcp does and why | ✅ Implemented (v0.1.0) |
| `plans/2026-05-26-remote-mcp-implementation.md` | Executed plan — 31 TDD tasks across 6 stages | ✅ Complete |

The repo also has `软件设计文档.md` at root — the **v1 design draft**,
superseded by v2. Kept for decision provenance; do not rely on it.

## How to read these

**If you're new to remote-mcp** and want to understand the system:
1. Start with `README.md` at the repo root (user-facing intro)
2. Then `CLAUDE.md` at the repo root (architecture briefing)
3. Dive into `specs/2026-05-26-remote-mcp-design.md` for the full design

**If you're modifying remote-mcp**: read the spec end-to-end before touching
architecture. See `CONTRIBUTING.md` at the repo root for dev setup.

**If you're auditing decision history**: the spec's §3 lists the major
architectural decisions with rationales. Discussion that led to v2 is preserved
in the git history of the spec file.

## Future plans

Future design work follows the same pattern: new spec under `specs/`, then a
plan under `plans/`. v0.1.0's `[Unreleased]` features (see `CHANGELOG.md`) and
spec §15 future work will be drafted here when prioritized.
