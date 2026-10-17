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
import time

VERSION = "0.3.0"

# 超时窗（秒）：须盖住 rsrs runtime 冷启动（实测 doctor 模型加载 7s+），否则首轮静默、热后即灵
RECALL_T = 14
PROBE_T = 10
STORE_T = 18
LOG_MAX = 256 * 1024  # hook.log 超此整文件清轮

DEFAULTS = {
    "rsrs": "",                 # respire 引擎（rsrs）路径；空 = 自动探测
    "recall_threshold": 0.31,   # 召回注入下限（0.34 曾拦真相关：技能轮「笔痕v1.2.0」0.32；无关 rsrs 自带 skip；只拦极端低分）
    "recall_limit": 5,          # 取前 N 条
    "min_prompt_chars": 2,      # 过短不检索（1 字才跳；2 字起即查，rsrs 自带 skip 门、本地 100–400ms）
    "session_rules": True,      # SessionStart 是否注入用法简则
    "budget_chars": 1500,       # 单轮注入总字数预算
    "log": True,                # hook.log 轻量留痕（每事件一行，复盘时灵时不灵的抓手）
}

# 显式落库前缀：prompt 以「记：」等开头 → 直接入库并回执
STORE_PREFIX = re.compile(r"^(?:记|存|记录|记住|remember)\s*[:：]\s*", re.I)
# 本轮跳过召回
SKIP_PREFIX = re.compile(r"^(?:/nomem|#nomem)\b")
# Dim 技能指认前缀：$skill: 名称 后才是真任务——技能名会词面污染召回 query，须剥掉
SKILL_PREFIX = re.compile(r"^\$\s*skill\s*:\s*\S+\s*", re.I)

RULES = """【respire 记忆层 · 已挂接】本机 respire（rsrs）记忆库随本会话生效；数据本地加密、云端同步（账号注册与登录不归本层管，见 rsrs.rs）。
1. 答前先翻忆：rsrs recall "项目名+关键词"（--json 结构化、--titles 只要 id+标题）；报错、异常先按报错原文翻忆。
2. 收尾可存：rsrs remember "内容" --title "事实句" --importance important（判后即存：相似会给候选，先决断再发）。**title 是召回与判重的门面，须你从内容抽取「主语＋动作＋结果」的完整事实句，禁主题分类名、禁硬截断**；prompt 以「记：」开头时由本层先落库保底——回执带暂拟标题与短 id，**你须抽取更准的事实句并 rsrs retitle <短id> --title 替换**。
3. 每轮自动召回已随 prompt 注入；**未见召回注入、命中不贴题、或话题涉及此前的项目、报错、约定、日期时，换词 rsrs recall 补查再答（同义词、上位词、英文对应词各试一路），可见地调用**；仅当已有注入确实相关方才勿重复。本轮加 /nomem 前缀可关闭自动召回。
4. 口令、证件号、手机号、卡号、私钥禁入记忆正文与查询词，只写存放位置——库虽加密，密钥泄露即全裸。
5. 同步 rsrs sync（autosync 常开）、rsrs status 查态、rsrs prompt 读完整工作流；深用法见 respire 技能。"""

NO_RSRS = """【respire】已装配但未找到 respire 引擎（rsrs CLI），记忆层暂不可用。
安装：npm i -g @rsrsai/cli@latest （或在 respire 插件目录跑 ./install.sh）。可代为执行安装后继续本轮。"""

LOGIN_NUDGE = """注意：本机 respire 尚未登录——记忆只存本机、不同步、不跨设备。引导用户：去 rsrs.rs 注册后跑 rsrs register（首台设备，密码与超级密码须本人在终端设）；日常登录可由你代跑 rsrs login --oauth --no-open，把授权链接交给用户点击。"""

EMPTY_NUDGE = """注意：本机 respire 记忆库还是空的——没有记忆可召回，自动召回无动静是正常而非故障。引导：用「记：〈事实〉」由本层落库，或让 agent 先把既有项目的约定、报错教训、关键结论 rsrs remember 存上几条；既有规则与记忆可一次成库——让 agent 读 ~/AGENTS.md、常用项目 AGENTS.md、~/.dimcode/v2/skills/*/SKILL.md 与 hooks.json，分析抽条后分条存入（口令证件卡号排除）；有货之后每轮召回才有内容。"""

NO_MODEL = """注意：respire 语义模型（BGE-M3）未装——recall 目前仅词面档（等同 memlite 未配嵌入的回退效果）。引导安装：rsrs model install 下载模型（约 1.1GB），再 rsrs model activate m3 建索引激活，召升降为语义档。可代跑，建索引耗时较长可后台挂起。"""

PROBE_FAIL = """注意：respire 状态探测失败（rsrs status 未回）——runtime 可能正在冷启动或异常。首轮召回可能空转，稍候重发即通；持续无回请跑 rsrs doctor 诊断并转告用户。"""


def log_event(cfg: dict, event: str, outcome: str, detail: str = "", ms=None):
    """轻量留痕：hook.log 单行 JSONL、超 256KB 整文件清轮；日志失败绝不影响主链。
    config log:false 关闭。字段：ts/ev/out/ms（耗时毫秒）/d（摘要）。"""
    if not cfg.get("log", True):
        return
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook.log")
        try:
            if os.path.exists(path) and os.path.getsize(path) > LOG_MAX:
                os.remove(path)
        except Exception:
            pass
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "ev": event, "out": outcome}
        if ms is not None:
            rec["ms"] = int(ms)
        if detail:
            rec["d"] = detail[:160]
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


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
        log_event(cfg, "store", "empty_content")
        return ""
    title = extract_title(content) or "respire 快存"
    t0 = time.time()
    try:
        r = run_rsrs(bin_path, ["remember", content, "--title", title,
                                "--importance", "important", "--json"], STORE_T)
    except Exception as e:
        log_event(cfg, "store", "timeout_or_error", f"{type(e).__name__}: {e}", (time.time() - t0) * 1000)
        return "【respire·落库】respire 超时未回，请改手动 rsrs remember 核实是否入库。"
    ms = (time.time() - t0) * 1000
    try:
        doc = json.loads(r.stdout) if r.stdout else {}
    except Exception:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    status = str(doc.get("status") or "")
    if status == "ok":
        sid = str((doc.get("summary") or {}).get("id") or "")
        log_event(cfg, "store", "ok", sid[:8], ms)
        tail = f"（{sid[:8]}）" if sid else ""
        return (f"【respire·落库】已存入：{title}{tail}。标题系规则暂拟——"
                "请从内容抽取「主语＋动作＋结果」的完整事实句，"
                f"rsrs retitle {sid[:8]} --title 替换（title 是召回与判重的门面）。")
    if status == "pending":
        # 判后即存判定疑似重复/可挂靠，未写入（written:false）——转述候选，模型接续决断
        log_event(cfg, "store", "pending", f"cand={len(doc.get('items') or [])}", ms)
        lines = ["【respire·落库待决】respire 判定本条与既有记忆相似，未写入。候选："]
        for it in (doc.get("items") or [])[:5]:
            if isinstance(it, dict):
                lines.append(f"- [{it.get('name', '?')}] {it.get('value', '')}")
        lines.append("请决断：挂靠则 rsrs remember 同文 --parent <id>；确属独立则加 --force 直写。")
        return "\n".join(lines)
    errs = doc.get("errors") or []
    msg = json.dumps(errs, ensure_ascii=False)[:200] if errs else f"status={status or r.returncode}"
    log_event(cfg, "store", "fail", msg, ms)
    return f"【respire·落库失败】respire 未收：{msg}"


def do_recall(bin_path: str, prompt: str, cfg: dict) -> str:
    """每轮召回：--titles 标题档（respire 设计——只注分数＋短 id＋标题，正文由 agent rsrs show <id> 按需取）。
    rsrs 自带相关性门（无关→skip 零命中），本层再按阈值滤掉碰瓷命中。"""
    t0 = time.time()
    try:
        r = run_rsrs(bin_path, ["recall", prompt, "--limit",
                                str(int(cfg["recall_limit"])), "--titles", "--json"], RECALL_T)
    except Exception as e:
        log_event(cfg, "recall", "timeout_or_error", f"{type(e).__name__}", (time.time() - t0) * 1000)
        return ""
    ms = (time.time() - t0) * 1000
    if r.returncode != 0:
        log_event(cfg, "recall", "rc_nonzero", f"rc={r.returncode} {r.stderr[:80] if r.stderr else ''}", ms)
        return ""
    try:
        doc = json.loads(r.stdout)
    except Exception:
        log_event(cfg, "recall", "parse_error", (r.stdout or "")[:80], ms)
        return ""
    if not isinstance(doc, dict) or doc.get("status") not in ("ok", "skip"):
        log_event(cfg, "recall", "status_fail", str(doc.get("status") if isinstance(doc, dict) else "?"), ms)
        return ""  # fail 静默（fail-open）；skip = 自带门判为无关
    details = doc.get("details") or []
    if not isinstance(details, list):
        log_event(cfg, "recall", "bad_details", "", ms)
        return ""
    thr = float(cfg["recall_threshold"])
    keep = []
    max_score = 0.0
    for d in details:
        if not isinstance(d, dict):
            continue
        score = d.get("score")
        if isinstance(score, (int, float)):
            max_score = max(max_score, float(score))
        if isinstance(score, (int, float)) and float(score) >= thr:
            keep.append((float(score), d))
        if len(keep) >= int(cfg["recall_limit"]):
            break
    if not keep:
        log_event(cfg, "recall",
                  "skip" if doc.get("status") == "skip" else "below_thr",
                  f"max={max_score:.3f} thr={thr:g} q={prompt[:40]}", ms)
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
        log_event(cfg, "recall", "budget_empty", "", ms)
        return ""
    head = (f"【respire·自动召回】命中 {len(lines)} 条（阈值 {thr:g}；标题档，"
            "正文 rsrs show <短id> 按需读；分数是相关度不是可信度）：")
    log_event(cfg, "recall", "hit", f"n={len(lines)} max={max_score:.3f} q={prompt[:40]}", ms)
    return "\n".join([head] + lines)


def probe_status(bin_path: str):
    """SessionStart 一次 status 三态共用（登录态＋库量＋探测成败；开销实测热态约 190ms）。
    返回 (logged, total, probe_ok)：logged True/False/None；total int/None；
    probe_ok False=status 未回（冷启动/异常），注入 PROBE_FAIL 段。
    后门：RESPITE_FAKE_LOGGED_OUT=1 / RESPITE_FAKE_EMPTY=1 / RESPITE_FAKE_PROBE_FAIL=1。"""
    fake_out = os.environ.get("RESPITE_FAKE_LOGGED_OUT") == "1"
    fake_empty = os.environ.get("RESPITE_FAKE_EMPTY") == "1"
    if os.environ.get("RESPITE_FAKE_PROBE_FAIL") == "1":
        log_event(DEFAULTS, "probe", "fake_fail")
        return (None, None, False)
    t0 = time.time()
    try:
        r = run_rsrs(bin_path, ["status", "--json"], PROBE_T)
        doc = json.loads(r.stdout) if r.stdout else {}
        if not isinstance(doc, dict) or doc.get("status") != "ok":
            log_event(DEFAULTS, "probe", "status_not_ok",
                      str(doc.get("status") if isinstance(doc, dict) else "?"),
                      (time.time() - t0) * 1000)
            return (None, None, False)
        summ = doc.get("summary") or {}
        sess = summ.get("session") or {}
        logged = bool(sess.get("has_token")) and bool(sess.get("user"))
        total = summ.get("local_total")
        total = int(total) if isinstance(total, int) else None
    except Exception as e:
        log_event(DEFAULTS, "probe", "error", f"{type(e).__name__}: {e}",
                  (time.time() - t0) * 1000)
        return (None, None, False)
    ms = (time.time() - t0) * 1000
    if fake_out:
        logged = False
    if fake_empty:
        total = 0
    log_event(DEFAULTS, "probe", "ok", f"logged={logged} total={total}", ms)
    return (logged, total, True)


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
        log_event(cfg, "prompt", "bad_prompt", "非字符串")
        return ""
    prompt = prompt.strip()
    if not prompt or SKIP_PREFIX.match(prompt):
        log_event(cfg, "prompt", "nomem_or_empty", prompt[:40])
        return ""
    m = STORE_PREFIX.match(prompt)
    if m:
        rest = prompt[m.end():].strip()
        if not engine:
            log_event(cfg, "store", "engine_missing", prompt[:40])
            return NO_RSRS
        return do_store(engine, rest, cfg)
    if len(prompt) < int(cfg["min_prompt_chars"]):
        log_event(cfg, "prompt", "too_short", prompt[:40])
        return ""
    if not engine:
        log_event(cfg, "recall", "engine_missing", prompt[:40])
        return ""
    query = SKILL_PREFIX.sub("", prompt).strip() or prompt  # 技能指认轮剥前缀，防技能名污染 query
    return do_recall(engine, query, cfg)


def main() -> None:
    try:
        event = (sys.argv[1] if len(sys.argv) > 1 else "") or os.environ.get("DIM_HOOK_EVENT", "")
        try:
            # 事件 JSON 恒为 UTF-8；Windows 非 UTF-8 区域（如 cp1252）下 read() 会按本地码页误解码
            raw = "" if sys.stdin.isatty() else sys.stdin.buffer.read().decode("utf-8", "replace")
        except Exception:
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
                log_event(cfg, "session", "engine_missing")
            else:
                out = RULES
                logged, total, probe_ok = probe_status(engine)  # 一次 status：登录＋库量＋成败
                segs = []
                if not probe_ok:
                    out += "\n" + PROBE_FAIL          # 探测失败可见（冷启动/异常）
                    segs.append("probe_fail")
                else:
                    if logged is False:                # 仅未登录才附引导，已登录零打扰
                        out += "\n" + LOGIN_NUDGE
                        segs.append("login")
                    if total is not None and total < 10:   # 仅空库首日才附引导
                        out += "\n" + EMPTY_NUDGE
                        segs.append("empty")
                if check_model() is False:             # 仅缺模型才附装法，已装零打扰
                    out += "\n" + NO_MODEL
                    segs.append("no_model")
                log_event(cfg, "session", "ok", "segs=" + (",".join(segs) or "none"))
        elif event == "UserPromptSubmit":
            out = on_prompt(data, cfg, engine)
        else:
            out = ""
    except Exception as e:
        out = ""  # fail-open——但必须留痕，否则「时灵时不灵」无从复盘
        try:
            log_event(DEFAULTS, event or "unknown", "fatal", f"{type(e).__name__}: {e}")
        except Exception:
            pass

    if out:
        try:
            buf = getattr(sys.stdout, "buffer", None)
            if buf is None:
                sys.stdout.write(out)
                sys.stdout.flush()
            else:
                buf.write(out.encode("utf-8"))
                buf.flush()
        except Exception:
            pass
    sys.exit(0)  # 恒 exit 0：纯文本 stdout 即 additionalContext，无文本即无决策


if __name__ == "__main__":
    main()
