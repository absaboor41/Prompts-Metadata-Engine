import copy
import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import metadata as md  # noqa: E402

BASE_WORDS = [
    "ransomware", "containment", "endpoint", "isolation", "honeycomb", "hexagon", "cells", "glass", "capsule",
    "quarantine", "threat", "detection", "cybersecurity", "security", "network", "defense", "infection",
    "malware", "protection", "navy", "red", "cyan", "blue", "white background", "clean background",
    "3d animation", "motion graphics", "technology background", "isometric", "seamless loop", "abstract",
    "concept", "digital", "data", "safety", "shield", "system", "business", "corporate", "software",
    "innovation", "modern", "minimal", "structure", "geometric", "pattern", "incident response", "soc",
    "firewall", "virus", "attack", "hexagonal", "spread", "isolate",
]


def item(pid, title=None):
    return {
        "ID": pid,
        "Filename": f"{pid}.mp4",
        "Adobe_Title": title or f"Hexagon honeycomb isolating an infected cell on white number {pid:03d}"[:70].strip(),
        "Adobe_Keywords": BASE_WORDS[:49],
        "SS_Description": ("Navy hexagon honeycomb seals one red infected cell inside a glass capsule on a clean "
                           "white background, ideal for cybersecurity ads and news."),
        "SS_Keywords": list(reversed(BASE_WORDS[:47])),
        "SS_Category_2": "Objects",
    }


def titled(pid):
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet",
             "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango",
             "uniform", "victor", "whiskey", "xray", "yankee"]
    t = f"Hexagon honeycomb isolating an infected cell {words[pid % 25]} {words[(pid // 25) % 25]}"
    return item(pid, t)


class TestValidation(unittest.TestCase):
    def test_valid_item_passes(self):
        errors, _ = md.validate_items([titled(918)])
        self.assertEqual(errors, [])

    def test_title_rules(self):
        cases = {
            "short": "Too short title here",
            "comma": "Hexagon honeycomb, isolating an infected cell on white background",
            "colon": "Hexagon honeycomb: isolating an infected cell on white background",
            "quote": "Hexagon honeycomb isolating an \"infected\" cell on white background",
            "4k": "Hexagon honeycomb isolating an infected cell on white background 4K",
            "video": "Hexagon honeycomb video isolating an infected cell on white background",
        }
        for name, title in cases.items():
            with self.subTest(name):
                errors, _ = md.validate_items([item(918, title)])
                self.assertTrue(any("Adobe_Title" in e for e in errors), errors)

    def test_duplicate_titles(self):
        a, b = titled(918), titled(919)
        b["Adobe_Title"] = a["Adobe_Title"]
        errors, _ = md.validate_items([a, b])
        self.assertTrue(any("duplicates ID 918" in e for e in errors))

    def test_keyword_counts(self):
        it = titled(918)
        it["Adobe_Keywords"] = BASE_WORDS[:48]
        it["SS_Keywords"] = BASE_WORDS[:44]
        errors, _ = md.validate_items([it])
        self.assertTrue(any("exactly 49" in e for e in errors))
        self.assertTrue(any("45-50" in e for e in errors))

    def test_keyword_duplicates_and_case(self):
        it = titled(918)
        it["Adobe_Keywords"] = BASE_WORDS[:48] + ["glass"]
        it["SS_Keywords"] = list(reversed(BASE_WORDS[:46])) + ["Shield"]
        errors, _ = md.validate_items([it])
        self.assertTrue(any("duplicate keywords: glass" in e for e in errors))
        self.assertTrue(any("not lowercase" in e for e in errors))

    def test_banned_words(self):
        for bad in ["nvidia", "ai generated", "4k", "zoom", "orbit", "render", "#1d4ed8", "1d4ed8", "fps"]:
            with self.subTest(bad):
                it = titled(918)
                it["Adobe_Keywords"] = BASE_WORDS[:48] + [bad]
                errors, _ = md.validate_items([it])
                self.assertTrue(any("banned words" in e for e in errors), errors)

    def test_hex_regex_has_no_false_positive_on_words(self):
        self.assertEqual(md.banned_terms("facade decade beaded panel panorama zoology"), [])

    def test_description_rules(self):
        it = titled(918)
        it["SS_Description"] = "A" * 201 + "."
        errors, _ = md.validate_items([it])
        self.assertTrue(any("max 200" in e for e in errors))
        it["SS_Description"] = "Navy hexagon honeycomb seals a cell on white. Great for cybersecurity ads and news reports today."
        errors, _ = md.validate_items([it])
        self.assertTrue(any("one sentence" in e for e in errors))

    def test_category(self):
        it = titled(918)
        it["SS_Category_2"] = "Technology"
        errors, _ = md.validate_items([it])
        self.assertTrue(any("SS_Category_2" in e for e in errors))

    def test_ss_copy_of_adobe(self):
        it = titled(918)
        it["SS_Keywords"] = BASE_WORDS[:47]
        errors, _ = md.validate_items([it])
        self.assertTrue(any("copy of the Adobe list" in e for e in errors))

    def test_prompt_cross_checks(self):
        it = titled(918)
        it["Adobe_Keywords"] = BASE_WORDS[:48] + ["copy space"]
        prompts = {918: "Copy space: none (subject may use the full frame)\n- Seamless loop: ...",
                   919: "Copy space: none"}
        errors, _ = md.validate_items([it], prompts)
        self.assertTrue(any("'copy space' keyword" in e for e in errors))
        self.assertTrue(any("no metadata for prompt IDs: 919" in e for e in errors))


class TestCsv(unittest.TestCase):
    def test_chunking_and_names(self):
        items = [titled(i) for i in range(941, 917, -1)]  # 24 items, unsorted
        chunks = md.chunk_items(items)
        self.assertEqual([len(c) for c in chunks], [10, 10, 4])
        self.assertEqual(md.chunk_filenames(chunks[0]), ("adobe_918-927.csv", "shutterstock_918-927.csv"))
        self.assertEqual(md.chunk_filenames(chunks[2]), ("adobe_938-941.csv", "shutterstock_938-941.csv"))

    def test_fifty_prompts_give_ten_files(self):
        items = [titled(i) for i in range(900, 950)]
        errors, _ = md.validate_items(items)
        self.assertEqual(errors, [])
        with tempfile.TemporaryDirectory() as d:
            written = md.write_all(items, d)
            names = sorted(p.name for p, _, _ in written)
            self.assertEqual(len(names), 10)
            self.assertIn("adobe_900-909.csv", names)
            self.assertIn("shutterstock_940-949.csv", names)

    def test_exact_headers_category_and_format(self):
        items = [titled(i) for i in range(918, 930)]
        with tempfile.TemporaryDirectory() as d:
            md.write_all(items, d)
            a_path = Path(d) / "adobe_918-927.csv"
            s_path = Path(d) / "shutterstock_918-927.csv"
            raw = a_path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertTrue(raw.startswith(b"Filename,Title,Keywords,Category,Releases\r\n"))
            self.assertTrue(s_path.read_bytes().startswith(
                b"Filename,Description,Keywords,Categories,Editorial,Mature Content\r\n"))
            with open(a_path, encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(len(rows), 11)
            self.assertEqual(rows[1][0], "918.mp4")
            self.assertEqual(rows[1][3], "19")
            self.assertEqual(rows[1][4], "")
            self.assertEqual(len(rows[1][2].split(", ")), 49)
            # Category written as a bare number, keywords quoted because they contain commas
            line = raw.decode("utf-8").splitlines()[1]
            self.assertTrue(line.endswith(",19,"))
            self.assertIn(',"ransomware, containment,', line)
            with open(s_path, encoding="utf-8", newline="") as f:
                srows = list(csv.reader(f))
            self.assertEqual(srows[1][3], "Technology,Objects")
            self.assertEqual(srows[1][4:], ["No", "No"])
            self.assertIn('"Technology,Objects",No,No', s_path.read_text(encoding="utf-8"))
            self.assertTrue((Path(d) / "adobe_928-929.csv").exists())

    def test_build_writes_nothing_on_error(self):
        import json
        items = [titled(918), copy.deepcopy(titled(919))]
        items[1]["SS_Category_2"] = "Bad"
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "metadata.json"
            f.write_text(json.dumps({"items": items}), encoding="utf-8")
            out = Path(d) / "out"
            rc = md.main(["build", "--file", str(f), "--out-dir", str(out)])
            self.assertEqual(rc, 1)
            self.assertFalse(out.exists())
            items[1]["SS_Category_2"] = "Science"
            f.write_text(json.dumps({"items": items}), encoding="utf-8")
            self.assertEqual(md.main(["build", "--file", str(f), "--out-dir", str(out)]), 0)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["adobe_918-919.csv", "shutterstock_918-919.csv"])

    def test_id_range_parse(self):
        self.assertEqual(md.parse_id_range("900-949"), (900, 949))
        self.assertEqual(md.parse_id_range("900 to 949"), (900, 949))


if __name__ == "__main__":
    unittest.main()
