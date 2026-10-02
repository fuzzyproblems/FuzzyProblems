"""Real local OCR on generated pages; no model transcription or original PDFs."""
from pathlib import Path
import tempfile
import unittest

import fitz
import bootstrap as b


class RuntimeTests(unittest.TestCase):
    def test_rotated_local_ocr_and_blank_page(self):
        try:runtime=b.dependencies('auto')
        except ValueError:self.skipTest('Local Tesseract/language data unavailable')
        with tempfile.TemporaryDirectory(prefix='local OCR café ') as temporary:
            root=Path(temporary).resolve()
            (root/'Textbooks').mkdir();stage=root/'cache';stage.mkdir()
            original=root/'Textbooks/Neutral OCR.pdf'
            with fitz.open() as donor:
                page=donor.new_page(width=450,height=160)
                page.insert_text((30,80),'LOCAL OCR TEST 123',fontsize=26)
                png=page.get_pixmap(dpi=180).tobytes('png')
            with fitz.open() as pdf:
                page=pdf.new_page(width=450,height=160);page.insert_image(page.rect,stream=png)
                page.set_rotation(90);pdf.new_page(width=450,height=160);pdf.save(original)
            before=b.sha(original)
            source={'source_id':'fixture-ocr','path':'Textbooks/Neutral OCR.pdf','sha256':before}
            config=b.read(b.ROOT/'bootstrap-settings.json')['ocr']
            record=b.read(stage/b.recognize((root,stage,source,1,config,runtime)))
            self.assertIn('LOCAL OCR TEST 123',record['text'])
            self.assertFalse(record['geometry_reviewed']);self.assertEqual(record['factual_review'],'unreviewed')
            for word in record['words']:
                x0,y0,x1,y1=word['bbox_original_unrotated']
                self.assertTrue(0<=x0<x1<=450 and 0<=y0<y1<=160)
            blank=b.read(stage/b.recognize((root,stage,source,2,config,runtime)))
            self.assertEqual(blank['status'],'empty');self.assertEqual(b.sha(original),before)


if __name__=='__main__':unittest.main()
