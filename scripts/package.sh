#!/usr/bin/env bash
# respire 插件打包 —— CI 与本地共用同一口径。
# 规范：zip 根=插件根（dimagent.cn 托管市场安装链：unzip 后根读 .codex-plugin/plugin.json）。
# 产出 dist/respire-<version>-<yyyymmdd>.zip，zip 注释行为构建基线 commit。
# stdout 恰两行：第一行 zip 路径，第二行 sha256。
# 兼容 macOS bash 3.2：变量展开一律 ${VAR} 花括号隔离，邻近不放中文标点。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VER="$(python3 -c "import json; print(json.load(open('.codex-plugin/plugin.json'))['version'])")"
REV="$(git rev-parse HEAD)"
STAMP="$(date +%Y%m%d)"
OUT="dist/respire-${VER}-${STAMP}.zip"

mkdir -p dist
rm -f "$OUT"

zip -r "$OUT" \
  .codex-plugin .claude-plugin .gitignore CHANGELOG.md LICENSE README.md \
  assets hooks scripts skills tests \
  -x 'hooks/__pycache__/*' 'hooks/__pycache__/' \
  -x 'hooks/hook.log' 'hooks/.nudge_counter' \
  -x '*.DS_Store' '*.pyc' >/dev/null

printf '%s\n' "$REV" | zip -z "$OUT" >/dev/null

echo "$OUT"
python3 -c "import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest())" "$OUT"
