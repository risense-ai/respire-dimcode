# Changelog

## 0.5.5 — 数据存储安全三点说明（安装引导注入）

- README 新增「数据存储安全」节：① 可离线使用（本地库，不联网不注册不登录照常召回与落库，离线写入留队列联网补同步）② 上云只有密文（本地加密后上传，服务端无解密密钥）③ 企业可自建同步服务器（respire-server，Docker Compose + Postgres 内网部署，数据不出企业网络）
- 钩子侧落点：三点说明并入 `NO_RSRS`（引擎未装、安装时注入），**不进 `RULES`**——每会话简则不重复宣讲，只在安装/缺引擎时说明
- SKILL.md 增「Data safety (user-facing)」小节（用户问到直说）；清单 `description` 与 `interface.longDescription` 同步追加（插件页安装前可见）

## 0.5.4 — Stop 节流改问引擎（agent 侧落库也放行）

- Stop「近 10 分钟已落库则不再催」原本只扫本层 hook.log 的 store 事件，而该事件只有钩子侧「记：」路径会写——agent 直接 `rsrs remember` 看不见，实测事件恒 0、分支从未命中，每轮都催（Qoder 侧 0.6.3 已修同一缺陷）
- 新增 `engine_last_store()`：`rsrs list --limit 3 --json` 取 `updated_at`/`created_at` 最大值与 600s 比对，命中留痕 `stored_recent_skip src=engine`；6s 超时与异常一律放行照常催，日志快路径保留
- 测试 45 → 48：引擎近期落库不催 / 陈旧仍催 / 留痕 src=engine；节流断言改走 stale/fresh 引擎桩，去掉真机库依赖
- 随版发布：移除 `respire-qoder/` 子目录，Qoder 版只在独立仓 risense-ai/respire-qoder 维护，README/CHANGELOG 已改指

## 0.5.3 — 提示词英文化＋市场元数据与图标

- SKILL.md、钩子注入简则、落库/待决/召回回执全部改为英文；保留「记：」等中文前缀兼容
- Dim 插件清单 `defaultPrompt` 与 `shortDescription` 改为英文；测试断言同步英文并去 locale/实时库依赖
- `interface.logo` 指向新增 `assets/logo.png`（512x512，Dim 插件列表显示）；顶层补 `author`/`homepage`/`repository`/`license`/`keywords`，interface 补 `longDescription`（英文）
- CI：`.github/workflows/release.yml`——push tag（`*.*.*`）自动打包出 Release（`scripts/package.sh` 共用口径）；push main/PR 跑自检；`workflow_dispatch` 出 artifact 演练
- 打包清单含 `assets/`

## 0.5.0 — 干完活也要存（Stop 钩子）

- 生命周期补齐：用户说话→注入召回（UserPromptSubmit）；**AI 干完活→注入存储检查**（Stop）——
  `block+reason` 续跑一轮，提示把本轮新事实/决定/约定/教训/踩坑分条 `rsrs remember`
- 规范防循环：续跑轮 `stop_hook_active=true` 放行；实测纯文本注入在 Stop 不可见、必须 block+reason
- 节流 `store_nudge_every`（默认每轮，可调 N/0）；近 10 分钟已落库则不再催
- 测试日志与节流状态可经 `RESPITE_LOG`／`RESPITE_NUDGE_STATE` 隔离；47 断言

## 0.4.0 — 安装器与管理器
## 0.4.0 — 安装器与管理器

- **定位收束**：插件＝安装器＋管理器＋正常钩子——引擎未装时把安装命令与配置下一步注给 agent 代跑（同会话实时探测、装完即用）；就绪后自动走正常钩子
- **总开关** `enabled`（false=全线静默，hook.log 留 disabled 痕）；管理三档：`/nomem` 单轮／`enabled` 总控／Dim 插件页 hook 组件开关
- PROBE_FAIL 补「全新机器尚未注册」分支口；NO_RSRS 升级为安装指令＋配置引导
- 升级三连须含 `marketplace upgrade`（install 吃注册时快照）

## 0.3.0 — Dim 标准插件形态
## 0.3.0 — Dim 标准插件形态

- 分发改走 Dim 标准插件市场：`dim plugin marketplace add .agents/plugins/marketplace.json` + `dim plugin install respire@risense`；**移除自定义 install.sh / uninstall.sh**
- 包结构对齐规范：`.codex-plugin/plugin.json`（interface 补 developerName/category/capabilities/websiteURL/defaultPrompt）、hooks 归 `hooks/hooks.json`、command 带 `python3 || python` 回退链与 `commandWindows`
- 新增 `scripts/validate_plugin.py` 自检（结构/清单/hooks 形状/可编译/fail-open/敏感扫描）
- **降级为一等公民**：注册、登录、同步与词面召回均不依赖端侧模型；BGE-M3 纯可选增强（`rsrs model install && rsrs model activate m3`）
- 阈值默认关闭（rsrs 直出）；`$skill:` 指认前缀剥除；hook.log 留痕；冷启动超时窗

## 0.2.x — 初版（手装脚本时代）

- memlite→respire(rsrs) 引擎换装、标题档召回、判后即存落库、三态会话引导
