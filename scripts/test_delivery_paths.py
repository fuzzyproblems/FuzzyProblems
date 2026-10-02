"""Portable destination validation using only disposable synthetic folders."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import delivery_paths
import pipeline_core as v


class DeliveryPathTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='delivery café ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        self.pack=self.root/'packs/Example'
        self.pack.mkdir(parents=True)
        for patcher in (patch.object(v,'ROOT',self.root),patch.dict(os.environ,{'STUDY_DIAGNOSTICS':'0'})):
            patcher.start();self.addCleanup(patcher.stop)

    def configure(self,value):
        (self.pack/'delivery.json').write_text(json.dumps(value),encoding='utf-8')

    def test_flat_default_and_nested_depths(self):
        self.assertIsNone(delivery_paths.configured_folder(self.pack))
        self.assertEqual(delivery_paths.source_prefix(self.pack),'../../')
        for folder in ('Example-v1','Example-Lesson/Objective-1-v1','Year/Example/Objective-v2'):
            with self.subTest(folder=folder):
                self.configure({'folder':folder})
                self.assertEqual(delivery_paths.configured_folder(self.pack),folder)
                self.assertEqual(delivery_paths.target(folder),self.root/'output'/folder)
                self.assertEqual(delivery_paths.source_link(self.pack,'Textbooks/Example.pdf'),
                                 '../'*(folder.count('/')+2)+'Textbooks/Example.pdf')

    def test_reject_unsafe_destination_components(self):
        for folder in (None,4,'','/Absolute','C:/Absolute','//server/share','Group//Objective',
                       'Group/','./Objective','Group/../Objective','Group/./Objective',
                       'Group\\Objective','Group/CON','Group/con.html','Group/NUL',
                       'Group/LPT9','Group/Objective.','Group/Objective ','Group/has space',
                       'Group/%2e%2e','Group/Objective?x=1','Group/Objective#anchor'):
            with self.subTest(folder=folder),self.assertRaises(ValueError):
                delivery_paths.target(folder)
        self.assertFalse((self.root/'output').exists())

    def test_case_conflicts_and_regular_file_ancestors(self):
        output=self.root/'Output';output.mkdir()
        with self.assertRaises(ValueError):delivery_paths.target('Example')
        output.rename(self.root/'output')
        (self.root/'output/Group').mkdir()
        with self.assertRaises(ValueError):delivery_paths.target('group/Example')
        (self.root/'output/Group/Leaf').write_text('Preserved',encoding='utf-8')
        for name in ('Group/Leaf','Group/Leaf/Example'):
            with self.assertRaises(ValueError):delivery_paths.target(name)
        self.assertEqual((self.root/'output/Group/Leaf').read_text(),'Preserved')

    def test_configuration_is_strict_and_internal(self):
        for config in ([],{}, {'folder':'Example','machine':'extra'}, {'folder':'../escape'}, {'folder':None}):
            self.configure(config)
            with self.assertRaises(ValueError):delivery_paths.configured_folder(self.pack)
        (self.pack/'delivery.json').unlink()
        (self.pack/'delivery.json').mkdir()
        with self.assertRaises(ValueError):delivery_paths.configured_folder(self.pack)

    def test_symlinks_and_dangling_links_cannot_redirect_destinations(self):
        outside=self.root/'outside';outside.mkdir()
        output=self.root/'output';output.mkdir()
        try:(output/'Linked').symlink_to(outside,target_is_directory=True)
        except (OSError,NotImplementedError):self.skipTest('Symlink creation unavailable on this host')
        (output/'Dangling').symlink_to(self.root/'absent',target_is_directory=True)
        for folder in ('Linked/Example','Dangling/Example'):
            with self.assertRaises(ValueError):delivery_paths.target(folder)
        (self.pack/'delivery.json').symlink_to(self.root/'absent.json')
        with self.assertRaises(ValueError):delivery_paths.configured_folder(self.pack)
        self.assertEqual(list(outside.iterdir()),[])

    def test_junction_ancestors_are_rejected(self):
        boundary=self.root/'output/Group'
        with patch.object(Path,'is_junction',lambda path:path==boundary,create=True):
            with self.assertRaises(ValueError):delivery_paths.target('Group/Example')


if __name__=='__main__':unittest.main()
