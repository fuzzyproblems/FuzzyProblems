"""Explicitly requested serial queues using the public Codex CLI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pipeline_core as v
import workflow as w
import host_runtime
from review_runner import Lock, RunnerError, cli_path, log_metadata, process_alive, require_model


def directory(name):
    return w.safe_tree(v.ROOT / '.job-queue' / w.safe_name(name))


def require_bulk_gate(count):
    if count <= 1:
        return
    gate = v.BASE / 'production-gate.json'
    if not gate.is_file():
        raise ValueError('Complete and publish one full lesson before a multi-job queue.')
    value = v.read(gate)
    pack = w.pack(value['pack'])
    if (value.get('status') != 'complete_first_lesson_validated'
            or v.digest(pack / 'validation/completion.json') != value['completion_sha256']
            or v.digest(pack / 'publication.json') != value['publication_sha256']):
        raise ValueError('The full-lesson gate is missing or changed.')
    completion = v.read(pack / 'validation/completion.json')
    if completion.get('kind') != 'educational_pack' or not completion.get('full_lesson') or completion.get('status') != 'pass':
        raise ValueError('A technical fixture or partial pack cannot satisfy the full-lesson gate.')


def create(name, plan, model, effort, cli=None, host=None):
    host_runtime.require_codex(v.ROOT,host)
    require_model(model, effort)
    cli_path(cli)
    value = v.read(w.project_path(plan))
    jobs = value.get('jobs', [])
    if not jobs or any(not j.get('prompt', '').strip() for j in jobs):
        raise ValueError('Provide at least one exact job prompt.')
    ids = [w.safe_name(j['id']) for j in jobs]
    if len(ids) != len(set(ids)):
        raise ValueError('Job IDs must be distinct.')
    require_bulk_gate(len(jobs))
    target = directory(name)
    target.mkdir(parents=True, exist_ok=False)
    state = {'version': 1, 'id': name, 'model': model, 'effort': effort, 'host': 'codex',
             'status': 'queued', 'jobs': [dict(id=j['id'], prompt=j['prompt'], status='queued') for j in jobs]}
    v.write(target / 'state.json', state)
    return {'status': 'queued', 'id': name, 'jobs': len(jobs)}


def attach(name, pack_name):
    target = directory(name)
    state = v.read(target / 'state.json')
    active = v.read(target / 'active.json')
    job = next(j for j in state['jobs'] if j['id'] == active['job'])
    if job.get('token') != active['token'] or job['status'] not in {'dispatching', 'running', 'attention', 'incomplete'}:
        raise ValueError('No matching queue dispatch to attach.')
    pack = w.pack(pack_name)
    if not (pack / 'scope.json').is_file():
        raise ValueError('Prepare the job pack before attaching it.')
    context = {'queue': name, 'job': active['job'], 'token': active['token']}
    path = w.safe_tree(pack / 'queue-context.json')
    if path.exists() and v.read(path) != context:
        raise ValueError('Pack belongs to another dispatch; preserve its existing ownership.')
    # A dispatch has one pack. This association is routing, never approval.
    ownership = target / ('pack-' + active['job'] + '.json')
    if ownership.exists() and v.read(ownership) != {'pack': pack_name, **context}:
        raise ValueError('Dispatch already owns a different pack.')
    v.write(ownership, {'pack': pack_name, **context})
    v.write(path, context)
    return {'status': 'attached_not_approved', 'pack': pack_name, 'job': active['job']}


def record_publication(root, pack):
    context_file = w.safe_tree(pack / 'queue-context.json')
    if not context_file.is_file():
        return
    context = v.read(context_file)
    target = directory(context['queue'])
    active = v.read(target / 'active.json')
    if context['token'] != active['token'] or context['job'] != active['job']:
        raise ValueError('Queue ownership does not match this publisher.')
    ownership = v.read(target / ('pack-' + context['job'] + '.json'))
    if ownership != {'pack': pack.name, **context}:
        raise ValueError('This pack is not attached to the current dispatch.')
    completion = v.read(pack / 'validation/completion.json')
    publication = v.read(pack / 'publication.json')
    if completion.get('status') != 'pass' or completion.get('kind') != 'educational_pack':
        raise ValueError('Only current educational acceptance may complete a queue job.')
    receipt = {'job': active['job'], 'token': active['token'], 'pack': pack.name,
               'completion_sha256': v.digest(pack / 'validation/completion.json'),
               'publication_sha256': v.digest(pack / 'publication.json')}
    if publication['completion_sha256'] != receipt['completion_sha256']:
        raise ValueError('Publication is not bound to current completion.')
    path = target / ('receipt-' + active['job'] + '.json')
    if path.exists() and v.read(path) != receipt:
        raise ValueError('Queue job already has a different publication; reconcile explicitly.')
    v.write(path, receipt)


def validate_publication(target, job, token):
    receipt = v.read(target / ('receipt-' + job + '.json'))
    if receipt['job'] != job or receipt['token'] != token:
        raise ValueError('Missing current dispatch publication receipt.')
    pack = w.pack(receipt['pack'])
    if any(v.digest(pack / rel) != receipt[key] for rel, key in
           [('validation/completion.json', 'completion_sha256'), ('publication.json', 'publication_sha256')]):
        raise ValueError('Queue publication changed.')
    from production import check
    checked = check(pack)
    if checked['kind'] != 'educational_pack':
        raise ValueError('A technical fixture cannot complete a job.')
    pub = v.read(pack / 'publication.json')
    folder = w.safe_tree(w.project_path(pub['folder']))
    if pub['artifacts'] != {n: v.digest(folder / n) for n in pub['allowlist']}:
        raise ValueError('Published artifact bytes changed.')
    return receipt['pack']


def run(name, force=False, resume=False, message=None, cli=None, host=None):
    host_runtime.require_codex(v.ROOT,host)
    target = directory(name)
    with Lock(target / 'runner.lock', force=force) as lock:
        state = v.read(target / 'state.json')
        executable = cli_path(cli or state.get('cli'))  # Read old state; never store new machine paths.
        pending = [j for j in state['jobs'] if j['status'] != 'complete']
        if resume:
            if not pending or pending[0]['status'] not in {'attention', 'incomplete', 'running'}:
                raise ValueError('No interrupted coordinator to resume; use run for queued jobs.')
            job = pending[0]
            if isinstance(job.get('pid'), int) and process_alive(job['pid']):
                raise ValueError('The recorded coordinator may still be alive; do not duplicate it.')
            if not job.get('session_id'):
                raise ValueError('No recorded session to resume. Inspect the dispatch log before explicit recovery.')
            uuid.UUID(job['session_id'])
            if any(j['status'] != 'queued' for j in pending[1:]):
                raise ValueError('More than one unresolved dispatch; reconcile ownership first.')
        elif any(j['status'] != 'queued' for j in pending):
            raise ValueError('Resolve the incomplete dispatch before continuing; do not duplicate live work.')
        state['status'] = 'running'
        v.write(target / 'state.json', state)
        for job in pending:
            if (target / 'stop').exists():
                state['status'] = 'stopped';break
            continuing = resume and job is pending[0]
            token = job['token'] if continuing else uuid.uuid4().hex
            active = {'job': job['id'], 'token': token, 'started': time.time()}
            v.write(target / 'active.json', active)
            job.update(status='dispatching', token=token)
            v.write(target / 'state.json', state)
            prompt = ('Read AGENTS.md, START_HERE.md and the job-queue skill. You are the queue coordinator '
                      'running in Codex; use HOST_CODEX.md and host --host codex even if the saved default host differs. '
                      'for exactly this one job. Use the default native author/reviewer/delivery route with one '
                      'active worker and fresh contexts. Do not launch another detached queue. Preserve the '
                      'exact scope, all original objectives, source-only facts and publication gates. '
                      'Use the selected model and effort for substantive workers and record actual provenance. '
                      'Complete and publish only after actual independent acceptance. After preparing the pack, '
                      f'run python pipeline.py queue attach {name} PACK --host codex with its pack name. '
                      'Publish only that attached pack; publication records this dispatch automatically.\n\n' + job['prompt'])
            if continuing:
                prompt += '\nContinue your recorded coordinator session from its checkpoint; do not duplicate completed work or live workers.'
                if message:
                    prompt += '\nAdditional user direction:\n' + w.project_path(message).read_text(encoding='utf-8')
            attempt = job['id'] + '-' + uuid.uuid4().hex[:8]
            log = target / (attempt + '.jsonl')
            last = target / (attempt + '-last.md')
            command = [executable, 'exec']
            if continuing:
                command += ['resume', '--skip-git-repo-check', '-c', 'sandbox_mode="workspace-write"']
            else:
                command += ['-C', str(v.ROOT), '--skip-git-repo-check', '--sandbox', 'workspace-write']
            command += ['-m', state['model'], '-c', 'model_reasoning_effort=' + json.dumps(state['effort']),
                        '--json', '-o', str(last)]
            if continuing: command += [job['session_id']]
            command += ['-']
            child = None
            attempt_record = {'log': log.relative_to(v.ROOT).as_posix(),
                              'last_message': last.relative_to(v.ROOT).as_posix(), 'resumed': continuing}
            job.setdefault('attempts', []).append(attempt_record)
            try:
                with log.open('x', encoding='utf-8') as stream:
                    lock.launching()
                    child = subprocess.Popen(command, cwd=v.ROOT, stdin=subprocess.PIPE, stdout=stream,
                                             stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                             env=dict(os.environ, PYTHONUTF8='1'))
                    lock.child(child.pid)
                    job.update(status='running', pid=child.pid)
                    v.write(target / 'state.json', state)
                    child.communicate(prompt)
                job['exit_code'] = child.returncode
                if child.returncode:
                    raise RunnerError('Codex exited before accepted publication; inspect the job log.')
                job['pack'] = validate_publication(target, job['id'], token)
                job['status'] = 'complete'
            except BaseException as exc:
                job['status'] = 'attention' if child is not None and child.poll() is None else 'incomplete'
                job['detail'] = str(exc)[:500]
                state['status'] = 'attention'
            finally:
                metadata = log_metadata(log)
                job['session_id'] = metadata['session_id'] or job.get('session_id')
                attempt_record.update(status=job['status'], usage=metadata['usage'])
                v.write(target / 'state.json', state)
            if state['status'] == 'attention':
                return state
        else:
            state['status'] = 'complete'
        v.write(target / 'state.json', state)
        return state


def reconcile(name, force=False):
    target = directory(name)
    with Lock(target / 'runner.lock', force=force):
        state = v.read(target / 'state.json')
        pending = [j for j in state['jobs'] if j['status'] != 'complete']
        if not pending:
            return {'status': 'complete'}
        job = pending[0]
        if job['status'] not in {'running', 'incomplete', 'attention'}:
            raise ValueError('No dispatched job to reconcile.')
        if isinstance(job.get('pid'), int) and process_alive(job['pid']):
            raise ValueError('Coordinator may still be running; wait for it to finish.')
        job['pack'] = validate_publication(target, job['id'], job['token'])
        job['status'] = 'complete'
        state['status'] = 'queued' if pending[1:] else 'complete'
        v.write(target / 'state.json', state)
        return {'status': state['status'], 'job': job['id']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('create');p.add_argument('name');p.add_argument('--plan', required=True)
    p.add_argument('--model', required=True);p.add_argument('--effort', required=True);p.add_argument('--cli')
    p = sub.add_parser('attach');p.add_argument('name');p.add_argument('pack')
    for name in ('run', 'start', 'status', 'stop', 'continue', 'resume', 'reconcile'):
        p = sub.add_parser(name);p.add_argument('name')
        if name in {'run','continue','resume','reconcile'}: p.add_argument('--force', action='store_true')
        if name == 'resume': p.add_argument('--message', help='Root-relative text file containing additional user direction')
        if name in {'run','start','continue','resume'}:p.add_argument('--cli',help='Runtime CLI path; never stored')
    for command_parser in sub.choices.values():
        command_parser.add_argument('--host',choices=host_runtime.HOSTS,help='Detached commands are Codex-only')
    args = parser.parse_args()
    try:
        host_runtime.require_codex(v.ROOT,args.host)
    except ValueError as error:
        parser.exit(2,str(error)+'\n')
    if args.command == 'create':
        result = create(args.name, args.plan, args.model, args.effort, args.cli,args.host)
    elif args.command == 'attach':
        result = attach(args.name, args.pack)
    elif args.command == 'reconcile':
        result = reconcile(args.name, args.force)
    elif args.command == 'status':
        state = v.read(directory(args.name) / 'state.json')
        result = {'status': state['status'], 'jobs': [{k: j[k] for k in ('id','status','pack') if k in j} for j in state['jobs']]}
    elif args.command == 'stop':
        (directory(args.name) / 'stop').touch(exist_ok=True)
        result = {'status': 'stop_after_active_job'}
    elif args.command == 'start':
        target = directory(args.name)
        # Atomic runner ownership is acquired by run; concurrent starts cannot
        # dispatch two workers. No shell or executable-file bit is required.
        command = [sys.executable, '-B', str(Path(__file__).resolve()), 'run', args.name]
        if args.host:command += ['--host',args.host]
        if args.cli:command += ['--cli',args.cli]
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if os.name == 'nt' else {'start_new_session': True}
        with (target / 'runner.log').open('a', encoding='utf-8') as output:
            child = subprocess.Popen(command, cwd=v.ROOT, stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT, **options)
        result = {'status': 'starting', 'pid': child.pid}
    else:
        if args.command in {'continue','resume'}: (directory(args.name) / 'stop').unlink(missing_ok=True)
        result = run(args.name, args.force, resume=args.command == 'resume', message=getattr(args, 'message', None),cli=args.cli,host=args.host)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get('status') == 'attention' else 0

if __name__ == '__main__':
    raise SystemExit(main())
