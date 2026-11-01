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
assert isinstance(expected_argv, list) and expected_argv
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
    # 先把继承的 stdout/stderr 写端转投 devnull、CWD 挪出测试临时目录再挂起：
    # Windows 下引擎是 .cmd 壳，run() 超时 kill 的只是壳——孙进程攥着管道会让
    # communicate 阻塞到 sleep 自然结束（超时形同虚设），攥着 CWD 会让用例清理
    # PermissionError。写端一关 EOF 立即到达（TimeoutExpired 按时抛出），CWD 一挪
    # 孤儿进程不再锁任何测试产物。
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
            args_seq = [['list','--limit','3','--json']]
        elif event == 'SessionStart':
            args_seq = [['status','--json']]
        elif prompt.startswith(('记：','store:')):
            content = prompt.replace('：',':',1).split(':',1)[1].strip()
            argv = ['remember',content,'--title',content,'--importance','important','--json']
            if mode in ('ok','show_fail','show_mismatch','show_wrongid','show_tail','show_badarr','show_badstr','show_numcontent','show_noentryid'):
                args_seq = [argv, ['show','dddddddddddddddd','--json']]
            elif mode == 'warn':
                args_seq = [argv, ['show','eeeeeeeeeeeeeeee','--json']]
            elif mode in ('silent','ok_noid','ok_junkid','bad_summary','ok_numid','ok_dashid'):  # 未知回执 → 只读核实 list
                args_seq = [argv, ['list','--limit','3','--json']]
            else:                    # pending / hang / skip_status / slow_garbage：不再有后续引擎调用
                args_seq = [argv]
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
        output = self.call('记：数据库密码 = hunter2u')
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
        self.assertIn('respire memory layer', out)
        self.assertNotIn('not signed in', out)
        self.assertEqual([args[0] for args in self.recorded()], ['status'])

    def test_explicit_store_receipt_comes_from_stub(self):
        out = self.call('store: durable fixture fact')
        self.assertIn('respire · stored', out)
        self.assertIn('retitle dddddddd', out)
        self.assertIn('verified by read-back', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'show'])

    def test_store_warn_is_written_not_refused(self):
        # CLI 契约：status=warn + 有效 id = 已提交但有警告（parent 未解析等）——
        # 不得误报「未接受」，更不得引导重发（重复写风险）
        out = self.call('store: durable fixture fact', mode='warn')
        self.assertIn('Saved with warnings', out)
        self.assertIn('parent (cause) cannot be resolved', out)
        self.assertIn('retitle eeeeeeee', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'show'])

    def test_store_pending_relays_candidates_and_actions(self):
        # §7.2：pending 保留候选（含短 id）与引擎建议动作（改＞并＞挂＞存），不得缩成 parent/force 两项
        out = self.call('store: durable fixture fact', mode='pending')
        self.assertIn('store pending', out)
        self.assertIn('nothing was written', out)
        self.assertIn('[aaaabbbb]', out)
        self.assertIn('similarity=88% title=stub candidate', out)
        self.assertIn('merge or attach', out)
        self.assertIn('--merge-ids', out)
        self.assertIn('--force', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember'])

    def test_store_readback_states(self):
        # R11 写后核验：verified / mismatch / unavailable 三态都如实进回执
        self.assertIn('verified by read-back', self.call('store: durable fixture fact'))
        self.assertIn('DIFFERENT title/content',
                      self.call('store: durable fixture fact', mode='show_mismatch'))
        self.assertIn('Read-back unavailable',
                      self.call('store: durable fixture fact', mode='show_fail'))

    def test_store_unknown_receipt_never_demands_resend(self):
        # R10：坏回执 = 结果未知 → 只读核实；绝不当确定失败、绝不引导重发 remember
        out = self.call('store: durable fixture fact', mode='silent')
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertIn('rsrs list --limit 3', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'list'])

    def test_store_timeout_is_unknown_and_makes_no_further_calls(self):
        # 超时 = 结果未知：回执只允许只读核实指引，不再发引擎调用（预算已耗尽）
        before = self.recorded()
        out = self.call('store: durable fixture fact', mode='hang', fast=True)
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
            self.call(f'ordinary input {number}')          # 每轮都是新请求：重新武装收尾预算
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
        # 第四轮①：旧请求已存→持锁令新登记失败→释放→新请求 Stop 不凭旧记录免催
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
            self.assertTrue(mod.turn_stored(sid))
            lock = mod._map_lock(sid, wait_s=0.05)
            self.assertIsNotNone(lock)
            try:
                gen2 = mod.mark_prompt(sid)   # 标记盲写成功；状态更新因锁失败
                self.assertFalse(mod.turn_stored(sid))  # 旧凭证已被标记失效
            finally:
                mod._release_lock(lock)
            self.assertFalse(mod.turn_stored(sid))
            mod.mark_store(sid, gen2)
            self.assertFalse(mod.turn_stored(sid))  # 登记曾失败：保守失效（多催方向）
            gen3 = mod.mark_prompt(sid)              # 恢复路径：正常登记+写入
            mod.mark_store(sid, gen3)
            self.assertTrue(mod.turn_stored(sid))
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old
            else:
                _os.environ.pop('RESPITE_TURN_STATE', None)

    def test_common_write_failure_poisons_old_receipt(self):
        # 第五轮：旧同代凭证 → 新 gen/状态写入均失败 → 降级 → 不免催；正常登记恢复
        import importlib.util as iu, tempfile as tf, shutil as sh
        from pathlib import Path as P
        import os as _os
        spec = iu.spec_from_file_location('rh7', ROOT / 'hooks' / 'respire.py')
        mod = iu.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P(tf.mkdtemp(prefix='dimcode-r5-'))
        self.addCleanup(sh.rmtree, base, True)
        old = _os.environ.get('RESPITE_TURN_STATE')
        _os.environ['RESPITE_TURN_STATE'] = str(base)
        try:
            sid = 'poison'
            gen1 = mod.mark_prompt(sid)
            mod.mark_store(sid, gen1)
            self.assertTrue(mod.turn_stored(sid))
            orig_w, orig_u = mod._write_gen_marker, mod._map_update
            mod._write_gen_marker = lambda s2, g2: False   # 共同写失败
            mod._map_update = lambda s2, p2: False
            mod._write_gen_marker = orig_w                 # 降级写恢复
            mod._map_update = lambda s2, p2: False          # 状态持续失败
            gen2 = mod.mark_prompt(sid)                     # 标记写成功（新代），状态失败
            self.assertFalse(mod.turn_stored(sid))          # 旧凭证 != 新标记 → 不免催
            mod._map_update = orig_u
            gen3 = mod.mark_prompt(sid)
            mod.mark_store(sid, gen3)
            self.assertTrue(mod.turn_stored(sid))           # 正常恢复
            self.assertTrue(mod._poison_marker(sid))
            self.assertFalse(mod.turn_stored(sid))          # POISON：任何有限凭证失效
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old
            else:
                _os.environ.pop('RESPITE_TURN_STATE', None)

    def test_common_write_failure_poisons_old_receipt(self):
        # 第五轮：旧同代成功凭证→共同写失败（旧文件保持可读）→降级/恢复→不免催；正常登记恢复
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
            self.assertTrue(mod.turn_stored(sid))
            orig_w, orig_u = mod._write_gen_marker, mod._map_update
            mod._write_gen_marker = lambda s2, g2: False   # 共同写失败：标记 False
            mod._map_update = lambda s2, p2: False          # 状态 False；降级也失败
            mod.mark_prompt(sid)                            # 旧文件保持相等可读
            mod._write_gen_marker = orig_w                  # 降级写恢复（写 POISON）
            self.assertTrue(mod._poison_marker(sid))
            self.assertFalse(mod.turn_stored(sid))           # POISON：任何有限凭证失效
            mod._map_update = orig_u
            gen3 = mod.mark_prompt(sid)                     # 完全恢复
            mod.mark_store(sid, gen3)
            self.assertTrue(mod.turn_stored(sid))           # 免催恢复
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old
            else:
                _os.environ.pop('RESPITE_TURN_STATE', None)

    def test_lock_ownership_no_steal_no_wrong_release(self):
        # 第四轮②：无年龄抢占（活持有者期间第二进程超窗放弃）；token 校验释放
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
            self.assertIsNone(mod._map_lock(sid, wait_s=0.05))  # 等待超窗放弃，不抢
            self.assertIsNone(mod._map_lock(sid, wait_s=0.05))
            lp = P(first[0])
            lp.write_text('other-holder-token', encoding='utf-8')
            mod._release_lock(first)      # token 不匹配：不删后继的锁
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
        # 第三轮①：同会话 R1 写暂停→R2 prompt→R1 完成——旧 gen 凭证不免催 R2
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
            self.assertFalse(mod.turn_stored(sid))     # R1 旧代凭证不免催 R2
            mod.mark_store(sid, gen2)
            self.assertTrue(mod.turn_stored(sid))      # R2 当前代凭证免催
            # ② 事务锁：持新鲜锁 → _map_update 保守放弃；解锁后可用
            lock = mod._map_lock(sid, wait_s=0.05)
            self.assertIsNotNone(lock)
            self.assertFalse(mod._map_update(sid, {'store_ts': _t.time(), 'store_req_ts': gen2}))
            mod._release_lock(lock)
            self.assertTrue(mod._map_update(sid, {'store_ts': _t.time(), 'store_req_ts': gen2}))
        finally:
            if old is not None:
                _os.environ['RESPITE_TURN_STATE'] = old

    def test_strict_envelope_id_and_schema(self):
        # 第三轮②：数字 id 12345678、"a-------"（宽松 hex-连字符）→ unknown 不 Saved
        for mode_key, stub_mode in (('numid', 'ok_numid'), ('dashid', 'ok_dashid')):
            out = self.call('store: strict fact', mode=stub_mode)
            self.assertIn('store unknown', out, mode_key)
            self.assertNotIn('Saved', out, mode_key)
            self.assertIn('Do NOT resend', out, mode_key)
        # 回读三方 id 一致 + 原生字符串：summary 对但 entry.id 错/缺 → mismatch
        out = self.call('store: strict fact ok', mode='show_wrongid')
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)
        out = self.call('store: strict fact num', mode='show_numcontent')
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)

    def test_stop_never_queries_engine(self):
        # 复核整改：Stop 完全不再查询引擎——无归属的全库时间抑制已移除，也没有查库失败强迫续跑路径
        for mode in ('ok', 'recent', 'failed', 'malformed'):
            self.call(f'request before stop {mode}')
            self.assertEqual(json.loads(self.call(event='Stop', mode=mode))['decision'], 'block', mode)
        self.assertEqual([a[0] for a in self.recorded()].count('list'), 0)

    def test_latch_is_per_session_and_permanent_until_new_prompt(self):
        self.call('session A first request', session='A')
        self.assertEqual(json.loads(self.call(event='Stop', session='A'))['decision'], 'block')
        self.call('session B unrelated request', session='B')
        self.assertEqual(json.loads(self.call(event='Stop', session='B'))['decision'], 'block')
        self.assertEqual(self.call(event='Stop', session='A'), '')  # A 的锁不被 B 消耗
        self.call('session A second request', session='A')
        self.assertEqual(json.loads(self.call(event='Stop', session='A'))['decision'], 'block')

    def test_receipt_edge_cases_are_unknown_not_failed(self):
        for mode in ('ok_noid', 'ok_junkid', 'bad_summary'):
            out = self.call('store: edge fact', mode=mode)
            self.assertIn('store unknown', out, mode)
            self.assertIn('Do NOT resend', out, mode)
            self.assertNotIn('did not accept', out, mode)
            self.assertNotIn('Saved', out, mode)
        out = self.call('store: edge fact', mode='skip_status')
        self.assertIn('not stored', out)
        self.assertIn('never force a write', out)
        self.assertNotIn('did not accept', out)

    def test_readback_full_verification(self):
        out = self.call('store: full verify fact', mode='show_wrongid')
        self.assertIn('Saved:', out)
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)
        out = self.call('store: full verify fact tail', mode='show_tail')
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)
        out = self.call('store: full verify fact ok')
        self.assertIn('verified by read-back', out)

    def test_slow_bad_receipt_respects_shared_budget(self):
        before = self.recorded()
        out = self.call('store: slow garbage fact', mode='slow_garbage',
                        extra_env={'RESPITE_HOOK_BUDGET_S': '4'})
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(len(self.recorded()) - len(before), 1)

    def test_verify_list_schema_failures_are_not_attribution(self):
        for mode in ('list_schema', 'list_notimes'):
            out = self.call('store: schema fact', mode='silent', list_mode=mode)
            self.assertIn('store unknown', out, mode)
            self.assertNotIn('may already be written', out, mode)
    def test_stop_after_hook_store_does_not_query_engine(self):
        self.call('store: durable fixture fact')
        before = self.recorded()
        self.assertEqual(self.call(event='Stop'), '')
        self.assertEqual(self.recorded(), before)

    def test_turn_receipt_suppression_is_request_scoped(self):
        # T18：只有「同会话、本轮 prompt 之后」的成功写回执才免催；新请求不被旧轮抑制
        self.call('store: durable fixture fact')
        self.assertEqual(self.call(event='Stop'), '')
        self.call('another ordinary input without storing')   # 新请求（未存）
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')

    def test_stop_once_per_request_latch(self):
        # DM-04：宿主未带 stop_hook_active 时，同一请求也至多催一次；新请求重新武装
        self.call('ordinary input')
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')
        before = self.recorded()
        self.assertEqual(self.call(event='Stop'), '')
        self.assertEqual(self.recorded(), before)
        self.call('fresh request after wrap-up')
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')

    def test_receipt_suppression_is_session_scoped(self):
        # 会话隔离：A 会话的写回执不免 B 会话的催存
        self.call('store: durable fixture fact', session='a')
        self.assertEqual(json.loads(self.call(event='Stop', session='b'))['decision'], 'block')

    def test_malformed_spy_cannot_pass_positive_control(self):
        self.positive_control()
        self.assertEqual(self.call('ordinary input', mode='malformed'), '')
        self.assertIn('parse_error', self.log.read_text(encoding="utf-8"))

    def test_readback_bad_details_keeps_saved_receipt(self):
        # 二轮复核#2：show 回读的 details 非字典（数组/字符串）→ unavailable；
        # 类型错误绝不允许掀翻整条已写回执（丢 Saved = 把已提交数据当没写）
        for mode in ('show_badarr', 'show_badstr'):
            before = self.recorded()
            out = self.call('store: durable fixture fact', mode=mode)
            self.assertIn('Saved:', out, mode)
            self.assertIn('Read-back unavailable', out, mode)
            self.assertNotIn('verified by read-back', out, mode)
            self.assertEqual([a[0] for a in self.recorded()[len(before):]], ['remember', 'show'], mode)

    def test_remember_timeout_is_capped_by_remaining_budget(self):
        # 二轮复核#3：remember 超时 = min(STORE_T, 剩余预算)（monotonic 共享截止）——
        # 紧预算（3s 预算 → 进场仅剩 0.5s）不得按 STORE_T=18s 全窗死等（用耗时上界钉死）
        before = self.recorded()
        started = time.monotonic()
        out = self.call('store: tight budget fact', mode='hang',
                        extra_env={'RESPITE_HOOK_BUDGET_S': '3'})
        elapsed = time.monotonic() - started
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(len(self.recorded()) - len(before), 1)
        self.assertLess(elapsed, 15, f'remember waited {elapsed:.1f}s - not capped by remaining budget')

    def test_exhausted_budget_skips_remember_entirely(self):
        # 二轮复核#3：进场剩余预算 ≤0 → 连 remember 也不发（零引擎调用），直接 unknown
        before = self.recorded()
        out = self.call('store: budget gone fact', extra_env={'RESPITE_HOOK_BUDGET_S': '2'})
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(self.recorded(), before)


class TurnStateIsolation(unittest.TestCase):
    """二轮复核主项：凭证状态按会话独立文件 st_<sidkey>.json。
    共享 turn_map 的跨进程 read-modify-write（B 读旧快照 → A 更新 → B 整体写回）
    会把 A 的新请求凭证回滚成旧值——一次成功的原子 rename 只保证写完整，不保证事务。"""

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
        # 显式播种凭证时刻（相对 now 的过去偏移，prompt 在前 store 在后）：与真实时钟粒度无关，
        # 任何平台/任何 tick 下「真实 mark_prompt 时刻 > 播种 store_ts」恒成立
        now = time.time()
        self.assertTrue(self.hook._map_update(
            session, {'prompt_ts': now - prompt_ago, 'store_ts': now - store_ago,
                      'store_req_ts': now - prompt_ago}))  # 同代凭证（三轮复核①语义）
        self.assertTrue(self.hook._write_gen_marker(session, now - prompt_ago))  # ④①真值链：标记同步

    def test_b_write_cannot_rollback_a_new_prompt(self):
        # 复核点名的交错：A 旧 prompt_ts/store_ts → B 读旧快照 → A 新请求更新 → B 写回。
        # 共享 map 下 B 的整体写回会把 A 回滚成旧值（旧 store 被误认本轮已写而跳过存储检查）；
        # 每会话独立文件下 A 的新请求状态原样保留——旧 store 不免催。
        h = self.hook
        self._seed('sessA')                        # 旧轮凭证：store_ts=now-5
        self.assertTrue(h.turn_stored('sessA'))
        h.mark_prompt('sessA')                     # A 新真实请求（= B 读旧快照之后的 A-update）
        self.assertFalse(h.turn_stored('sessA'))
        snapshot = self._a_file().read_bytes()
        h.mark_prompt('sessB')                     # B-write：恢复执行、更新自己的条目并写回
        h.mark_store('sessB')
        h.mark_prompt('sessB')
        h.mark_store('sessB')
        self.assertEqual(self._a_file().read_bytes(), snapshot,
                         'B session write rewrote A state (cross-process RMW rollback)')
        self.assertFalse(h.turn_stored('sessA'),
                         'A rolled back to the old prompt/store pair - stale store would suppress Stop')
        names = sorted(p.name for p in self.dir.iterdir())
        self.assertNotIn('turn_map.json', names)
        # 每会话恰一个状态文件（.gen 标记与 .lock 为伴生运行时文件，不计入）
        self.assertEqual(len([n for n in names if n.startswith('st_') and n.endswith('.json')]), 2)

    def test_a_fresh_receipt_survives_b_updates(self):
        # 反向交错：A 刚写成功的凭证不被 B 的更新抹掉（否则会造成多余催存）
        h = self.hook
        self._seed('sessA')
        snapshot = self._a_file().read_bytes()
        h.mark_prompt('sessB')
        h.mark_store('sessB')
        self.assertEqual(self._a_file().read_bytes(), snapshot)
        self.assertTrue(h.turn_stored('sessA'), 'A fresh receipt erased by B update')

    def test_new_prompt_after_store_no_longer_suppresses(self):
        h = self.hook
        self._seed('sessA')                        # 旧轮已存 → 免催
        self.assertTrue(h.turn_stored('sessA'))
        h.mark_prompt('sessA')                     # 新真实请求：prompt_ts>store_ts → 旧回执不免催
        self.assertFalse(h.turn_stored('sessA'))
        self._seed('sessA')                        # 新一轮：prompt 在前、store 在后 → 重新免催
        self.assertTrue(h.turn_stored('sessA'))
        h.mark_prompt('sessB')
        h.mark_store('sessB')
        self.assertTrue(h.turn_stored('sessA'), 'B update erased A fresh receipt')


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
