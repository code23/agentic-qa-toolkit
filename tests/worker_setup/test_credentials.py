"""Synthetic canaries only; no native model, SSH host or credential store."""
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from stubs import ROOT, FakeMac
from test_install import run_runner

EXECUTOR = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
if sys.argv[1:] == ['--version']:
    print('codex-cli synthetic'); sys.exit(0)
if sys.argv[1] == 'debug':
    print('{"models":[{"slug":"model-alpha","priority":0,"visibility":"list"}]}'); sys.exit(0)
if sys.argv[1] in ('login','plugin'):
    sys.exit(0)
if sys.argv[1:] == ['exec', '--help']:
    if os.environ.get('NO_EPHEMERAL') != '1': print('--ephemeral')
    sys.exit(0)
a=sys.argv
assert '--ephemeral' in a
assert 'history.persistence="none"' in a
folder=pathlib.Path(a[a.index('-C')+1])
text=sys.stdin.read()
access=json.loads(next(x[7:] for x in text.splitlines() if x.startswith('ACCESS=')))
values=[access.get('username',''), access.get('password','')]
for value in values:
    print(value)
    print(value, file=sys.stderr)
(folder/'extra.task').write_text(text)
(folder/'native-log').mkdir()
(folder/'native-log'/'native.log').write_text(text)
(folder/'home.png').write_bytes(b'PNG synthetic evidence')
if os.environ.get('CREDENTIAL_MODE') in ('unreadable', 'root-unreadable'):
    hidden = folder / values[1]
    hidden.mkdir()
    (hidden/'copy.task').write_text(text)
    (hidden/'outside-link').symlink_to(os.environ['OUTSIDE_FIXTURE'])
    hidden.chmod(0)
state=pathlib.Path(os.environ['FAKE_STATE'])
(state/'started').write_text(str(os.getpid()))
if os.environ.get('CREDENTIAL_MODE') == 'wait':
    subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
    time.sleep(60)
if os.environ.get('CREDENTIAL_MODE') == 'malformed':
    (folder/'result.json').write_text(text)
else:
    observed = json.dumps(access) if os.environ.get('CREDENTIAL_MODE') == 'escaped' else values[1]
    status = {'raw_transcript':text} if os.environ.get('CREDENTIAL_MODE') == 'schema' else 'completed'
    (folder/'result.json').write_text(json.dumps({'status':status,
        'observations':[{'check':values[0], 'observed':observed, 'as_expected':True, 'evidence':['home.png'], 'raw_transcript':text}],
        'blockers':[], 'evidence':['home.png'], 'extra':text}))
if os.environ.get('CREDENTIAL_MODE') == 'root-unreadable': folder.chmod(0)
sys.exit(int(os.environ.get('EXEC_RC','0')))
'''


class CredentialLifetimeTest(unittest.TestCase):
    def setUp(self):
        self.mac = FakeMac()
        for d in ('jobs', 'done', 'tmp'):
            (self.mac.base / d).mkdir(parents=True)
        self.mac.ack()
        self.values = ['synthetic-user-' + secrets.token_hex(12), 'synthetic-pass-' + secrets.token_hex(12)]
        self.access = {'environment':'test', 'username':self.values[0], 'password':self.values[1]}
        self.executor = self.mac.bin / 'credential-executor'
        self.mac._write(self.executor, EXECUTOR)

    def tearDown(self):
        self.mac.cleanup()

    def task(self, name='job.task', access=None):
        p = self.mac.base / 'jobs' / name
        p.write_text('ACCESS=' + json.dumps(self.access if access is None else access) + '\nCheck signed-in page\n')
        return p

    def launch(self, job, **extra):
        return subprocess.Popen([sys.executable, str(ROOT/'worker/lockrun.py'), 'run',
                                 str(self.mac.base/'.active.lock'), str(self.mac.base/'.active.info'),
                                 sys.executable, str(ROOT/'worker/jobrun.py'), str(self.mac.base),
                                 str(job), str(self.executor), 'model-alpha', 'test'],
                                env=self.mac.env(**extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def assert_clean(self, process, returncode=0):
        stdout, stderr = process.communicate(timeout=15)
        for value in self.values:
            self.assertNotIn(value.encode(), stdout + stderr)
            for p in self.mac.base.rglob('*'):
                if p.is_file() and not p.is_symlink():
                    self.assertNotIn(value.encode(), p.read_bytes(), str(p.relative_to(self.mac.base)))
        self.assertEqual(list((self.mac.base/'jobs').iterdir()), [])
        self.assertEqual(list((self.mac.base/'tmp').iterdir()), [])
        self.assertEqual(process.returncode, returncode)

    def test_success_failure_and_malformed_result_purge_all_copies(self):
        for index, extra in enumerate(({}, {'EXEC_RC':'7'}, {'CREDENTIAL_MODE':'malformed'})):
            with self.subTest(extra=extra):
                self.assert_clean(self.launch(self.task('job-%s.task' % index), **extra))
                out=self.mac.base/'done'/('job-%s' % index)
                self.assertTrue((out/'.done').exists())
                if extra.get('CREDENTIAL_MODE') != 'malformed':
                    result=json.loads((out/'result.json').read_text())
                    self.assertEqual(result['observations'][0]['observed'], '<redacted>')
                    self.assertEqual(result['evidence'], ['home.png'])
                    self.assertTrue((out/'home.png').exists())
                self.assertFalse((out/'extra.task').exists())

    def test_escaped_credentials_and_nested_extra_fields_are_not_retained(self):
        self.values[1] += '\n"\\\u00e9'
        self.access['password'] = self.values[1]
        self.assert_clean(self.launch(self.task(), CREDENTIAL_MODE='escaped'))
        result=json.loads((self.mac.base/'done/job/result.json').read_text())
        observation=result['observations'][0]
        self.assertEqual(set(observation), {'check','observed','as_expected','evidence'})
        copied_access=json.loads(observation['observed'])
        self.assertEqual(copied_access['password'], '<redacted>')
        self.assertEqual(copied_access['username'], '<redacted>')

    def test_malformed_nested_result_becomes_fixed_blocked_response(self):
        self.assert_clean(self.launch(self.task(), CREDENTIAL_MODE='schema'))
        result=json.loads((self.mac.base/'done/job/result.json').read_text())
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['observations'], [])

    def test_rejection_duplicate_and_invalid_access_never_archive_brief(self):
        previous=self.mac.base/'done'/'duplicate'
        previous.mkdir()
        (previous/'owned.txt').write_text('previous evidence')
        for name, access in (('-invalid.task', self.access), ('duplicate.task', self.access),
                             ('production.task', dict(self.access, environment='production')),
                             ('unknown.task', dict(self.access, environment='unknown'))):
            self.assert_clean(self.launch(self.task(name, access)))
        self.assertEqual((previous/'owned.txt').read_text(), 'previous evidence')
        self.assertFalse((self.mac.base/'rejected').exists())
        self.assertFalse((self.mac.state/'started').exists())

    def test_production_secure_reference_is_permitted(self):
        self.assert_clean(self.launch(self.task(access={'environment':'production','secureReference':'named-test-reference'})))

    def test_missing_ephemeral_fails_before_prompt_delivery(self):
        self.assert_clean(self.launch(self.task(), NO_EPHEMERAL='1'))
        self.assertFalse((self.mac.state/'started').exists())

    def test_catchable_signals_terminate_executor_and_purge(self):
        for index, sig in enumerate((signal.SIGTERM, signal.SIGINT, signal.SIGHUP)):
            p=self.launch(self.task('signal-%s.task' % index), CREDENTIAL_MODE='wait')
            started=self.mac.state/'started'
            for _ in range(150):
                if started.exists(): break
                time.sleep(.02)
            self.assertTrue(started.exists())
            child_pid=int(started.read_text())
            os.kill(p.pid, sig)
            self.assert_clean(p)
            with self.assertRaises(ProcessLookupError): os.kill(child_pid, 0)
            started.unlink()

    def test_job_symlink_is_unlinked_without_touching_target(self):
        target=self.mac.tmp/'outside.txt'
        target.write_text('unrelated user-owned file')
        job=self.mac.base/'jobs'/'link.task'
        job.symlink_to(target)
        self.assert_clean(self.launch(job))
        self.assertEqual(target.read_text(), 'unrelated user-owned file')

    def test_receiver_publication_companion_is_purged_without_false_rejection(self):
        job = self.task()
        os.link(job, self.mac.base / 'jobs/.job.tmp')
        self.assert_clean(self.launch(job))
        result = json.loads((self.mac.base/'done/job/result.json').read_text())
        self.assertEqual(result['status'], 'completed')

    def test_unreadable_credential_directories_are_purged_without_following_symlinks(self):
        outside = self.mac.tmp / 'outside-user-file'
        outside.write_text('unrelated user-owned data')
        outside.chmod(0o400)
        before = outside.stat()
        for index, mode in enumerate(('unreadable', 'root-unreadable')):
            self.assert_clean(self.launch(self.task('unreadable-%s.task' % index),
                                          CREDENTIAL_MODE=mode, OUTSIDE_FIXTURE=str(outside)))
            out = self.mac.base/'done'/('unreadable-%s' % index)
            self.assertTrue((out/'.done').exists())
            self.assertEqual(outside.read_text(), 'unrelated user-owned data')
            self.assertEqual(outside.stat().st_mode, before.st_mode)
            self.assertEqual(outside.stat().st_ino, before.st_ino)

    def test_forced_purge_error_is_quiet_incomplete_and_recoverable(self):
        job = self.task()
        driver = self.mac.bin / 'forced-purge-driver'
        driver.write_text('''import importlib.util,json,os,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('jobrun',sys.argv[1])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
job=Path(sys.argv[3])
value=json.loads(job.read_text().splitlines()[0][7:])['password']
def denied(*args,**kwargs):
    raise PermissionError('forced synthetic cleanup failure: '+value)
m.os.rmdir=denied
sys.exit(m.entry([sys.argv[1],*sys.argv[2:]]))
''')
        proc = subprocess.Popen([sys.executable, str(ROOT/'worker/lockrun.py'), 'run',
                                 str(self.mac.base/'.active.lock'), str(self.mac.base/'.active.info'),
                                 sys.executable, str(driver), str(ROOT/'worker/jobrun.py'), str(self.mac.base),
                                 str(job), str(self.executor), 'model-alpha', 'test'],
                                env=self.mac.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate(timeout=15)
        self.assertEqual(proc.returncode, 75)
        self.assertEqual(stdout, b'')
        self.assertEqual(stderr, b'Private cleanup pending; worker recovery required\n')
        for value in self.values: self.assertNotIn(value.encode(), stdout+stderr)
        out = self.mac.base/'done/job'
        self.assertFalse((out/'.done').exists(), 'purge failure must never look completed')
        roots = [p for p in (self.mac.base/'tmp').iterdir() if p.is_dir()]
        self.assertEqual(len(roots), 1)
        marker = roots[0].with_name(roots[0].name+'.owner.json')
        proof = json.loads(marker.read_text())
        self.assertEqual(proof['inode'], roots[0].stat().st_ino)
        self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
        # Next owned recovery uses the real filesystem operations, no model run.
        recovered = subprocess.run([sys.executable,str(ROOT/'worker/lockrun.py'),'run',
                                    str(self.mac.base/'.active.lock'),str(self.mac.base/'.active.info'),
                                    sys.executable,str(ROOT/'worker/jobrun.py'),'--recover',str(self.mac.base)],
                                   capture_output=True)
        self.assertEqual(recovered.returncode, 0)
        self.assertEqual(recovered.stdout+recovered.stderr, b'')
        self.assertEqual(list((self.mac.base/'tmp').iterdir()), [])
        self.assertFalse((out/'.done').exists(), 'recovery purges data; it never invents a QA result')

    def test_marker_inode_mismatch_preserves_replacement_directory(self):
        private = self.mac.base/'tmp/active-owned'
        private.mkdir()
        private.with_name(private.name+'.owner.json').write_text(json.dumps({
            'kind':'qa-worker-private-v2','folder':private.name,'uid':os.getuid(),
            'device':private.stat().st_dev,'inode':private.stat().st_ino+1}))
        keep=private/'keep.txt'; keep.write_text('unrelated replacement')
        result=subprocess.run([sys.executable,str(ROOT/'worker/lockrun.py'),'run',
                               str(self.mac.base/'.active.lock'),str(self.mac.base/'.active.info'),
                               sys.executable,str(ROOT/'worker/jobrun.py'),'--recover',str(self.mac.base)],
                              capture_output=True)
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stderr, b'Private cleanup pending; worker recovery required\n')
        self.assertEqual(keep.read_text(), 'unrelated replacement')

    def test_scheduled_root_replacement_preserves_both_roots_before_chmod(self):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location('jobrun_binding', ROOT/'worker/jobrun.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cases = [(boundary, retained, mode) for boundary in ('helper-entry', 'descriptor')
                 for retained, mode in ((False, 0o700), (True, 0o700), (True, 0))]
        for boundary, retained, replacement_mode in cases:
            with self.subTest(boundary=boundary, retained=retained, replacement_mode=replacement_mode):
                private = self.mac.base/'tmp'/('active-binding-%s-%s-%s' % (boundary, retained, replacement_mode))
                private.mkdir()
                (private/'original.txt').write_text('owned original sentinel')
                module.register_private(self.mac.base, private)
                marker = private.with_name(private.name+'.owner.json')
                proof = marker.read_bytes()
                saved = private.with_name('saved-'+private.name)
                incoming = private.with_name('incoming-'+private.name)
                incoming.mkdir()
                (incoming/'keep.txt').write_text('unrelated replacement sentinel')
                incoming.chmod(replacement_mode)
                fd = os.open(private, module.DIR_FLAGS) if retained else None
                if fd is not None:
                    self.assertFalse(os.get_inheritable(fd))
                    private.chmod(0)
                original_mode = private.stat().st_mode
                original_open = module.owned_directory
                original_os_open = os.open
                original_dup = os.dup
                swapped = []
                def replace():
                    private.rename(saved)
                    incoming.rename(private)
                    swapped.append(True)
                def replace_then_open(parent, name, *args):
                    # The outer proof has matched; the root open has not run.
                    if name == private.name and boundary == 'helper-entry': replace()
                    return original_open(parent, name, *args)
                def descriptor_open(name, flags, *args, **kwargs):
                    if boundary == 'descriptor' and name == private.name and flags == module.DIR_FLAGS:
                        replace()
                    return original_os_open(name, flags, *args, **kwargs)
                def descriptor_dup(value):
                    if boundary == 'descriptor': replace()
                    return original_dup(value)
                try:
                    with mock.patch.object(module, 'owned_directory', replace_then_open), \
                         mock.patch.object(module.os, 'open', descriptor_open), \
                         mock.patch.object(module.os, 'dup', descriptor_dup), \
                         mock.patch.object(module.os, 'chmod', side_effect=AssertionError('unexpected pathname chmod')), \
                         mock.patch.object(module.os, 'fchmod', side_effect=AssertionError('unexpected descriptor chmod')):
                        self.assertFalse(module.purge_private(self.mac.base, private, fd))
                    self.assertEqual(swapped, [True])
                    self.assertEqual(marker.read_bytes(), proof)
                    self.assertEqual(saved.stat().st_mode, original_mode)
                    self.assertEqual(private.stat().st_mode & 0o777, replacement_mode)
                finally:
                    if fd is not None: os.close(fd)
                    for folder in (saved, private):
                        if folder.exists(): folder.chmod(0o700)
                self.assertEqual((saved/'original.txt').read_text(), 'owned original sentinel')
                self.assertEqual((private/'keep.txt').read_text(), 'unrelated replacement sentinel')
        # A restart has no creation FD: unreadable root recovery must retain
        # identity and data without attempting a pathname permission repair.
        private = self.mac.base/'tmp/active-unreadable-restart'
        private.mkdir()
        (private/'keep.txt').write_text('restart sentinel')
        module.register_private(self.mac.base, private)
        private.chmod(0)
        try:
            with mock.patch.object(module.os, 'chmod', side_effect=AssertionError('unexpected pathname chmod')):
                self.assertFalse(module.purge_private(self.mac.base, private))
            self.assertEqual(private.stat().st_mode & 0o777, 0)
            self.assertTrue(private.with_name(private.name+'.owner.json').is_file())
        finally:
            private.chmod(0o700)
        self.assertEqual((private/'keep.txt').read_text(), 'restart sentinel')

    def test_unlocked_recovery_cannot_delete_a_live_private_job(self):
        private = self.mac.base/'tmp/active-live'
        private.mkdir()
        (private/'.qa-worker-private.json').write_text(json.dumps(
            {'kind':'qa-worker-private-v1','folder':private.name,'uid':os.getuid()}))
        (private/'keep').write_text('job still owns this folder')
        result=subprocess.run([sys.executable,str(ROOT/'worker/jobrun.py'),'--recover',str(self.mac.base)],
                              capture_output=True)
        self.assertEqual(result.returncode, 75)
        self.assertEqual(result.stderr, b'Private cleanup pending; worker recovery required\n')
        self.assertEqual((private/'keep').read_text(), 'job still owns this folder')

    def test_service_termination_forwards_to_the_cleanup_owner(self):
        self.task()
        p = subprocess.Popen(['/bin/bash', str(ROOT/'worker/runner.sh'), '--once'],
                             env=self.mac.env(QA_WORKER_BASE=str(self.mac.base), QA_WORKER_CODEX=str(self.executor),
                                              CREDENTIAL_MODE='wait'),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        started=self.mac.state/'started'
        for _ in range(150):
            if started.exists(): break
            time.sleep(.02)
        self.assertTrue(started.exists())
        os.kill(p.pid, signal.SIGTERM)
        self.assert_clean(p, returncode=130)
        result=json.loads((self.mac.base/'done/job/result.json').read_text())
        self.assertEqual(result['status'], 'blocked')

    def test_owned_recovery_ignores_unmarked_and_symlinked_folders(self):
        owned=self.mac.base/'tmp'/'active-owned'
        owned.mkdir()
        (owned/'.qa-worker-private.json').write_text(json.dumps({'kind':'qa-worker-private-v1','folder':owned.name,'uid':os.getuid()}))
        (owned/'copy.task').write_text(self.values[1])
        unrelated=self.mac.base/'tmp'/'active-user'
        unrelated.mkdir()
        outside=self.mac.tmp/'outside'
        outside.mkdir()
        (outside/'keep').touch()
        (self.mac.base/'tmp'/'active-link').symlink_to(outside)
        run_runner(self.mac,'--once')
        self.assertFalse(owned.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue((outside/'keep').exists())
