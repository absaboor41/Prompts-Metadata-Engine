#!/usr/bin/env python3
"""Stock prompt engine: run folders, slot assignment, concept validation/dedupe, prompt rendering.

Commands:
  new-run                                   create runs/<YYYY-MM-DD_HHMM>/ and print its path
  slots --niche-id ID --n N [--out F]       asset type + look + palette per slot (deterministic by day)
  build --niche-id ID --concepts F [--used F] [--slots F] [--out F]
                                            validate concepts, dedupe, render prompts_<id>.json
Exit codes: 0 ok, 1 error, 2 build finished but some concepts were rejected.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    CONFIG, ID_PLACEHOLDER, RUNS, UserError, find_brands, get_niche, load_json, load_looks,
    load_niches, load_settings, local_now, run_main, save_json,
)

JACCARD_THRESHOLD = 0.5

STOPWORDS = set("""
a an the and or but nor of to in on at by for with from into onto over under as is are was were be been
being am that this these those it its itself their there which who whom whose what while where when than
then so such very each every one two three four five six seven eight nine ten its into through across
around between within without about above below up down out off again further once only own same too can
will just like as also both all any some more most other another while until s t that's it's becomes
become becoming turns turning turn into via per
""".split())

REQUIRED_STR = [
    "concept_name", "trend_hook", "buyer_use_case", "visual_metaphor", "scene_description",
    "copy_space", "camera", "motion_details", "color_usage", "lighting_and_fx",
]

COPY_SPACE_TEXT = {
    "left third": "left third stays clean pure white so buyers can add their own title",
    "right third": "right third stays clean pure white so buyers can add their own title",
    "none": "none (subject may use the full frame with balanced negative space)",
}

VAGUE_WORDS = ["dynamic", "stunning", "futuristic elements", "cutting-edge", "cutting edge",
               "amazing", "awesome", "sleek futuristic", "high-tech elements", "epic"]
CLICHES = ["binary rain", "circuit brain", "padlock on circuit", "hooded hacker", "hoodie",
           "robot hand", "spinning globe", "plexus"]
BUILD_3D_LINE = ("Build in true 3D with @remotion/three (React Three Fiber) "
                 "so camera moves and depth are real.")


# ---------------------------------------------------------------- slots

def day_number(date=None):
    """Days since 1970-01-01 (UTC)."""
    if date is None:
        date = dt.datetime.now(dt.timezone.utc).date()
    return (date - dt.date(1970, 1, 1)).days


def compute_slots(niche_id, n, looks=None, day=None):
    looks = looks or load_looks()
    day = day_number() if day is None else day
    rotation = looks["rotation"]
    palettes = looks["looks"]
    slots = []
    for i in range(n):
        asset_type = rotation[(day + niche_id + i) % len(rotation)]
        look = palettes[(day * 3 + niche_id * 5 + i * 3) % len(palettes)]
        at = looks["asset_types"][asset_type]
        slots.append({
            "slot": i + 1,
            "asset_type": asset_type,
            "asset_type_label": at["label"],
            "asset_type_brief": at["brief"],
            "look": look["name"],
            "palette": look["colors"],
        })
    return slots


def palette_text(colors):
    return ", ".join(f"{c['hex']} {c['name']} ({c['role']})" for c in colors)


# ---------------------------------------------------------------- dedupe helpers

def normalize_name(name):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (name or "").lower())).strip()


def content_words(text):
    words = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if w in STOPWORDS or len(w) < 2:
            continue
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        words.add(w)
    return words


def jaccard(a, b):
    sa, sb = content_words(a), content_words(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from iter_strings(v)


# ---------------------------------------------------------------- validation

HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")


def off_palette_hexes(concept, slot_info):
    """Hex codes used in the concept that are not in the slot's palette (white is always allowed)."""
    allowed = {c["hex"].upper() for c in slot_info["palette"]} | {"#FFFFFF"}
    used = {m.group(0).upper() for s in iter_strings(concept) for m in HEX_RE.finditer(s)}
    return sorted(used - allowed)


def field_errors(c, n_slots):
    """Structural problems with one concept (missing/invalid fields)."""
    errs = []
    if not isinstance(c, dict):
        return ["concept is not a JSON object"]
    slot = c.get("slot")
    if not isinstance(slot, int) or not (1 <= slot <= n_slots):
        errs.append(f"slot must be an integer 1..{n_slots} (got {slot!r})")
    for k in REQUIRED_STR:
        v = c.get(k)
        if not isinstance(v, str) or not v.strip():
            errs.append(f"missing or empty field '{k}'")
    name = c.get("concept_name")
    if isinstance(name, str) and name.strip():
        wc = len(name.split())
        if not 2 <= wc <= 5:
            errs.append(f"concept_name must be 2-5 words (got {wc})")
    cs = c.get("copy_space")
    if isinstance(cs, str) and cs.strip().lower() not in COPY_SPACE_TEXT:
        errs.append("copy_space must be 'left third', 'right third' or 'none'")
    tl = c.get("timeline")
    if not isinstance(tl, list) or len(tl) < 3:
        errs.append("timeline must be a list of at least 3 beats")
    else:
        for i, beat in enumerate(tl):
            if not (isinstance(beat, dict) and str(beat.get("time", "")).strip()
                    and str(beat.get("action", "")).strip()):
                errs.append(f"timeline beat {i + 1} needs 'time' and 'action'")
    if not isinstance(c.get("build_3d"), bool):
        errs.append("build_3d must be true or false")
    kw = c.get("search_keywords")
    if not isinstance(kw, list) or not all(isinstance(k, str) and k.strip() for k in kw):
        errs.append("search_keywords must be a list of strings")
    elif not 10 <= len(kw) <= 15:
        errs.append(f"search_keywords must have 10-15 items (got {len(kw)})")
    return errs


def concept_warnings(c, slot_info):
    warns = []
    text = " ".join(iter_strings(c)).lower()
    for w in VAGUE_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", text):
            warns.append(f"vague word '{w}'")
    for w in CLICHES:
        if w in text:
            warns.append(f"cliche '{w}' (needs a genuinely fresh twist)")
    motion_text = " ".join([c.get("motion_details", ""), c.get("scene_description", "")]
                           + [b.get("action", "") for b in c.get("timeline", []) if isinstance(b, dict)])
    if "%" not in motion_text:
        warns.append("no % sizes/movements in scene/timeline/motion")
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%\s*(?:of\s+)?(?:frame\s+)?width", motion_text.lower()):
        if float(m.group(1)) < 5:
            warns.append(f"movement of {m.group(1)}% width is below the 5% minimum")
    if slot_info:
        cs = str(c.get("copy_space", "")).strip().lower()
        if slot_info["asset_type"] == "loop_background" and cs == "none":
            warns.append("loop_background slot should have copy_space 'left third' or 'right third'")
        if slot_info["asset_type"] == "hero_3d_object" and c.get("build_3d") is False:
            warns.append("hero_3d_object slot usually needs build_3d true")
    tl = c.get("timeline") or []
    if isinstance(tl, list) and tl and isinstance(tl[-1], dict):
        last = str(tl[-1].get("action", "")).lower()
        if not any(w in last for w in ("return", "back", "opening", "loop", "reset", "start")):
            warns.append("last timeline beat does not say how it returns to the opening state")
    if isinstance(c.get("search_keywords"), list):
        if any(k != k.lower() for k in c["search_keywords"] if isinstance(k, str)):
            warns.append("search_keywords were lowercased")
    return warns


def check_concepts(concepts, used, n_slots, slots_by_num=None):
    """Return (accepted, rejected, warnings).

    used: {"concept_names": [...], "visual_metaphors": [...]}
    rejected: list of {"slot", "concept_name", "reasons": [...]}
    """
    slots_by_num = slots_by_num or {}
    used_names = {normalize_name(n) for n in used.get("concept_names", []) if n}
    used_metaphors = [m for m in used.get("visual_metaphors", []) if m]
    accepted, rejected, warnings = [], [], {}
    batch_names, batch_metaphors, seen_slots = {}, [], set()

    for idx, c in enumerate(concepts):
        reasons = field_errors(c, n_slots)
        name = c.get("concept_name", "") if isinstance(c, dict) else ""
        slot = c.get("slot") if isinstance(c, dict) else None
        if isinstance(c, dict):
            brands = find_brands(" ".join(iter_strings(c)))
            if brands:
                reasons.append("brand terms: " + ", ".join(brands))
            if slot in seen_slots:
                reasons.append(f"slot {slot} appears twice in this batch")
            if slot in slots_by_num:
                off = off_palette_hexes(c, slots_by_num[slot])
                if off:
                    reasons.append(f"hex colors not in the slot's palette ({slots_by_num[slot]['look']}): "
                                   + ", ".join(off))
            nn = normalize_name(name)
            if nn and nn in used_names:
                reasons.append(f"concept name '{name}' already used")
            elif nn and nn in batch_names:
                reasons.append(f"concept name '{name}' duplicates another concept in this batch")
            metaphor = c.get("visual_metaphor", "")
            if isinstance(metaphor, str) and metaphor.strip():
                for um in used_metaphors:
                    j = jaccard(metaphor, um)
                    if j >= JACCARD_THRESHOLD:
                        reasons.append(f"metaphor too similar (Jaccard {j:.2f}) to used: '{um}'")
                        break
                for other_name, om in batch_metaphors:
                    j = jaccard(metaphor, om)
                    if j >= JACCARD_THRESHOLD:
                        reasons.append(f"metaphor too similar (Jaccard {j:.2f}) to '{other_name}' in this batch")
                        break
        if reasons:
            rejected.append({"index": idx, "slot": slot, "concept_name": name, "reasons": reasons})
            continue
        seen_slots.add(slot)
        batch_names[normalize_name(name)] = True
        batch_metaphors.append((name, c["visual_metaphor"]))
        w = concept_warnings(c, slots_by_num.get(slot))
        if w:
            warnings[f"slot {slot} '{name}'"] = w
        accepted.append(c)
    return accepted, rejected, warnings


# ---------------------------------------------------------------- rendering

def load_template(path=None):
    path = Path(path or CONFIG / "prompt_template.md")
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<!-- TEMPLATE START -->\s*(.*?)\s*<!-- TEMPLATE END -->", text, re.S)
    if not m:
        raise UserError(f"{path} has no <!-- TEMPLATE START --> ... <!-- TEMPLATE END --> block")
    lines = m.group(1).strip("\n").splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def _one_line(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def render_prompt(concept, slot_info, niche, settings, looks, template):
    fps = int(settings["fps"])
    duration = int(settings["duration_sec"])
    frames = fps * duration
    lighting = _one_line(looks["lighting"] + " " + concept.get("lighting_and_fx", ""))
    timeline = "\n".join(
        f"- {_one_line(b['time'])}: {_one_line(b['action'])}" for b in concept["timeline"])
    keywords = ", ".join(_one_line(k).lower() for k in concept["search_keywords"])
    tokens = {
        "ID": ID_PLACEHOLDER,
        "concept_name": _one_line(concept["concept_name"]),
        "niche": niche["niche"],
        "asset_type_label": slot_info["asset_type_label"],
        "buyer_use_case": _one_line(concept["buyer_use_case"]),
        "trend_hook": _one_line(concept["trend_hook"]),
        "visual_metaphor": _one_line(concept["visual_metaphor"]),
        "scene_description": _one_line(concept["scene_description"]),
        "copy_space_text": COPY_SPACE_TEXT[concept["copy_space"].strip().lower()],
        "duration": str(duration),
        "fps": str(fps),
        "frames": str(frames),
        "timeline_lines": timeline,
        "camera": _one_line(concept["camera"]),
        "look": slot_info["look"],
        "palette_hex_list": palette_text(slot_info["palette"]),
        "color_usage": _one_line(concept["color_usage"]),
        "lighting": lighting,
        "motion_details": _one_line(concept["motion_details"]),
        "build_3d_line": BUILD_3D_LINE,
        "keywords": keywords,
    }
    out = []
    for line in template.splitlines():
        if "{build_3d_line}" in line and not concept["build_3d"]:
            continue
        # single pass: replaced content is never re-scanned for placeholders
        out.append(re.sub(r"\{(\w+)\}", lambda m: tokens.get(m.group(1), m.group(0)), line))
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- commands

def _parse_date(s):
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise UserError(f"--date must be YYYY-MM-DD (got {s!r})")


def cmd_new_run(args):
    settings = load_settings()
    stamp = local_now(settings).strftime("%Y-%m-%d_%H%M")
    path = RUNS / stamp
    suffix = 2
    while path.exists():
        path = RUNS / f"{stamp}_{suffix}"
        suffix += 1
    path.mkdir(parents=True)
    print(path.relative_to(RUNS.parent).as_posix())
    return 0


def cmd_slots(args):
    niche = get_niche(args.niche_id)
    if args.n < 1:
        raise UserError("--n must be at least 1")
    date = _parse_date(args.date)
    slots = compute_slots(int(args.niche_id), args.n, day=day_number(date) if date else None)
    data = {"niche_id": niche["niche_id"], "niche": niche["niche"],
            "day": day_number(date) if date else day_number(), "slots": slots}
    if args.out:
        save_json(args.out, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def _load_used(args, niche, settings):
    if args.used:
        data = load_json(args.used)
    else:
        import sheets  # live fetch only when no --used file is given
        data = sheets.get_used(settings, niche["niche"], int(settings.get("used_history_per_niche", 120)))
    return {"concept_names": data.get("concept_names", []),
            "visual_metaphors": data.get("visual_metaphors", [])}


def cmd_build(args):
    settings, looks = load_settings(), load_looks()
    niche = get_niche(args.niche_id, load_niches())
    concepts_path = Path(args.concepts)
    raw = load_json(concepts_path)
    concepts = raw.get("concepts") if isinstance(raw, dict) else raw
    if not isinstance(concepts, list) or not concepts:
        raise UserError(f"{concepts_path} must contain {{\"concepts\": [...]}} with at least one concept")

    if args.slots:
        slot_list = load_json(args.slots)["slots"]
    else:
        max_slot = max([c.get("slot", 0) for c in concepts if isinstance(c, dict)
                        and isinstance(c.get("slot"), int)] + [len(concepts),
                       int(settings.get("concepts_per_niche", 5))])
        slot_list = compute_slots(int(niche["niche_id"]), max_slot, looks,
                                  day=day_number(_parse_date(args.date)) if args.date else None)
    slots_by_num = {s["slot"]: s for s in slot_list}

    used = _load_used(args, niche, settings)
    accepted, rejected, warnings = check_concepts(concepts, used, len(slot_list), slots_by_num)

    template = load_template()
    items = []
    for c in sorted(accepted, key=lambda c: c["slot"]):
        s = slots_by_num[c["slot"]]
        items.append({
            "slot": c["slot"],
            "concept_name": _one_line(c["concept_name"]),
            "visual_metaphor": _one_line(c["visual_metaphor"]),
            "asset_type": s["asset_type"],
            "asset_type_label": s["asset_type_label"],
            "look": s["look"],
            "trend_hook": _one_line(c["trend_hook"]),
            "prompt": render_prompt(c, s, niche, settings, looks, template),
        })

    out = Path(args.out) if args.out else concepts_path.parent / f"prompts_{niche['niche_id']}.json"
    save_json(out, {
        "niche_id": niche["niche_id"],
        "niche": niche["niche"],
        "category": niche["category"],
        "generated_at": local_now(settings).isoformat(timespec="seconds"),
        "items": items,
    })
    rej_path = concepts_path.parent / f"rejected_{niche['niche_id']}.json"
    if rejected:
        save_json(rej_path, {"rejected": rejected})
    elif rej_path.exists():
        rej_path.unlink()

    print(f"Niche {niche['niche_id']} {niche['niche']}: {len(accepted)} accepted, {len(rejected)} rejected")
    for r in rejected:
        print(f"  REJECTED slot {r['slot']} '{r['concept_name']}':")
        for reason in r["reasons"]:
            print(f"    - {reason}")
    for who, ws in warnings.items():
        print(f"  WARN {who}: " + "; ".join(ws))
    print(f"Prompts written: {out}")
    if rejected:
        print(f"Rejections written: {rej_path}")
        return 2
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new-run", help="create a run folder and print its path")
    s = sub.add_parser("slots", help="asset type + look per slot")
    s.add_argument("--niche-id", type=int, required=True)
    s.add_argument("--n", type=int, required=True)
    s.add_argument("--out")
    s.add_argument("--date", help="YYYY-MM-DD (UTC day); default today")
    b = sub.add_parser("build", help="validate concepts and render prompts")
    b.add_argument("--niche-id", type=int, required=True)
    b.add_argument("--concepts", required=True)
    b.add_argument("--used", help="JSON from `sheets.py used --out`; fetched live if omitted")
    b.add_argument("--slots", help="JSON from `engine.py slots --out`; recomputed if omitted")
    b.add_argument("--out", help="default: prompts_<id>.json next to the concepts file")
    b.add_argument("--date", help="YYYY-MM-DD (UTC day) when recomputing slots")
    args = p.parse_args(argv)
    return {"new-run": cmd_new_run, "slots": cmd_slots, "build": cmd_build}[args.cmd](args)


if __name__ == "__main__":
    run_main(main)
