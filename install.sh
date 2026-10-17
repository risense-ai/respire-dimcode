#!/usr/bin/env bash
# respire 安装器 —— 走 Dim 正式插件管线：dim plugin install（本目录）
# 旧装存在时先搬走备份（同名插件已装即拒），装完恢复用户配置。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="respire"

# 首次使用引导：①端侧模型 ②注册登录 ③导入既有记忆（LLM 代抽）
print_guide() {
  cat <<'GUIDE_EOF'

================ 首次使用 · 三件事 ================
① 端侧模型（建议装，召回效果更好）
   rsrs model install && rsrs model activate m3
   约 1.1GB 端侧推理；不装也不挡用——自动回退词面档（SessionStart 会提示）。

② 注册登录（跨设备同步）
   去 https://rsrs.rs 注册 → 本机跑 rsrs register（首台设备，密码与超级密码本人设）
   日常登录 rsrs login（浏览器授权）；rsrs status 查态。未登录时插件会注入引导。

③ 导入既有记忆与规则（一次成库，让 Dim 的 LLM 代抽）
   开一个 Dim 新会话，把下面整段粘进去：
   ┌─────────────────────────────────────────────
   │ 请把本机 Dim 的既有规则与记忆导入 respire：逐个读取——
   │ ~/AGENTS.md（家目录规则，若在）、你常用项目根下的 AGENTS.md、
   │ ~/.dimcode/v2/skills/*/SKILL.md（技能知识）、~/.dimcode/v2/hooks.json（钩子策略）、
   │ ~/.dimcode/v2/notes/ 与 ~/.dimcode/v2/plan-drafts/ 下的 md（笔记与计划）；
   │ 抽出可复用的事实、约定、教训与红线（口令、证件号、卡号、私钥一律排除、只记位置），
   │ 去重后用 rsrs remember 分条存入（--importance important，标题按事实句抽取；
   │ 判重给候选时先决断挂靠或合并），存完给我一份清单。
   └─────────────────────────────────────────────
===================================================
GUIDE_EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --guide) print_guide; exit 0 ;;
    -h|--help) echo "用法: ./install.sh [--guide]  （--guide 只打印首次使用三件事，不安装）"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 1 ;;
  esac
done

# 插件安装根随发行版而异（实测 CN 落 ~/.dimcode/v2/plugins，源码默认 ~/.agents/plugins），逐一探测
find_installed() {
  local d
  for d in "$HOME/.dimcode/v2/plugins/$NAME" "$HOME/.dim/v2/plugins/$NAME" "$HOME/.agents/plugins/$NAME"; do
    [ -d "$d" ] && { echo "$d"; return 0; }
  done
  return 1
}

command -v dim >/dev/null 2>&1 || { echo "错误：dim CLI 不在 PATH，插件须经 dim plugin install 装配。" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "错误：需要 python3（hook 主体的唯一解析依赖）。" >&2; exit 1; }

# —— 职责一：装引擎 respire（rsrs）——缺失则 npm 全局装；不碰账号、登录、配置 ——
find_rsrs() {
  command -v rsrs >/dev/null 2>&1 && return 0
  [ -x "$HOME/.local/bin/rsrs" ] && return 0
  [ -x "$HOME/.rsrs/bin/rsrs" ] && return 0
  return 1
}
if find_rsrs; then
  echo "respire 引擎已就位：$(command -v rsrs 2>/dev/null || echo "$HOME/.local/bin/rsrs")（$(rsrs --version 2>/dev/null | head -1)）"
else
  if command -v npm >/dev/null 2>&1; then
    echo "未检测到 respire 引擎，正在安装 npm i -g @rsrsai/cli@latest …"
    if ! npm i -g @rsrsai/cli@latest; then
      echo "警告：npm 全局安装失败（常见于无全局写权限）。手动执行：npm i -g @rsrsai/cli@latest（需权限时加 sudo）。"
      echo "插件照装——未装引擎时会话内会注入装法，可让 agent 代装。"
    fi
  else
    echo "警告：未找到 npm，无法自动安装引擎。手动执行：npm i -g @rsrsai/cli@latest"
    echo "插件照装——未装引擎时会话内会注入装法。"
  fi
fi

RESTORE_BAK=""
OLD="$(find_installed || true)"
if [ -n "$OLD" ]; then
  # 备份必须移出 plugins 根：根内带 manifest 的目录会被 Dim 当第二个插件加载（钩子双跑）
  STAMP="$(date +%Y%m%d%H%M%S)"
  BAKROOT="$(dirname "$(dirname "$OLD")")/plugins-backup"
  mkdir -p "$BAKROOT"
  mv "$OLD" "$BAKROOT/respire.bak-$STAMP"
  RESTORE_BAK="$BAKROOT/respire.bak-$STAMP"
  echo "发现旧装：$OLD，已搬走备份 → $RESTORE_BAK"
fi

if ! dim plugin install "$ROOT"; then
  if [ -n "$RESTORE_BAK" ] && [ ! -d "$OLD" ]; then
    mv "$RESTORE_BAK" "$OLD"
    echo "安装失败，已回滚旧装。" >&2
  fi
  exit 1
fi

NEW="$(find_installed || true)"
if [ -n "$NEW" ]; then
  if [ -n "$RESTORE_BAK" ] && [ -f "$RESTORE_BAK/hooks/respire.config.json" ]; then
    cp "$RESTORE_BAK/hooks/respire.config.json" "$NEW/hooks/respire.config.json"
    echo "已恢复既有配置：$NEW/hooks/respire.config.json"
    echo "注：从旧版升级时新默认值（如阈值 0.31）不会自动套用——如未自定义过，建议 rm 该文件或 cp respire.config.example.json respire.config.json 后按需改。"
  elif [ ! -f "$NEW/hooks/respire.config.json" ] && [ -f "$NEW/hooks/respire.config.example.json" ]; then
    cp "$NEW/hooks/respire.config.example.json" "$NEW/hooks/respire.config.json"
    echo "已生成配置：$NEW/hooks/respire.config.json（改完新会话生效）"
  fi
fi

echo
echo "安装完成：${NEW:-未知位置}"
echo "验证："
echo "  ls \"${NEW:-~/.dimcode/v2/plugins/respire}\"      # manifest、hooks.json、respire.py 三件齐"
echo "  echo '{\"prompt\":\"respire 测试\"}' | python3 \"${NEW:-~/.dimcode/v2/plugins/respire}/hooks/respire.py\" UserPromptSubmit"
echo "  注：dim 无 plugin list 子命令；dim hooks list 只列 project/user 两路、不列插件钩子（皆为 Dim 现状）。插件本体在 TUI/Desktop 插件面板查，生效与否看新会话实测。"
echo "新会话起生效。回执：「记：…」即落库；/nomem 关本轮召回。"
echo
echo "首次使用请完成三件事（随时可看：./install.sh --guide）："
print_guide
