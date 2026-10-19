#!/usr/bin/env python3
"""respire 插件自检 —— 结构与规范校验（对齐 Dim 插件包要求），零第三方依赖。

用法: python3 scripts/validate_plugin.py   （退出码 0=通过；任一 FAIL=1）
"""
import json
import os
import py_compile
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
failed = False


def ok(msg: str) -> None:
    print(f"OK: {msg}")


def fail(msg: str) -> None:
    global failed
    failed = True
    print(f"FAIL: {msg}", file=sys.stderr)


def read_text(rel: str) -> str:
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        fail(f"missing {rel}")
        return ""
    with open(p, encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        fail(f"empty {rel}")
    else:
        ok(rel)
    return text


def parse_json(rel: str):
    text = read_text(rel)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception as e:
        fail(f"invalid JSON {rel}: {e}")
        return None


REQUIRED = [
    ".codex-plugin/plugin.json",
    "hooks/hooks.json",
    "hooks/respire.py",
    "hooks/respire.config.example.json",
    ".claude-plugin/marketplace.json",
    "skills/respire/SKILL.md",
    "tests/test_hooks.sh",
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
]
for rel in REQUIRED:
    read_text(rel)

# manifest 规范
manifest = parse_json(".codex-plugin/plugin.json")
if manifest:
    if manifest.get("name") != "respire":
        fail("manifest name must be respire")
    else:
        ok("manifest name")
    ver = str(manifest.get("version") or "")
    if not re.match(r"^\d+\.\d+\.\d+$", ver):
        fail(f"manifest version must be plain SemVer: {ver!r}")
    else:
        ok(f"manifest version {ver}")
    if manifest.get("hooks") != "./hooks/hooks.json":
        fail('manifest hooks must be "./hooks/hooks.json"')
    else:
        ok("manifest hooks pointer")
    iface = manifest.get("interface") or {}
    for k in ("displayName", "shortDescription", "developerName", "category"):
        if not iface.get(k):
            fail(f"manifest interface.{k} missing")
    else:
        ok("manifest interface core fields")

# hooks 规范：事件合法、command 走 \${CLAUDE_PLUGIN_ROOT}、含回退链与 Windows 通道
hooks_cfg = parse_json("hooks/hooks.json")
if hooks_cfg:
    events = hooks_cfg.get("hooks") or {}
    if set(events) - {"SessionStart", "UserPromptSubmit"}:
        fail(f"unexpected events: {sorted(set(events) - {'SessionStart', 'UserPromptSubmit'})}")
    else:
        ok("hook events subset")
    for ev, groups in events.items():
        if not isinstance(groups, list) or not groups:
            fail(f"hooks.{ev} must be a non-empty array")
            continue
        for g in groups:
            for h in (g.get("hooks") or []):
                if h.get("type") != "command":
                    fail(f"{ev}: handler type must be command")
                cmd = h.get("command") or ""
                if "${CLAUDE_PLUGIN_ROOT}" not in cmd:
                    fail(f"{ev}: command must use ${{CLAUDE_PLUGIN_ROOT}}")
                if "python3 " not in cmd or " || python " not in cmd:
                    fail(f"{ev}: command should carry python3||python fallback chain")
                if not h.get("commandWindows"):
                    fail(f"{ev}: commandWindows missing")
                t = h.get("timeout")
                if not isinstance(t, (int, float)) or t <= 0:
                    fail(f"{ev}: timeout must be positive")
    ok("hooks.json shape")

# 主脚本可编译 + 铁律在（fail-open 恒 exit 0）
try:
    py_compile.compile(os.path.join(ROOT, "hooks/respire.py"), doraise=True)
    ok("respire.py compiles")
except Exception as e:
    fail(f"respire.py compile: {e}")
src = read_text("hooks/respire.py")
if src and "sys.exit(0)" not in src:
    fail("respire.py must keep fail-open exit 0")
elif src:
    ok("fail-open exit present")

# marketplace 清单
mp = parse_json(".claude-plugin/marketplace.json")
if mp:
    if mp.get("name") != "risense":
        fail("marketplace name must be risense")
    plugs = mp.get("plugins") or []
    if not any(p.get("name") == "respire" for p in plugs):
        fail("marketplace must list plugin respire")
    else:
        ok("marketplace lists respire")

# 敏感模式扫描（分发前自检）
SECRET = re.compile(r"sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY")
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules"}]
    for fn in filenames:
        if fn.endswith((".pyc", ".webp", ".png", ".jpg")):
            continue
        p = os.path.join(dirpath, fn)
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                if SECRET.search(f.read()):
                    fail(f"secret-like pattern in {os.path.relpath(p, ROOT)}")
        except Exception:
            pass
ok("secret scan done")

print("----")
if failed:
    print("VALIDATE: FAIL")
    sys.exit(1)
print("VALIDATE: PASS")
sys.exit(0)
