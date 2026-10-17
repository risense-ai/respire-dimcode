# respire

> 吸即存，呼即取——给 Dim agent 装上本地加密记忆。

`respire` 插件只做两件事：**安装引擎**与**注入 hook**。不碰登录、不碰账号配置——注册同步是 respire（rsrs）自己的事，去 [rsrs.rs](https://rsrs.rs) 注册后 `rsrs sync` 自动双向同步。记忆引擎 [respire（CLI 名 rsrs）](https://www.npmjs.com/package/@rsrsai/cli)：本地优先、端侧加密、BGE-M3 向量、云端 LWW 同步。

## 装上后发生什么

| 时机 | 行为 |
| --- | --- |
| `SessionStart` | 注入记忆层简则（何时翻忆、如何落库、红线），对整会话生效；并**探测登录态**（`rsrs status`，实测 174–451ms）——未登录才另附引导段（去 rsrs.rs 注册、`rsrs register` 首设备、`rsrs login --oauth --no-open` 代开授权链接），已登录零打扰；并**一次探测三态**——未登录附注册引导、**库空（<10 条）附首日存料引导**（新用户首日无得忆非故障）、缺语义模型（`~/.rsrs/models/bge-m3`）附装法（`rsrs model install` ＋ `rsrs model activate m3`，未装期间引擎自带词面回退） |
| `UserPromptSubmit` | 自动 `rsrs recall --titles`：**标题档注入**——只给分数＋8 位短 id＋标题（respire 设计：正文由 agent `rsrs show <id>` 按需取，附完整因果链）；rsrs 自带无关过滤（零命中即 skip），本层再按 0.34 阈值兜底 |
| `prompt` 以「记：」「存：」「remember:」开头 | 直接 `rsrs remember … --importance important` 落库并回执；判后即存判为相似时**不写入**、回执转述候选（挂靠 `--parent` 或 `--force` 直写），由模型决断 |
| `prompt` 以 `/nomem` 开头 | 本轮跳过召回 |
| `skills/respire` | 按需加载的操作法：recall/remember/show/forget/sync 与信封解析要点 |

引擎缺失时 SessionStart 注入装法（`npm i -g @rsrsai/cli@latest`），可让 agent 代装。单字 prompt 不检索；单轮注入预算 1500 字。

## 依赖

- Dim agent（`dim` CLI 在 PATH）
- `python3`（hook 主体的唯一解析依赖，无需 jq）
- respire 引擎（`rsrs` CLI）——**`install.sh` 检测到缺失会自动 `npm i -g @rsrsai/cli@latest`**（无全局写权限时提示手动）
- 语义模型 BGE-M3（约 1.1GB，`rsrs model install` ＋ `rsrs model activate m3`）——**未装不阻塞**：引擎自动词面回退（等同 memlite 未配嵌入的效果），SessionStart 注入装法提示

## 安装

```bash
git clone https://github.com/risense-ai/respire-dimcode.git && cd respire-dimcode
./install.sh
```

一步做两件：先装引擎（缺才装），再 `dim plugin install <本目录>` 装插件；旧装存在先搬至 `plugins-backup/`、装完恢复你的 `respire.config.json`。也可分开手跑两条 `npm i -g @rsrsai/cli@latest`、`dim plugin install /path/to/respire`。

验证：

```bash
rsrs --version
ls ~/.dimcode/v2/plugins/respire        # manifest、hooks.json、respire.py 三件齐
echo '{"prompt":"respire 测试"}' | python3 ~/.dimcode/v2/plugins/respire/hooks/respire.py UserPromptSubmit
```

两条 Dim 现状须知（已核源码）：`dim` **无** `plugin list` 子命令；`dim hooks list` 只列 project/user 两路配置、**不列插件钩子**——list 显示空不等于钩子没挂，插件本体在 TUI / Desktop 插件页查（可装、可删、skill/hook/mcp 逐组件开关），生效与否以新会话实测为准。

**新会话起生效。** 插件装入 `~/.dimcode/v2/plugins/respire/`（CN 发行版；Global 为 `~/.dim/v2/plugins/`，源码默认 `~/.agents/plugins/`。复制安装，改源码需重装）。

## 登录与同步（不归插件管）

插件不代跑注册、不读写任何账号配置；但 SessionStart 会探测登录态，**未登录时在提示词里注入引导**（注册去 rsrs.rs、首设备 `rsrs register` 须本人设密码、日常登录可代跑 `rsrs login --oauth --no-open` 把授权链接交给用户）。登录后 autosync 常开，`rsrs sync` 手动双向同步，`rsrs status` 查态。

## 调优（可选）

`~/.dimcode/v2/plugins/respire/hooks/respire.config.json`（缺失即全默认，改完新会话生效；**不涉及登录与账号**）：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `rsrs` | `""` | 引擎路径；空 = 自动探测（PATH → `~/.local/bin` → `~/.rsrs/bin`） |
| `recall_threshold` | `0.34` | 召回注入下限 |
| `recall_limit` | `5` | 取前 N 条 |
| `min_prompt_chars` | `2` | 1 字才跳，2 字起即查 |
| `session_rules` | `true` | 是否注入 SessionStart 简则（已有全局记忆规则时可关） |
| `budget_chars` | `1500` | 单轮注入总预算（标题行远短于此） |

阈值依据：实测 rsrs（4396 条真库）——短查询强相关 0.45–0.61，但**长指令句会把正主稀释到 0.36–0.38**（0.44 曾实证漏召），真无关 rsrs 自带 skip，故取 0.34 只作安全网。

## 卸载

```bash
./uninstall.sh        # 搬走插件目录留档（含你的配置）；不卸引擎
```

`dim` 无 `plugin uninstall` 子命令（已核源码），故搬移式卸载至 `plugins-backup/`——**必须在 plugins 根之外**，根内带 manifest 的残留目录会被 Dim 当插件继续加载、钩子双跑。

## 设计要点

- **fail-open**：hook 任何异常 → 空 stdout + `exit 0`（协议里的「无决策、放行」），永不拦会话
- **纯文本输出**：stdout 即 `additionalContext`，无 JSON 输出面，也就没有误拦面
- **标题档注入**：`recall --titles` 只回 id/score/title（无 content），正文交给 `show <id>` 按需拉取——省 token 且不肢解记忆正文；`superseded_by` 非空标注「已被取代」
- **rsrs 信封**：失败也是 `status:"fail"`（查 status 不查退出码）；进度写 stderr、只解析 stdout；titles 档 details=[{id,score,title,superseded_by}]、零命中 status=skip+details null
- **判后即存尊重设计**：落库不带 `--force`，`pending` 候选原样转述给模型决断
- **`${CLAUDE_PLUGIN_ROOT}` 占位符**：Dim 运行时替换为插件安装根，跨机器自洽，不动用户自己的 `hooks.json`
- **字段逐个依协议**：Dim 的 hooks 配置校验严格，任一违例整文件拒载——改 `hooks.json` 后须重装（复制安装）

## 已知边界

- **召回质量是引擎上限**：用词鸿沟（如「远程连接」↔「手机遥控/remote」）下 BGE-M3 可能漏召真条而被同域条霸屏——hook 无法治本，简则已约束模型「命中不贴题换词补查」（同义词/上位词/英文词分路）
- **冷启动窗**：runtime 冷启＋模型加载实测 7s+，故 Dim hook timeout 20s、recall 14s、probe 10s；仍失败时 SessionStart 注入「状态探测失败」诊断段
- **PostCompact 不可重注**（Dim 协议该事件仅副作用）：长会话压缩后简则如丢失，开新会话即复
- **留痕**：`hooks/hook.log` 每事件一行（ts/ev/out/ms/d），超 256KB 清轮；`log:false` 关闭——「时灵时不灵」按行复盘

## 测试

```bash
bash test/test_hooks.sh            # 只读 10 断言：简则/召回/阈值/短路/坏输入，不碰库
bash test/test_hooks.sh --store    # 加写探针 3 断言：写真库→回执→rsrs forget 自清理
```

rsrs 无 data-dir 隔离（runtime 单例＋全局 client.json），故写测试只在显式开启时进行，且即写即忘。

## License

MIT
