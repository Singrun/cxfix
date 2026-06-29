# cxfix

`cxfix` 是一套本地 Codex 配置与线程修复工具。它面向 macOS 上的 Codex Desktop / Codex CLI，主要用于修复线程列表、工作目录、provider、插件技能缓存以及 provider 切换后可能出现的加密推理内容问题。

这是一个独立社区工具，不隶属于 OpenAI，也不由 OpenAI 官方支持。Codex 的本地数据库结构不是公开稳定接口，使用前请关闭 Codex，并保留工具生成的备份。

## 能做什么

- 检查 Codex Desktop 和活跃 Codex CLI 进程是否已关闭。
- 对 SQLite 数据库执行 `PRAGMA quick_check`。
- 修改前自动备份数据库、配置文件或 rollout 文件。
- 从本地 rollout 文件重建缺失的线程索引。
- 修复 `has_user_event` 标记。
- 将历史线程 provider 统一到当前配置的 provider，或统一到指定 provider。
- 清理 provider 切换后可能导致官方 OpenAI 接口报错的加密推理字段。
- 展示当前 Codex 配置、provider、profile、插件、MCP server、项目路径和线程 provider 分布。
- 修复错误工作目录，例如把 `～/dev/know ` 迁移为 `~/dev/know` 展开后的真实路径。
- 将缓存中的 Codex 插件技能挂载到 `~/.codex/skills`。

工具不会上传对话内容，也不会把 rollout 内容复制到 GitHub 或任何远程服务。

## 环境要求

- macOS
- Python 3.10 或更新版本
- 已安装 Codex Desktop 或 Codex CLI

## 安装

从 release 包安装：

```bash
python3 install.py
source ~/.zshrc
```

从源码安装：

```bash
git clone https://github.com/Singrun/cxfix.git
cd cxfix
python3 install.py
source ~/.zshrc
```

安装器会把 `~/.local/bin` 加入 `PATH`，复制 `cxfix` Python 包，并写入 `cxfix` alias。

## zsh 配置

安装器维护下面这段配置：

```zsh
# >>> codex session history repair >>>
export PATH="$HOME/.local/bin:$PATH"
alias cxfix="noglob codex-history-repair"
# <<< codex session history repair <<<
```

`noglob` 的作用是让 `cxfix -?` 在 zsh 中正常显示帮助，而不是被 shell 当成文件匹配模式。

## 命令总览

查看所有命令：

```bash
cxfix -?
```

显示当前 Codex 配置概览：

```bash
cxfix config show
```

输出脱敏 JSON：

```bash
cxfix config show -j
```

切换顶层 provider：

```bash
cxfix provider switch aimai1
```

修复当前数据库：

```bash
cxfix fix -y
```

修复所有发现的 Codex 数据库：

```bash
cxfix fix-all -y
```

保留历史 provider 标签：

```bash
cxfix fix-all -y -k
```

统一到指定 provider：

```bash
cxfix fix-all -y -g aimai1
```

只准备回填，不启动 Codex 官方回填流程：

```bash
cxfix fix-all -y -r
```

清理加密推理内容：

```bash
cxfix clean -y
```

修复全部数据库时同时清理加密推理内容：

```bash
cxfix fix-all -y -e
```

列出线程工作目录：

```bash
cxfix path list
```

按文本过滤线程工作目录：

```bash
cxfix path list -c know
```

预览路径迁移：

```bash
cxfix path migrate -f '～/dev/know '
```

应用路径迁移，并把匹配线程同步到当前 provider：

```bash
cxfix path migrate -f '～/dev/know ' -a -y
```

指定迁移目标路径和 provider：

```bash
cxfix path migrate -f '～/dev/know ' -o '~/dev/know' -g aimai1 -a -y
```

挂载缓存中的插件技能：

```bash
cxfix plugins mount
```

预览插件技能挂载：

```bash
cxfix plugins mount -n
```

创建顶层缓存技能软链接：

```bash
cxfix plugins cache -a
```

只处理某个缓存来源：

```bash
cxfix plugins cache -s openai-primary-runtime -a
```

## 参数约定

每个常用参数保留一个短参数和一个完整参数：

| 短参数 | 完整参数 | 用途 |
| --- | --- | --- |
| `-t` | `--timeout` | 等待官方回填的最长秒数 |
| `-r` | `--prepare-only` | 只准备数据库，不启动回填 |
| `-y` | `--yes` | 自动确认关闭残留 app-server |
| `-k` | `--preserve-providers` | 保留历史 provider 标签 |
| `-g` | `--target-provider` | 指定目标 provider |
| `-e` | `--clean-encrypted` | 同时清理加密推理字段 |
| `-d` | `--display-config` | 显示配置概览 |
| `-p` | `--provider` | 切换顶层 provider |
| `-j` | `--json` | 输出 JSON |
| `-f` | `--from-cwd` | 待迁移的原工作目录 |
| `-o` | `--to-cwd` | 迁移后的目标工作目录 |
| `-l` | `--list-cwd` | 列出线程工作目录 |
| `-c` | `--contains-cwd` | 过滤工作目录 |
| `-a` | `--apply` | 写入修改 |
| `-n` | `--dry-run` | 预览，不写入 |
| `-b` | `--cache-root` | 插件缓存根目录 |
| `-u` | `--skills-root` | skills 目标目录 |
| `-s` | `--source` | 指定缓存来源 |
| `-m` | `--visible-mounts` | 创建可见挂载包装 |
| `-x` | `--skip-symlinks` | 只创建可见挂载，不创建顶层软链接 |

## Provider 修复

默认情况下，`cxfix` 会把线程 provider 统一到 `~/.codex/config.toml` 顶层的 `model_provider`。如果没有配置，则回退到 `openai`。

如果希望明确指定 provider：

```bash
cxfix fix-all -y -g aimai1
```

如果希望保留历史 provider：

```bash
cxfix fix-all -y -k
```

切换 provider 会先备份 `config.toml`，再修改顶层 `model_provider`：

```bash
cxfix provider switch aimai1
```

## 路径迁移

`cxfix path` 用于修复线程工作目录漂移。它会更新 SQLite 中的 `threads.cwd`，也会同步更新 rollout 里的 `session_meta.cwd`。写入前会备份数据库和受影响的 rollout 文件。

典型场景是误写了全角波浪号或尾部空格：

```bash
cxfix path migrate -f '～/dev/know ' -a -y
```

默认目标路径会把开头的 `～` 转为 `~`，展开 home 目录，并去掉首尾空白。原路径会精确匹配，包含尾部空格时必须在 shell 中加引号。

## 插件技能挂载

可见挂载会生成类似下面的技能名：

```text
cache:<skill>:<hash>
```

生成文件位于：

```text
~/.codex/skills/_cache_plugin_mounts/
```

这些文件只是包装入口，指向原始缓存中的 `SKILL.md`，不会修改官方插件缓存。

## 备份位置

所有修复产生的备份和 manifest 默认写入：

```text
~/.codex/backups/session-history-repair/
```

## 开发验证

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile codex_history_repair.py install.py
```

## 安全提示

运行会写入本地 Codex 状态，请先退出 Codex Desktop。涉及 provider、路径迁移、加密字段清理等操作时，优先使用不带 `-a` 的预览命令确认影响范围，再执行写入。
