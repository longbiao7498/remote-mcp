# 参考文档

> English version: [`README.md`](./README.md)

参考文档**描述系统的运作机制**：参数列表、返回格式、配置 Schema、错误目录。内容精确、中立且完整。

参考页面既不是教程（无叙述性内容），也不是操作指南（无建议——只有事实）。需要查询具体内容时请阅读本文档。

## 工具参考

remote-mcp 所暴露的每个工具对应一个页面。每个页面记录：完整参数 Schema、返回格式、错误措辞、行为说明、带宽/延迟特征。

| 工具 | 用途 |
|------|------|
| [Read](./tools/read.md) | 读取远程文件中的行（服务端 `sed` 切片） |
| [Write](./tools/write.md) | 将内容写入远程文件（通过 SFTP 创建父级目录） |
| [Edit](./tools/edit.md) | 替换远程文件中的精确字符串（检查唯一性） |
| [MultiEdit](./tools/multi-edit.md) | 原子性地对单个文件应用多处编辑 |
| [MultiRead](./tools/multi-read.md) | 在一次往返中批量读取多个远程文件 |
| [FileStat](./tools/file-stat.md) | 获取元数据（存在性、大小、mtime、mode），无需传输文件内容 |
| [Bash](./tools/bash.md) | 执行 shell 命令（持久状态；前台或后台） |
| [Glob](./tools/glob.md) | 查找匹配 glob 模式的文件（服务端 `find`） |
| [Grep](./tools/grep.md) | 搜索文件内容中的正则表达式（服务端 `grep`，支持上下文） |
| [Feedback](./tools/feedback.md) | 在本地记录关于 remote-mcp 本身的 bug/改进建议 |
| [Upload](./tools/upload.zh.md) | 通过 SFTP 把本地文件推到远程（二进制安全）。Windows 兜底；Linux 优先 Bash + scp。 |
| [Download](./tools/download.zh.md) | 通过 SFTP 把远程文件拉到本地（二进制安全）。Windows 兜底；Linux 优先 Bash + scp。 |
| [RemoteInfo](./tools/remote-info.zh.md) | 返回连接的已配置身份（host、user、hostname、port、jump_host）。不发 SSH——VPN 安全。 |

## 系统参考

| 页面 | 内容 |
|------|------|
| [配置 Schema](./config-schema.md) | `~/.config/remote-mcp/config.yaml` 中的所有字段 |
| [CLI](./cli.md) | `python -m remote_mcp` 的参数及退出码 |
| [错误措辞目录](./errors.md) | 工具返回的所有 `"Error: ..."` 字符串及其触发条件 |

## 参考文档的写作规范（面向贡献者）

- 描述系统**当前的**行为，而非理想中的行为。若行为出乎意料，请如实记录——不要为此道歉。
- 结构必须可预期。每个工具页面的标题顺序保持一致。
- 不写教程、不发表意见、不给出建议。相关内容请交叉链接到操作指南或说明文档。
- 代码块都是事实（真实的 CLI 输出、真实的 Schema、真实的错误字符串——原文照录）。
- 行为发生变化时必须同步更新。失实的参考文档比没有参考文档更糟糕。
