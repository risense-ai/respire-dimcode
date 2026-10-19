# Changelog

## 0.3.0 — Dim 标准插件形态

- 分发改走 Dim 标准插件市场：`dim plugin marketplace add .agents/plugins/marketplace.json` + `dim plugin install respire@risense`；**移除自定义 install.sh / uninstall.sh**
- 包结构对齐规范：`.codex-plugin/plugin.json`（interface 补 developerName/category/capabilities/websiteURL/defaultPrompt）、hooks 归 `hooks/hooks.json`、command 带 `python3 || python` 回退链与 `commandWindows`
- 新增 `scripts/validate_plugin.py` 自检（结构/清单/hooks 形状/可编译/fail-open/敏感扫描）
- **降级为一等公民**：注册、登录、同步与词面召回均不依赖端侧模型；BGE-M3 纯可选增强（`rsrs model install && rsrs model activate m3`）
- 阈值默认关闭（rsrs 直出）；`$skill:` 指认前缀剥除；hook.log 留痕；冷启动超时窗

## 0.2.x — 初版（手装脚本时代）

- memlite→respire(rsrs) 引擎换装、标题档召回、判后即存落库、三态会话引导
