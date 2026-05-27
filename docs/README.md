# remote-mcp documentation

> 中文版本：[`README.zh.md`](./README.zh.md)

The documentation is organized along the [Diátaxis](https://diataxis.fr/) framework — four distinct kinds of documentation for four distinct reader needs.

Pick the entry point that matches what you need *right now*:

| If you want to... | Read | Type |
|------------------|------|------|
| **Get something working** for the first time | [`tutorial/`](./tutorial/) | 📘 Tutorial — guided lessons |
| **Solve a specific problem** you already know you have | [`how-to/`](./how-to/) | 🛠 How-to — recipes |
| **Look up exact behavior, parameters, errors** | [`reference/`](./reference/) | 📚 Reference — technical specs |
| **Understand why the system is the way it is** | [`explanation/`](./explanation/) | 💡 Explanation — concepts & rationale |

These four kinds don't mix. A tutorial won't explain why we chose paramiko; an explanation won't walk you step-by-step through configuration. If a page is doing too much, please file [feedback](./how-to/inspect-feedback-log.md).

## Suggested reading paths

**Brand new to remote-mcp:**
1. [Tutorial — Your first remote session](./tutorial/first-remote-session.md) (15 min)
2. [Explanation — Architecture overview](./explanation/architecture.md) (background)
3. Skim [Reference — Tool reference index](./reference/) (so you know what exists)

**Familiar with remote-mcp, hit a specific problem:**
1. Check [`how-to/`](./how-to/) — pick the closest match
2. Open the matching tool in [`reference/tools/`](./reference/tools/) for exact behavior
3. If still stuck, [inspect the feedback log](./how-to/inspect-feedback-log.md) or file a new entry

**Contributing or modifying remote-mcp:**
1. [Explanation — Design decisions](./explanation/design-decisions.md) (read this first)
2. [How-to — Add a new tool](./how-to/add-a-new-tool.md)
3. [Reference — Config schema](./reference/config-schema.md) and [Errors](./reference/errors.md)

## Authoritative design records

`docs/superpowers/` holds the project's design history — kept separate from user-facing docs:

- [`superpowers/specs/2026-05-26-remote-mcp-design.md`](./superpowers/specs/2026-05-26-remote-mcp-design.md) — v2 design specification (implemented as v0.1.0)
- [`superpowers/plans/2026-05-26-remote-mcp-implementation.md`](./superpowers/plans/2026-05-26-remote-mcp-implementation.md) — the 31-task implementation plan that was executed

These are for *understanding how the system came to be*, not day-to-day use. Most readers won't need them.

## Bilingual

Every English document under `docs/` has a Chinese twin with `.zh.md` suffix (e.g., `tutorial/first-remote-session.md` and `tutorial/first-remote-session.zh.md`). The English version is the source of truth; translations are kept in sync but may lag by a release.
