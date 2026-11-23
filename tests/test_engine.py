import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import engine  # noqa: E402
import sheets  # noqa: E402
from common import ID_PLACEHOLDER, find_brands, load_looks, load_settings, get_niche  # noqa: E402

SAMPLE = json.loads((ROOT / "tests" / "fixtures" / "sample_concepts.json").read_text(encoding="utf-8"))


def sample():
    return copy.deepcopy(SAMPLE["concepts"][0])


EMPTY_USED = {"concept_names": [], "visual_metaphors": []}


class TestBrandFilter(unittest.TestCase):
    def test_catches_brands_whole_word_case_insensitive(self):
        self.assertEqual(find_brands("Runs on NVIDIA chips and AWS"), ["aws", "nvidia"])
        self.assertEqual(find_brands("a Vision Pro style headset"), ["vision pro"])
        self.assertEqual(find_brands("like GPT-4 and gpt-4o"), ["gpt-4", "gpt-4o"])

    def test_no_false_positives_inside_words(self):
        self.assertEqual(find_brands("artificial intelligence pineapple metadata appleton"), [])
        self.assertEqual(find_brands("amdocs integral cloud meta data"), [])

    def test_brand_concept_rejected(self):
        c = sample()
        c["trend_hook"] = "Inspired by the latest Microsoft security launch"
        acc, rej, _ = engine.check_concepts([c], EMPTY_USED, 5)
        self.assertEqual(acc, [])
        self.assertIn("brand terms: microsoft", rej[0]["reasons"][0])

    def test_brand_in_nested_field_rejected(self):
        c = sample()
        c["timeline"][1]["action"] += " like a Tesla"
        c["search_keywords"][0] = "bitcoin"
        _, rej, _ = engine.check_concepts([c], EMPTY_USED, 5)
        self.assertTrue(any("bitcoin" in r and "tesla" in r for r in rej[0]["reasons"]))


class TestDedupe(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(engine.normalize_name("  Quarantine-Cell   BLOOM! "), "quarantine cell bloom")

    def test_jaccard(self):
        self.assertEqual(engine.jaccard("glass cube splits", "glass cube splits"), 1.0)
        self.assertEqual(engine.jaccard("", "anything"), 0.0)
        a = "A honeycomb of hexagonal cells seals off one tainted cell"
        b = "Hexagonal cells in a honeycomb seal off a tainted cell"
        self.assertGreaterEqual(engine.jaccard(a, b), 0.5)
        self.assertLess(engine.jaccard(a, "A paper plane folds itself into a shield"), 0.5)

    def test_stopwords_ignored(self):
        self.assertEqual(engine.content_words("The cube and the sphere"), {"cube", "sphere"})

    def test_used_name_rejected(self):
        used = {"concept_names": ["quarantine cell bloom"], "visual_metaphors": []}
        _, rej, _ = engine.check_concepts([sample()], used, 5)
        self.assertIn("already used", rej[0]["reasons"][0])

    def test_used_metaphor_rejected(self):
        used = {"concept_names": [],
                "visual_metaphors": ["Glass walls grow around a tainted cell in a hexagonal honeycomb of cells"]}
        _, rej, _ = engine.check_concepts([sample()], used, 5)
        self.assertTrue(rej and "too similar" in rej[0]["reasons"][0])

    def test_batch_duplicates_rejected(self):
        a, b = sample(), sample()
        b["slot"] = 2
        b["concept_name"] = "Totally Different Name"
        acc, rej, _ = engine.check_concepts([a, b], EMPTY_USED, 5)
        self.assertEqual(len(acc), 1)
        self.assertIn("in this batch", rej[0]["reasons"][0])

    def test_missing_fields_rejected(self):
        c = sample()
        del c["camera"]
        c["search_keywords"] = ["one", "two"]
        c["copy_space"] = "top"
        _, rej, _ = engine.check_concepts([c], EMPTY_USED, 5)
        reasons = " | ".join(rej[0]["reasons"])
        self.assertIn("'camera'", reasons)
        self.assertIn("10-15", reasons)
        self.assertIn("copy_space", reasons)

    def test_off_palette_hex_rejected(self):
        looks = load_looks()
        slots = {1: {"slot": 1, "asset_type": "hero_concept", "look": looks["looks"][2]["name"],
                     "palette": looks["looks"][2]["colors"]}}  # Indigo and Magenta
        _, rej, _ = engine.check_concepts([sample()], EMPTY_USED, 5, slots)
        self.assertIn("#1E3A8A", rej[0]["reasons"][0])
        slots[1]["palette"] = looks["looks"][5]["colors"]  # Security Red and Navy
        acc, rej, _ = engine.check_concepts([sample()], EMPTY_USED, 5, slots)
        self.assertEqual((len(acc), rej), (1, []))

    def test_valid_concept_accepted(self):
        acc, rej, _ = engine.check_concepts([sample()], EMPTY_USED, 5)
        self.assertEqual((len(acc), rej), (1, []))


class TestSlots(unittest.TestCase):
    def setUp(self):
        self.looks = load_looks()

    def test_day_number(self):
        self.assertEqual(engine.day_number(dt.date(1970, 1, 1)), 0)
        self.assertEqual(engine.day_number(dt.date(2026, 11, 16)), 20773)

    def test_formula(self):
        rot, looks = self.looks["rotation"], self.looks["looks"]
        for day in (0, 20773, 20774):
            for nid in range(1, 11):
                slots = engine.compute_slots(nid, 5, self.looks, day=day)
                for i, s in enumerate(slots):
                    self.assertEqual(s["slot"], i + 1)
                    self.assertEqual(s["asset_type"], rot[(day + nid + i) % 8])
                    self.assertEqual(s["look"], looks[(day * 3 + nid * 5 + i * 3) % 8]["name"])

    def test_known_values(self):
        s = engine.compute_slots(1, 2, self.looks, day=0)
        self.assertEqual([x["asset_type"] for x in s], ["hero_concept", "hero_3d_object"])
        self.assertEqual([x["look"] for x in s], ["Security Red and Navy", "Corporate Blue"])

    def test_rotation_varies_daily(self):
        a = engine.compute_slots(3, 5, self.looks, day=100)
        b = engine.compute_slots(3, 5, self.looks, day=101)
        self.assertNotEqual([x["asset_type"] for x in a], [x["asset_type"] for x in b])
        self.assertNotEqual([x["look"] for x in a], [x["look"] for x in b])

    def test_eight_slots_cover_all_looks(self):
        s = engine.compute_slots(2, 8, self.looks, day=5)
        self.assertEqual(len({x["look"] for x in s}), 8)


class TestRender(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()
        self.looks = load_looks()
        self.niche = get_niche(7)
        self.template = engine.load_template()
        self.slot = engine.compute_slots(7, 1, self.looks, day=0)[0]

    def render(self, c):
        return engine.render_prompt(c, self.slot, self.niche, self.settings, self.looks, self.template)

    def test_exact_structure(self):
        p = self.render(sample())
        lines = p.splitlines()
        self.assertEqual(lines[0], f"=== PROMPT {ID_PLACEHOLDER} ===")
        self.assertEqual(lines[1], "Title: Quarantine Cell Bloom")
        self.assertEqual(lines[2], f"Niche: Cybersecurity | Asset type: {self.slot['asset_type_label']}")
        self.assertTrue(lines[3].startswith("Buyer use: "))
        self.assertTrue(lines[4].startswith("Trend: "))
        for header in ["CONCEPT", "CAMERA", "COLOR & LIGHTING (on pure white #FFFFFF)", "MOTION", "BUILD SPECS"]:
            self.assertIn(header, lines)
        self.assertIn("TIMELINE (15s @ 30fps = 450 frames)", lines)
        self.assertIn("- 0-4s: Slab rests in navy", p)
        self.assertIn("Copy space: none (subject may use the full frame with balanced negative space)", p)
        self.assertIn(f'- Composition id "Asset{ID_PLACEHOLDER}", 3840x2160, 30fps, durationInFrames 450; '
                      f"code in src/assets/{ID_PLACEHOLDER}/.", p)
        self.assertIn(f"npx remotion render Asset{ID_PLACEHOLDER} output/{ID_PLACEHOLDER}.mp4 --codec=h264 "
                      "--crf=16 --pixel-format=yuv420p --color-space=bt709", p)
        self.assertIn("frame 450 must equal frame 0", p)
        self.assertIn("@remotion/three", p)
        self.assertTrue(lines[-1].startswith("KEYWORDS: ransomware containment, endpoint isolation"))
        palette = engine.palette_text(self.slot["palette"])
        self.assertIn(f"Palette ({self.slot['look']}): {palette}", p)
        self.assertIn("Lighting: Soft studio key light from top-left.", p)
        self.assertNotRegex(p, r"\{\w+\}")

    def test_build_3d_false_drops_line(self):
        c = sample()
        c["build_3d"] = False
        p = self.render(c)
        self.assertNotIn("@remotion/three", p)
        self.assertNotIn("- \n", p)

    def test_copy_space_text(self):
        c = sample()
        c["copy_space"] = "Left third"
        self.assertIn("Copy space: left third stays clean pure white so buyers can add their own title",
                      self.render(c))

    def test_braces_in_content_not_expanded(self):
        c = sample()
        c["camera"] = "pan {frames} wide {ID}"
        self.assertIn("pan {frames} wide {ID}", self.render(c))


class TestSheetsHelpers(unittest.TestCase):
    def test_header_map_case_space_insensitive(self):
        headers = ["ID ", "Niche  Category", "prompt", "STATUS", "Adobe Status", "SS_Status ", "Filename",
                   "Date_Uploaded", "Title"]
        m = sheets.header_map(headers, sheets.MAIN_COLS, "Prompt-Rendering")
        self.assertEqual(m["ID"], 0)
        self.assertEqual(m["Adobe_Status"], 4)
        self.assertEqual(m["SS_Status"], 5)

    def test_header_map_missing(self):
        from common import UserError
        with self.assertRaises(UserError) as ctx:
            sheets.header_map(["ID", "Prompt"], sheets.MAIN_COLS, "Prompt-Rendering")
        self.assertIn("Status", str(ctx.exception))

    def test_max_id(self):
        self.assertEqual(sheets.max_id_from_column(["ID", "5", "", "abc", "917", "12.0", "3"]), 917)
        self.assertEqual(sheets.max_id_from_column(["ID"]), 0)

    def test_build_rows_fills_ids(self):
        prompts = {"niche": "Cybersecurity", "items": [
            {"prompt": f"=== PROMPT {ID_PLACEHOLDER} ===\nAsset{ID_PLACEHOLDER}", "concept_name": "A B",
             "visual_metaphor": "m1", "asset_type": "hero_concept", "look": "Ocean Gradient", "trend_hook": "t"},
            {"prompt": f"=== PROMPT {ID_PLACEHOLDER} ===", "concept_name": "C D", "visual_metaphor": "m2"}]}
        main_map = sheets.header_map(sheets.MAIN_COLS + ["Title"], sheets.MAIN_COLS, "m")
        used_map = sheets.header_map(sheets.USED_COLS, sheets.USED_COLS, "u")
        main, used, assigned = sheets.build_rows(prompts, 918, 8, main_map, 8, used_map, "2026-11-16")
        self.assertEqual(main[0], [918, "Cybersecurity", "=== PROMPT 918 ===\nAsset918", "Pending", "Pending",
                                   "Pending", "918.mp4", ""])
        self.assertEqual(main[1][0], 919)
        self.assertEqual(used[0], ["Cybersecurity", "A B", "m1", "hero_concept", "Ocean Gradient", "t", 918,
                                   "2026-11-16"])
        self.assertEqual([a["id"] for a in assigned], [918, 919])


if __name__ == "__main__":
    unittest.main()
