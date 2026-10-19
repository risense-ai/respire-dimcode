# respire

> 吸即存，呼即取——给 Dim agent 装上本地加密记忆。

`respire` 是 Dim 标准内容插件：以命令钩子把 [respire（CLI 名 rsrs）](https://www.npmjs.com/package/@rsrsai/cli) 记忆引擎挂进 agent 循环——每轮标题档自动召回、「记：」一前缀即落库。本地优先、端侧加密、云端 LWW 同步；**不带自定义安装脚本，按 Dim 插件市场标准安装**。

## 不装模型完全可用（降级是一等公民）

- **注册、登录、同步、召回全不依赖端侧模型**——装完插件即可用，未装模型时引擎自动走词面档（等同 memlite 未配嵌入的效果）。
- BGE-M3（约 1.1GB）是**纯可选增强**：想要更好的语义召回再 `rsrs model install && rsrs model activate m3`，插件检测到未装会在会话内提示一句，装与不装都不报错、不拦路。

## 安装（Dim 标准插件市场）

```bash
git clone https://github.com/risense-ai/respire-dimcode.git && cd respire-dimcode
python3 scripts/validate_plugin.py                     # 自检：结构/清单/hooks/敏感扫描
dim plugin marketplace add .agents/plugins/marketplace.json
dim plugin install respire@risense
```

升级（源仓拉新后覆盖装）：

```bash
git pull
dim plugin marketplace upgrade risense     # 刷新注册源——marketplace 装的是注册时快照，缺此步装回旧版
dim plugin install respire@risense --overwrite
```

> 你的 `hooks/respire.config.json` 若需保留，从旧目录拷回后删掉即可按新默认走（旧默认值不会自动升级）。

引擎（rsrs CLI）缺失时插件会在会话内注入装法（`npm i -g @rsrsai/cli@latest`），可让 agent 代装。**新会话起生效。**

安装位置：`~/.dimcode/v2/plugins/respire/`（CN 发行版；Global 为 `~/.dim/v2/plugins/`，源码默认 `~/.agents/plugins/`——复制安装，改源码需重装）。

验证：

```bash
ls ~/.dimcode/v2/plugins/respire                 # .codex-plugin、hooks、skills 齐
echo '{"prompt":"respire 测试"}' | python3 ~/.dimcode/v2/plugins/respire/hooks/respire.py UserPromptSubmit
```

两条 Dim 现状须知（已核源码）：`dim` **无** `plugin list` 子命令；`dim hooks list` 只列 project/user 两路配置、**不列插件钩子**——list 显示空不等于钩子没挂，插件本体在 TUI / Desktop 插件页查，生效与否以新会话实测为准。

## 装上后发生什么

| 时机 | 行为 |
| --- | --- |
| `SessionStart` | 注入记忆层简则（何时翻忆、如何落库、红线），对整会话与 subagent 生效；**一次探测三态**——未登录附注册引导（rsrs.rs 注册、`rsrs register` 首设备、`rsrs login --oauth --no-open` 代开授权链接）、库空（<10 条）附首日存料与导入引导、缺语义模型附**可选**装法；常态零打扰 |
| `UserPromptSubmit` | 自动 `rsrs recall --titles`：**标题档注入**——只给分数＋8 位短 id＋标题，正文由 agent `rsrs show <id>` 按需取（附因果链）；默认**直出不过滤**，噪音边界＝rsrs skip 门＋limit 5＋标题档 |
| `prompt` 以「记：」「存：」「remember:」开头 | 直接 `rsrs remember … --importance important` 落库并回执；判后即存判为相似时**不写入**、回执转述候选（`--parent` 挂靠或 `--force` 直写），由模型决断；回执硬约束 AI 抽「主语＋动作＋结果」事实句 `retitle` 替换暂拟题 |
| `prompt` 以 `/nomem` 开头 | 本轮跳过召回 |
| `prompt` 带 `$skill: 名称` | 召回前剥除前缀——技能名词面会撞技能记忆 |
| `skills/respire` | 按需加载的操作法（recall/remember/show/forget/sync 与信封解析要点）；**注意技能只是说明书，动作全由钩子驱动** |

## 首次使用 · 三件事

1. **注册登录**（开箱即用，不依赖模型）：[rsrs.rs](https://rsrs.rs) 注册 → 本机 `rsrs register`；日常 `rsrs login` 浏览器授权；autosync 常开，`rsrs sync` 手动同步，`rsrs status` 查态。
2. **导入既有记忆与规则（一次成库，LLM 代抽）**：开个 Dim 新会话粘贴下面整段——

   > 请把本机 Dim 的既有规则与记忆导入 respire：逐个读取——`~/AGENTS.md`（家目录规则，若在）、你常用项目根下的 `AGENTS.md`、`~/.dimcode/v2/skills/*/SKILL.md`、`~/.dimcode/v2/hooks.json`、`~/.dimcode/v2/notes/` 与 `plan-drafts/` 下的 md；抽出可复用的事实、约定、教训与红线（口令、证件号、卡号、私钥一律排除、只记位置），去重后用 `rsrs remember` 分条存入（`--importance important`、标题按事实句；判重给候选先决断挂靠或合并），存完给我一份清单。

   空库首日 SessionStart 会注入同一线索。
3. **端侧模型（可选增强）**：`rsrs model install && rsrs model activate m3`——不装完全可用，想要更好语义召回再装。

## 调优（可选）

`~/.dimcode/v2/plugins/respire/hooks/respire.config.json`（缺失即全默认，改完新会话生效；**不涉及登录与账号**）：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `rsrs` | `""` | 引擎路径；空 = 自动探测（PATH → `~/.local/bin` → `~/.rsrs/bin`） |
| `recall_threshold` | `0.0` | 召回下限；**0=默认关（rsrs 直出）**，设正数才启用过滤 |
| `recall_limit` | `5` | 取前 N 条 |
| `min_prompt_chars` | `2` | 1 字才跳，2 字起即查 |
| `session_rules` | `true` | 是否注入 SessionStart 简则 |
| `budget_chars` | `1500` | 单轮注入总预算（标题行远短于此） |
| `log` | `true` | `hooks/hook.log` 留痕（超 256KB 清轮） |

过滤策略：**默认不设阈值**——三层已框住噪音：rsrs skip 门、limit 5、标题档。历史教训：阈值 0.56→0.31 每降一次都是真相关被拦的补救，漏召代价远大于多看两行标题。

## 卸载

`dim` 无 `plugin uninstall` 子命令（已核源码）——搬移式卸载，**目标必须在 plugins 根之外**（根内带 manifest 的残留目录会被 Dim 当插件继续加载、钩子双跑）：

```bash
mv ~/.dimcode/v2/plugins/respire ~/.dimcode/v2/plugins-backup/respire.removed-$(date +%s)
```

## 设计要点

- **fail-open**：hook 任何异常 → 空 stdout + `exit 0`，永不拦会话；失败必留痕于 hook.log
- **纯文本输出**：stdout 即 `additionalContext`，没有误拦面
- **标题档注入**：`recall --titles` 只回 id/score/title，正文交 `show` 按需拉取；`superseded_by` 标「已被取代」
- **判后即存尊重设计**：落库不带 `--force`，`pending` 候选原样转述给模型决断
- **`${CLAUDE_PLUGIN_ROOT}` 占位符**：Dim 运行时替换为插件安装根，跨机器自洽；command 带 `python3 || python` 回退与 `commandWindows` 通道
- **包内自检**：`python3 scripts/validate_plugin.py`（结构/清单/hooks 形状/可编译/fail-open/敏感扫描），分发前必跑

## 已知边界

- **召回质量是引擎上限**：用词鸿沟下 BGE-M3 可能漏召真条——简则已约束模型「命中不贴题换词补查」（同义词/上位词/英文词分路）
- **冷启动窗**：runtime 冷启＋模型加载实测 7s+，故 hook timeout 20s、recall 14s、probe 10s；探测失败时 SessionStart 注入诊断段
- **PostCompact 不可重注**（Dim 协议该事件仅副作用）：长会话压缩后简则如丢失，开新会话即复
- **留痕**：`hooks/hook.log` 每事件一行（ts/ev/out/ms/d 含 query 摘要），按行复盘「灵不灵」

## 测试

```bash
python3 scripts/validate_plugin.py   # 包结构自检
bash tests/test_hooks.sh             # 行为只读断言（简则/召回/清洗/引导），不碰库
bash tests/test_hooks.sh --store     # 加写探针（写真库→回执→rsrs forget 自清理）
```

rsrs 无 data-dir 隔离（runtime 单例＋全局 client.json），故写测试仅在显式开启时进行，即写即忘。

## License

MIT
