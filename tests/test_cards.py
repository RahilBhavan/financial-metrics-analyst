import hashlib
import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'reports/cards/cards-manifest.json').read_text())
CARDS = {card['id']: card for card in MANIFEST['cards']}


def png_size(path):
    header = path.read_bytes()[:24]
    assert header[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', header[16:24])


class CardTests(unittest.TestCase):
    def test_png_and_alt_files_match_the_manifest(self):
        for card in CARDS.values():
            png, alt = ROOT / card['png'], ROOT / card['alt_file']
            self.assertEqual(hashlib.sha256(png.read_bytes()).hexdigest(), card['sha256'])
            self.assertEqual(hashlib.sha256(alt.read_bytes()).hexdigest(), card['alt_sha256'])
            self.assertEqual(png_size(png), (1080, 1080))

    def test_alt_text_is_one_paragraph(self):
        for card in CARDS.values():
            text = (ROOT / card['alt_file']).read_text()
            self.assertEqual(text.count('\n'), 1, 'only the final newline')
            self.assertTrue(text.endswith('\n'))
            body = text.rstrip('\n')
            self.assertNotIn('  ', body)
            self.assertNotIn('..', body)

    def test_microsoft_card_states_the_ground_truth_and_parser_limit(self):
        year = json.loads((ROOT / 'data/msft/ground-truth.json').read_text())['years']['2026']
        alt = (ROOT / CARDS['ambiguity']['alt_file']).read_text()
        self.assertEqual((int(year['operating_income']), int(year['net_income'])), (155237000000, 133749000000))
        for phrase in ('$155.237B', '$133.749B', year['accession'], 'Sep 21, 2026', 'not all the meanings of profit'):
            self.assertIn(phrase, alt)

    def test_kraft_heinz_card_keeps_the_bridge_and_the_short_date(self):
        khc = json.loads((ROOT / 'data/reference-cases/khc/ground-truth.json').read_text())
        original, before, recast = (int(khc['original']['value']), int(khc['restated_before_recast']),
                                    int(khc['restated_and_recast']['value']))
        self.assertEqual((original - before, before - recast, original - recast), (80000000, 636000000, 716000000))
        alt = (ROOT / CARDS['restatement']['alt_file']).read_text()
        for phrase in ('$80M error correction', '$636M presentation change (ASU 2017-07)', '$716M', 'Jun 7, 2019',
                       'test fixture', 'not a supported issuer'):
            self.assertIn(phrase, alt)
        self.assertNotIn('June 7', alt)

    def test_design_review_is_recorded_as_pending(self):
        self.assertTrue(MANIFEST['design_review'].startswith('pending'))


if __name__ == '__main__':
    unittest.main()
