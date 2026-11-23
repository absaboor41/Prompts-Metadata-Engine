# Adobe Stock Trend Prompt Engine

Local replacement for the n8n workflow "Adobe Stock 10-Niche V5 Trend Engine". Claude is the creative engine: it researches live trends per niche, invents buyer-focused stock-animation concepts, renders them into Remotion production prompts, appends them to the Google Sheet, and writes Adobe Stock / Shutterstock metadata CSVs.

## Trigger phrases

When the user says any of these, invoke the **`stock-prompt-engine`** skill and follow it exactly:

- "Start the workflow", "Do your work", "run the engine", `/start-workflow` → full run (all active niches from `config/settings.json`)
- "Start the workflow for <niches>, <N> each" → partial run (only those niches, N concepts each)
- "Make metadata for IDs <A> to <B>" → metadata only (skill section "Metadata-only mode")

## Hard rules

- Never call an external LLM API. Claude writes all concepts, prompts and metadata itself.
- Research with Claude's own web search / web fetch tools. Never SerpAPI.
- The Google Sheet is append-only: never update, overwrite, rename or reorder existing rows or columns. Only `scripts/sheets.py append` writes.
- During setup or testing, use `append --dry-run` only.
- Don't ask the user questions mid-run unless the Google credentials are broken.

## Running the scripts

Python lives in `.venv` (the bare `python` command is not on PATH on this machine):

```
.venv/Scripts/python.exe scripts/sheets.py test
.venv/Scripts/python.exe scripts/engine.py slots --niche-id 7 --n 5
.venv/Scripts/python.exe scripts/metadata.py build --file runs/<run>/metadata.json
.venv/Scripts/python.exe -m unittest discover -s tests
```

Recreate the venv with `py -3 -m venv .venv` then `.venv/Scripts/python.exe -m pip install -r requirements.txt`.

## Layout

- `config/` – settings, niches, looks (asset types + palettes), creative rules, prompt template, metadata rules
- `scripts/sheets.py` – Google Sheets I/O (gspread OAuth, same token as the rendering agent)
- `scripts/engine.py` – run folders, slot assignment, concept validation/dedupe, prompt rendering
- `scripts/metadata.py` – collect run prompts, read old prompts from the sheet, validate metadata, write CSVs
- `runs/<YYYY-MM-DD_HHMM>/` – per-run research, concepts, reviews, prompts, logs (git-ignored)
- `metadata/` – final CSVs for Adobe Stock and Shutterstock
