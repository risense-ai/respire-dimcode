# Changelog

## 未发布 — 同仓加 Qoder 版（`respire-qoder/`）

- Dim 根插件不动；新增 `respire-qoder/` 子目录为 Qoder 插件形态（`.qoder-plugin/plugin.json`＋marketplace 清单、`${QODER_PLUGIN_ROOT}`、Stop 用 `decision: deny`、`skip_prefixes` 内部提示白名单）
- 独立仓：risense-ai/respire-qoder

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
