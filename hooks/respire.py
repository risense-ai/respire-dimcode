#!/usr/bin/env python3
# respire —— respire(rsrs) × Dim agent 记忆插件（hook 端单入口）
# 职责仅两件：安装到位（install.sh 负责）＋ 注入 dim hook（本脚本）。不碰登录、不碰账号配置。
# 用法: python3 respire.py <SessionStart|UserPromptSubmit>   （事件 JSON 走 stdin）
# 铁律: fail-open —— 任何异常 → 空 stdout、exit 0（协议里即「无决策、放行」），绝不 exit 2。
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

VERSION = "0.2.0"

DEFAULTS = {
    "rsrs": "",                 # respire 引擎（rsrs）路径；空 = 自动探测
    "recall_threshold": 0.34,   # 召回注入下限（实测：短查询强相关 0.45–0.61、长指令句正主衰减至 0.36–0.38、真无关 rsrs 自带 skip；高阈值会拦长句正主）
    "recall_limit": 5,          # 取前 N 条
    "min_prompt_chars": 2,      # 过短不检索（1 字才跳；2 字起即查，rsrs 自带 skip 门、本地 100–400ms）
    "session_rules": True,      # SessionStart 是否注入用法简则
    "budget_chars": 1500,       # 单轮注入总字数预算
}

# 显式落库前缀：prompt 以「记：」等开头 → 直接入库并回执
STORE_PREFIX = re.compile(r"^(?:记|存|记录|记住|remember)\s*[:：]\s*", re.I)
# 本轮跳过召回
SKIP_PREFIX = re.compile(r"^(?:/nomem|#nomem)\b")

RULES = """【respire 记忆层 · 已挂接】本机 respire（rsrs）记忆库随本会话生效；数据本地加密、云端同步（账号注册与登录不归本层管，见 rsrs.rs）。
1. 答前先翻忆：rsrs recall "项目名+关键词"（--json 结构化、--titles 只要 id+标题）；报错、异常先按报错原文翻忆。
2. 收尾可存：rsrs remember "内容" --title "事实句" --importance important（判后即存：相似会给候选，先决断再发）。**title 是召回与判重的门面，须你从内容抽取「主语＋动作＋结果」的完整事实句，禁主题分类名、禁硬截断**；prompt 以「记：」开头时由本层先落库保底——回执带暂拟标题与短 id，**你须抽取更准的事实句并 rsrs retitle <短id> --title 替换**。
3. 每轮自动召回已随 prompt 注入；**未见召回注入、或话题涉及此前的项目、报错、约定、日期时，先 rsrs recall 补查再答，可见地调用**；同词已有注入方才勿重复。本轮加 /nomem 前缀可关闭自动召回。
4. 口令、证件号、手机号、卡号、私钥禁入记忆正文与查询词，只写存放位置——库虽加密，密钥泄露即全裸。
5. 同步 rsrs sync（autosync 常开）、rsrs status 查态、rsrs prompt 读完整工作流；深用法见 respire 技能。"""

NO_RSRS = """【respire】已装配但未找到 respire 引擎（rsrs CLI），记忆层暂不可用。
安装：npm i -g @rsrsai/cli@latest （或在 respire 插件目录跑 ./install.sh）。可代为执行安装后继续本轮。"""

LOGIN_NUDGE = """注意：本机 respire 尚未登录——记忆只存本机、不同步、不跨设备。引导用户：去 rsrs.rs 注册后跑 rsrs register（首台设备，密码与超级密码须本人在终端设）；日常登录可由你代跑 rsrs login --oauth --no-open，把授权链接交给用户点击。"""

NO_MODEL = """注意：respire 语义模型（BGE-M3）未装——recall 目前仅词面档（等同 memlite 未配嵌入的回退效果）。引导安装：rsrs model install 下载模型（约 1.1GB），再 rsrs model activate m3 建索引激活，召升降为语义档。可代跑，建索引耗时较长可后台挂起。"""


def _typed(val, ref) -> bool:
    if isinstance(ref, bool):
        return isinstance(val, bool)
    if isinstance(ref, (int, float)):
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    return isinstance(val, type(ref))


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    path = os.environ.get("RESPITE_CONFIG") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "respire.config.json")
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict):
            for key, ref in DEFAULTS.items():
                if key in doc and _typed(doc[key], ref):
                    cfg[key] = doc[key]
    except Exception:
        pass  # 配置缺失/损坏 → 用默认值，绝不拦
    return cfg


def find_rsrs(cfg: dict):
    home = os.path.expanduser("~")
    cands = [cfg.get("rsrs") or "", os.environ.get("RESPITE_RSRS") or "",
             shutil.which("rsrs") or "",
             f"{home}/.local/bin/rsrs", f"{home}/.rsrs/bin/rsrs", "/usr/bin/rsrs"]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def run_rsrs(bin_path: str, args: list, timeout: int):
    # rsrs 的 --json 模式下进度写 stderr，capture 须分离，只解析 stdout
    return subprocess.run([bin_path] + args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def extract_title(content: str) -> str:
    """无 LLM 下尽量抽完整事实句：整句优先 → 退到分隔符 → 绝不在词中硬截（上限 70 字）。
    引擎不代抽题（retitle --title 必填），抽毕由回执引导 agent 用 retitle 精修。"""
    s = re.sub(r"\s+", " ", content.strip())
    if not s:
        return ""
    m = re.match(r"^(.{6,}?[。！？!?])", s)          # 第一个 ≥6 字的完整句
    if m:
        return m.group(1)[:70].strip()
    head = s[:70]
    cuts = [head.rfind(c) for c in "，；、,;"]        # 退到分隔符，不切半词
    cut = max(cuts)
    if cut >= 20:
        return head[:cut + 1].rstrip("，,；; ").strip()
    return head                                       # 无标点长串才落到 70 字上界


def do_store(bin_path: str, content: str, cfg: dict) -> str:
    """显式落库：判后即存三态——ok 直写 / pending 给候选待决 / 其余为失败，皆回执不静默。"""
    if not content:
        return ""
    title = extract_title(content) or "respire 快存"
    try:
        r = run_rsrs(bin_path, ["remember", content, "--title", title,
                                "--importance", "important", "--json"], 15)
    except Exception:
        return "【respire·落库】respire 超时未回，请改手动 rsrs remember 核实是否入库。"
    try:
        doc = json.loads(r.stdout) if r.stdout else {}
    except Exception:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    status = str(doc.get("status") or "")
    if status == "ok":
        sid = str((doc.get("summary") or {}).get("id") or "")
        tail = f"（{sid[:8]}）" if sid else ""
        return (f"【respire·落库】已存入：{title}{tail}。标题系规则暂拟——"
                "请从内容抽取「主语＋动作＋结果」的完整事实句，"
                f"rsrs retitle {sid[:8]} --title 替换（title 是召回与判重的门面）。")
    if status == "pending":
        # 判后即存判定疑似重复/可挂靠，未写入（written:false）——转述候选，模型接续决断
        lines = ["【respire·落库待决】respire 判定本条与既有记忆相似，未写入。候选："]
        for it in (doc.get("items") or [])[:5]:
            if isinstance(it, dict):
                lines.append(f"- [{it.get('name', '?')}] {it.get('value', '')}")
        lines.append("请决断：挂靠则 rsrs remember 同文 --parent <id>；确属独立则加 --force 直写。")
        return "\n".join(lines)
    errs = doc.get("errors") or []
    msg = json.dumps(errs, ensure_ascii=False)[:200] if errs else f"status={status or r.returncode}"
    return f"【respire·落库失败】respire 未收：{msg}"


def do_recall(bin_path: str, prompt: str, cfg: dict) -> str:
    """每轮召回：--titles 标题档（respire 设计——只注分数＋短 id＋标题，正文由 agent rsrs show <id> 按需取）。
    rsrs 自带相关性门（无关→skip 零命中），本层再按阈值滤掉碰瓷命中。"""
    try:
        r = run_rsrs(bin_path, ["recall", prompt, "--limit",
                                str(int(cfg["recall_limit"])), "--titles", "--json"], 10)
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    try:
        doc = json.loads(r.stdout)
    except Exception:
        return ""
    if not isinstance(doc, dict) or doc.get("status") not in ("ok", "skip"):
        return ""  # fail 静默（fail-open）；skip = 自带门判为无关
    details = doc.get("details") or []
    if not isinstance(details, list):
        return ""
    thr = float(cfg["recall_threshold"])
    keep = []
    for d in details:
        if not isinstance(d, dict):
            continue
        score = d.get("score")
        if isinstance(score, (int, float)) and float(score) >= thr:
            keep.append((float(score), d))
        if len(keep) >= int(cfg["recall_limit"]):
            break
    if not keep:
        return ""
    budget = int(cfg["budget_chars"])
    lines, used = [], 90  # 90 留给头行上界，砍点据此提前
    for score, d in keep:
        title = str(d.get("title") or "").strip() or "(无题)"
        eid = str(d.get("id") or "")[:8]
        stale = " →已被取代" if d.get("superseded_by") else ""
        line = f"- [{score:.2f}] {title}（{eid}）{stale}"
        if lines and used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return ""
    head = (f"【respire·自动召回】命中 {len(lines)} 条（阈值 {thr:g}；标题档，"
            "正文 rsrs show <短id> 按需读；分数是相关度不是可信度）：")
    return "\n".join([head] + lines)


def check_login(bin_path: str):
    """登录态探测（SessionStart 专用）：True 已登录 / False 未登录 / None 探测失败（不打扰）。
    开销实测 174–451ms。RESPITE_FAKE_LOGGED_OUT=1 为自测后门。"""
    if os.environ.get("RESPITE_FAKE_LOGGED_OUT") == "1":
        return False
    try:
        r = run_rsrs(bin_path, ["status", "--json"], 6)
        doc = json.loads(r.stdout) if r.stdout else {}
        sess = (doc.get("summary") or {}).get("session") or {}
        return bool(sess.get("has_token")) and bool(sess.get("user"))
    except Exception:
        return None


def check_model():
    """语义模型态（SessionStart 专用）：~/.rsrs/models/bge-m3 目录存在即已装（stat 零开销）。
    未装时引擎自带词面回退（源码 indexed==0 → lexical_only），即 memlite 未配嵌入的效果。
    RESPITE_FAKE_NO_MODEL=1 为自测后门。"""
    if os.environ.get("RESPITE_FAKE_NO_MODEL") == "1":
        return False
    try:
        return os.path.isdir(os.path.expanduser("~/.rsrs/models/bge-m3"))
    except Exception:
        return None  # 探测失败不打扰


def on_prompt(data: dict, cfg: dict, engine) -> str:
    prompt = data.get("prompt")
    if not isinstance(prompt, str):
        return ""
    prompt = prompt.strip()
    if not prompt or SKIP_PREFIX.match(prompt):
        return ""
    m = STORE_PREFIX.match(prompt)
    if m:
        rest = prompt[m.end():].strip()
        return do_store(engine, rest, cfg) if engine else NO_RSRS
    if len(prompt) < int(cfg["min_prompt_chars"]) or not engine:
        return ""
    return do_recall(engine, prompt, cfg)


def main() -> None:
    try:
        event = (sys.argv[1] if len(sys.argv) > 1 else "") or os.environ.get("DIM_HOOK_EVENT", "")
        try:
            raw = "" if sys.stdin.isatty() else sys.stdin.read()
        except Exception:
            raw = ""
        try:
            data = json.loads(raw) if raw.strip() else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data, event = {}, ""

    try:
        cfg = load_config()
        engine = find_rsrs(cfg)
        if event == "SessionStart":
            if not cfg["session_rules"]:
                out = ""
            elif not engine:
                out = NO_RSRS
            else:
                out = RULES
                if check_login(engine) is False:  # 仅未登录才附引导，已登录零打扰
                    out += "\n" + LOGIN_NUDGE
                if check_model() is False:        # 仅缺模型才附装法，已装零打扰
                    out += "\n" + NO_MODEL
        elif event == "UserPromptSubmit":
            out = on_prompt(data, cfg, engine)
        else:
            out = ""
    except Exception:
        out = ""  # fail-open

    if out:
        try:
            sys.stdout.write(out)
            sys.stdout.flush()
        except Exception:
            pass
    sys.exit(0)  # 恒 exit 0：纯文本 stdout 即 additionalContext，无文本即无决策


if __name__ == "__main__":
    main()
