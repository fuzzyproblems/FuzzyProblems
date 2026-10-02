"""Synthetic delivery regressions. Test receipts never authorize real output."""
import contextlib
import copy
import importlib.util
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote,unquote,urlsplit
import zipfile

import fitz
from PIL import Image,PngImagePlugin

import anki_preferences
import contracts
import delivery_paths
import export_privacy
import learner_export
import pipeline_core as v
import production
import qa
import workflow as w


class ProductionDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='fuzzy delivery café ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        source=Path(__file__).resolve().parent
        (self.root/'scripts').mkdir()
        for script in source.glob('*.py'):
            (self.root/'scripts'/script.name).write_bytes(script.read_bytes())
        for name in ('regenerate_study_guide.py','requirements.txt','bootstrap-settings.json'):
            (self.root/name).write_bytes((source.parent/name).read_bytes())
        for name in ('Textbooks','Objectives','PastPapers','foundation/sources',
                     'foundation/curriculum','foundation/reviews','foundation/library/entries','packs'):
            (self.root/name).mkdir(parents=True,exist_ok=True)
        (self.root/'.synthetic-fixture').write_text('Synthetic test only. No educational approval.\n',encoding='utf-8')
        (self.root/'foundation/SPECIFICATION.md').write_bytes((source.parent/'foundation/SPECIFICATION.md').read_bytes())
        for patcher in (patch.object(v,'ROOT',self.root),patch.object(v,'BASE',self.root/'foundation'),
                        patch.dict(os.environ,{'STUDY_DIAGNOSTICS':'0'})):
            patcher.start();self.addCleanup(patcher.stop)
        self.book=self.root/'Textbooks/Café & guide #1.pdf'
        with fitz.open() as pdf:
            page=pdf.new_page(width=360,height=480)
            page.insert_text((30,65),'Alpha points to beta.')
            page.insert_text((30,110),'Ada Scholar: a synthetic scholarly attribution.')
            pdf.set_metadata({'title':'Neutral Handbook','author':'Ada Scholar'})
            pdf.save(self.book)
        self.source_hash=v.digest(self.book)
        self.sid='src-'+self.source_hash[:16]
        source_path=self.book.relative_to(self.root).as_posix()
        v.write(v.BASE/'sources/sources.json',[{'source_id':self.sid,'sha256':self.source_hash,
            'path':source_path,'aliases':[source_path],'role':'textbooks','pdf_pages':1,
            'intake_required':True,'quality_status':'original_samples_inspected',
            'quality_record':{'fixture':'synthetic inspection only'},
            'book_identity':{'title':'Neutral Handbook by Ada Scholar','edition':'1'}}])
        objective=self.root/'Objectives/Example.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((30,65),'1. Explain the alpha route.')
            pdf.save(objective)
        obj={'id':'obj_example_1','lesson_id':'les_example','entry_kind':'objective',
             'source_path':'Objectives/Example.pdf','original_number':'1','original_order':1,
             'wording':'Explain the alpha route. (Workshop A)',
             'pbl_labels':['(Workshop A)'],'teaching_labels':['Example seminar'],
             'component_ids':['cmp_1'],'required_item_ids':['req_1']}
        lesson={'id':'les_example','filename':'Example.pdf','source_path':'Objectives/Example.pdf',
                'source_sha256':v.digest(objective)}
        v.write(v.BASE/'curriculum/objective_register.json',{'lessons':[lesson],'entries':[obj]})
        v.write(v.BASE/'curriculum/curriculum_blueprint.json',{'objective_plans':[],'relationship_edges':[]})
        w.prepare('Example.pdf','Example',practice_types=['short_answer'])
        self.pack=w.pack('Example')
        anki_preferences.configure(self.pack,course='Café Studies',lesson='Example Lesson',use_defaults=True)
        self.content=v.read(self.pack/'content.json')
        self.content.update(authors=['fixture-author'],authoring_models={
            'fixture-author':{'model':'fixture-model','reasoning':'fixture-effort',
                              'configuration_check':'Synthetic test declaration; no model was run.'}},
            quantity_rationale='One neutral question and card exercise only the delivery contract.')
        sentence='Alpha points to beta.'
        support={'text':sentence,'support':{'evidence_id':'evidence-1','passage':sentence}}
        common={'evidence_ids':['evidence-1'],'objective_ids':['obj_example_1']}
        self.content['chapters'][0].update(title='Alpha connections',teaching_approach='Synthetic relation',
            sections=[{'id':'connections','title':'Connections','blocks':[
                {'id':'block-1','type':'paragraph','text':sentence,'claims':[support],**common}]}])
        self.content['saqs']=[{'id':'question-1','prompt':'Explain the alpha route.','marks':1,
            'marking_points':[{'text':sentence,'marks':1}],'explanation':sentence,'guide_blocks':['block-1'],
            'claims':[{'text':'Explain the alpha route.','exempt':'instruction'},support,support],**common}]
        self.content['cards']=[{'id':'card-1','front':'Where does alpha point?','back':sentence,'tags':['Connections'],
            'claims':[{'text':'Where does alpha point?','exempt':'instruction'},support],**common}]
        coverage=v.read(self.pack/'coverage.json')
        coverage['chapters'][0].update(complete_wording_interpretation='Synthetic complete route.',depth_rationale='Fixture only.')
        for component in coverage['chapters'][0]['components']:
            component.update(requirement='The alpha route',guide_blocks=['block-1'],evidence_ids=['evidence-1'],
                             completion_test='Explain the synthetic route.',status='covered')
        self.evidence={'evidence-1':{'source_id':self.sid,'source_sha256':self.source_hash,'pdf_page':1,
            'passages':[sentence],'context':'Complete neutral original sentence','limitations':[]}}
        for name,value in [('content.json',self.content),('coverage.json',coverage),('evidence.json',self.evidence)]:
            v.write(self.pack/name,value)
        self.build=production.build(self.pack,test=True)
        receipt=production.review_request(self.pack)
        axes={axis:'pass' for axis in receipt['required_axes']}
        receipt.update(kind='synthetic_test',status='pass',fresh_context=True,unresolved_findings=[],guide_only_assessed=True,
            reviewer={'id':'fixture-reviewer','model':'fixture-model','reasoning':'fixture-effort'},
            reviewed_records=[row['id'] for row in w.records(self.content)],verdicts=axes,
            independent_searches=[{'query':'alpha','result':'Synthetic fixture only'}],
            original_pages_inspected=[{'source_id':self.sid,'pdf_pages':[1]}],
            claim_binding_assessment='Synthetic binding fixture only.')
        receipt['selection_review']['verdict']='pass'
        for chapter in receipt['chapters']:
            chapter.update(**axes,teaching_approach_assessment='Fixture only.',complete_wording_assessment='Fixture only.')
            for component in chapter['components']:
                component.update(**axes,rationale='Fixture only.',evidence_assessment='Synthetic original.')
        v.write(self.pack/'review/independent.json',receipt)
        self.allowed=learner_export.allowlist(self.content)
        self.prefix='../../'+quote(source_path,safe='/')+'#page=1'

    def assert_links(self,folder,root):
        for file in folder.glob('*.html'):
            for href in qa.Links(file.read_text(encoding='utf-8')).links:
                link=urlsplit(href)
                self.assertFalse(link.scheme or link.netloc)
                target=(file.parent/unquote(link.path)).resolve() if link.path else file
                self.assertTrue(target.is_relative_to(root.resolve()),href)
                self.assertTrue(target.is_file(),href)
                current=root.resolve()
                for part in target.relative_to(current).parts:
                    self.assertIn(part,[p.name for p in current.iterdir()])
                    current/=part

    def test_flat_delivery_preserves_default_and_refreshes_catalogue(self):
        self.assertIn(self.prefix,(self.pack/'learner/objective-01.html').read_text(encoding='utf-8'))
        self.assertIsNone(v.read(self.pack/'build.json')['delivery_folder'])
        result=production.publish(self.pack,'Example-v1',test=True)
        target=self.root/result['folder']
        self.assertEqual(set(p.name for p in target.iterdir()),set(self.allowed))
        self.assertIn('output/Example-v1/objective-01.html',result['catalogue']['links'])
        self.assert_links(target,self.root)
        self.assertFalse((v.BASE/'production-gate.json').exists())
        with self.assertRaises(ValueError):production.publish(self.pack,'Example-v1',test=True)

    def test_nested_delivery_is_bound_to_build_and_exact_bytes(self):
        folder='Example-Lesson/Objective-1-v1'
        inputs=w.inputs(self.pack)
        result=production.build(self.pack,test=True,folder=folder)
        self.assertTrue(result['evidence_reused'])
        self.assertEqual(w.inputs(self.pack),inputs)
        self.assertEqual(v.read(self.pack/'build.json')['delivery_folder'],folder)
        self.assertIn('../'+self.prefix,(self.pack/'learner/objective-01.html').read_text(encoding='utf-8'))
        for wrong in ('Other-Lesson/Objective-1-v1','Flat-v1','Year/Example/Objective-1-v1'):
            with self.subTest(destination=wrong),self.assertRaises(ValueError):
                production.publish(self.pack,wrong,test=True)
        self.assertFalse((self.root/'output').exists())
        result=production.publish(self.pack,folder,test=True)
        target=self.root/result['folder']
        self.assertEqual(export_privacy.check_files(target,self.allowed),
                         export_privacy.check_files(self.pack/'learner',self.allowed))
        self.assert_links(target,self.root)
        self.assertTrue((self.root/'output/Example-Lesson/navigation.html').is_file())
        page=(self.root/'output/Example-Lesson/navigation.html').read_text(encoding='utf-8')
        self.assertIn('Objective 1 · Alpha connections',page)
        self.assertIn('Objective-1-v1/objective-01.html',page)
        self.assertTrue(production.build(self.pack,test=True)['evidence_reused'])
        self.assertEqual(delivery_paths.configured_folder(self.pack),folder)

    def test_destination_changes_invalidate_cached_acceptance(self):
        production.build(self.pack,test=True,folder='First/Objective-v1')
        first=production.check(self.pack,test=True)
        old_key=v.read(self.pack/'validation/artifacts.json')['key']
        receipt=(self.pack/'review/independent.json').read_bytes()
        self.assertTrue(production.check(self.pack,test=True)['reused'])
        v.write(self.pack/'delivery.json',{'folder':'Second/Objective-v1'})
        with self.assertRaisesRegex(ValueError,'Delivery location changed'):production.check(self.pack,test=True)
        qa.validate(self.pack)
        self.assertNotEqual(v.read(self.pack/'validation/artifacts.json')['key'],old_key)
        production.build(self.pack,test=True)
        second=production.check(self.pack,test=True)
        self.assertNotEqual(first['validation_key'],second['validation_key'])
        self.assertEqual((self.pack/'review/independent.json').read_bytes(),receipt)
        (self.pack/'delivery.json').unlink()
        with self.assertRaisesRegex(ValueError,'Delivery location changed'):production.check(self.pack,test=True)

    def test_unbound_nested_and_explicit_flat_mismatches_are_rejected(self):
        with self.assertRaises(ValueError):production.publish(self.pack,'Group/Example',test=True)
        production.build(self.pack,test=True,folder='Explicit-v1')
        with self.assertRaises(ValueError):production.publish(self.pack,'Other-v1',test=True)
        production.publish(self.pack,'Explicit-v1',test=True)

    def test_qa_rejects_wrong_depth_wrong_source_and_wrong_page(self):
        production.build(self.pack,test=True,folder='Year/Example/Objective-v1')
        chapter=self.pack/'learner/objective-01.html'
        original=chapter.read_text(encoding='utf-8')
        correct='../../'+self.prefix
        self.assertIn(correct,original)
        for wrong in (self.prefix,'../'+self.prefix,correct.replace('Textbooks/','Objectives/'),
                      correct.replace('#page=1','#page=2'),'/'+correct,'https://example.invalid/book.pdf#page=1'):
            with self.subTest(link=wrong):
                chapter.write_text(original.replace(correct,wrong),encoding='utf-8')
                with self.assertRaises((ValueError,KeyError)):qa.artifacts(self.pack)
        chapter.write_text(original,encoding='utf-8')
        self.assertEqual(qa.artifacts(self.pack)['status'],'pass')

    def test_path_helper_invalidates_html_checks_but_reuses_evidence(self):
        before=w.engine();inputs=w.inputs(self.pack)
        helper=self.root/'scripts/delivery_paths.py'
        helper.write_bytes(helper.read_bytes()+b'\n# Synthetic code-change fixture.\n')
        after=w.engine()
        self.assertNotEqual(before['html'],after['html'])
        self.assertNotEqual(before['validation'],after['validation'])
        self.assertEqual(before['evidence'],after['evidence'])
        with self.assertRaises(ValueError):production.check(self.pack,test=True)
        self.assertTrue(production.build(self.pack,test=True)['evidence_reused'])
        self.assertEqual(w.inputs(self.pack),inputs)

    def test_relocation_preserves_links_only_with_checked_relative_layout(self):
        folder='Example-Lesson/Objective-1-v1'
        production.build(self.pack,test=True,folder=folder)
        production.publish(self.pack,folder,test=True)
        portable=self.root/'Copied project café'
        shutil.copytree(self.root/'Textbooks',portable/'Textbooks')
        destination=portable/'output'/folder
        shutil.copytree(self.root/'output'/folder,destination)
        self.assert_links(destination,portable)
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in destination.iterdir()}
        moved=portable/'output/Deeper'/folder
        moved.parent.mkdir(parents=True)
        destination.rename(moved)
        spec=importlib.util.spec_from_file_location('fixture_navigation',self.root/'regenerate_study_guide.py')
        generator=importlib.util.module_from_spec(spec);spec.loader.exec_module(generator)
        generator.refresh(portable)
        self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in moved.iterdir()},before)
        href=next(link for link in qa.Links((moved/'objective-01.html').read_text(encoding='utf-8')).links if 'Textbooks/' in link)
        self.assertFalse((moved/unquote(urlsplit(href).path)).resolve().is_file())

    def test_export_projection_metadata_and_archive_boundaries(self):
        baseline=export_privacy.check_files(self.pack/'learner',self.allowed)
        projected=copy.deepcopy(self.content)
        projected['user_profile']={'name':'FixturePrivate','home':'C:/Users/FixturePrivate','session':'fixture-session'}
        projected['claude_runtime']={'system_prompt':'Synthetic internal prompt','reviewer_settings':{'model':'private-fixture-model'},
            'usage_records':[{'tokens':123}],'checkpoint':{'stage':'review'},'internal_manifest':{'private':True},
            'engineering_notes':'Synthetic internal notes'}
        projected['chapters'][0]['sections'][0]['blocks'][0]['personal_feedback']='Fixture private feedback'
        ledger=v.read(self.pack/'citation-occurrences.json')
        learner_export.render(self.pack/'learner',projected,ledger,{},v.read(self.pack/'scope.json'),self.pack)
        self.assertEqual(export_privacy.check_files(self.pack/'learner',self.allowed),baseline)
        chapter=(self.pack/'learner/objective-01.html').read_text(encoding='utf-8')
        self.assertIn('Ada Scholar',chapter);self.assertIn('Example seminar',chapter)
        self.assertIn('Café_Studies',(self.pack/'learner/anki.tsv').read_text(encoding='utf-8'))
        with fitz.open(self.pack/'learner/evidence-unmarked.pdf') as pdf:
            self.assertIn('Ada Scholar',pdf[0].get_text())
            self.assertTrue(all(not pdf.metadata.get(k) for k in ('author','creator','producer','creationDate','modDate')))
        image=Image.new('RGB',(4,4),'white');buffer=io.BytesIO();metadata=PngImagePlugin.PngInfo()
        metadata.add_text('author','FixturePrivate');image.save(buffer,format='PNG',pnginfo=metadata)
        clean=export_privacy.clean_png(buffer.getvalue())
        self.assertNotIn(b'FixturePrivate',clean)
        self.assertEqual(Image.open(io.BytesIO(clean)).tobytes(),image.tobytes())
        for name in ('diagnostics.txt','delivery.json','review.json'):
            extra=self.pack/'learner'/name;extra.write_text('Internal fixture',encoding='utf-8')
            with self.assertRaises(ValueError):production.publish(self.pack,'Rejected',test=True)
            extra.unlink()
        production.publish(self.pack,'Example-v1',test=True)
        archive=self.root/'output/Example.zip'
        export_privacy.archive_bytes(self.root/'output/Example-v1',archive,self.allowed)
        with zipfile.ZipFile(archive) as opened:
            self.assertEqual(set(opened.namelist()),{'Example-v1/'+name for name in self.allowed})
            for info in opened.infolist():
                self.assertEqual(info.date_time,(1980,1,1,0,0,0))
                self.assertEqual(opened.read(info), (self.pack/'learner'/Path(info.filename).name).read_bytes())
        self.assertEqual(v.digest(self.book),self.source_hash)

    def test_real_route_rejects_synthetic_or_missing_review(self):
        with self.assertRaises(ValueError):production.publish(self.pack,'Not-approved')
        (self.pack/'review/independent.json').unlink()
        with self.assertRaises(FileNotFoundError):production.publish(self.pack,'Not-reviewed',test=True)
        self.assertFalse((self.root/'output').exists())

    def test_rejection_revision_and_host_switch_preserve_exact_acceptance_boundary(self):
        import host_runtime
        import review_handoff
        # All decisions below are explicit test fixtures, never model judgments.
        for name in review_handoff.READ:
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((Path(__file__).resolve().parents[1]/name).read_bytes())
        first=review_handoff.create(self.pack)
        accepted=v.read(self.pack/'review/independent.json')
        rejected=copy.deepcopy(accepted)
        rejected.update(status='needs_revision',unresolved_findings=['Synthetic revision required'])
        v.write(self.pack/'review/independent.json',rejected)
        with self.assertRaises(ValueError):production.publish(self.pack,'Rejected',test=True)
        self.assertFalse((self.root/'output').exists())
        before_inputs=w.inputs(self.pack)
        self.content['chapters'][0]['title']='Revised alpha connections'
        v.write(self.pack/'content.json',self.content)
        changes=review_handoff.changes(self.pack,first['version'])
        self.assertNotEqual(changes['status'],'unchanged_not_approval')
        v.write(self.pack/'review/independent.json',accepted)
        production.build(self.pack,test=True)
        with self.assertRaises(ValueError):production.check(self.pack,test=True)
        # Bind a fresh synthetic reviewer receipt to the revision, then verify
        # changing host routing alone leaves that content/dependency binding intact.
        refreshed=production.review_request(self.pack)
        accepted['inputs']=refreshed['inputs']
        accepted['selection_review']=refreshed['selection_review']
        accepted['selection_review']['verdict']='pass'
        self.assertNotEqual(accepted['inputs'],before_inputs)
        v.write(self.pack/'review/independent.json',accepted)
        receipt=(self.pack/'review/independent.json').read_bytes()
        inputs=w.inputs(self.pack)
        host_runtime.select(self.root,'claude')
        self.assertEqual(w.inputs(self.pack),inputs)
        self.assertEqual((self.pack/'review/independent.json').read_bytes(),receipt)
        production.check(self.pack,test=True)
        publication=production.publish(self.pack,'Revised-v1',test=True)
        folder=self.root/publication['folder']
        before={p.name:p.read_bytes() for p in folder.iterdir()}
        host_runtime.select(self.root,'codex')
        self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()})
        self.assertFalse((v.BASE/'production-gate.json').exists())

    def test_public_build_cli_forwards_folder(self):
        with patch.object(sys,'argv',['pipeline.py','build','Example','--folder','Group/Example-v1']), \
             patch.object(production,'build',return_value={'evidence':{}}) as build,contextlib.redirect_stdout(io.StringIO()):
            production.main()
        build.assert_called_once_with(self.pack,folder='Group/Example-v1')


if __name__=='__main__':unittest.main()
