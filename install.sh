#!/usr/bin/env bash
# respire 安装器 —— 走 Dim 正式插件管线：dim plugin install（本目录）
# 旧装存在时先搬走备份（同名插件已装即拒），装完恢复用户配置。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="respire"

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
