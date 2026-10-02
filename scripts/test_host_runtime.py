"""Synthetic host/configuration tests; fake probes never establish live support."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import host_runtime as h
import initialize
import job_queue
import pipeline_core as v
import review_runner
import workflow


class HostTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='hosts café ')
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve()
        self.value={'host':'codex','hosts':{host:{'delivery':copy.deepcopy(pair)} for host,pair in h.DEFAULTS.items()}}
        (self.root/'pipeline-config.example.json').write_text(json.dumps(self.value),encoding='utf-8')

    def write(self,value):
        (self.root/'pipeline-config.json').write_text(json.dumps(value),encoding='utf-8')

    def test_legacy_delivery_is_preserved_across_host_switches(self):
        legacy={'delivery':{'model':'custom-provider-model','reasoning_effort':'custom-supported-level'},'recipient_choice':{'keep':True}}
        self.write(legacy)
        self.assertEqual(h.configuration(self.root),('codex',legacy['delivery']))
        h.select(self.root,'claude')
        self.assertEqual(h.configuration(self.root),('claude',h.DEFAULTS['claude']))
        h.select(self.root,'codex')
        saved=h.load(self.root)
        self.assertEqual(saved['delivery'],legacy['delivery'])
        self.assertEqual(saved['recipient_choice'],legacy['recipient_choice'])
        before=(self.root/'pipeline-config.json').read_bytes()
        h.select(self.root)
        self.assertEqual((self.root/'pipeline-config.json').read_bytes(),before)

    def test_initializer_empty_repeat_and_switch_preserve_work(self):
        with patch.object(initialize,'ROOT',self.root):
            initialize.create_initial('claude')
            files={'Objectives/original.pdf':b'synthetic original bytes',
                   'packs/Existing/checkpoint.json':b'{"stage":"review"}',
                   'packs/Existing/review/independent.json':b'{"status":"needs_revision"}',
                   'output/Old/index.html':b'previous export',
                   'foundation/preferences/anki.json':b'{"course":"Selected course"}'}
            for name,data in files.items():
                target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            before={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            initialize.create_initial()
            self.assertEqual(before,{p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
            initialize.create_initial('codex')
            for name,data in before.items():
                if name!='pipeline-config.json':self.assertEqual((self.root/name).read_bytes(),data)

    def test_unsupported_host_effort_and_malformed_settings_do_not_mutate(self):
        bad_values=[{'host':'other'}, {'hosts':[]}, {'host':'claude','hosts':{'claude':{'delivery':{'model':'inherit','reasoning_effort':'ultra'}}}},
                    {'delivery':{'model':'','reasoning_effort':'medium'}}, {'delivery':{'model':'model\nwith newline','reasoning_effort':'medium'}}]
        for value in bad_values:
            self.write(value);before=(self.root/'pipeline-config.json').read_bytes()
            with self.subTest(value=value),self.assertRaises(ValueError):h.select(self.root)
            self.assertEqual((self.root/'pipeline-config.json').read_bytes(),before)

    def test_missing_and_old_host_diagnostics_exclude_probe_output(self):
        with patch.object(h.shutil,'which',return_value=None):
            report=h.describe(self.root,'claude')
        self.assertFalse(report['cli_available'])
        self.assertEqual(report['authentication'],'not_checked')
        # Missing adapters take priority; with complete adapters the CLI is missing.
        self.install_adapters()
        with patch.object(h.shutil,'which',return_value=None):
            self.assertEqual(h.describe(self.root,'claude')['status'],'cli_missing')
        for text,status in [('2.1.250 (Claude Code)','cli_upgrade_required'),
                            ('2.1.251 (Claude Code)','cli_detected_auth_not_checked'),
                            ('unparseable PRIVATE_PROBE_OUTPUT','cli_probe_failed')]:
            with patch.object(h.subprocess,'run',return_value=subprocess.CompletedProcess([],0,text,'PRIVATE_PROBE_OUTPUT')):
                report=h.describe(self.root,'claude',cli='/synthetic/private/executable')
            self.assertEqual(report['status'],status)
            encoded=json.dumps(report)
            self.assertNotIn('PRIVATE_PROBE_OUTPUT',encoded);self.assertNotIn('/synthetic/private',encoded)
        with patch.object(h.subprocess,'run',side_effect=OSError('PRIVATE_PROBE_OUTPUT')):
            self.assertEqual(h.describe(self.root,'claude',cli='fake')['status'],'cli_probe_failed')

    def install_adapters(self):
        for name in ('CLAUDE.md','.claude/skills/fuzzy-start/SKILL.md','.claude/skills/job-queue/SKILL.md',
                     '.claude/agents/fuzzy-author.md','.claude/agents/fuzzy-reviewer.md','.claude/agents/fuzzy-delivery.md'):
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((h.ROOT/name).read_bytes())

    def test_delivery_override_uses_native_frontmatter_without_changing_shipped_roles(self):
        self.install_adapters()
        base=(self.root/'.claude/agents/fuzzy-delivery.md').read_bytes()
        pair={'model':'selected-claude-model','reasoning_effort':'medium'}
        self.assertEqual(h.sync_claude_delivery(self.root,pair),'fuzzy-delivery-local')
        generated=(self.root/h.LOCAL_DELIVERY).read_text(encoding='utf-8')
        self.assertIn('model: "selected-claude-model"',generated)
        self.assertIn('effort: medium',generated)
        self.assertEqual((self.root/'.claude/agents/fuzzy-delivery.md').read_bytes(),base)
        self.assertEqual(h.sync_claude_delivery(self.root,h.DEFAULTS['claude']),'fuzzy-delivery')
        (self.root/h.LOCAL_DELIVERY).write_text('Recipient worker; preserve.',encoding='utf-8')
        with self.assertRaises(ValueError):h.sync_claude_delivery(self.root,pair)

    def test_cli_transports_reject_claude_before_creating_state_or_calling_cli(self):
        self.write({'host':'claude'})
        with patch.object(v,'ROOT',self.root),patch.object(review_runner,'cli_path') as cli,patch.object(job_queue,'cli_path') as queue_cli:
            for action in (lambda:review_runner.run('Missing',dry_run=True),
                           lambda:review_runner.run('Missing',validate_only=True),
                           lambda:job_queue.create('Queue','missing.json','model','high'),
                           lambda:job_queue.run('Missing')):
                with self.assertRaisesRegex(ValueError,'Codex-only'):action()
            cli.assert_not_called();queue_cli.assert_not_called()
            self.assertFalse((self.root/'.job-queue').exists())
            self.assertFalse((self.root/'packs').exists())
            h.require_codex(self.root,'codex')

    def test_legacy_codex_commands_keep_flags_and_new_queue_state_has_no_machine_path(self):
        self.write({'delivery':{'model':'custom-model','reasoning_effort':'custom-effort'}})
        (self.root/'plan.json').write_text(json.dumps({'jobs':[{'id':'One','prompt':'Synthetic transport only'}]}))
        with patch.object(v,'ROOT',self.root),patch.object(job_queue,'cli_path',return_value='/synthetic/tool path/codex'):
            created=job_queue.create('One','plan.json','custom-model','custom-effort')
            self.assertEqual(created['status'],'queued')
            state=(self.root/'.job-queue/One/state.json').read_text()
            self.assertNotIn('/synthetic/tool path',state);self.assertNotIn('"cli"',state)
            fresh=review_runner.build_command('codex','packs/One/review/handoff.md','custom-model','custom-effort','work/last.md','logical-reviewer')
            self.assertIn('--skip-git-repo-check',fresh)
            self.assertIn('workspace-write',fresh)
            self.assertEqual(fresh[fresh.index('-m')+1],'custom-model')
            self.assertIn('model_reasoning_effort="custom-effort"',fresh)
            resumed=review_runner.build_command('codex','packs/One/review/handoff.md','custom-model','custom-effort','work/last.md','logical-reviewer','synthetic-handle')
            self.assertIn('resume',resumed);self.assertIn('sandbox_mode="workspace-write"',resumed)
            self.assertIn('unverified',resumed[-1])

    def test_receipts_accept_provider_neutral_provenance_but_not_author_self_review(self):
        who={'id':'logical-reviewer','model':'unverified','reasoning':'unverified',
             'configuration_check':'Synthetic unavailable exposure; no model run.','host':'claude'}
        receipt={'reviewer':who,'fresh_context':True,'status':'pass','unresolved_findings':[]}
        workflow.identity(receipt,['logical-author'])
        with self.assertRaises(ValueError):workflow.identity(receipt,['logical-reviewer'])
        receipt['status']='needs_revision'
        with self.assertRaises(ValueError):workflow.identity(receipt,['logical-author'])

    def test_config_symlink_and_junction_are_rejected(self):
        external=self.root/'outside.json';external.write_text('{}')
        try:(self.root/'pipeline-config.json').symlink_to(external)
        except OSError:self.skipTest('Symlink privilege unavailable')
        with self.assertRaises(ValueError):h.select(self.root,'claude')
        (self.root/'pipeline-config.json').unlink()
        with patch.object(Path,'is_junction',return_value=True):
            with self.assertRaises(ValueError):h.select(self.root,'claude')


if __name__=='__main__':unittest.main()
