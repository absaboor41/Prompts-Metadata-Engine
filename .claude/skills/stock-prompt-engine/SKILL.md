---
name: stock-prompt-engine
description: Run the Adobe Stock trend prompt engine end to end - research live trends per niche, invent and self-review new stock-animation concepts, render Remotion production prompts, append them to the Google Sheet, and write Adobe Stock + Shutterstock metadata CSVs. Use when the user says "Start the workflow", "Do your work", "run the engine", /start-workflow, "Start the workflow for <niches>, N each", or "Make metadata for IDs A to B".
---

# Stock prompt engine – run procedure

You are the creative engine. Never call an external LLM API. Research only with your own web search and web fetch tools (if no WebFetch tool is loaded, use the `web-fetch` agent to open a page). Never use SerpAPI.

All commands run from the project root. Python is `.venv/Scripts/python.exe` (written `PY` below; the bare `python` command is not on PATH):

```
PY = .venv/Scripts/python.exe
```

Read these before creating anything (once per run): `config/creative_rules.md`, `config/looks.json`, `config/niches.json`, `config/settings.json`. Read `config/metadata_rules.md` before Step 8.

Never ask the user questions mid-run unless the Google credentials are broken. If one niche fails, log it in `runs/<run>/log.md` and continue with the next.

Keep a task list: one item per niche plus "Metadata" and "Summary".

---

## Step 0 – Preflight

1. `PY scripts/sheets.py test` → must print both tab names and the current max ID. If it fails on credentials, follow its message (usually: a browser opens, the user logs in once). This is the only reason to stop and ask the user.
2. `PY scripts/engine.py new-run` → prints the new run folder `runs/<YYYY-MM-DD_HHMM>/` (Asia/Karachi time). Use it as `RUN` below. Start `RUN/log.md` with the start time and scope.
3. Scope: if the user named niches or a number ("only cybersecurity, 3 prompts", "Cybersecurity and AI, 3 each"), map the names to `niche_id`s in `config/niches.json` and use that N. Otherwise use `active_niche_ids` and `concepts_per_niche` from settings.json.

## Then, for each niche in scope, one at a time

### Step 1 – Research
- At least 3 web searches:
  - each of the niche's `research_queries`
  - `site:stock.adobe.com <niche> animation` (what the competition already sells)
  - one query you design yourself from what you just found
- Open 1–2 of the most useful pages.
- Write `RUN/research_<niche_id>.md` (keep it compact, ~40 lines):
  - top 8 current topics, each with its date and source
  - rising buyer interests
  - what the competition already covers, and the gaps to fill
- Only information from the last ~30 days counts as "trending". Mark older items as **evergreen**.

### Step 2 – Memory
- `PY scripts/sheets.py used --niche "<niche>" --out RUN/used_<niche_id>.json`
- It returns the last 120 Concept_Name and Visual_Metaphor values for the niche. Never reuse those names or metaphors (or near-paraphrases).

### Step 3 – Slots
- `PY scripts/engine.py slots --niche-id <id> --n <N> --out RUN/slots_<niche_id>.json`
- Gives asset_type (+ label and brief), look and palette for each slot. Each concept must fit its slot's asset type and use only its slot's palette.

### Step 4 – Create
Follow `config/creative_rules.md` and write `RUN/concepts_<niche_id>.json` (schema in that file). One concept per slot, `slot` = 1..N. Every concept:
- turns a real current trend from the research into a generic, brand-free visual;
- names a concrete buyer and the exact spot in their edit;
- uses a central metaphor different from the other concepts, the used list, and what the competition already covers;
- gives exact counts, sizes (% of frame), movements (% of frame width, at least 5%), colors per element and timings;
- returns to the exact opening state at 12–15s.

### Step 5 – Self-review (quality gate)
Score each concept 1–10 on:
- (a) buyer usefulness
- (b) trend relevance
- (c) originality vs the used list and the competition
- (d) visual clarity and large subject on white
- (e) specificity (exact sizes, counts, colors, timings)
- (f) Remotion buildability and loop correctness

Rewrite any concept that scores below 8 on any line until it passes; update the concepts file. Movements, separations and offsets must be % of frame width and at least 5% of width. Save `RUN/review_<niche_id>.md` with the score table (before → after) and what you changed.

### Step 6 – Validate and render
- `PY scripts/engine.py build --niche-id <id> --concepts RUN/concepts_<id>.json --used RUN/used_<id>.json --slots RUN/slots_<id>.json`
- Besides brands, missing fields, used names and similar metaphors (Jaccard ≥ 0.5), build also rejects hex codes that are not in the slot's palette.
- Exit 0 = all accepted. Exit 2 = some rejected: reasons are printed and saved to `RUN/rejected_<id>.json`. The accepted ones are already rendered into `RUN/prompts_<id>.json` (IDs still the `__ID__` placeholder).
- On rejection: replace the rejected concept in the concepts file with a new one for the same slot (run it through Step 5 again), then re-run build. Stop after 2 retries and log what is still missing.
- Read the warnings too (vague words, missing %, copy-space mismatch) and fix them if they are real.

### Step 7 – Write to the sheet
- `PY scripts/sheets.py append --file RUN/prompts_<id>.json`
- The script reads the max ID right before writing, assigns sequential IDs, fills `__ID__`, appends the main rows (Status / Adobe_Status / SS_Status = Pending, Filename = `<ID>.mp4`) and the Used_Concepts rows, verifies them, and records the IDs back into the prompts file. It refuses to append the same file twice.
- Log the new ID range in `RUN/log.md`.

---

## Step 8 – Metadata (after all niches are in the sheet)

1. `PY scripts/metadata.py collect --run RUN` → writes `RUN/run_prompts.json` and `RUN/all_prompts.md` with every prompt of this run, real IDs, in ID order.
2. Read `config/metadata_rules.md`. Then read each prompt in full and write its metadata object. Work in groups of 10 prompts (IDs in order); after each group, append to `RUN/metadata.json` (`{"items":[...]}`).
3. `PY scripts/metadata.py build --file RUN/metadata.json`
   - It validates every row (and cross-checks against `RUN/run_prompts.json`), prints all errors, and writes CSVs to `metadata/` only when everything passes.
   - Fix every error in `metadata.json` and run it again until it passes.

## Step 9 – Summary

- Write `RUN/summary.md`: per niche the new IDs, concepts rejected/rewritten, top trend used, errors; plus the CSV files created.
- `RUN/all_prompts.md` is already written by `collect` (re-run `collect` if anything changed).
- Reply with a short table: `niche | new IDs | concepts rejected/rewritten | top trend used`, then list the CSV files created in `metadata/`, then any errors.

---

## Metadata-only mode ("Make metadata for IDs 900 to 949")

Run only Step 8 for existing prompts:
1. `PY scripts/metadata.py from-sheet --ids 900-949` → creates `runs/<stamp>_metadata/` with `run_prompts.json` and `all_prompts.md` from the sheet, and prints the folder plus any IDs it could not find.
2. Do Step 8 points 2–3 with that folder as `RUN`.
3. Reply with the list of CSV files created and any missing IDs or errors.
