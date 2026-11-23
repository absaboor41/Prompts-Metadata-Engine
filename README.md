# Prompts Metadata Engine

A [Claude Code](https://claude.com/claude-code) project for selling stock video animations. In each run Claude:

1. **researches** live trends in 10 tech niches with its own web search;
2. **invents** new stock-animation concepts aimed at what buyers need, then reviews them and rewrites any weak ones;
3. **renders** each concept into a detailed **Remotion** production prompt (15 s, 30 fps, seamless loop);
4. **appends** the prompts to a **Google Sheet** that a separate rendering agent reads;
5. **writes** upload-ready metadata CSVs (title, keywords, categories) for **Adobe Stock** and **Shutterstock**.

There are no external LLM APIs and no SerpAPI. Claude Code writes all of the creative text. The Python scripts handle the steps that have to be exact: assigning slots, rejecting duplicates and brand names, checking palettes, adding rows to the sheet without changing existing ones, and validating and writing the CSVs.

Default niches: Data Analytics, DevOps/CI-CD, AR, VR, Network Security, AI/ML, Cybersecurity, Cloud Computing, Blockchain/Crypto and IoT/5G. You can edit them in `config/niches.json`.

## Requirements

| Tool | Why |
|---|---|
| [Claude Code](https://claude.com/claude-code) | runs the workflow (the skill in `.claude/skills/stock-prompt-engine`) |
| Python 3.10+ | the scripts in `scripts/` |
| A Google account + Google Cloud OAuth client | read and append the Google Sheet |

This repo does **not** render the videos, so you don't need Node.js or ffmpeg here. It only produces the prompts and metadata. Rendering them with Remotion (which needs Node.js and ffmpeg) is the job of a separate rendering project that reads the same sheet.

## Install

```powershell
git clone https://github.com/absaboor41/Prompts-Metadata-Engine.git
cd Prompts-Metadata-Engine
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

macOS / Linux: `python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`. Then use `.venv/bin/python` wherever these docs say `.venv/Scripts/python.exe`.

## Configure

Personal values never go in tracked files. Copy the example file and fill it in:

```powershell
copy config\settings.local.example.json config\settings.local.json
```

```json
{
  "sheet_id": "YOUR_SHEET_ID",
  "oauth_credentials": "C:/Users/YOUR_USER/AppData/Roaming/gspread/credentials.json",
  "oauth_authorized_user": "C:/Users/YOUR_USER/AppData/Roaming/gspread/authorized_user.json"
}
```

- `sheet_id` is the long ID in the sheet URL: `docs.google.com/spreadsheets/d/<sheet_id>/edit`.
- The paths can use `~` and environment variables. If you leave out `oauth_authorized_user`, the token is saved next to `credentials.json`.
- `config/settings.local.json` is git-ignored. Any key in it overrides the same key in `config/settings.json`, which holds the shared defaults (tab names, concepts per niche, active niches, duration, fps, timezone).

### The Google Sheet

Create a sheet with two tabs. Their names are set by `main_tab` and `used_tab` in `config/settings.json`:

- **Prompt-Rendering** with the header row `ID | Niche category | Prompt | Status | Adobe_Status | SS_Status | Filename`. Columns can be in any order, and extra columns are fine.
- **Used_Concepts** with the header row `Niche | Concept_Name | Visual_Metaphor | Asset_Type | Look | Trend_Hook | Prompt_ID | Date_Added`

The engine only **appends** rows. It never edits, reorders or deletes existing rows.

### Google OAuth setup (once)

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project (or pick one).
2. **APIs & Services → Library:** enable the **Google Sheets API** and the **Google Drive API**.
3. **APIs & Services → OAuth consent screen:** choose External and add yourself as a test user.
4. **Credentials → Create credentials → OAuth client ID → Desktop app.** Download the JSON.
5. Save it at the path you set in `oauth_credentials`, for example `%APPDATA%\gspread\credentials.json`.
6. Run the connection test. A browser opens once for you to log in, and the token is saved for later runs:

```powershell
.venv/Scripts/python.exe scripts/sheets.py test
```

It should print both tab names and the current highest ID. If the token ever expires, run `scripts/sheets.py login`.

## Use it

Open the folder in Claude Code and type one of these:

| You say | What happens |
|---|---|
| `Start the workflow` (or `Do your work`, `run the engine`, `/start-workflow`) | full run over every niche in `active_niche_ids`, `concepts_per_niche` concepts each |
| `Start the workflow for Cybersecurity and AI, 3 each` | runs only the niches you name, with N concepts each |
| `Make metadata for IDs 900 to 949` | metadata only: reads those prompts from the sheet and writes the CSVs |

Each run gets its own folder `runs/<YYYY-MM-DD_HHMM>/` for research notes, concepts, reviews, prompts and a log. The final CSVs go in `metadata/`, named like `adobe_<from>-<to>.csv` and `shutterstock_<from>-<to>.csv`, with 10 rows per file. Both folders are git-ignored.

### Scripts (used by the skill, also usable by hand)

```powershell
.venv/Scripts/python.exe scripts/sheets.py test                      # check the connection
.venv/Scripts/python.exe scripts/sheets.py append --file F --dry-run # preview an append, no writes
.venv/Scripts/python.exe scripts/engine.py slots --niche-id 7 --n 5  # asset type, look and palette per slot
.venv/Scripts/python.exe scripts/metadata.py from-sheet --ids 900-949
.venv/Scripts/python.exe scripts/metadata.py build --file runs/<run>/metadata.json
.venv/Scripts/python.exe -m unittest discover -s tests               # run the tests
```

## Layout

```
config/      settings, niches, looks (asset types + palettes), creative rules,
             prompt template, metadata rules, settings.local.example.json
scripts/     sheets.py (Google Sheets I/O), engine.py (slots, validation, prompt
             rendering), metadata.py (CSV metadata), common.py
.claude/     the stock-prompt-engine skill and the /start-workflow command
tests/       unit tests and fixtures
runs/        per-run working files (git-ignored)
metadata/    final CSVs (git-ignored)
```

## License

[MIT](LICENSE)
