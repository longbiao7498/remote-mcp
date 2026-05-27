# remote-mcp

> 中文版本：[README.zh.md](./README.zh.md)

A local Python MCP server that proxies file and shell tools to a remote Linux host over SSH. Claude Code (and any other MCP client) gets 10 tools — `Read`, `Write`, `Edit`, `MultiEdit`, `MultiRead`, `FileStat`, `Bash`, `Glob`, `Grep`, `Feedback` — all operating on the remote.

## Quick start

```bash
git clone <repo>
cd remote-mcp
pip install -e .
```

Then [the tutorial](./docs/tutorial/first-remote-session.md) walks you from here to a working setup in about 15 minutes.

## Documentation

All documentation lives in [`docs/`](./docs/), organized along the [Diátaxis](https://diataxis.fr/) framework:

| | I want to... | Read |
|---|---|---|
| 📘 | **get something working** for the first time | [`docs/tutorial/`](./docs/tutorial/) |
| 🛠 | **solve a specific problem** I already have | [`docs/how-to/`](./docs/how-to/) |
| 📚 | **look up exact parameters / errors / config** | [`docs/reference/`](./docs/reference/) |
| 💡 | **understand why the system is the way it is** | [`docs/explanation/`](./docs/explanation/) |

Every page is bilingual — every `name.md` has a `name.zh.md` sibling.

## Project status

v0.1.0 — see [`CHANGELOG.md`](./CHANGELOG.md).

Design history (specs and execution plans) is preserved under [`docs/superpowers/`](./docs/superpowers/) for anyone auditing how the project came to be.

## License

MIT — see [`LICENSE`](./LICENSE).

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md) and the developer how-to: [add a new tool](./docs/how-to/add-a-new-tool.md).
