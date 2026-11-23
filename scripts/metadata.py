#!/usr/bin/env python3
"""Metadata for Adobe Stock + Shutterstock: collect prompts, validate metadata, write CSVs.

Commands:
  collect --run RUN_DIR              gather this run's appended prompts -> run_prompts.json + all_prompts.md
  from-sheet --ids 900-949 [--out D] read existing prompts from the sheet into a new metadata run folder
  build --file metadata.json [--prompts run_prompts.json] [--out-dir metadata]
                                     validate every row; write CSVs (10 rows per file) only if all pass
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    BRAND_RE, METADATA_DIR, RUNS, UserError, load_json, load_settings, local_now, run_main, save_json,
)

ADOBE_HEADER = ["Filename", "Title", "Keywords", "Category", "Releases"]
SS_HEADER = ["Filename", "Description", "Keywords", "Categories", "Editorial", "Mature Content"]
ADOBE_CATEGORY = 19  # Technology
SS_CATEGORIES = ["Backgrounds/Textures", "Business/Finance", "Science", "Objects", "Industrial"]
CHUNK = 10
ADOBE_KEYWORDS = 49
SS_KW_MIN, SS_KW_MAX = 45, 50
TITLE_MIN, TITLE_MAX = 50, 70
DESC_MAX, DESC_SOFT_MIN, DESC_SOFT_MAX = 200, 120, 195

BANNED_RE = re.compile(
    r"\b(?:ai[ -]generated|generative ai|4k|uhd|fps|resolution|codec|render(?:s|ed|ing)?|"
    r"orbit(?:s|ed|ing)?|dolly|zoom(?:s|ed|ing)?|pan(?:s|ned|ning)?)\b"
    r"|#[0-9a-f]{3,8}\b|\b(?=[0-9a-f]*\d)[0-9a-f]{6}\b",
    re.IGNORECASE)
TITLE_BANNED_RE = re.compile(r"\b(?:4k|video|videos|footage|clip|clips|stock)\b", re.IGNORECASE)
QUOTE_CHARS = "\"'‘’“”`"


# ---------------------------------------------------------------- validation

def banned_terms(text):
    found = {m.group(0).lower() for m in BRAND_RE.finditer(text or "")}
    found |= {m.group(0).lower() for m in BANNED_RE.finditer(text or "")}
    return sorted(found)


def _kw_errors(kws, label, n_min, n_max):
    errs = []
    if not isinstance(kws, list) or not all(isinstance(k, str) for k in kws):
        return [f"{label} must be a list of strings"]
    if n_min == n_max and len(kws) != n_min:
        errs.append(f"{label} must have exactly {n_min} keywords (has {len(kws)})")
    elif not n_min <= len(kws) <= n_max:
        errs.append(f"{label} must have {n_min}-{n_max} keywords (has {len(kws)})")
    seen, dups = set(), []
    for k in kws:
        ks = k.strip()
        if not ks:
            errs.append(f"{label} has an empty keyword")
            continue
        if ks != k.lower().strip():
            errs.append(f"{label} keyword not lowercase: '{k}'")
        if "," in ks or ";" in ks:
            errs.append(f"{label} keyword contains a comma/semicolon: '{k}'")
        key = re.sub(r"\s+", " ", ks.lower())
        if key in seen:
            dups.append(ks)
        seen.add(key)
    if dups:
        errs.append(f"{label} duplicate keywords: {', '.join(dups)}")
    bad = banned_terms(" | ".join(kws))
    if bad:
        errs.append(f"{label} banned words: {', '.join(bad)}")
    return errs


def one_sentence(text):
    t = text.strip()
    if not t or t[-1] not in ".!?":
        return False
    # sentence breaks: terminal punctuation followed by space + anything
    return not re.search(r"[.!?]\s+\S", t)


def has_copy_space(prompt):
    m = re.search(r"^Copy space:\s*(.*)$", prompt or "", re.M | re.I)
    return bool(m) and not m.group(1).strip().lower().startswith("none")


def is_loop(prompt):
    return "seamless loop" in (prompt or "").lower()


def validate_items(items, prompts_by_id=None):
    """Return (errors, warnings), both lists of strings."""
    errors, warnings = [], []
    if not isinstance(items, list) or not items:
        return ["metadata file has no items"], warnings
    titles, ids = {}, set()
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            errors.append(f"item {n}: not an object")
            continue
        pid = it.get("ID")
        tag = f"ID {pid}"
        if not isinstance(pid, int) or isinstance(pid, bool):
            errors.append(f"item {n}: ID must be an integer (got {pid!r})")
            continue
        if pid in ids:
            errors.append(f"{tag}: duplicate ID")
        ids.add(pid)
        fn = it.get("Filename", f"{pid}.mp4")
        if fn != f"{pid}.mp4":
            errors.append(f"{tag}: Filename must be '{pid}.mp4' (got {fn!r})")

        title = it.get("Adobe_Title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{tag}: Adobe_Title missing")
        else:
            if title != title.strip():
                errors.append(f"{tag}: Adobe_Title has leading/trailing spaces")
            if not TITLE_MIN <= len(title) <= TITLE_MAX:
                errors.append(f"{tag}: Adobe_Title is {len(title)} chars (must be {TITLE_MIN}-{TITLE_MAX})")
            if "," in title or ":" in title or any(q in title for q in QUOTE_CHARS):
                errors.append(f"{tag}: Adobe_Title must not contain commas, quotes or colons")
            tb = sorted({m.group(0).lower() for m in TITLE_BANNED_RE.finditer(title)})
            if tb:
                errors.append(f"{tag}: Adobe_Title must not use: {', '.join(tb)}")
            bad = banned_terms(title)
            if bad:
                errors.append(f"{tag}: Adobe_Title banned words: {', '.join(bad)}")
            key = title.strip().lower()
            if key in titles:
                errors.append(f"{tag}: Adobe_Title duplicates ID {titles[key]}")
            titles.setdefault(key, pid)

        akw = it.get("Adobe_Keywords")
        skw = it.get("SS_Keywords")
        errors += [f"{tag}: {e}" for e in _kw_errors(akw, "Adobe_Keywords", ADOBE_KEYWORDS, ADOBE_KEYWORDS)]
        errors += [f"{tag}: {e}" for e in _kw_errors(skw, "SS_Keywords", SS_KW_MIN, SS_KW_MAX)]
        if isinstance(akw, list) and isinstance(skw, list) and skw and skw == akw[:len(skw)]:
            errors.append(f"{tag}: SS_Keywords is a copy of the Adobe list; write its own ordering")

        desc = it.get("SS_Description")
        if not isinstance(desc, str) or not desc.strip():
            errors.append(f"{tag}: SS_Description missing")
        else:
            if len(desc) > DESC_MAX:
                errors.append(f"{tag}: SS_Description is {len(desc)} chars (max {DESC_MAX})")
            elif not DESC_SOFT_MIN <= len(desc) <= DESC_SOFT_MAX:
                warnings.append(f"{tag}: SS_Description is {len(desc)} chars (target {DESC_SOFT_MIN}-{DESC_SOFT_MAX})")
            if not one_sentence(desc):
                errors.append(f"{tag}: SS_Description must be exactly one sentence ending with a period")
            bad = banned_terms(desc)
            if bad:
                errors.append(f"{tag}: SS_Description banned words: {', '.join(bad)}")
            if isinstance(title, str) and title.strip() and desc.lower().startswith(title.strip().lower()):
                errors.append(f"{tag}: SS_Description must not copy the title")

        cat = it.get("SS_Category_2")
        if cat not in SS_CATEGORIES:
            errors.append(f"{tag}: SS_Category_2 must be one of {', '.join(SS_CATEGORIES)} (got {cat!r})")

        if prompts_by_id is not None:
            prompt = prompts_by_id.get(pid)
            if prompt is None:
                errors.append(f"{tag}: no prompt with this ID in this run")
            else:
                all_kw = [k.lower() for k in (akw or []) + (skw or []) if isinstance(k, str)]
                if "copy space" in all_kw and not has_copy_space(prompt):
                    errors.append(f"{tag}: 'copy space' keyword but the prompt has no copy space")
                if "seamless loop" in all_kw and not is_loop(prompt):
                    errors.append(f"{tag}: 'seamless loop' keyword but the prompt does not loop")
                if isinstance(akw, list) and has_copy_space(prompt) and "copy space" not in [k.lower() for k in akw]:
                    warnings.append(f"{tag}: prompt has copy space but Adobe_Keywords lacks 'copy space'")
                if isinstance(akw, list) and is_loop(prompt) and "seamless loop" not in [k.lower() for k in akw]:
                    warnings.append(f"{tag}: prompt loops but Adobe_Keywords lacks 'seamless loop'")

    if prompts_by_id is not None:
        missing = sorted(set(prompts_by_id) - ids)
        if missing:
            errors.append(f"no metadata for prompt IDs: {', '.join(map(str, missing))}")
    return errors, warnings


# ---------------------------------------------------------------- CSV

def chunk_items(items, size=CHUNK):
    s = sorted(items, key=lambda it: it["ID"])
    return [s[i:i + size] for i in range(0, len(s), size)]


def chunk_filenames(chunk):
    a, b = chunk[0]["ID"], chunk[-1]["ID"]
    return f"adobe_{a}-{b}.csv", f"shutterstock_{a}-{b}.csv"


def adobe_row(it):
    return [f"{it['ID']}.mp4", it["Adobe_Title"].strip(),
            ", ".join(k.strip() for k in it["Adobe_Keywords"]), ADOBE_CATEGORY, ""]


def ss_row(it):
    return [f"{it['ID']}.mp4", it["SS_Description"].strip(),
            ", ".join(k.strip() for k in it["SS_Keywords"]),
            f"Technology,{it['SS_Category_2']}", "No", "No"]


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(header)
        w.writerows(rows)


def verify_csv(path, header, n_rows):
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise UserError(f"{path} has a UTF-8 BOM")
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] != header:
        raise UserError(f"{path}: header mismatch {rows[0] if rows else None}")
    if len(rows) - 1 != n_rows:
        raise UserError(f"{path}: expected {n_rows} data rows, found {len(rows) - 1}")
    for i, r in enumerate(rows[1:], 2):
        if len(r) != len(header):
            raise UserError(f"{path} line {i}: {len(r)} columns, expected {len(header)}")


def write_all(items, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for chunk in chunk_items(items):
        a_name, s_name = chunk_filenames(chunk)
        for name, header, fn in ((a_name, ADOBE_HEADER, adobe_row), (s_name, SS_HEADER, ss_row)):
            path = out_dir / name
            existed = path.exists()
            write_csv(path, header, [fn(it) for it in chunk])
            verify_csv(path, header, len(chunk))
            written.append((path, len(chunk), existed))
    return written


# ---------------------------------------------------------------- prompts collection

def _all_prompts_md(entries):
    parts = [f"# All prompts ({len(entries)})\n"]
    for e in entries:
        parts.append(e["prompt"].rstrip() + "\n")
    return "\n\n".join(parts)


def _write_prompt_set(folder, entries, source):
    folder = Path(folder)
    entries = sorted(entries, key=lambda e: e["ID"])
    save_json(folder / "run_prompts.json", {"source": source, "count": len(entries), "prompts": entries})
    (folder / "all_prompts.md").write_text(_all_prompts_md(entries), encoding="utf-8", newline="\n")
    return entries


def load_run_prompts(path):
    data = load_json(path)
    return {int(p["ID"]): p["prompt"] for p in data.get("prompts", [])}


def cmd_collect(args):
    run = Path(args.run)
    if not run.is_dir():
        raise UserError(f"run folder not found: {run}")
    entries, not_appended = [], []
    for f in sorted(run.glob("prompts_*.json")):
        data = load_json(f)
        if not data.get("appended"):
            not_appended.append(f.name)
            continue
        for it in data["items"]:
            entries.append({"ID": int(it["id"]), "niche": data.get("niche", ""),
                            "concept_name": it.get("concept_name", ""), "prompt": it["prompt_final"]})
    if not entries:
        raise UserError(f"no appended prompts found in {run} (prompts_*.json files with IDs)")
    entries = _write_prompt_set(run, entries, f"run {run.name}")
    print(f"Collected {len(entries)} prompts, IDs {entries[0]['ID']}-{entries[-1]['ID']}")
    print(f"Wrote {run / 'run_prompts.json'} and {run / 'all_prompts.md'}")
    if not_appended:
        print(f"WARNING: not appended to the sheet (skipped): {', '.join(not_appended)}")
    return 0


def parse_id_range(s):
    m = re.fullmatch(r"\s*(\d+)\s*(?:-|to|\.\.)\s*(\d+)\s*", s or "")
    if not m:
        raise UserError(f"--ids must look like 900-949 (got {s!r})")
    lo, hi = int(m.group(1)), int(m.group(2))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def cmd_from_sheet(args):
    import sheets
    settings = load_settings()
    lo, hi = parse_id_range(args.ids)
    found = sheets.get_prompts(settings, lo, hi)
    if not found:
        raise UserError(f"no prompts with IDs {lo}-{hi} in the sheet")
    if args.out:
        folder = Path(args.out)
    else:
        folder = RUNS / f"{local_now(settings).strftime('%Y-%m-%d_%H%M')}_metadata_{lo}-{hi}"
    folder.mkdir(parents=True, exist_ok=True)
    entries = _write_prompt_set(folder, found, f"sheet IDs {lo}-{hi}")
    got = {e["ID"] for e in entries}
    missing = [i for i in range(lo, hi + 1) if i not in got]
    print(f"Run folder: {folder.relative_to(RUNS.parent).as_posix() if folder.is_relative_to(RUNS.parent) else folder}")
    print(f"Read {len(entries)} prompts (IDs {entries[0]['ID']}-{entries[-1]['ID']}) "
          f"-> run_prompts.json, all_prompts.md")
    if missing:
        print(f"Missing or empty IDs: {', '.join(map(str, missing))}")
    return 0


def cmd_build(args):
    path = Path(args.file)
    data = load_json(path)
    items = data.get("items") if isinstance(data, dict) else data
    prompts_path = Path(args.prompts) if args.prompts else path.parent / "run_prompts.json"
    prompts_by_id = load_run_prompts(prompts_path) if prompts_path.exists() else None
    if prompts_by_id is None:
        print(f"NOTE: {prompts_path} not found; skipping prompt cross-checks.")
    errors, warnings = validate_items(items, prompts_by_id)
    for w in warnings:
        print(f"WARN  {w}")
    if errors:
        for e in errors:
            print(f"ERROR {e}")
        print(f"\n{len(errors)} error(s). No CSV files written. Fix {path} and run again.")
        return 1
    for it in items:
        it.setdefault("Filename", f"{it['ID']}.mp4")
    written = write_all(items, args.out_dir or METADATA_DIR)
    print(f"All {len(items)} rows valid. Wrote {len(written)} files:")
    for p, n, existed in written:
        print(f"  {p} ({n} rows){' [overwrote existing file]' if existed else ''}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--run", required=True)
    f = sub.add_parser("from-sheet")
    f.add_argument("--ids", required=True)
    f.add_argument("--out")
    b = sub.add_parser("build")
    b.add_argument("--file", required=True)
    b.add_argument("--prompts")
    b.add_argument("--out-dir")
    args = p.parse_args(argv)
    return {"collect": cmd_collect, "from-sheet": cmd_from_sheet, "build": cmd_build}[args.cmd](args)


if __name__ == "__main__":
    run_main(main)
