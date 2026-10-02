"""Exercise a clean release outside its source tree with a newly created venv.

This opt-in tooling check installs pinned dependencies (or uses --wheelhouse).
It makes no AI calls and requires no host authentication or global project skills.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import package_distribution as release


def run(command, cwd):
    result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,encoding='utf-8',
                          env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'),timeout=300)
    if result.returncode:
        stage=next((Path(arg).name for arg in command if arg.endswith('.py')),'command')
        raise RuntimeError('Standalone stage '+stage+' failed with exit '+str(result.returncode)+'.')
    return json.loads(result.stdout[result.stdout.find('{'):])


def check(archive, wheelhouse=None):
    release.verify(archive,release.payload())
    with tempfile.TemporaryDirectory(prefix='standalone café ') as temporary:
        temporary=Path(temporary).resolve()
        with zipfile.ZipFile(archive) as opened:opened.extractall(temporary)
        root=temporary/'FuzzyProblems'
        moved=temporary/'Extracted project café with spaces';root.rename(moved);root=moved
        self_python=getattr(sys,'_base_executable',sys.executable)
        base=[self_python,'-X','utf8','-B',str(root/'pipeline.py')]
        # Use an unrelated cwd; all project routing must be relative to the launcher.
        command=base+['init','--host','claude']
        if wheelhouse:command+=['--wheelhouse',str(Path(wheelhouse).resolve())]
        initialized=run(command,temporary)
        if initialized['status']!='initialized' or not initialized['runtime']['production_runtime_ready']:
            raise RuntimeError('Initialization did not establish Python readiness.')
        for directory in ('Textbooks','Objectives','PastPapers'):
            if any((root/directory).iterdir()):raise RuntimeError('Fresh input folders were not empty.')
        run(base+['intake','--scan-only'],temporary)
        sentinels={'Objectives/Synthetic.pdf':b'synthetic preservation fixture',
                   'packs/Existing/checkpoint.json':b'{"stage":"review"}',
                   'packs/Existing/review/independent.json':b'{"status":"needs_revision"}',
                   'output/Previous/index.html':b'previous synthetic export'}
        for name,data in sentinels.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        config=(root/'pipeline-config.json').read_bytes()
        run(base+['init','--no-install'],temporary)
        if (root/'pipeline-config.json').read_bytes()!=config:raise RuntimeError('Repeated init changed configuration.')
        run(base+['init','--no-install','--host','codex'],temporary)
        run(base+['init','--no-install','--host','claude'],temporary)
        if (root/'pipeline-config.json').read_bytes()!=config:raise RuntimeError('Host round trip changed saved settings.')
        if any((root/name).read_bytes()!=data for name,data in sentinels.items()):
            raise RuntimeError('Repeated initialization changed existing work.')
        python=root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        # Public entry points must explain unsupported transport without exposing
        # absolute traceback paths or creating a review/queue for the missing pack.
        commands=[base+['review-run','Missing','--host','claude'],
                  base+['queue','status','Missing','--host','claude'],
                  [str(python),'-B',str(root/'scripts/review_runner.py'),'Missing','--host','claude']]
        for command in commands:
            rejected=subprocess.run(command,cwd=temporary,capture_output=True,text=True,
                                    encoding='utf-8',timeout=30,
                                    env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1'))
            response=rejected.stdout+rejected.stderr
            if not rejected.returncode or 'Codex-only' not in response or 'Traceback' in response or str(root) in response:
                raise RuntimeError('Claude optional transport rejection was not concise and actionable.')
        if (root/'packs/Missing').exists() or (root/'.job-queue').exists():
            raise RuntimeError('Rejected optional transport created operational state.')
        tests=run([str(python),'-X','utf8','-B',str(root/'scripts/check.py'),'--strict'],temporary)
        return {'status':'pass','platform':sys.platform,'fresh_environment':True,'empty_inputs':True,
                'repeat_and_host_switch_preserved_work':True,'public_cli_guards':True,'extracted_tests':tests,
                'host':initialized['host'],'synthetic_only':True,'live_ai_execution':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--wheelhouse',type=Path)
    args=parser.parse_args(argv)
    try:report=check(args.archive,args.wheelhouse)
    except RuntimeError as error:
        parser.exit(1,str(error)+' Repeat that stage locally to diagnose; raw host/install logs remain internal.\n')
    except (OSError,ValueError,subprocess.TimeoutExpired):
        parser.exit(1,'Clean standalone check failed; repeat the documented stages to diagnose locally. No live-host or educational acceptance is claimed.\n')
    print(json.dumps(report,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
