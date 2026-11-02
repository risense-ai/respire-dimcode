#!/usr/bin/env bash
# respire plugin packaging -- CI and local use the same recipe.
# Spec: zip root = plugin root (the dimagent.cn hosted marketplace install chain reads .codex-plugin/plugin.json at the root after unzip).
# Produces dist/respire-<version>-<yyyymmdd>.zip with the build baseline commit as the zip comment.
# stdout is exactly two lines: the zip path, then the sha256.
# macOS bash 3.2 compatible: always brace variable expansions as ${VAR} and never place CJK punctuation next to them.
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
