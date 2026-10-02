"""Optional CLI transport for the shared independent-review assignment.

Native visible agents are the default. This fallback never chooses a provider,
creates an approval, or replaces a live worker. No model calls occur on import.
"""
import argparse
import ctypes
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pipeline_core as v
import workflow as w
import host_runtime

DEFAULT_TIMEOUT = 3600
LOCK = 'review/runner.lock'
RESULT = 'review/runner-result.json'


class RunnerError(RuntimeError):
    """A condition the caller must fix; never silently worked around."""


def cli_path(explicit=None):
    candidate = explicit or os.environ.get('CODEX_CLI_PATH') or shutil.which('codex')
    if not candidate or not Path(candidate).is_file():
        raise RunnerError('Codex CLI not found. Set CODEX_CLI_PATH or pass --cli.')
    return str(candidate)


def reviewer_identity(pack_name):
    safe = ''.join(c if c.isalnum() or c in '-_.' else '-' for c in pack_name).strip('-')
    return f'{safe}-independent-reviewer'


def require_model(model, effort):
    if not w.model_recorded({'model': model, 'reasoning': effort}):
        raise RunnerError('Pass an explicit nonempty --model and --effort (SPECIFICATION SG-004); '
                          'the host/provider determines which settings are supported.')


def build_command(cli, handoff, model, effort, last_message, reviewer, session_id=None):
    prompt = (f'Read {handoff} and complete that shared independent-review assignment. '
              f'Use logical reviewer id {reviewer}. Requested model is {model}, effort is {effort}. '
              'Check exposed runtime settings once; record actual model/effort separately from requested settings, '
              'or mark unexposed values unverified with a configuration_check note. Never claim a flag proves actual execution. '
              + ('Continue your own previous review; inspect revisions and unresolved findings. '
                 if session_id else 'Start with fresh independent context; do not delegate. ')
              + 'Return your verdict and actionable findings.')
    command = [cli, 'exec']
    if session_id:
        command += ['resume', '--skip-git-repo-check', '-c', 'sandbox_mode="workspace-write"']
    else:
        command += ['-C', str(v.ROOT), '--skip-git-repo-check', '-s', 'workspace-write']
    command += ['-m', model, '-c', f'model_reasoning_effort={json.dumps(effort)}',
                '--json', '-o', str(last_message)]
    if session_id:
        command += [session_id]
    return command + [prompt]


def process_alive(pid):
    """Conservative liveness check. os.kill(pid, 0) is unsafe on Windows."""
    if not isinstance(pid, int) or pid <= 0:
        return True
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Lock:
    """Hold pack ownership from handoff generation through acceptance."""

    def __init__(self, path, force=False):
        self.path, self.force = path, force
        self.owner = {'pid': os.getpid(), 'token': uuid.uuid4().hex, 'started': time.time()}

    def __enter__(self):
        try:
            handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                old = v.read(self.path)
            except (ValueError, OSError):
                raise RunnerError('Unreadable runner lock; confirm and stop its worker before recovery.')
            if (not self.force or old.get('launching') or process_alive(old.get('pid'))
                    or ('child_pid' in old and process_alive(old['child_pid']))):
                raise RunnerError('Runner lock exists. --force only removes a lock whose parent and child are confirmed stopped.')
            if v.read(self.path) != old:
                raise RunnerError('Runner lock changed during recovery; retry after checking its owner.')
            self.path.unlink()
            handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(self.owner, stream)
        return self

    def child(self, pid):
        self.owner.pop('launching', None)
        self.owner['child_pid'] = pid
        v.write(self.path, self.owner)

    def launching(self):
        # A crashed parent between Popen and child() must not expose an
        # unrecorded live worker to automatic lock recovery.
        self.owner['launching'] = True
        v.write(self.path, self.owner)

    def __exit__(self, *exception):
        if self.path.exists() and v.read(self.path).get('token') == self.owner['token']:
            self.path.unlink()
        return False


def log_metadata(path):
    """Parse only session/usage events, never send command output back to an LLM."""
    result = {'session_id': None, 'usage': {}}
    if path.exists():
        with path.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get('type') == 'thread.started':
                    try:
                        result['session_id'] = str(uuid.UUID(event.get('thread_id', '')))
                    except (ValueError, TypeError, AttributeError):
                        pass
                if event.get('type') == 'turn.completed':
                    for key, value in (event.get('usage') or {}).items():
                        if isinstance(value, (int, float)):
                            result['usage'][key] = result['usage'].get(key, 0) + value
    return result


def declared_entries(pack):
    return list(v.read(pack / 'content.json').get('entry_dependencies', {}))


def validate_receipts(pack, entries):
    outcomes = {}
    for eid in entries:
        try:
            w.entry_dependency(eid, w.entry_inputs(eid)['entry_hash'])
            outcomes[eid] = 'current'
        except Exception as error:
            outcomes[eid] = f'not current: {error}'
    return outcomes


def acceptance(pack):
    import production
    try:
        build = production.build(pack)
        result = production.check(pack)
    except Exception as error:
        return {'status': 'failed', 'detail': str(error)[:600]}
    return {'status': result['status'], 'kind': result.get('kind'), 'checks': result.get('checks'),
            'highlight_warnings': len(build['evidence'].get('highlight_warnings', []))}


def finish(pack, summary, publish_folder):
    summary['entries'] = validate_receipts(pack, declared_entries(pack))
    summary['acceptance'] = acceptance(pack)
    passed = (all(value == 'current' for value in summary['entries'].values())
              and summary['acceptance'].get('status') == 'pass'
              and summary['acceptance'].get('kind') == 'educational_pack')
    summary['status'] = 'accepted' if passed else 'review_incomplete'
    if passed and publish_folder:
        import production
        summary['publication'] = production.publish(pack, publish_folder)
        summary['status'] = 'published'
    return summary


def receipt_stamp(pack):
    path = pack / 'review/independent.json'
    return (path.stat().st_mtime_ns, v.digest(path)) if path.exists() else None


def run(pack_name, model=None, effort=None, timeout=DEFAULT_TIMEOUT, force=False,
        dry_run=False, publish_folder=None, cli=None, validate_only=False, resume=False, host=None):
    host_runtime.require_codex(v.ROOT,host)
    w.safe_name(pack_name)
    pack = w.pack(pack_name)
    if not (pack / 'content.json').is_file():
        raise RunnerError(f'No prepared pack at packs/{pack_name}')
    review_dir = w.safe_tree(pack / 'review')
    result_path = w.safe_tree(pack / RESULT)
    if timeout <= 0 or (validate_only and (resume or dry_run)):
        raise RunnerError('Use a positive timeout; --validate-only cannot combine with --resume or --dry-run.')
    session_id = None
    if resume:
        if not (pack / RESULT).is_file():
            raise RunnerError('No recorded reviewer session to resume.')
        previous = v.read(pack / RESULT)
        try:
            session_id = str(uuid.UUID(previous.get('session_id', '')))
        except (ValueError, TypeError, AttributeError):
            raise RunnerError('No valid recorded reviewer session. Diagnose the prior attempt before starting fresh.')
        model, effort = model or previous['model'], effort or previous['effort']
        if (model, effort) != (previous['model'], previous['effort']):
            raise RunnerError('Resume must keep the recorded reviewer model and effort.')
    if not validate_only:
        require_model(model, effort)
    handoff = f'packs/{pack_name}/review/handoff.md'
    summary = {'pack': f'packs/{pack_name}', 'handoff_file': handoff}
    if not validate_only:
        executable = cli_path(cli)
        summary.update(reviewer=reviewer_identity(pack_name), model=model, effort=effort,
                       session_id=session_id, resumed=resume,
                       runtime_provenance='Requested CLI settings only; actual exposure belongs in the independent receipt.')
    if dry_run:
        summary.update(status='dry_run', command=build_command(executable, handoff, model, effort,
                       '<new-attempt>/last-message.md', summary['reviewer'], session_id))
        return summary
    review_dir.mkdir(parents=True, exist_ok=True)
    with Lock(w.safe_tree(pack / LOCK), force=force) as lock:
        if validate_only:
            return finish(pack, summary, publish_folder)
        import review_handoff
        summary['handoff'] = review_handoff.create(pack)['version']
        attempt = w.safe_tree(pack / 'review/runner-attempts' / (time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]))
        attempt.mkdir(parents=True)
        log, last = attempt / 'output.jsonl', attempt / 'last-message.md'
        summary.update(log=log.relative_to(v.ROOT).as_posix(),
                       last_message=last.relative_to(v.ROOT).as_posix())
        command = build_command(executable, handoff, model, effort, last, summary['reviewer'], session_id)
        started = time.time()
        before = receipt_stamp(pack)
        try:
            with log.open('w', encoding='utf-8', newline='\n') as stream:
                lock.launching()
                process = subprocess.Popen(command, cwd=str(v.ROOT), stdin=subprocess.DEVNULL,
                                           stdout=stream, stderr=subprocess.STDOUT, text=True,
                                           encoding='utf-8', env=dict(os.environ, PYTHONUTF8='1'))
                try:
                    lock.child(process.pid)
                    summary['exit_code'] = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    summary.update(status='timeout', detail=f'Reviewer exceeded {timeout}s and was stopped.')
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
        except OSError as error:
            summary.update(status='command_failed', detail=str(error)[:600])
        except KeyboardInterrupt:
            summary.update(status='interrupted', detail='Reviewer was stopped; its saved session can be resumed.')
        summary['seconds'] = round(time.time() - started, 1)
        metadata = log_metadata(log)
        summary['session_id'] = metadata['session_id'] or session_id
        summary['usage'] = metadata['usage']
        if 'status' not in summary:
            if summary['exit_code'] != 0:
                summary['status'] = 'command_failed'
            elif receipt_stamp(pack) in (None, before):
                summary.update(status='review_incomplete', detail='Reviewer did not write a current pack receipt; inspect its findings.')
            else:
                try:
                    finish(pack, summary, publish_folder)
                except Exception as error:
                    summary.update(status='completion_failed', detail=str(error)[:600])
        v.write(attempt / 'result.json', summary)
        v.write(result_path, summary)
        return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description='Optional CLI transport for independent review.')
    parser.add_argument('pack_name')
    parser.add_argument('--model')
    parser.add_argument('--host',choices=host_runtime.HOSTS,help='This optional transport supports Codex only')
    parser.add_argument('--effort')
    parser.add_argument('--resume', action='store_true', help='Continue the recorded reviewer session')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument('--force', action='store_true', help='Recover a lock only when its owners are stopped')
    parser.add_argument('--dry-run', action='store_true', help='Preview without modifying the pack or calling a model')
    parser.add_argument('--publish', dest='publish_folder', metavar='FOLDER')
    parser.add_argument('--cli', help='Codex CLI path (otherwise CODEX_CLI_PATH or PATH)')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        host_runtime.require_codex(v.ROOT, args.host)
    except ValueError as error:
        parser.exit(2, str(error) + '\n')
    return run(**vars(args))


if __name__ == '__main__':
    result = main()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] in {'accepted', 'published', 'dry_run'} else 1)
