import hashlib
import json
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
SIZES = {"ambiguity-landscape.png": (1024, 640), "ambiguity-square.png": (1024, 1024)}


def png_size(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


class AmbiguityCard(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((IMAGES / "ambiguity-manifest.json").read_text())
        self.truth = json.loads((ROOT / "data" / "msft" / "ground-truth.json").read_text())["years"]["2026"]

    def test_manifest_hashes_and_sizes_match_the_committed_pngs(self):
        self.assertEqual(set(self.manifest["images"]), set(SIZES))
        for name, entry in self.manifest["images"].items():
            path = IMAGES / name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["sha256"], name)
            self.assertEqual(png_size(path), SIZES[name], name)
            self.assertEqual((entry["width"], entry["height"]), SIZES[name], name)

    def test_alt_text_states_the_card_numbers_and_source(self):
        alt = (IMAGES / self.manifest["alt_file"]).read_text()
        for key in ("operating_income", "net_income"):
            self.assertIn(f"${int(self.truth[key]) / 1e9:,.3f}B", alt)
        self.assertIn(self.truth["accession"], alt)
        self.assertIn("Sep 21, 2026", alt)

    def test_title_states_a_takeaway(self):
        title = self.manifest["title"]
        self.assertIn("two answers", title)
        self.assertLessEqual(len(title), 70)


if __name__ == "__main__":
    unittest.main()
