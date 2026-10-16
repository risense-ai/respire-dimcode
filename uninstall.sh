#!/usr/bin/env bash
# respire 卸载器 —— dim 无 plugin uninstall 子命令（源码已核），搬移式卸载。
# 搬移目标必须在 plugins 根之外：根内带 manifest 的目录会被 Dim 当插件继续加载（钩子双跑）。
# 插件根随发行版而异：CN ~/.dimcode/v2/plugins、Global ~/.dim/v2/plugins、源码默认 ~/.agents/plugins。
set -euo pipefail

NAME="respire"
FOUND=0
for d in "$HOME/.dimcode/v2/plugins/$NAME" "$HOME/.dim/v2/plugins/$NAME" "$HOME/.agents/plugins/$NAME"; do
  if [ -d "$d" ]; then
    STAMP="$(date +%Y%m%d%H%M%S)"
    BK="$(dirname "$(dirname "$d")")/plugins-backup"
    mkdir -p "$BK"
    mv "$d" "$BK/$NAME.removed-$STAMP"
    echo "已卸载：$d → $BK/$NAME.removed-$STAMP（含你的 respire.config.json，留档可回）"
    FOUND=1
  fi
done
if [ "$FOUND" = 0 ]; then
  echo "未发现已装插件（可能已卸载）。"
fi
echo "确认：新会话中 respire 注入消失；插件面板不再列 respire。"
echo "彻底删除：rm -rf ~/.dimcode/v2/plugins-backup/$NAME.removed-* ~/.dim/v2/plugins-backup/$NAME.removed-*"
