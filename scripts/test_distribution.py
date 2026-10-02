"""Explicit release boundary and adapter discovery contracts, using synthetic data."""
import json
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
import zipfile

import package_distribution as release


class DistributionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='release café ');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve()/'source with spaces';self.root.mkdir()
        self.expected=release.payload()
        for name,data in self.expected.items():
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)

    def test_populated_working_tree_never_enters_reusable_archive(self):
        private=('Textbooks/private.pdf','Objectives/private.pdf','PastPapers/private.pdf',
                 'packs/Private/checkpoint.json','output/Private/index.html','work/prompt.md',
                 'foundation/intake-cache/private.txt','foundation/reviews/private.json',
                 '.env','.venv/private.txt','pipeline-config.json','.diagnostics/private.jsonl',
                 '.codex/auth.json','.codex/sessions/private.jsonl','.claude/settings.local.json',
                 '.claude/agents/fuzzy-delivery-local.md','.claude/projects/private.jsonl',
                 'CLAUDE.local.md','.job-queue/private.json')
        sentinel=b'SYNTHETIC_' + b'PRIVATE_RECORD'
        for name in private:
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(sentinel)
        archive=self.root.parent/'release.zip'
        report=release.build(archive,self.root)
        self.assertTrue(report['exact_bytes'])
        release.verify(archive,self.expected)
        with zipfile.ZipFile(archive) as opened:
            self.assertTrue(all('FuzzyProblems/'+name not in opened.namelist() for name in private))
            self.assertTrue(all(sentinel not in opened.read(name) for name in opened.namelist()))
        second=self.root.parent/'second.zip';release.build(second,self.root)
        self.assertEqual(archive.read_bytes(),second.read_bytes())
        with self.assertRaises(FileExistsError):release.build(archive,self.root)

    def test_bad_allowlist_paths_and_private_families_are_rejected(self):
        original=json.loads((self.root/release.MANIFEST).read_text())
        for name in ('../escape','/absolute','C:/absolute','scripts/CON.py','scripts/a\\b.py',
                     'scripts/../private','scripts/trailing.','Textbooks/private.pdf',
                     '.claude/settings.local.json','.claude/agents/fuzzy-delivery-local.md','pipeline-config.json'):
            value=dict(original,files=original['files']+[name])
            (self.root/release.MANIFEST).write_text(json.dumps(value))
            with self.subTest(path=name),self.assertRaises(ValueError):release.payload(self.root)
        (self.root/release.MANIFEST).write_text(json.dumps(dict(original,files=original['files']+['README.md'])))
        with self.assertRaises(ValueError):release.payload(self.root)

    def test_case_and_symlink_sources_are_rejected(self):
        role=self.root/'.claude/agents/fuzzy-author.md'
        saved=role.read_bytes();role.unlink()
        external=self.root.parent/'outside.md';external.write_bytes(saved)
        try:role.symlink_to(external)
        except OSError:self.skipTest('Symlink privilege unavailable')
        with self.assertRaises(ValueError):release.payload(self.root)
        role.unlink();role.with_name('Fuzzy-author.md').write_bytes(saved)
        with self.assertRaises(ValueError):release.payload(self.root)

    def test_all_shipped_markdown_links_resolve_with_exact_case_without_parent(self):
        for name,data in self.expected.items():
            if not name.endswith('.md'):continue
            text=data.decode('utf-8')
            for target in re.findall(r'\]\(([^)]+)\)',text):
                if '://' in target or target.startswith('#'):continue
                target=target.split('#')[0]
                if not target:continue
                resolved=(self.root/name).parent.joinpath(target).resolve()
                self.assertTrue(resolved.is_relative_to(self.root), (name,target))
                self.assertTrue(resolved.is_file(),(name,target))
                current=self.root
                for part in resolved.relative_to(self.root).parts:
                    self.assertIn(part,{p.name for p in current.iterdir()},(name,target));current/=part

    def test_native_adapter_discovery_formats_and_tool_boundary(self):
        for role in ('author','reviewer','delivery'):
            codex=tomllib.loads((self.root/f'.codex/agents/{role}.toml').read_text())
            self.assertEqual(codex['name'],role)
            self.assertNotIn('model',codex);self.assertNotIn('model_reasoning_effort',codex)
            self.assertIn('foundation/guidance/AGENT_ROLES.md',codex['developer_instructions'])
            claude=(self.root/f'.claude/agents/fuzzy-{role}.md').read_text()
            _,header,body=claude.split('---',2)
            fields=dict(line.split(':',1) for line in header.strip().splitlines())
            self.assertEqual(fields['name'].strip(),'fuzzy-'+role)
            self.assertEqual(fields['model'].strip(),'inherit');self.assertNotIn('effort',fields)
            self.assertEqual({t.strip() for t in fields['tools'].split(',')},{'Read','Glob','Grep','Bash','PowerShell','Write','Edit'})
            self.assertIn('foundation/guidance/AGENT_ROLES.md',body)
        for host in ('.agents','.claude'):
            for name in ('fuzzy-start','job-queue'):
                text=(self.root/f'{host}/skills/{name}/SKILL.md').read_text()
                _,header,_=text.split('---',2)
                fields=dict(line.split(':',1) for line in header.strip().splitlines())
                self.assertEqual(fields['name'].strip(),name)
                self.assertNotIn('context',fields);self.assertNotIn('allowed-tools',fields)
        settings=json.loads((self.root/'.claude/settings.json').read_text())
        self.assertEqual(set(settings),{'env'})
        self.assertEqual(settings['env'],{'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1',
            'CLAUDE_CODE_ENABLE_TELEMETRY':'0','CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL':'1'})


if __name__=='__main__':unittest.main()
