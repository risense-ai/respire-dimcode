#!/usr/bin/env python3
"""Portable, isolated hook tests. No real engine discovery or user data access."""
import importlib.util
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'sk-' + 'q7xkwm2vbnr8tzc41p9e'


def allowed_process(executable, argv, expected_argv, windows):
    """Match only the complete expected invocation, including all arguments.

    CPython's Windows audit event receives executable=None and the already
    list2cmdline-encoded string; POSIX receives an executable and an argv list.
    """
    if executable != expected_argv[0] and not (windows and executable is None):
        return False
    if isinstance(argv, (list, tuple)):
        return list(argv) == expected_argv
    return windows and isinstance(argv, str) and argv == subprocess.list2cmdline(expected_argv)


# Run the unmodified hook with a subprocess allowlist. A failure cannot silently
# fall through to a real rsrs executable, even on machines where one is installed.
# TEST_EXPECTED_ARGV is an ORDERED SEQUENCE of argv lists: every subprocess must
# match the next expected invocation exactly (store now legitimately chains
# remember -> show read-back / remember -> list verification).
LAUNCHER = r'''
import json, os, pathlib, runpy, sys
case = pathlib.Path(os.environ['RESPITE_CONFIG']).resolve().parent
expected = os.environ['TEST_ENGINE']
expected_argv = json.loads(os.environ['TEST_EXPECTED_ARGV'])
assert isinstance(expected_argv, list)   # empty sequence = zero engine calls (review 6: Stop does not query the engine)
for argv in expected_argv:
    assert isinstance(argv, list) and argv[0] == expected
config = json.loads(pathlib.Path(os.environ['RESPITE_CONFIG']).read_text(encoding="utf-8"))
assert config['rsrs'] == expected and os.access(expected, os.X_OK)
sys.path.insert(0, str(pathlib.Path(os.environ['TEST_HOOK']).parents[1] / 'tests'))
from test_ci import allowed_process
state = {'next': 0}
def audit(event, args):
    if event == 'subprocess.Popen':
        executable, argv, cwd, env = args
        index = state['next']
        if index >= len(expected_argv) or not allowed_process(executable, argv, expected_argv[index], os.name == 'nt'):
            pathlib.Path(os.environ['TEST_DENIED']).write_text('unexpected subprocess')
            raise SystemExit(91)
        state['next'] += 1
    elif event.startswith('socket.') or event in ('os.system', 'os.posix_spawn', 'os.exec'):
        pathlib.Path(os.environ['TEST_DENIED']).write_text('unexpected external action')
        raise SystemExit(92)
sys.addaudithook(audit)
sys.argv = [os.environ['TEST_HOOK'], os.environ['TEST_EVENT']]
# Test-only helper dispatch; StoreReceipt is not a host hook event.
if os.environ['TEST_EVENT'] == 'StoreReceipt':
    hook = runpy.run_path(sys.argv[0])
    payload = json.load(sys.stdin)
    content = payload['prompt'].replace('：', ':', 1).split(':', 1)[1].strip()
    print(hook['do_store'](expected, content, config, payload.get('session_id', '')))
else:
    runpy.run_path(sys.argv[0], run_name='__main__')
'''


class CredentialGuard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dimcode-guard-')
        self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name)
        self.spy = self.case / 'spy.py'
        self.calls = self.case / 'calls.jsonl'
        self.log = self.case / 'hook.log'
        self.denied = self.case / 'denied'
        self.spy.write_text(r'''import json, os, sys, datetime, time
with open(os.environ['TEST_CALLS'], 'a', encoding='utf-8') as f:
    f.write(json.dumps(sys.argv[1:]) + '\n')
sub = sys.argv[1]
mode = os.environ.get('STUB_MODE', 'ok')
list_mode = os.environ.get('STUB_LIST', mode)
if mode == 'dead': sys.exit(7)
if mode == 'malformed': print('not json'); sys.exit(0)
if mode == 'hang':
# redirect the inherited stdout/stderr write ends to devnull and move the CWD out of the test temp dir before suspending:
# on Windows the engine is a .cmd shell and run() timeout kills only the shell -- a grandchild holding the pipe would make
# communicate block until the sleep ends naturally (the timeout is useless) and one holding the CWD would make cleanup fail
# with PermissionError. Closing the write end makes EOF arrive at once (TimeoutExpired raises on time) and moving the CWD keeps
# orphan processes from locking any test artifact.
    try:
        _dn = os.open(os.devnull, os.O_WRONLY)
        os.dup2(_dn, 1)
        os.dup2(_dn, 2)
        os.chdir(os.environ.get('SYSTEMROOT') or os.sep)
    except Exception:
        pass
    time.sleep(30)
if sub == 'recall':
    print(json.dumps({'status':'ok','details':[{'id':'cccccccccccccccc','title':'spy','score':0.9}]}))
elif sub == 'remember':
    if mode == 'warn':
        print(json.dumps({'status':'warn','summary':{'action':'created','id':'eeeeeeeeeeeeeeee'},
                          'errors':['parent (cause) cannot be resolved; stored independently']}))
        sys.exit(2)
    if mode == 'pending':
        print(json.dumps({'status':'pending','summary':{'state':'candidates','written':False},
                          'items':[{'name':'aaaabbbb','status':'pending',
                                    'value':'similarity=88% title=stub candidate',
                                    'action':'merge or attach'}],
                          'actions':['rsrs remember "<combined content>" --merge-ids "aaaabbbb"',
                                     'rsrs remember "<content>" --parent <candidate id>',
                                     'rsrs remember "<content>" --force to write as new entry']}))
        sys.exit(2)
    if mode == 'ok_numid': print(json.dumps({'status':'ok','summary':{'id':12345678}})); sys.exit(0)
    if mode == 'ok_dashid': print(json.dumps({'status':'ok','summary':{'id':'a-------'}})); sys.exit(0)
    if mode == 'silent': sys.exit(0)
    if mode == 'ok_noid': print(json.dumps({'status':'ok','summary':{'action':'created'}})); sys.exit(0)
    if mode == 'ok_junkid': print(json.dumps({'status':'ok','summary':{'id':'zz!!not-hex'}})); sys.exit(0)
    if mode == 'bad_summary': print(json.dumps({'status':'ok','summary':'boom'})); sys.exit(0)
    if mode == 'skip_status': print(json.dumps({'status':'skip','summary':{}})); sys.exit(0)
    if mode == 'slow_garbage': time.sleep(2.5); print('garbage not json'); sys.exit(0)
    print(json.dumps({'status':'ok','summary':{'action':'created','id':'dddddddddddddddd'}}))
elif sub == 'show':
    if mode == 'show_fail':
        print(json.dumps({'status':'fail','errors':['not found']}))
        sys.exit(2)
    if mode == 'show_badarr':
        print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':'stub'},
                          'details':[{'broken':True}]}))
        sys.exit(0)
    if mode == 'show_badstr':
        print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':'stub'},
                          'details':'broken'}))
        sys.exit(0)
    title, content = 'stub', 'stub'
    try:
        for line in open(os.environ['TEST_CALLS'], encoding='utf-8').read().splitlines():
            call = json.loads(line)
            if call and call[0] == 'remember':
                content, title = call[1], call[3]
    except Exception:
        pass
    if mode == 'show_mismatch':
        title = title + ' (drifted)'
    if mode == 'show_numcontent':
        print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':title},
                          'details':{'entry':{'id':sys.argv[2],'title':title,'content':42}}}))
        sys.exit(0)
    if mode == 'show_noentryid':
        print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':title},
                          'details':{'entry':{'title':title,'content':content}}}))
        sys.exit(0)
    if mode == 'show_wrongid':
        print(json.dumps({'status':'ok','summary':{'id':'99999999-9999-4999-8999-999999999999','title':title},
                          'details':{'entry':{'id':'99999999-9999-4999-8999-999999999999','title':title,'content':content}}}))
        sys.exit(0)
    if mode == 'show_tail' and content:
        content = content[:40] + 'TAMPERED-TAIL'
    print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':title},
                      'details':{'entry':{'id':sys.argv[2],'title':title,'content':content}}}))
elif sub == 'status':
    print(json.dumps({'status':'ok','summary':{'session':{'has_token':True,'user':'stub'},'local_total':42}}))
elif sub == 'list':
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() if list_mode == 'recent' else '2020-01-01T00:00:00Z'
    if list_mode == 'list_schema':
        print(json.dumps({'status':'ok','details':{'broken':True}}))
    elif list_mode == 'list_notimes':
        print(json.dumps({'status':'ok','details':[{'id':'record','no_dates':True}]}))
    else:
        print(json.dumps({'status':'fail'} if list_mode == 'failed' else {'status':'ok','details':[{'id':'record','updated_at':ts}]}))
else: sys.exit(1)
''', encoding="utf-8")
        if os.name == 'nt':
            self.engine = self.case / 'rsrs-spy.cmd'
            self.engine.write_text(f'@echo off\n"{sys.executable}" "{self.spy}" %*\n', encoding="utf-8")
        else:
            self.engine = self.case / 'rsrs-spy'
            self.engine.write_text(f'#!{sys.executable}\n' + self.spy.read_text(encoding="utf-8"), encoding="utf-8")
        self.engine.chmod(0o700)
        self.config = self.case / 'config.json'
        self.config.write_text(json.dumps({'rsrs': str(self.engine), 'session_rules': True}), encoding="utf-8")
        self.launcher = self.case / 'launcher.py'
        self.launcher.write_text(LAUNCHER, encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items()
                    if k.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'PATHEXT', 'TEMP', 'TMP', 'COMSPEC'}}
        self.env.update(RESPITE_CONFIG=str(self.config), RESPITE_LOG=str(self.log),
                        HOME=str(self.case / 'home'), USERPROFILE=str(self.case / 'home'),
                        XDG_CONFIG_HOME=str(self.case / 'config'),
                        XDG_DATA_HOME=str(self.case / 'data'),
                        XDG_CACHE_HOME=str(self.case / 'cache'),
                        RESPITE_NUDGE_STATE=str(self.case / 'nudge'),
                        RESPITE_DATA=str(self.case / 'plugin-data'),
                        RESPITE_TURN_STATE=str(self.case / 'turn-state'),
                        DIMCODE_PLUGIN_DATA=str(self.case / 'plugin-data'),
                        TEST_ENGINE=str(self.engine), TEST_CALLS=str(self.calls),
                        TEST_DENIED=str(self.denied), TEST_HOOK=str(ROOT / 'hooks/respire.py'),
                        PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')

    def call(self, prompt='', event='UserPromptSubmit', mode='ok', active=False, every=1,
             session='s1', fast=False, extra_env=None, list_mode=None):
        self.config.write_text(json.dumps({'rsrs':str(self.engine), 'session_rules':True,
                                          'store_nudge_every':every}), encoding="utf-8")
        if event == 'Stop':
            args_seq = []   # review 6: Stop does not query the engine at all (zero-call sequence)
        elif event == 'SessionStart':
            args_seq = [['status','--json']]
        elif event == 'StoreReceipt':
            content = prompt.replace('：',':',1).split(':',1)[1].strip()
            argv = ['remember',content,'--title',content,'--importance','important','--json']
            if mode in ('ok','show_fail','show_mismatch','show_wrongid','show_tail','show_badarr','show_badstr','show_numcontent','show_noentryid'):
                args_seq = [argv, ['show','dddddddddddddddd','--json']]
            elif mode == 'warn':
                args_seq = [argv, ['show','eeeeeeeeeeeeeeee','--json']]
            elif mode in ('silent','ok_noid','ok_junkid','bad_summary','ok_numid','ok_dashid'):   # unknown receipt -> read-only list verification
                args_seq = [argv, ['list','--limit','3','--json']]
            else:                     # pending / hang / skip_status / slow_garbage: no further engine call
                args_seq = [argv]
        elif re.match(r'^(?:\u8bb0|\u5b58|\u8bb0\u5f55|\u8bb0\u4f4f|remember|store)\s*[:\uff1a]', prompt, re.I):
            args_seq = []
        else:
            args_seq = [['recall',prompt,'--limit','5','--titles','--json']]
        env = dict(self.env, TEST_EXPECTED_ARGV=json.dumps([[str(self.engine)] + a for a in args_seq]),
                   TEST_EVENT=event, STUB_MODE=mode)
        if fast:
            env['RESPITE_TEST_FAST'] = '1'
        if extra_env:
            env.update(extra_env)
        if list_mode is not None:
            env['STUB_LIST'] = list_mode
        payload = {'prompt':prompt,'hook_event_name':event,'stop_hook_active':active}
        if session is not None:
            payload['session_id'] = session
        result = subprocess.run([sys.executable, str(self.launcher)],
                                input=json.dumps(payload), text=True,
                                encoding='utf-8', capture_output=True, env=env,
                                cwd=self.case, timeout=40)
        self.assertFalse(self.denied.exists(), 'Isolation denied an external action')
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()] if self.calls.exists() else []

    def positive_control(self):
        before = len(self.recorded())
        output = self.call('rsrs envelope structure recall')
        self.assertEqual(len(self.recorded()), before + 1, 'Live spy must record normal input')
        self.assertEqual(self.recorded()[-1][0], 'recall')
        self.assertIn('auto-recall', output)
        self.assertIn('matched 1 item(s)', output)
        self.assertIn('[0.90] spy', output)
        return output

    def test_normal_input_requires_live_spy(self):
        output = self.positive_control()
        self.assertIn('[0.90] spy', output)

    def test_credential_has_zero_calls_and_no_disclosure(self):
        self.positive_control()
        before = self.recorded()
        output = self.call('api_key = ' + SECRET + ' store this')
        self.assertIn('contains a credential', output)
        self.assertEqual(self.recorded(), before)
        self.assertNotIn(SECRET, output)
        self.assertNotIn(SECRET, self.log.read_text(encoding="utf-8"))
        entries = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        skipped = [entry for entry in entries if entry['out'] == 'secret_skip']
        self.assertEqual(len(skipped), 1)
        self.assertNotIn('d', skipped[0])

    def test_store_prefix_credential_is_blocked(self):
        self.positive_control()
        before = self.recorded()
        output = self.call('\u8bb0\uff1a\u6570\u636e\u5e93\u5bc6\u7801 = hunter2u')
        self.assertIn('contains a credential', output)
        self.assertEqual(self.recorded(), before)
        self.assertNotIn('hunter2u', output + self.log.read_text(encoding="utf-8"))

    def test_dead_spy_must_fail_positive_control(self):
        # A valid executable that does not record/return JSON must never count as
        # proof of a zero-call guard. This explicitly exercises that failure.
        if os.name == 'nt':
            self.spy.write_text('import sys\nsys.exit(7)\n', encoding="utf-8")
        else:
            self.engine.write_text(f'#!{sys.executable}\nimport sys\nsys.exit(7)\n', encoding="utf-8")
        with self.assertRaisesRegex(AssertionError, 'Live spy must record normal input'):
            self.positive_control()

    def test_session_uses_only_stub_status(self):
        out = self.call(event='SessionStart')
        self.assertIn('respire memory discipline', out)
        self.assertNotIn('not signed in', out)
        self.assertEqual([args[0] for args in self.recorded()], ['status'])

    def test_explicit_store_prefix_hands_off_without_writes(self):
        for prefix in ('store:', 'remember:', '\u8bb0\uff1a', '\u5b58\uff1a', '\u8bb0\u5f55\uff1a', '\u8bb0\u4f4f\uff1a'):
            out = self.call(prefix + ' durable fixture fact')
            self.assertIn('store pending', out)
            self.assertIn('Nothing was written', out)
            self.assertIn('rsrs prompt', out)
            self.assertIn('rsrs show <id> --json', out)
            self.assertIn('update > merge > attach > new', out)
            self.assertIn('DO NOT retry automatically or claim success', out)
            self.assertIn('read-only, paused', out.lower())
            self.assertIn('ONLY AFTER reading the full body', out)
            self.assertIn('DO NOT guess', out)
            self.assertIn('downgrade', out)
            self.assertIn('DO NOT execute engineering tasks', out)
        self.assertEqual(self.recorded(), [])

        import runpy
        from types import SimpleNamespace
        from unittest.mock import patch
        hook = runpy.run_path(str(ROOT / "hooks" / "respire.py"))
        guard = hook["on_pre_tool_use"]
        parent = "12345678-1234-1234-1234-123456789012"
        tool = "exec" if "exec" in hook["SHELL_TOOLS"] else "Bash"
        def check(command):
            return guard({"tool_name": tool, "tool_input": {"command": command}})
        blocked = [
            "rsrs remember body --importance important",
            "rsrs remember 'body --parent " + parent + "' --importance important",
            "rsrs remember body --importance important --parent ''",
            "rsrs remember body --importance important --parent missing",
            "rsrs remember body --force",
            "echo ok && rsrs remember body --importance important",
            "rsrs remember body --importance important --parent " + parent + "; rsrs remember bad --force",
            "bash -c 'rsrs remember body --importance important'",
            "env X=1 rsrs remember body --importance important",
            "rsrs remember body --importance important --parent $PARENT",
            "rsrs update id --parent ''",
            "rsrs update id --clear-parent",
            ">out.log rsrs remember body --importance important --force",
            "echo $(rsrs remember body --importance important --force)",
            'echo "$(rsrs remember body --importance important --force)"',
            "echo `rsrs remember body --importance important --force`",
            "npx rsrs remember body --importance important --force",
            "rsrs --model-task-id fixture remember body --importance important",
            "rsrs --progress-id=fixture remember body --force",
            "rsrs --unknown fixture remember body --force",
            "r'srs' --unknown fixture remember body --force",
            "env -- rsrs --model-task-id fixture remember body --importance important",
            "command -- rsrs --progress-id fixture remember body --force",
            "rsrs attach id ''",
        ]
        with patch.dict(guard.__globals__, load_config=lambda: {}, find_rsrs=lambda cfg: "fixture"):
            for command in blocked:
                with self.subTest(command=command):
                    result = check(command)
                    self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
                    self.assertNotIn(command, json.dumps(result))
            for command in ("echo 'rsrs remember body --force'", "rsrs show remember",
                            "rsrs recall 'remember --force'", "rsrs recall remember --titles --json",
                            "echo '$(rsrs remember body --force)'", "echo rsrs remember > out.log",
                            "npx rsrs recall remember --titles --json",
                            "echo $(rsrs recall remember --titles --json)",
                            "echo `date` rsrs remember",
                            "rsrs update id --content 'body --parent fake'",
                            "rsrs remember 'body --force --parent fake'", "printf ok"):
                with self.subTest(command=command):
                    self.assertEqual(check(command), "")
            result = SimpleNamespace(returncode=0, stdout=json.dumps({
                "status": "ok", "summary": {"id": parent}, "details": {"entry": {"id": parent}}}))
            with patch.dict(guard.__globals__, run_rsrs=lambda *args: result):
                self.assertEqual(check("rsrs remember body --importance important --parent " + parent), "")
                self.assertEqual(guard({"tool_name": "mcp__respire__memory_remember",
                                       "tool_input": {"content": "body", "importance": "important", "parent": parent}})
                                 ["hookSpecificOutput"]["permissionDecision"], "deny")
            with patch.dict(guard.__globals__, run_rsrs=lambda *args: result):
                self.assertEqual(check("rsrs --client-only --json --model-task-id fixture --progress-id=fixture remember body --importance important --parent " + parent
                                       + " --project demo --tags a,b --type context --summary summary --emotion -1"
                                       + " --source-refs '[]' --review-at 2026-12-01T00:00:00Z --artifact '{}'"), "")
            calls = []
            def read_only(engine, args, timeout):
                calls.append(args)
                return result
            with patch.dict(guard.__globals__, run_rsrs=read_only):
                self.assertEqual(check("rsrs remember body --importance important --parent " + parent), "")
            self.assertEqual(calls, [["--client-only", "show", parent, "--json"]])
            for bad in ("{}", '{"status":"ok","summary":{"id":"wrong"}}'):
                with patch.dict(guard.__globals__, run_rsrs=lambda *args: SimpleNamespace(returncode=0, stdout=bad)):
                    self.assertEqual(check("rsrs remember body --importance important --parent " + parent)
                                     ["hookSpecificOutput"]["permissionDecision"], "deny")
            def failed(*args):
                raise subprocess.TimeoutExpired("fixture", 1)
            with patch.dict(guard.__globals__, run_rsrs=failed):
                self.assertEqual(check("rsrs remember body --importance important --parent " + parent)
                                 ["hookSpecificOutput"]["permissionDecision"], "deny")
            for payload in ({"content": "body", "importance": "important"},
                            {"content": "body", "force": True}, {"parent": None},
                            {"content": "body", "merge_ids": parent, "importance": "important"}):
                self.assertEqual(guard({"tool_name": "memory_remember", "tool_input": payload})
                                 ["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(guard({"tool_name": "Read", "tool_input": {"command": "rsrs remember x --force"}}), "")

        import contextlib
        import io
        import runpy
        from unittest.mock import patch
        hook = runpy.run_path(str(ROOT / "hooks" / "respire.py"))
        tool = "exec" if "exec" in hook["SHELL_TOOLS"] else "Bash"
        payload = {"tool_name": tool, "tool_input": {"command": "rsrs remember synthetic-body --force"}}
        output = io.StringIO()
        def forbidden():
            raise AssertionError("unsafe write must not discover an engine")
        with patch.object(sys, "argv", ["respire.py", "PreToolUse"]), \
                patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                patch.dict(hook["main"].__globals__, load_config=forbidden), \
                contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit_context:
                hook["main"]()
        self.assertEqual(exit_context.exception.code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertNotIn("synthetic-body", output.getvalue())

    def test_store_warn_is_written_not_refused(self):
        # CLI contract: status=warn with a valid id means committed with warnings (e.g. unresolved parent) --
        # never report "not accepted" and never prompt a resend (duplicate-write risk)
        out = self.call('store: durable fixture fact', event='StoreReceipt', mode='warn')
        self.assertIn('Saved with warnings', out)
        self.assertIn('parent (cause) cannot be resolved', out)
        self.assertIn('retitle eeeeeeee', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'show'])

    def test_store_pending_relays_candidates_and_actions(self):
        # §7.2: pending keeps the candidates (with short ids) and the engine-suggested actions (update > merge > attach > store), never reduced to parent/force
        out = self.call('store: durable fixture fact', event='StoreReceipt', mode='pending')
        self.assertIn('store pending', out)
        self.assertIn('nothing was written', out)
        self.assertIn('[aaaabbbb]', out)
        self.assertIn('similarity=88% title=stub candidate', out)
        self.assertIn('merge or attach', out)
        self.assertIn('--merge-ids', out)
        self.assertIn('--force', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember'])

    def test_store_readback_states(self):
        # R11 post-write verification: verified / mismatch / unavailable are all reported honestly in the receipt
        self.assertIn('verified by read-back', self.call('store: durable fixture fact', event='StoreReceipt'))
        self.assertIn('DIFFERENT title/content',
                      self.call('store: durable fixture fact', event='StoreReceipt', mode='show_mismatch'))
        self.assertIn('Read-back unavailable',
                      self.call('store: durable fixture fact', event='StoreReceipt', mode='show_fail'))

    def test_store_unknown_receipt_never_demands_resend(self):
        # R10: bad receipt = unknown result -> read-only verification; never a definite failure, never prompt a resend
        out = self.call('store: durable fixture fact', event='StoreReceipt', mode='silent')
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertIn('rsrs list --limit 3', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'list'])

    def test_store_timeout_is_unknown_and_makes_no_further_calls(self):
# timeout = unknown result: the receipt allows read-only verification only and sends no further engine call (budget exhausted)
        before = self.recorded()
        out = self.call('store: durable fixture fact', event='StoreReceipt', mode='hang', fast=True)
        self.assertIn('store unknown', out)
        self.assertIn('timed out', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(len(self.recorded()) - len(before), 1)

    def test_stop_deny_and_reentry_zero_calls(self):
        out = json.loads(self.call(event='Stop'))
        self.assertEqual(out['decision'], 'block')
        self.assertIn('rsrs remember', out['reason'])
        before, count = self.recorded(), (self.case / 'nudge').read_text(encoding="utf-8")
        self.assertEqual(self.call(event='Stop', active=True), '')
        self.assertEqual(self.recorded(), before)
        self.assertEqual((self.case / 'nudge').read_text(encoding="utf-8"), count)

    def test_stop_every_third_request_and_disabled_zero_calls(self):
        for number in range(1, 7):
            self.call(f'ordinary input {number}')           # every turn is a new request: re-arm the completion budget
            raw = self.call(event='Stop', every=3)
            if number in (3, 6):
                self.assertEqual(json.loads(raw)['decision'], 'block')
            else:
                self.assertEqual(raw, '')
        self.assertEqual([a[0] for a in self.recorded()].count('list'), 0)
        before = self.recorded()
        self.assertEqual(self.call(event='Stop', every=0), '')
        self.assertEqual(self.recorded(), before)
        self.assertEqual((self.case / 'nudge').read_text(encoding="utf-8"), '6')

    def test_prompt_registration_failure_invalidates_old_receipt(self):
# round four item 1: previous request already stored -> holding the lock makes the new registration fail -> release -> the new request's Stop must not suppress from the old record
        import importlib.util as iu, time as _t
        from pathlib import Path as P
        import os as _os
        spec = iu.spec_from_file_location('rh5', ROOT / 'hooks' / 'respire.py')
        mod = iu.module_from_spec(spec); spec.loader.exec_module(mod)
        import tempfile, shutil
        base = P(tempfile.mkdtemp(prefix='dimcode-r4-'))
        self.addCleanup(shutil.rmtree, base, True)
        old = _os.environ.get('RESPITE_TURN_STATE')
        _os.environ['RESPITE_TURN_STATE'] = str(base)
        try:
            sid = 'failreg'
            gen1 = mod.mark_prompt(sid)
            mod.mark_store(sid, gen1)
            self.assertFalse(mod.turn_stored(sid))
            lock = mod._map_lock(sid, wait_s=0.05)
            self.assertIsNotNone(lock)
            try:
                gen2 = mod.mark_prompt(sid)    # marker blind write succeeded; the state update fails on the lock
                self.assertFalse(mod.turn_stored(sid))   # the old receipt has been invalidated by the marker
            finally:
                mod._release_lock(lock)
            self.assertFalse(mod.turn_stored(sid))
            mod.mark_store(sid, gen2)
            self.assertFalse(mod.turn_stored(sid))   # registration once failed: conservative invalidation (bias to nudging)
            gen3 = mod.mark_prompt(sid)               # recovery path: normal registration and write
            mod.mark_store(sid, gen3)
            self.assertFalse(mod.turn_stored(sid))
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old
            else:
                _os.environ.pop('RESPITE_TURN_STATE', None)

    def test_common_write_failure_poisons_old_receipt(self):
# round five residual (review-flagged order): an old successful receipt -> mark_prompt called while all three writes fail
# -> write capability returns but mark_prompt is not called and POISON is not hand-written -> the current request's Stop does not suppress
# -> normal registration recovers. Key: invalidation relies on _invalidate_state's unlink (needs no disk space).
        import importlib.util as iu, tempfile, shutil
        from pathlib import Path as P
        import os as _os
        spec = iu.spec_from_file_location('rh7', ROOT / 'hooks' / 'respire.py')
        mod = iu.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P(tempfile.mkdtemp(prefix='dimcode-r5b-'))
        self.addCleanup(shutil.rmtree, base, True)
        old = _os.environ.get('RESPITE_TURN_STATE')
        _os.environ['RESPITE_TURN_STATE'] = str(base)
        try:
            sid = 'poison'
            gen1 = mod.mark_prompt(sid)
            mod.mark_store(sid, gen1)
            self.assertFalse(mod.turn_stored(sid))
            state_p = P(mod._map_path(sid))
            self.assertTrue(state_p.exists())
            orig_w, orig_u = mod._write_gen_marker, mod._map_update
            mod._write_gen_marker = lambda s2, g2: False   # marker and POISON both fail
            mod._map_update = lambda s2, p2: False         # state fails
            mod.mark_prompt(sid)                           # real call: unlink deletes the old state
            mod._write_gen_marker = orig_w                 # write capability restored
            mod._map_update = orig_u
# no mark_prompt, no hand-written POISON -- the current request's Stop:
            self.assertFalse(state_p.exists())             # the old state has been physically deleted
            self.assertFalse(mod.turn_stored(sid))         # does not suppress from the old record
            gen3 = mod.mark_prompt(sid)                    # recovery path
            mod.mark_store(sid, gen3)
            self.assertFalse(mod.turn_stored(sid))
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old
            else:
                _os.environ.pop('RESPITE_TURN_STATE', None)
    def test_common_write_failure_poisons_old_receipt(self):
# round five: an old valid receipt of the same generation -> all writes fail (the old file stays readable) -> degrade/recover -> no suppression; normal registration recovers
        import importlib.util as iu, tempfile, shutil
        from pathlib import Path as P
        import os as _os
        spec = iu.spec_from_file_location('rh7', ROOT / 'hooks' / 'respire.py')
        mod = iu.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P(tempfile.mkdtemp(prefix='dimcode-r5-'))
        self.addCleanup(shutil.rmtree, base, True)
        old = _os.environ.get('RESPITE_TURN_STATE')
        _os.environ['RESPITE_TURN_STATE'] = str(base)
        try:
            sid = 'poison'
            gen1 = mod.mark_prompt(sid)
            mod.mark_store(sid, gen1)
            self.assertFalse(mod.turn_stored(sid))
            orig_w, orig_u = mod._write_gen_marker, mod._map_update
            mod._write_gen_marker = lambda s2, g2: False    # all writes fail: marker False
            mod._map_update = lambda s2, p2: False           # state False; the degraded write fails too
            mod.mark_prompt(sid)                             # the old file stays readable and equal
            mod._write_gen_marker = orig_w                   # degraded write recovers (writes POISON)
            self.assertTrue(mod._poison_marker(sid))
            self.assertFalse(mod.turn_stored(sid))            # POISON: every finite receipt is invalid
            mod._map_update = orig_u
            gen3 = mod.mark_prompt(sid)                      # fully recovered
            mod.mark_store(sid, gen3)
            self.assertFalse(mod.turn_stored(sid))            # suppression recovered
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old
            else:
                _os.environ.pop('RESPITE_TURN_STATE', None)

    def test_lock_ownership_no_steal_no_wrong_release(self):
# round four item 2: no age-based preemption (a second process gives up past the window while the holder is alive); token-checked release
        import importlib.util as iu
        from pathlib import Path as P
        import os as _os, tempfile, shutil
        spec = iu.spec_from_file_location('rh6', ROOT / 'hooks' / 'respire.py')
        mod = iu.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P(tempfile.mkdtemp(prefix='dimcode-l4-'))
        self.addCleanup(shutil.rmtree, base, True)
        old = _os.environ.get('RESPITE_TURN_STATE')
        _os.environ['RESPITE_TURN_STATE'] = str(base)
        try:
            sid = 'locks'
            first = mod._map_lock(sid, wait_s=0.05)
            self.assertIsNotNone(first)
            self.assertIsNone(mod._map_lock(sid, wait_s=0.05))   # wait window exceeded, give up without preempting
            self.assertIsNone(mod._map_lock(sid, wait_s=0.05))
            lp = P(first[0])
            lp.write_text('other-holder-token', encoding='utf-8')
            mod._release_lock(first)       # token mismatch: do not delete a later holder's lock
            self.assertTrue(lp.exists())
            lp.write_text(first[1], encoding='utf-8')
            mod._release_lock(first)
            self.assertFalse(lp.exists())
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old
            else:
                _os.environ.pop('RESPITE_TURN_STATE', None)

    def test_stale_request_receipt_and_rmw_lock(self):
# round three item 1: same session R1 write pauses -> R2 prompt -> R1 completes -- R1's old-gen receipt must not suppress R2
        import importlib.util as iu, time as _t, json as j
        from pathlib import Path as P
        import os as _os
        spec = iu.spec_from_file_location('rh3', P(self.env['TEST_HOOK']))
        mod = iu.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P(self.env['RESPITE_TURN_STATE'])
        old = _os.environ.get('RESPITE_TURN_STATE')
        try:
            _os.environ['RESPITE_TURN_STATE'] = str(base)
            base.mkdir(parents=True, exist_ok=True)
            sid = 'genbind'
            gen1 = mod.mark_prompt(sid)
            gen2 = mod.mark_prompt(sid)
            self.assertGreater(gen2, gen1)
            mod.mark_store(sid, gen1)
            self.assertFalse(mod.turn_stored(sid))      # R1's old-generation receipt does not suppress R2
            mod.mark_store(sid, gen2)
            self.assertFalse(mod.turn_stored(sid))       # R2's current-generation receipt suppresses
# (2) transaction lock: holding a fresh lock -> _map_update conservatively abandons; usable after unlock
            lock = mod._map_lock(sid, wait_s=0.05)
            self.assertIsNotNone(lock)
            self.assertFalse(mod._map_update(sid, {'store_ts': _t.time(), 'store_req_ts': gen2}))
            mod._release_lock(lock)
            self.assertTrue(mod._map_update(sid, {'store_ts': _t.time(), 'store_req_ts': gen2}))
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old

    def test_strict_envelope_id_and_schema(self):
# round three item 2: numeric id 12345678 and "a-------" (loose hex-hyphen) -> unknown, not Saved
        for mode_key, stub_mode in (('numid', 'ok_numid'), ('dashid', 'ok_dashid')):
            out = self.call('store: strict fact', event='StoreReceipt', mode=stub_mode)
            self.assertIn('store unknown', out, mode_key)
            self.assertNotIn('Saved', out, mode_key)
            self.assertIn('Do NOT resend', out, mode_key)
        # Read-back three-way id identity plus native strings: summary ok but entry.id wrong/missing -> mismatch
        out = self.call('store: strict fact ok', event='StoreReceipt', mode='show_wrongid')
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)
        out = self.call('store: strict fact num', event='StoreReceipt', mode='show_numcontent')
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)

    def test_stop_never_queries_engine(self):
# review fix: Stop no longer queries the engine at all -- the unattributable whole-store time suppression is gone and there is no list-failure continuation path
        for mode in ('ok', 'recent', 'failed', 'malformed'):
            self.call(f'request before stop {mode}')
            self.assertEqual(json.loads(self.call(event='Stop', mode=mode))['decision'], 'block', mode)
        self.assertEqual([a[0] for a in self.recorded()].count('list'), 0)

    def test_latch_is_per_session_and_permanent_until_new_prompt(self):
        self.call('session A first request', session='A')
        self.assertEqual(json.loads(self.call(event='Stop', session='A'))['decision'], 'block')
        self.call('session B unrelated request', session='B')
        self.assertEqual(json.loads(self.call(event='Stop', session='B'))['decision'], 'block')
        self.assertEqual(self.call(event='Stop', session='A'), '')   # A's lock is not consumed by B
        self.call('session A second request', session='A')
        self.assertEqual(json.loads(self.call(event='Stop', session='A'))['decision'], 'block')

    def test_receipt_edge_cases_are_unknown_not_failed(self):
        for mode in ('ok_noid', 'ok_junkid', 'bad_summary'):
            out = self.call('store: edge fact', event='StoreReceipt', mode=mode)
            self.assertIn('store unknown', out, mode)
            self.assertIn('Do NOT resend', out, mode)
            self.assertNotIn('did not accept', out, mode)
            self.assertNotIn('Saved', out, mode)
        out = self.call('store: edge fact', event='StoreReceipt', mode='skip_status')
        self.assertIn('not stored', out)
        self.assertIn('never force a write', out)
        self.assertNotIn('did not accept', out)

    def test_readback_full_verification(self):
        out = self.call('store: full verify fact', event='StoreReceipt', mode='show_wrongid')
        self.assertIn('Saved:', out)
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)
        out = self.call('store: full verify fact tail', event='StoreReceipt', mode='show_tail')
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)
        out = self.call('store: full verify fact ok', event='StoreReceipt')
        self.assertIn('verified by read-back', out)

    def test_slow_bad_receipt_respects_shared_budget(self):
        before = self.recorded()
        out = self.call('store: slow garbage fact', event='StoreReceipt', mode='slow_garbage',
                        extra_env={'RESPITE_HOOK_BUDGET_S': '4'})
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(len(self.recorded()) - len(before), 1)

    def test_verify_list_schema_failures_are_not_attribution(self):
        for mode in ('list_schema', 'list_notimes'):
            out = self.call('store: schema fact', event='StoreReceipt', mode='silent', list_mode=mode)
            self.assertIn('store unknown', out, mode)
            self.assertNotIn('may already be written', out, mode)
    def test_stop_after_hook_store_does_not_query_engine(self):
        self.call('store: durable fixture fact', event='StoreReceipt')
        before = self.recorded()
        self.assertTrue(json.loads(self.call(event='Stop'))['decision'] == 'block')   # review 6: still nudges
        self.assertEqual(self.recorded(), before)   # zero engine queries

    def test_turn_receipt_suppression_is_request_scoped(self):
        # Review 6: disk-receipt suppression is cancelled -- Stop never suppresses from an old record; a second Stop for the same request is released by the latch
        self.call('store: durable fixture fact', event='StoreReceipt')
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')  # still nudges
        self.assertEqual(self.call(event='Stop', active=True), '')                  # latch: once per request
        self.call('another ordinary input without storing')
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')

    def test_stop_once_per_request_latch(self):
# DM-04: when the host sends no stop_hook_active the same request still nudges at most once; a new request re-arms
        self.call('ordinary input')
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')
        before = self.recorded()
        self.assertEqual(self.call(event='Stop'), '')
        self.assertEqual(self.recorded(), before)
        self.call('fresh request after wrap-up')
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')

    def test_receipt_suppression_is_session_scoped(self):
        # Session isolation: a write receipt in session A does not suppress the nudge for session B
        self.call('store: durable fixture fact', event='StoreReceipt', session='a')
        self.assertEqual(json.loads(self.call(event='Stop', session='b'))['decision'], 'block')

    def test_malformed_spy_cannot_pass_positive_control(self):
        self.positive_control()
        self.assertEqual(self.call('ordinary input', mode='malformed'), '')
        self.assertIn('parse_error', self.log.read_text(encoding="utf-8"))

    def test_readback_bad_details_keeps_saved_receipt(self):
# round two #2: show read-back details that are not a dict (array/string) -> unavailable;
# a type error must never tear down the whole written receipt (losing Saved = treating committed data as unwritten)
        for mode in ('show_badarr', 'show_badstr'):
            before = self.recorded()
            out = self.call('store: durable fixture fact', event='StoreReceipt', mode=mode)
            self.assertIn('Saved:', out, mode)
            self.assertIn('Read-back unavailable', out, mode)
            self.assertNotIn('verified by read-back', out, mode)
            self.assertEqual([a[0] for a in self.recorded()[len(before):]], ['remember', 'show'], mode)

    def test_remember_timeout_is_capped_by_remaining_budget(self):
# round two #3: remember timeout = min(STORE_T, remaining budget) (shared monotonic deadline) --
# a tight budget (3s budget -> only 0.5s left on entry) must not wait the full STORE_T=18s window (pinned by an elapsed upper bound)
        before = self.recorded()
        started = time.monotonic()
        out = self.call('store: tight budget fact', event='StoreReceipt', mode='hang',
                        extra_env={'RESPITE_HOOK_BUDGET_S': '3'})
        elapsed = time.monotonic() - started
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(len(self.recorded()) - len(before), 1)
        self.assertLess(elapsed, 15, f'remember waited {elapsed:.1f}s - not capped by remaining budget')

    def test_exhausted_budget_skips_remember_entirely(self):
# round two #3: remaining budget <=0 on entry -> even remember is skipped (zero engine calls) and it goes straight to unknown
        before = self.recorded()
        out = self.call('store: budget gone fact', event='StoreReceipt', extra_env={'RESPITE_HOOK_BUDGET_S': '2'})
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(self.recorded(), before)


class TurnStateIsolation(unittest.TestCase):
# round two main item: receipt state is a per-session file st_<sidkey>.json.
# A shared turn_map's cross-process read-modify-write (B reads a stale snapshot -> A updates -> B writes everything back)
# rolls A's new request receipt back to an old value -- one successful atomic rename guarantees a complete write, not a transaction.

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dimcode-turnstate-')
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self._saved = os.environ.get('RESPITE_TURN_STATE')
        os.environ['RESPITE_TURN_STATE'] = str(self.dir)
        self.addCleanup(self._restore_env)
        spec = importlib.util.spec_from_file_location('respire_hook', ROOT / 'hooks' / 'respire.py')
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)

    def _restore_env(self):
        if self._saved is None:
            os.environ.pop('RESPITE_TURN_STATE', None)
        else:
            os.environ['RESPITE_TURN_STATE'] = self._saved

    def _a_file(self):
        return self.dir / ('st_' + self.hook._sid_key('sessA') + '.json')

    def _seed(self, session, prompt_ago=10.0, store_ago=5.0):
# seed receipt timestamps explicitly (past offsets relative to now, prompt before store): independent of the real clock granularity,
# "real mark_prompt time > seeded store_ts" always holds on any platform and tick
        now = time.time()
        self.assertTrue(self.hook._map_update(
            session, {'prompt_ts': now - prompt_ago, 'store_ts': now - store_ago,
                      'store_req_ts': now - prompt_ago}))   # same-generation receipt (round three item 1 semantics)
        self.assertTrue(self.hook._write_gen_marker(session, now - prompt_ago))   # 4 item 1 truth chain: the marker is in sync

    def test_b_write_cannot_rollback_a_new_prompt(self):
# the review-flagged interleaving: A had old prompt_ts/store_ts -> B reads the stale snapshot -> A's new request updates -> B writes back.
# with a shared map B's full write-back would roll A back to the old values (the old store would look stored this turn and the store check would be skipped);
# with a per-session file A's new request state is preserved as-is -- the old store does not suppress.
        h = self.hook
        self._seed('sessA')                         # old turn's receipt: store_ts=now-5
        self.assertFalse(h.turn_stored('sessA'))
        h.mark_prompt('sessA')                      # A's new real request (= the A-update after B read the stale snapshot)
        self.assertFalse(h.turn_stored('sessA'))
        snapshot = self._a_file().read_bytes()
        h.mark_prompt('sessB')                      # B-write: resume, update its own entry and write back
        h.mark_store('sessB')
        h.mark_prompt('sessB')
        h.mark_store('sessB')
        self.assertEqual(self._a_file().read_bytes(), snapshot,
                         'B session write rewrote A state (cross-process RMW rollback)')
        self.assertFalse(h.turn_stored('sessA'),
                         'A rolled back to the old prompt/store pair - stale store would suppress Stop')
        names = sorted(p.name for p in self.dir.iterdir())
        self.assertNotIn('turn_map.json', names)
# exactly one state file per session (the .gen marker and .lock are companion runtime files and not counted)
        self.assertEqual(len([n for n in names if n.startswith('st_') and n.endswith('.json')]), 2)

    def test_a_fresh_receipt_survives_b_updates(self):
# reverse interleaving: A's just-written receipt is not erased by B's update (which would cause a redundant nudge)
        h = self.hook
        self._seed('sessA')
        snapshot = self._a_file().read_bytes()
        h.mark_prompt('sessB')
        h.mark_store('sessB')
        self.assertEqual(self._a_file().read_bytes(), snapshot)
        self.assertFalse(h.turn_stored('sessA'), 'A fresh receipt erased by B update')

    def test_new_prompt_after_store_no_longer_suppresses(self):
        h = self.hook
        self._seed('sessA')                         # old turn already stored -> suppresses
        self.assertFalse(h.turn_stored('sessA'))
        h.mark_prompt('sessA')                      # new real request: prompt_ts>store_ts -> the old receipt does not suppress
        self.assertFalse(h.turn_stored('sessA'))
        self._seed('sessA')                         # new turn: prompt first, store after -> suppresses again
        self.assertFalse(h.turn_stored('sessA'))
        h.mark_prompt('sessB')
        h.mark_store('sessB')
        self.assertFalse(h.turn_stored('sessA'), 'B update erased A fresh receipt')


def assert_versions(root):
    market=json.loads((root/'.claude-plugin/marketplace.json').read_text(encoding='utf-8'))
    entries=[entry for entry in market['plugins'] if entry['name']=='respire']
    manifest=json.loads((root/'.codex-plugin/plugin.json').read_text(encoding='utf-8'))
    hook=re.search(r'^VERSION = "([^"]+)"',(root/'hooks/respire.py').read_text(encoding='utf-8'),re.M).group(1)
    if len(entries)!=1 or hook!=manifest['version'] or ('version' in entries[0] and entries[0]['version']!=manifest['version']):
        raise ValueError('Plugin/hook/marketplace version mismatch')

class VersionConsistency(unittest.TestCase):
    def test_versions_match(self):
        assert_versions(ROOT)

    def test_each_mismatch_is_rejected(self):
        for component in ('marketplace','manifest','hook'):
            with self.subTest(component=component), tempfile.TemporaryDirectory(prefix='version-negative-') as directory:
                fixture=Path(directory)
                for name in ('.claude-plugin', '.codex-plugin', 'hooks'):
                    shutil.copytree(ROOT/name,fixture/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                if component=='hook':
                    path=fixture/'hooks/respire.py'
                    path.write_text(re.sub(r'^VERSION = "[^"]+"','VERSION = "999.0.0"',path.read_text(encoding='utf-8'),count=1,flags=re.M),encoding='utf-8')
                else:
                    path=fixture/('.claude-plugin/marketplace.json' if component=='marketplace' else '.codex-plugin/plugin.json')
                    doc=json.loads(path.read_text(encoding='utf-8'))
                    if component=='marketplace':
                        next(entry for entry in doc['plugins'] if entry['name']=='respire')['version']='999.0.0'
                    else:doc['version']='999.0.0'
                    path.write_text(json.dumps(doc),encoding='utf-8')
                with self.assertRaises(ValueError):assert_versions(fixture)


class ProcessAuditPolicy(unittest.TestCase):
    def test_windows_none_executable_and_exact_commandline_are_allowed(self):
        expected = [r'C:\temp\space name\rsrs-spy.cmd', 'recall', 'ordinary input', '--json']
        self.assertTrue(allowed_process(None, subprocess.list2cmdline(expected), expected, True))

    def test_posix_exact_executable_and_complete_argv_are_allowed(self):
        expected = ['/tmp/rsrs-spy', 'recall', 'ordinary input', '--json']
        self.assertTrue(allowed_process(expected[0], expected, expected, False))

    def test_other_programs_arguments_and_shell_additions_are_rejected(self):
        expected = [r'C:\temp\space name\rsrs-spy.cmd', 'recall', 'ordinary input', '--json']
        encoded = subprocess.list2cmdline(expected)
        for executable, argv, windows in (
                ('cmd.exe', encoded, True),
                ('python.exe', encoded, True),
                (None, encoded + ' & echo unwanted', True),
                (None, encoded + ' extra', True),
                (None, 'cmd.exe /c ' + encoded, True),
                (None, encoded.replace('rsrs-spy.cmd', 'rsrs-spy.cmd-other'), True),
                (None, encoded, False),
                (expected[0], expected + ['extra'], False),
        ):
            with self.subTest(executable=executable, argv=argv):
                self.assertFalse(allowed_process(executable, argv, expected, windows))


if __name__ == '__main__':
    unittest.main(verbosity=2)
