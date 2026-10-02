"""Portable catalogue fixtures; no lesson content or project runtime required."""
import json
import contextlib
import io
import importlib.util
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.hrefs = []; self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(value for key, value in attrs if key == 'href')


class StudyGuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Copied library caf\u00e9 & #1'
        self.output = self.root / 'output'
        self.output.mkdir(parents=True)
        self.script = self.root / 'regenerate_study_guide.py'
        shutil.copy2(Path(__file__).resolve().parents[1] / 'regenerate_study_guide.py', self.script)
        spec = importlib.util.spec_from_file_location('navigation_fixture', self.script)
        self.generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.generator)

    def lesson(self, name, heading='Fixture &amp; heading'):
        folder = self.output / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'index.html').write_text('<h1>' + heading + '</h1>', encoding='utf-8')
        return folder

    def refresh(self):
        # Isolated mode, no site packages and an unrelated cwd prove portability.
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(self.script)],
                                cwd=self.root.parent, capture_output=True, text=True, encoding='utf-8', check=True)
        return json.loads(result.stdout)

    def page(self, relative='StudyGuide.html'):
        return (self.root / relative).read_text(encoding='utf-8')

    def links(self, relative='StudyGuide.html'):
        return Links(self.page(relative)).hrefs

    def assert_links_resolve(self, result):
        for relative in result['navigation_pages']:
            page = self.root / unquote(relative)
            for link in Links(page.read_text(encoding='utf-8')).hrefs:
                self.assertFalse(urlsplit(link).scheme)
                self.assertNotIn('\\', link)
                self.assertNotIn(' ', link)
                target = (page.parent / unquote(link)).resolve()
                self.assertTrue(target.is_relative_to(self.root.resolve()), link)
                self.assertTrue(target.is_file(), link)
                # Check exact case even on a case-insensitive filesystem.
                current = self.root.resolve()
                for part in target.relative_to(current).parts:
                    self.assertIn(part, [p.name for p in current.iterdir()])
                    current /= part

    def test_discovery_versions_escaping_and_idempotence(self):
        self.lesson('Example-v2')
        self.lesson('Example-v10', '<em>Latest</em> &lt;safe&gt;')
        self.lesson('Caf\u00e9 & #1')
        self.lesson('.hidden')
        (self.output / 'unfinished').mkdir()
        (self.output / 'archive.zip').write_bytes(b'ignored')
        result = self.refresh()
        self.assertEqual(result['versions'], 3)
        self.assertEqual(result['lesson_or_objective_groups'], 2)
        page = self.root / 'StudyGuide.html'
        text = page.read_text(encoding='utf-8')
        self.assertIn('Latest &lt;safe&gt;', text)
        self.assertIn('Fixture &amp; heading', text)
        self.assertLess(text.index('href="output/Example-v10/index.html"'), text.index('href="output/Example-v2/index.html"'))
        for link in result['links']:
            self.assertTrue((self.root / unquote(link)).is_file())
            self.assertTrue(link.startswith('output/'))
        before = (page.read_bytes(), page.stat().st_mtime_ns)
        self.assertEqual(self.refresh(), result)
        self.assertEqual((page.read_bytes(), page.stat().st_mtime_ns), before)
        self.assertFalse((self.output / 'StudyGuide.html').exists())
        self.assert_links_resolve(result)


    def test_natural_objective_order_on_initial_and_repeated_generation(self):
        parents = ('', 'Year2/Lesson3', 'Year2/Lesson3/Section4')

        def add(number, version):
            for parent in parents:
                folder = self.lesson(str(Path(parent) / f'Objective-{number}-v{version}'))
                chapter = f'objective-{number:02d}.html'
                (folder / chapter).write_text('<h1>Example</h1>', encoding='utf-8')
                (folder / 'index.html').write_text(
                    '<ol class="lesson-chapters"><li>'
                    f'<a href="{chapter}">Objective {number} · Example</a>'
                    '</li></ol>', encoding='utf-8')

        for number, version in ((17, 2), (3, 1), (24, 1), (1, 1), (17, 10), (2, 1), (17, 1)):
            add(number, version)
        for numbers in ((1, 2, 3, 17, 24), (1, 2, 3, 10, 17, 24)):
            if 10 in numbers:
                add(10, 1)
            result = self.refresh()
            for parent in parents:
                page = f'output/{parent}/navigation.html' if parent else 'StudyGuide.html'
                prefix = '' if parent else 'output/'
                expected = [
                    f'{prefix}Objective-{number}-v{version}/objective-{number:02d}.html'
                    for number in numbers for version in ((10, 2, 1) if number == 17 else (1,))
                ]
                self.assertEqual([link for link in self.links(page) if '/objective-' in link], expected)
            self.assert_links_resolve(result)
        pages = {p: ((self.root / p).read_bytes(), (self.root / p).stat().st_mtime_ns)
                 for p in result['navigation_pages']}
        self.assertEqual(self.refresh(), result)
        for p, before in pages.items():
            self.assertEqual(((self.root / p).read_bytes(), (self.root / p).stat().st_mtime_ns), before)

    def test_natural_group_order_at_every_depth_with_own_guide(self):
        for year in (10, 2):
            self.lesson(f'Year{year}')
            for lesson in (10, 2):
                self.lesson(f'Year{year}/Lesson{lesson}/Objective-1')
        result = self.refresh()
        self.assertEqual(self.links(), ['output/Year2/navigation.html', 'output/Year10/navigation.html'])
        for year in (2, 10):
            links = self.links(f'output/Year{year}/navigation.html')
            self.assertEqual([link for link in links if not link.startswith('../')],
                             ['index.html', 'Lesson2/navigation.html', 'Lesson10/navigation.html'])
        self.assert_links_resolve(result)

    def test_natural_order_keeps_index_fallback_and_handles_numeric_text_ties(self):
        names = ('Objective-17', 'Objective-2', 'Objective-02', 'Objective-3', 'Square²')
        for name in names:
            self.lesson(name)
        result = self.refresh()
        expected = ('Objective-02', 'Objective-2', 'Objective-3', 'Objective-17', 'Square²')
        self.assertEqual([unquote(link) for link in self.links()],
                         [f'output/{name}/index.html' for name in expected])
        self.assert_links_resolve(result)

    def test_recursive_mixed_tree_and_breadcrumbs(self):
        self.lesson('OBJECTIVE1')
        self.lesson('Year1/Lesson1/OBJECTIVE2')
        self.lesson('Year1/Lesson1/GroupA/OBJECTIVE3')
        result = self.refresh()
        self.assertEqual(result['versions'], 3)
        self.assertEqual(set(self.links()), {'output/OBJECTIVE1/index.html', 'output/Year1/navigation.html'})
        self.assertEqual(set(result['navigation_pages']), {
            'StudyGuide.html', 'output/Year1/navigation.html',
            'output/Year1/Lesson1/navigation.html', 'output/Year1/Lesson1/GroupA/navigation.html'})
        year = self.links('output/Year1/navigation.html')
        self.assertIn('../../StudyGuide.html', year)
        self.assertIn('Lesson1/navigation.html', year)
        lesson = self.links('output/Year1/Lesson1/navigation.html')
        self.assertIn('../../../StudyGuide.html', lesson)
        self.assertIn('../navigation.html', lesson)
        self.assertIn('OBJECTIVE2/index.html', lesson)
        self.assertIn('GroupA/navigation.html', lesson)
        self.assertNotIn('GroupA/OBJECTIVE3/index.html', lesson)
        self.assert_links_resolve(result)

    def test_single_objective_links_directly_at_each_depth(self):
        for name in ('Objective-v1', 'Year/Lesson/Objective-v2'):
            folder = self.lesson(name, 'Course heading')
            (folder / 'objective-01.html').write_text('<h1>Chapter</h1>', encoding='utf-8')
            (folder / 'index.html').write_text(
                '<h1>Course heading</h1><ol class="lesson-chapters"><li>'
                '<a href="objective-01.html">Objective 1 · Alpha connections &amp; comparisons</a>'
                '</li></ol>', encoding='utf-8')
        result = self.refresh()
        self.assertIn('output/Objective-v1/objective-01.html', self.links())
        deep = self.page('output/Year/Lesson/navigation.html')
        self.assertIn('Objective 1 · Alpha connections &amp; comparisons', deep)
        self.assertIn('Objective-v2/objective-01.html', deep)
        self.assert_links_resolve(result)

    def test_chapter_falls_back_for_multiple_or_unsafe_links(self):
        cases = {
            'Multiple': '<li><a href="objective-01.html">Objective 1 · One</a></li><li><a href="objective-02.html">Objective 2 · Two</a></li>',
            'Traversal': '<li><a href="../escape.html">Objective 1 · One</a></li>',
            'Encoded': '<li><a href="%2e%2e.html">Objective 1 · One</a></li>',
            'Missing': '<li><a href="absent.html">Objective 1 · One</a></li>',
            'BadLabel': '<li><a href="objective-01.html">Chapter one</a></li>',
        }
        for name, items in cases.items():
            folder=self.lesson(name)
            (folder/'objective-01.html').write_text('Chapter',encoding='utf-8')
            (folder/'index.html').write_text('<h1>Course</h1><ol class="lesson-chapters">'+items+'</ol>',encoding='utf-8')
        result=self.refresh()
        self.assertEqual(set(self.links()), {f'output/{name}/index.html' for name in cases})
        self.assert_links_resolve(result)

    def test_unsafe_and_ambiguous_chapter_lists_keep_the_index(self):
        folder=self.lesson('Example')
        (folder/'objective-01.html').write_text('Chapter',encoding='utf-8')
        (folder/'directory.html').mkdir()
        link='<a href="objective-01.html">Objective 1 · Alpha</a>'
        invalid=[
            '<ol class="lesson-chapters"><li>'+link+'</li>',
            '<ol class="lesson-chapters"><li>'+link+link+'</li></ol>',
            '<ol class="lesson-chapters"><li>'+link+'</li><li></li></ol>',
            ('<ol class="lesson-chapters"><li>'+link+'</li></ol>')*2,
            '<ol class="lesson-chapters"><li><ol><li>'+link+'</li></ol></li></ol>',
            '<ol class="lesson-chapters"><div><li>'+link+'</li></div></ol>',
            '<ol class="lesson-chapters"><li><a href="objective-01.html" href="elsewhere.html">Objective 1 · Alpha</a></li></ol>',
        ]
        for target in ('https://example.invalid/objective.html','//example.invalid/a.html',
                       'file:///example.html','javascript:alert(1)','/absolute.html','C:/absolute.html',
                       '../objective-01.html','sub/objective-01.html','sub\\objective-01.html',
                       '%6fbjective-01.html','%2e%2e/escape.html','objective-01.html#section',
                       'objective-01.html?x=1','index.html','directory.html','CON.html',''):
            invalid.append('<ol class="lesson-chapters"><li><a href="'+target+'">Objective 1 · Alpha</a></li></ol>')
        for label in ('Objective 1 ·','Objective A · Alpha','Chapter 1 · Alpha','Objective 1 - Alpha'):
            invalid.append('<ol class="lesson-chapters"><li><a href="objective-01.html">'+label+'</a></li></ol>')
        invalid.append('<ol class="lesson-chapters"><li><a href>Objective 1 · Alpha</a></li></ol>')
        for text in invalid:
            with self.subTest(index=text):
                (folder/'index.html').write_text(text,encoding='utf-8')
                self.assertEqual(self.generator.refresh(self.root)['links'],['output/Example/index.html'])

    def test_direct_chapters_include_earlier_versions_and_group_own_guide(self):
        for name in ('Example-v1','Example-v2','Year/Lesson/Example-v1','Year/Lesson/Example-v2','Mixed'):
            folder=self.lesson(name)
            (folder/'objective-01.html').write_text('Chapter',encoding='utf-8')
            (folder/'index.html').write_text('<ol class="lesson-chapters"><li><a href="objective-01.html">'
                'Objective 1 · <em>Alpha &amp; beta</em></a><p>Complete wording<br>and context.</p></li></ol>',encoding='utf-8')
        self.lesson('Mixed/Child')
        result=self.refresh()
        for name in ('StudyGuide.html','output/Year/Lesson/navigation.html'):
            page=self.page(name)
            self.assertIn('Example-v1/objective-01.html',page)
            self.assertIn('Example-v2/objective-01.html',page)
            self.assertIn('Objective 1 · Alpha &amp; beta · v1',page)
        self.assertIn('href="objective-01.html"',self.page('output/Mixed/navigation.html'))
        self.assert_links_resolve(result)

    def test_diagnostics_omit_absolute_paths_and_raw_errors(self):
        self.lesson('Example')
        self.refresh()
        private_message='/Users/FixtureAccount/private C:\\Users\\FixtureAccount\\private'
        with patch.object(self.generator,'_refresh',side_effect=PermissionError(13,private_message)), self.assertRaises(PermissionError):
            self.generator.refresh(self.root)
        log=(self.output/'diagnostics.txt').read_text(encoding='utf-8')
        for value in (str(self.root),str(Path.cwd()),'FixtureAccount','Traceback','Working directory:','Resolved script:'):
            self.assertNotIn(value,log)
        self.assertIn('"category": "filesystem"',log)
        self.assertIn('"errno": 13',log)
        stderr=io.StringIO()
        with patch.object(self.generator,'refresh',side_effect=ValueError(private_message)), contextlib.redirect_stderr(stderr):
            self.assertEqual(self.generator.main(),1)
        self.assertNotIn('FixtureAccount',stderr.getvalue())
        self.assertNotIn('Traceback',stderr.getvalue())

    def test_diagnostics_write_failure_is_sanitized(self):
        stderr=io.StringIO()
        with patch.object(self.generator,'write_diagnostics',side_effect=OSError(13,'C:\\Users\\FixtureAccount\\private')), contextlib.redirect_stderr(stderr):
            self.generator.refresh(self.root)
        self.assertIn('diagnostics_write',stderr.getvalue())
        self.assertNotIn('FixtureAccount',stderr.getvalue())

    def test_cli_failure_keeps_paths_out_of_diagnostics_and_stderr(self):
        (self.root/'StudyGuide.html').write_text('Unowned page',encoding='utf-8')
        with self.assertRaises(subprocess.CalledProcessError) as result:self.refresh()
        combined=result.exception.stderr+(self.output/'diagnostics.txt').read_text(encoding='utf-8')
        self.assertNotIn(str(self.root),combined)
        self.assertNotIn('Traceback',combined)
        self.assertIn('navigation_validation',combined)

    def test_chapter_link_requires_exact_case_and_regular_file(self):
        folder=self.lesson('Case')
        (folder/'Objective-01.html').write_text('Chapter',encoding='utf-8')
        (folder/'index.html').write_text('<ol class="lesson-chapters"><li><a href="objective-01.html">Objective 1 · Example</a></li></ol>',encoding='utf-8')
        self.assertEqual(self.refresh()['links'], ['output/Case/index.html'])
        linked_folder=self.lesson('Linked')
        try:
            (linked_folder/'objective-01.html').symlink_to(folder/'Objective-01.html')
        except (OSError,NotImplementedError):
            self.skipTest('symlink creation unavailable')
        (linked_folder/'index.html').write_text('<ol class="lesson-chapters"><li><a href="objective-01.html">Objective 1 · Example</a></li></ol>',encoding='utf-8')
        self.assertEqual(set(self.refresh()['links']), {'output/Case/index.html','output/Linked/index.html'})

    def test_no_fixed_depth_limit(self):
        chain = '/'.join(f'g{n}' for n in range(25))
        self.lesson(chain + '/Objective')
        result = self.refresh()
        self.assertEqual(len(result['navigation_pages']), 26)
        self.assertEqual(self.links(), ['output/g0/navigation.html'])
        self.assert_links_resolve(result)

    def test_group_can_have_own_guide_and_children(self):
        self.lesson('Mixed', 'Its own guide')
        self.lesson('Mixed/Child')
        result = self.refresh()
        self.assertEqual(self.links(), ['output/Mixed/navigation.html'])
        page = self.page('output/Mixed/navigation.html')
        self.assertIn('Open this guide', page)
        self.assertIn('href="index.html"', page)
        self.assertIn('href="Child/index.html"', page)
        self.assertEqual(result['versions'], 2)
        self.assert_links_resolve(result)

    def test_versions_are_local_to_each_parent(self):
        self.lesson('A/Topic-objective-02-v2')
        self.lesson('A/Topic-objective-02-v10')
        self.lesson('B/Topic-objective-02-v1')
        result = self.refresh()
        self.assertEqual(result['lesson_or_objective_groups'], 2)
        self.assertEqual(set(self.links()), {'output/A/navigation.html', 'output/B/navigation.html'})
        page = self.page('output/A/navigation.html')
        self.assertIn('Objective 2 · v10', page)
        self.assertIn('Earlier versions', page)
        self.assertLess(page.index('Topic-objective-02-v10/index.html'), page.index('Topic-objective-02-v2/index.html'))
        self.assertNotIn('Earlier versions', self.page('output/B/navigation.html'))

    def test_unicode_spaces_url_characters_and_html_escaping(self):
        self.lesson("Ann\u00e9e & #1/Lesson 100%/Objectif d'\u00e9tude", '<em>Proof</em> &lt;safe&gt;')
        result = self.refresh()
        self.assertEqual(self.links(), ['output/Ann%C3%A9e%20%26%20%231/navigation.html'])
        page = self.page('output/Ann\u00e9e & #1/Lesson 100%/navigation.html')
        self.assertIn('Proof &lt;safe&gt;', page)
        self.assertIn('Ann\u00e9e &amp; #1', page)
        self.assertIn('Objectif%20d%27%C3%A9tude/index.html', page)
        self.assert_links_resolve(result)

    def test_supporting_trees_and_wrong_index_case_are_not_guides(self):
        for name in ('.hidden', 'assets', 'CACHE', 'caches', '__pycache__'):
            self.lesson('Group/' + name + '/Website')
        wrong = self.lesson('Group/WrongCase')
        (wrong / 'index.html').rename(wrong / 'Index.html')
        (self.output / 'Empty').mkdir()
        self.assertEqual(self.refresh()['versions'], 0)
        self.assertFalse((self.output / 'Group/navigation.html').exists())
        self.assertIn('expected exact filename index.html', (self.output / 'diagnostics.txt').read_text(encoding='utf-8'))

    def test_folder_changes_and_empty_catalogue(self):
        folder = self.lesson('Original')
        self.assertEqual(self.refresh()['links'], ['output/Original/index.html'])
        folder.rename(self.output / 'Renamed')
        self.assertEqual(self.refresh()['links'], ['output/Renamed/index.html'])
        shutil.copytree(self.output / 'Renamed', self.output / 'Copied')
        self.assertEqual(self.refresh()['versions'], 2)
        (self.output / 'Renamed/index.html').unlink()
        (self.output / 'Copied/index.html').unlink()
        self.assertEqual(self.refresh()['versions'], 0)
        self.assertIn('No study guides are available yet.', self.page())

    def test_moves_renames_removals_and_owned_page_cleanup(self):
        objective = self.lesson('Old/Inner/Objective')
        original = (objective / 'index.html').read_bytes()
        self.refresh()
        self.assertTrue((self.output / 'Old/Inner/navigation.html').exists())
        # Leaving an empty branch removes only its generated navigation pages.
        note = self.output / 'Old/notes.txt'; note.write_text('Keep this note.', encoding='utf-8')
        (self.output / 'New').mkdir()
        objective.rename(self.output / 'New/Objective')
        self.refresh()
        self.assertFalse((self.output / 'Old/navigation.html').exists())
        self.assertFalse((self.output / 'Old/Inner/navigation.html').exists())
        self.assertTrue(note.is_file())
        self.assertTrue((self.output / 'Old/Inner').is_dir())
        (self.output / 'New').rename(self.output / 'Renamed')
        result = self.refresh()
        self.assertEqual(self.links(), ['output/Renamed/navigation.html'])
        self.assertEqual((self.output / 'Renamed/Objective/index.html').read_bytes(), original)
        self.assert_links_resolve(result)
        (self.output / 'Renamed/Objective/index.html').unlink()
        self.assertEqual(self.refresh()['versions'], 0)
        self.assertFalse((self.output / 'Renamed/navigation.html').exists())

    def test_group_moved_into_support_tree_removes_only_owned_pages(self):
        self.lesson('Group/Objective'); self.refresh()
        (self.output / 'Group').rename(self.output / 'assets')
        self.assertEqual(self.refresh()['versions'], 0)
        self.assertFalse((self.output / 'assets/navigation.html').exists())
        self.assertTrue((self.output / 'assets/Objective/index.html').is_file())

    def test_legacy_group_pages_migrate_without_touching_user_pages(self):
        objective = self.lesson('Year/Lesson/Objective')
        legacy = self.generator.HEADER + '<html>Previous navigation</html>'
        old_pages = []
        for folder in ('', 'Year', 'Year/Lesson', 'Empty', 'assets/Old'):
            page = self.output / folder / 'StudyGuide.html'
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(legacy, encoding='utf-8')
            old_pages.append(page)
        user_page = objective / 'StudyGuide.html'
        user_page.write_bytes(b'Unrelated user page\xff')
        preserved = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in objective.iterdir()}
        result = self.refresh()
        self.assertEqual(set(result['navigation_pages']), {
            'StudyGuide.html', 'output/Year/navigation.html', 'output/Year/Lesson/navigation.html'})
        self.assertTrue(all(not p.exists() for p in old_pages))
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in objective.iterdir()}, preserved)
        self.assert_links_resolve(result)
        pages = [self.root / unquote(p) for p in result['navigation_pages']]
        unchanged = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in pages}
        self.assertEqual(self.refresh(), result)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in pages}, unchanged)

    def test_migration_collision_keeps_old_navigation_until_success(self):
        self.lesson('Year/Lesson/Objective')
        old_pages = [self.root / 'StudyGuide.html', self.output / 'Year/StudyGuide.html',
                     self.output / 'Year/Lesson/StudyGuide.html']
        legacy = (self.generator.HEADER + '<html>Previous navigation</html>').encode('utf-8')
        for page in old_pages:page.write_bytes(legacy)
        for name in ('navigation.html', 'Navigation.html'):
            with self.subTest(conflict=name):
                conflict = self.output / 'Year/Lesson' / name
                conflict.write_bytes(b'Unrelated user page\xff')
                with self.assertRaises(subprocess.CalledProcessError):self.refresh()
                self.assertTrue(all(p.read_bytes() == legacy for p in old_pages))
                self.assertFalse((self.output / 'Year/navigation.html').exists())
                self.assertEqual(conflict.read_bytes(), b'Unrelated user page\xff')
                conflict.unlink()
        result = self.refresh()
        self.assertTrue(all(not p.exists() for p in old_pages[1:]))
        self.assert_links_resolve(result)

    def test_preflight_preserves_unowned_pages_and_existing_navigation(self):
        self.lesson('Old/Objective'); self.refresh()
        before = (self.root / 'StudyGuide.html').read_bytes()
        (self.output / 'Old/Objective/index.html').unlink()
        self.lesson('New/Objective')
        conflict = self.output / 'New/navigation.html'
        conflict.write_bytes(b'Unrelated user page\xff')
        with self.assertRaises(subprocess.CalledProcessError):self.refresh()
        self.assertEqual(conflict.read_bytes(), b'Unrelated user page\xff')
        self.assertEqual((self.root / 'StudyGuide.html').read_bytes(), before)
        self.assertTrue((self.output / 'Old/navigation.html').is_file())
        # An unrelated navigation filename in an inactive branch is preserved too.
        (self.output / 'New/Objective/index.html').unlink()
        self.refresh()
        self.assertTrue(conflict.is_file())

    def test_root_page_and_case_collisions_are_protected(self):
        self.lesson('Group/Objective')
        dest = self.root / 'StudyGuide.html'; dest.write_text('User page', encoding='utf-8')
        with self.assertRaises(subprocess.CalledProcessError):self.refresh()
        self.assertEqual(dest.read_text(encoding='utf-8'), 'User page')
        self.assertFalse((self.output / 'Group/navigation.html').exists())
        dest.rename(self.root / 'studyguide.html')
        with self.assertRaises(subprocess.CalledProcessError):self.refresh()
        self.assertEqual((self.root / 'studyguide.html').read_text(encoding='utf-8'), 'User page')

    def test_case_only_sibling_collision_fails_before_writing(self):
        original = Path.iterdir
        def items(path):
            if path == self.output:
                return iter([path / 'Lesson', path / 'lesson'])
            return original(path)
        # Such a pair exists on Linux; exercise the same check on every OS.
        with patch.object(Path, 'iterdir', items):
            with self.assertRaisesRegex(ValueError, 'colliding'):
                self.generator.refresh(self.root)
        self.assertFalse((self.root / 'StudyGuide.html').exists())

    def test_missing_output_produces_empty_catalogue(self):
        self.output.rmdir()
        self.assertEqual(self.refresh()['versions'], 0)
        self.assertTrue((self.output / 'diagnostics.txt').is_file())
        self.assertIn('No study guides are available yet.', self.page())

    def test_failed_scan_does_not_prune_or_rewrite_navigation(self):
        self.lesson('Old/Objective'); self.refresh()
        before = (self.root / 'StudyGuide.html').read_bytes()
        (self.output / 'Old/Objective/index.html').unlink()
        self.lesson('Unreadable/Objective')
        original = Path.iterdir
        def items(path):
            if path == self.output / 'Unreadable':raise PermissionError('Fixture unreadable directory')
            return original(path)
        with patch.object(Path, 'iterdir', items):
            with self.assertRaises(PermissionError):self.generator.refresh(self.root)
        self.assertEqual((self.root / 'StudyGuide.html').read_bytes(), before)
        self.assertTrue((self.output / 'Old/navigation.html').is_file())

    def test_regeneration_preserves_all_objective_file_bytes_and_mtimes(self):
        objective = self.lesson('Year/Lesson/Objective')
        for name in ('practice.html', 'anki.tsv', 'evidence.pdf'):
            (objective / name).write_bytes(b'Preserve original study material\x00\xff')
        original = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in objective.iterdir()}
        self.refresh(); self.refresh()
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in objective.iterdir()}, original)

    def test_symlinks_skipped_and_catalogue_target_protected(self):
        target = self.lesson('Regular')
        try:
            (self.output / 'Linked').symlink_to(target, target_is_directory=True)
        except OSError as exc:
            self.skipTest('Symlink creation unavailable on this host')
        linked_index = self.output / 'LinkedIndex'
        linked_index.mkdir()
        (linked_index / 'index.html').symlink_to(target / 'index.html')
        self.assertEqual(self.refresh()['links'], ['output/Regular/index.html'])
        page = self.root / 'StudyGuide.html'
        page.unlink()
        page.symlink_to(target / 'index.html')
        before = (target / 'index.html').read_bytes()
        with self.assertRaises(subprocess.CalledProcessError):
            self.refresh()
        self.assertEqual((target / 'index.html').read_bytes(), before)

    def test_linked_output_is_never_scanned_or_written(self):
        outside = self.root.parent / 'Outside'; outside.mkdir()
        self.output.rmdir()
        try:self.output.symlink_to(outside, target_is_directory=True)
        except OSError as exc:self.skipTest('Symlink creation unavailable on this host')
        with self.assertRaises(subprocess.CalledProcessError):self.refresh()
        self.assertEqual(list(outside.iterdir()), [])

    def test_windows_junctions_are_skipped_and_targets_protected(self):
        folder = self.lesson('Linked/Objective')
        with patch.object(Path, 'is_junction', lambda p: p == folder.parent, create=True):
            self.assertEqual(self.generator.refresh(self.root)['versions'], 0)
        with patch.object(Path, 'is_junction', lambda p: p == self.output, create=True):
            with self.assertRaisesRegex(ValueError, 'junction'):
                self.generator.refresh(self.root)


if __name__ == '__main__':
    unittest.main()
