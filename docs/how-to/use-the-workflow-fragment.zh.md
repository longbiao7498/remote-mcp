# 使用 CLAUDE.md 工作流片段

> English version: [use-the-workflow-fragment.md](./use-the-workflow-fragment.md)

## 适用场景

你已经装好并注册了 `remote-mcp`，希望 agent 自动遵守带宽感知的工作流（Grep 用上下文行、MultiRead、FileStat、后台 Bash），而不用每次手动提示。

## 前置条件

- 一个已经能工作的 `remote-mcp` 注册（没有的话先做 [教程](../tutorial/first-remote-session.zh.md)）。
- 想清楚你要在哪个范围生效——见下面三种模式。

## 文件放哪——**本地**，不是远程

**这个 fragment 放到你**本地**机器上的某个 `CLAUDE.md` 里——也就是跑 Claude Code 的那台机器**。它**不**放到远程 SSH 主机上。Claude Code 在会话启动时从你本地文件系统读 `CLAUDE.md`，远程主机永远见不到这个文件。

> 一个小记忆术：`remote-mcp` 是工具；*它操作的对象*在远程，但 *Claude Code 本身*（以及它读的所有东西——包括 `CLAUDE.md`）都在你本地。

## 三种模式——挑一个

### 模式 1 —— 按项目（推荐默认）

适合：你有一个具体的本地项目，正在远程工作。

```bash
cd /path/to/your-local-project   # 你在 Claude Code 里打开的那个目录
cat /path/to/remote-mcp/CLAUDE.md.fragment.md >> CLAUDE.md
```

`>>` 是追加——如果 `CLAUDE.md` 还不存在，会被创建。规则只在你从 `/path/to/your-local-project` 里打开 Claude Code 时生效。

优点：精准——规则不会污染不该生效的地方（比如纯本地项目）。想 git 跟踪也很容易。

### 模式 2 —— 用户级（重度用户）

适合：你*大部分* Claude Code 项目都在用 `remote-mcp`。

```bash
cat /path/to/remote-mcp/CLAUDE.md.fragment.md >> ~/.claude/CLAUDE.md
```

规则对你打开的每个 Claude Code 项目都生效。权衡：在纯本地项目里这些规则没害——agent 会忽略它们——但每次对话都会占 token。

### 模式 3 —— 团队通过 git 共享

适合：团队多人协作同一个用了远程的项目。

把内容 commit 到项目的 `CLAUDE.md`。任何人 clone 之后自动得到这些规则。

```bash
cd /path/to/team-project
cat /path/to/remote-mcp/CLAUDE.md.fragment.md >> CLAUDE.md
git add CLAUDE.md
git commit -m "docs: add remote-mcp workflow rules for the agent"
```

优点：约定由版本控制强制；同事不小心删了规则，code review 能拦下。

## 验证

复制完，在该项目里启动 Claude Code。问 agent：*"你知道高效使用 remote-mcp 工具的方法吗？"*

正确加载的 fragment 会让 agent 列出具体的：`Grep -C 5`、`MultiRead`、`FileStat`、`run_in_background=true` 等。如果 agent 答的是泛泛而谈（或不提这些），说明 fragment 没被加载——检查 `CLAUDE.md` 在不在预期位置且包含相关内容（`grep -c MultiRead CLAUDE.md` 应该返回 ≥ 1）。

## 当前的局限（以及未来要做什么）

这是个**手动复制粘贴的工作流**。带来这些后果：

- **必须手动**——没有自动装入。忘了的话，agent 退回到效率更低的默认模式。
- **不会自动同步**——`remote-mcp` repo 里的 `CLAUDE.md.fragment.md` 升级了，你之前粘贴的副本不会自动更新。需要手动重新覆盖（或 diff 后合并）。
- **没有防误删保护**——你或队友不小心从 `CLAUDE.md` 里删了这段，没有任何提示。

这些正是 **M3 Claude Code plugin 形态**（见 spec §15.1）要解决的——plugin 发布后，`claude plugin install remote-mcp` 会装一个 always-on skill，提供同样的规则，无需任何文件复制。该工作在 roadmap 上但尚未完成。

## 常见问题排查

- **agent 仍用 Read 而不是 FileStat / 连续 Read 而不是 MultiRead** —— 检查 fragment 是否在正确的 `CLAUDE.md` 里（模式 1 或 3 需要你在项目根目录）。再次核实：从项目里跑 `grep "MultiRead" $(claude config get claude_md_path 2>/dev/null || echo CLAUDE.md)`。
- **多个 `CLAUDE.md` 冲突** —— Claude Code 会合并项目级和用户级的 `CLAUDE.md`。如果 `~/.claude/CLAUDE.md` 里有过时规则、项目里有更新规则，项目里的对该项目生效。误导性的过时副本可以删掉。
- **你用的是 `remote-mcp` 的 fork** —— 确认你 copy 的是正确 repo 的 fragment（不同 fork 的规则可能不同）。
