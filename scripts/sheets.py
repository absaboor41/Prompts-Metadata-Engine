#!/usr/bin/env python3
"""Google Sheets I/O for the stock prompt engine (gspread OAuth, append-only).

Commands:
  test                              open both tabs, check headers, print max ID
  max-id                            print the highest numeric ID in the main tab
  used --niche NAME [--limit N] [--out F]
                                    last N Concept_Name / Visual_Metaphor values for a niche (JSON)
  append --file F [--dry-run]       assign IDs and append prompt rows + Used_Concepts rows
  login                             force a fresh browser login (backs up the old token)
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ID_PLACEHOLDER, UserError, is_placeholder, load_json, load_niches, load_settings, local_now,
    run_main, save_json,
)

MAIN_COLS = ["ID", "Niche category", "Prompt", "Status", "Adobe_Status", "SS_Status", "Filename"]
USED_COLS = ["Niche", "Concept_Name", "Visual_Metaphor", "Asset_Type", "Look", "Trend_Hook",
             "Prompt_ID", "Date_Added"]
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
LOGIN_TIMEOUT_SEC = 300


# ---------------------------------------------------------------- pure helpers (unit-tested)

def norm_header(h):
    """Case-, space- and underscore-insensitive header key."""
    return re.sub(r"[\s_]+", "", str(h)).lower()


def header_map(headers, required, tab):
    """Map canonical column name -> 0-based index. Raises UserError listing missing columns."""
    idx = {}
    for i, h in enumerate(headers):
        k = norm_header(h)
        if k and k not in idx:
            idx[k] = i
    out, missing = {}, []
    for col in required:
        k = norm_header(col)
        if k in idx:
            out[col] = idx[k]
        else:
            missing.append(col)
    if missing:
        raise UserError(
            f"tab '{tab}' is missing column(s): {', '.join(missing)}. "
            f"Headers found in row 1: {', '.join(repr(h) for h in headers if str(h).strip()) or '(none)'}")
    return out


def parse_id(v):
    s = str(v).strip()
    if not s:
        return None
    try:
        f = float(s.replace(",", ""))
    except ValueError:
        return None
    return int(f) if f == int(f) else None


def max_id_from_column(values):
    """values: full column including header row."""
    ids = [i for i in (parse_id(v) for v in values[1:]) if i is not None]
    return max(ids) if ids else 0


def build_rows(prompts, start_id, main_headers_len, main_map, used_headers_len, used_map, today):
    """Return (main_rows, used_rows, assigned) for a prompts file."""
    main_rows, used_rows, assigned = [], [], []
    for offset, item in enumerate(prompts["items"]):
        pid = start_id + offset
        prompt = item["prompt"].replace(ID_PLACEHOLDER, str(pid))
        row = [""] * main_headers_len
        row[main_map["ID"]] = pid
        row[main_map["Niche category"]] = prompts["niche"]
        row[main_map["Prompt"]] = prompt
        row[main_map["Status"]] = "Pending"
        row[main_map["Adobe_Status"]] = "Pending"
        row[main_map["SS_Status"]] = "Pending"
        row[main_map["Filename"]] = f"{pid}.mp4"
        main_rows.append(row)
        u = [""] * used_headers_len
        u[used_map["Niche"]] = prompts["niche"]
        u[used_map["Concept_Name"]] = item["concept_name"]
        u[used_map["Visual_Metaphor"]] = item["visual_metaphor"]
        u[used_map["Asset_Type"]] = item.get("asset_type", "")
        u[used_map["Look"]] = item.get("look", "")
        u[used_map["Trend_Hook"]] = item.get("trend_hook", "")
        u[used_map["Prompt_ID"]] = pid
        u[used_map["Date_Added"]] = today
        used_rows.append(u)
        assigned.append({"id": pid, "prompt": prompt})
    return main_rows, used_rows, assigned


# ---------------------------------------------------------------- auth + open

def _imports():
    try:
        import gspread  # noqa: F401
        from google.auth import exceptions as gauth_exc  # noqa: F401
    except ImportError:
        raise UserError("Python packages missing. Run: .venv/Scripts/python.exe -m pip install -r requirements.txt")
    import gspread
    from google.auth import exceptions as gauth_exc
    return gspread, gauth_exc


def _expand(p):
    return Path(os.path.expandvars(os.path.expanduser(str(p))))


def _paths(settings):
    cred = _expand(settings["oauth_credentials"])
    token = _expand(settings.get("oauth_authorized_user") or cred.parent / "authorized_user.json")
    return cred, token


def _browser_flow(client_config, scopes, port=0):
    from google_auth_oauthlib.flow import InstalledAppFlow
    print("A browser window is opening for Google login. Log in once with the account that owns "
          f"the sheet (waiting up to {LOGIN_TIMEOUT_SEC // 60} minutes)...", file=sys.stderr)
    flow = InstalledAppFlow.from_client_config(client_config, scopes)
    try:
        return flow.run_local_server(port=port, timeout_seconds=LOGIN_TIMEOUT_SEC, open_browser=True)
    except Exception as e:  # timeout or user closed the window
        raise UserError(f"Google login was not completed ({e}). Run `.venv/Scripts/python.exe "
                        "scripts/sheets.py login` and finish the login in the browser.")


def get_client(settings):
    gspread, _ = _imports()
    cred, token = _paths(settings)
    if not cred.exists():
        raise UserError(
            f"OAuth client file not found: {cred}. Put the Google OAuth desktop-client JSON there "
            "(the same credentials.json your rendering agent uses).")
    try:
        return gspread.oauth(credentials_filename=str(cred), authorized_user_filename=str(token),
                             flow=_browser_flow)
    except UserError:
        raise
    except ValueError as e:
        raise UserError(f"OAuth files look broken ({e}). Check {cred} and {token}, or run "
                        "`sheets.py login` to create a fresh token.")


def _backup_token(token):
    if token.exists():
        bak = token.with_name(f"{token.stem}.expired-{int(time.time())}{token.suffix}")
        token.rename(bak)
        print(f"Old token moved to {bak}", file=sys.stderr)


def relogin(settings):
    _, token = _paths(settings)
    _backup_token(token)
    return get_client(settings)


def open_spreadsheet(settings):
    gspread, gauth_exc = _imports()
    if is_placeholder(settings.get("sheet_id")):
        raise UserError("sheet_id is not set. Copy config/settings.local.example.json to "
                        "config/settings.local.json and put your Google Sheet ID in it.")
    client = get_client(settings)
    for attempt in (1, 2):
        try:
            return client.open_by_key(settings["sheet_id"])
        except gauth_exc.RefreshError as e:
            if attempt == 2:
                raise UserError(f"OAuth token rejected again after login ({e}).")
            print(f"OAuth token expired or revoked ({e}): log in once in the browser that opens.",
                  file=sys.stderr)
            client = relogin(settings)
        except gauth_exc.TransportError as e:
            raise UserError(f"Network error talking to Google ({e}). Check the internet connection.")
        except gspread.exceptions.SpreadsheetNotFound:
            raise UserError(f"Spreadsheet {settings['sheet_id']} not found, or this Google account "
                            "has no access. Check sheet_id in config/settings.local.json.")
        except gspread.exceptions.APIError as e:
            code = _status(e)
            if code == 403:
                raise UserError("Google refused access (403). The logged-in account cannot open this "
                                "sheet, or the Sheets/Drive API is not enabled for the OAuth client.")
            raise UserError(f"Google Sheets API error {code}: {e}")


def _status(e):
    try:
        return e.response.status_code
    except Exception:
        return getattr(e, "code", None)


def open_tab(sh, name):
    gspread, _ = _imports()
    try:
        return sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        tabs = ", ".join(repr(w.title) for w in sh.worksheets())
        raise UserError(f"tab {name!r} not found in the spreadsheet. Tabs that exist: {tabs}. "
                        "Fix main_tab/used_tab in config/settings.json.")


def with_retry(fn, what, attempts=3, already_done=None):
    """Retry fn on transient API/network errors. already_done() -> True skips a retry
    (used by append so a write that succeeded but timed out is never duplicated)."""
    gspread, gauth_exc = _imports()
    import requests
    delay = 2
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (gspread.exceptions.APIError, requests.exceptions.RequestException,
                gauth_exc.TransportError) as e:
            code = _status(e) if isinstance(e, gspread.exceptions.APIError) else None
            transient = code is None or code in RETRYABLE_STATUS
            if not transient or attempt == attempts:
                raise UserError(f"{what} failed after {attempt} attempt(s): {e}")
            print(f"{what}: attempt {attempt} failed ({e}); retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
            try:
                done = bool(already_done and already_done())
            except Exception:
                done = False
            if done:
                print(f"{what}: the earlier attempt did go through; not writing again.", file=sys.stderr)
                return None


# ---------------------------------------------------------------- operations

def open_tabs(settings):
    sh = open_spreadsheet(settings)
    return sh, open_tab(sh, settings["main_tab"]), open_tab(sh, settings["used_tab"])


def read_max_id(main_ws, main_map):
    col = with_retry(lambda: main_ws.col_values(main_map["ID"] + 1), "read ID column")
    return max_id_from_column(col)


def get_used(settings, niche, limit=120, used_ws=None):
    if used_ws is None:
        _, _, used_ws = open_tabs(settings)
    values = with_retry(used_ws.get_all_values, "read Used_Concepts")
    if not values:
        raise UserError(f"tab {settings['used_tab']!r} is empty (no header row)")
    m = header_map(values[0], USED_COLS, settings["used_tab"])
    key = norm_header(niche)
    rows = [r for r in values[1:] if len(r) > m["Niche"] and norm_header(r[m["Niche"]]) == key]
    recent = rows[-limit:] if limit else rows

    def col(r, c):
        return r[m[c]].strip() if len(r) > m[c] else ""
    return {
        "niche": niche,
        "total_for_niche": len(rows),
        "count": len(recent),
        "concept_names": [col(r, "Concept_Name") for r in recent if col(r, "Concept_Name")],
        "visual_metaphors": [col(r, "Visual_Metaphor") for r in recent if col(r, "Visual_Metaphor")],
    }


def get_prompts(settings, lo, hi):
    """Prompts with lo <= ID <= hi from the main tab: [{ID, niche, prompt}] sorted by ID."""
    _, main_ws, _ = open_tabs(settings)
    values = with_retry(main_ws.get_all_values, "read main tab")
    if not values:
        raise UserError(f"tab {settings['main_tab']!r} is empty")
    m = header_map(values[0], ["ID", "Niche category", "Prompt"], settings["main_tab"])
    out = {}
    for r in values[1:]:
        pid = parse_id(r[m["ID"]]) if len(r) > m["ID"] else None
        if pid is None or not lo <= pid <= hi:
            continue
        prompt = r[m["Prompt"]] if len(r) > m["Prompt"] else ""
        if not prompt.strip():
            continue
        out[pid] = {"ID": pid, "niche": r[m["Niche category"]] if len(r) > m["Niche category"] else "",
                    "prompt": prompt}
    return [out[k] for k in sorted(out)]


def cmd_test(args):
    settings = load_settings()
    sh, main_ws, used_ws = open_tabs(settings)
    main_headers = with_retry(lambda: main_ws.row_values(1), "read main headers")
    used_headers = with_retry(lambda: used_ws.row_values(1), "read used headers")
    main_map = header_map(main_headers, MAIN_COLS, main_ws.title)
    header_map(used_headers, USED_COLS, used_ws.title)
    max_id = read_max_id(main_ws, main_map)
    print(f"Spreadsheet: {sh.title}")
    print(f"Main tab:    {main_ws.title} ({len(main_headers)} columns, {main_ws.row_count} rows allocated)")
    print(f"Used tab:    {used_ws.title} ({len(used_headers)} columns)")
    print(f"Main headers: {', '.join(h for h in main_headers if h.strip())}")
    print(f"Current max ID: {max_id} (next ID will be {max_id + 1})")
    print("OK")
    return 0


def cmd_max_id(args):
    settings = load_settings()
    _, main_ws, _ = open_tabs(settings)
    main_map = header_map(main_ws.row_values(1), MAIN_COLS, main_ws.title)
    print(read_max_id(main_ws, main_map))
    return 0


def cmd_used(args):
    settings = load_settings()
    names = {n["niche"].lower() for n in load_niches()}
    if args.niche.lower() not in names:
        print(f"WARNING: '{args.niche}' is not a niche name in config/niches.json", file=sys.stderr)
    limit = args.limit if args.limit is not None else int(settings.get("used_history_per_niche", 120))
    data = get_used(settings, args.niche, limit)
    if args.out:
        save_json(args.out, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def _validate_prompts_file(prompts, path):
    if not isinstance(prompts, dict) or not isinstance(prompts.get("items"), list):
        raise UserError(f"{path} is not a prompts file (expected {{'niche':..., 'items': [...]}})")
    if not prompts["items"]:
        raise UserError(f"{path} has no prompts to append")
    if not prompts.get("niche"):
        raise UserError(f"{path} has no 'niche'")
    for i, it in enumerate(prompts["items"]):
        for k in ("prompt", "concept_name", "visual_metaphor"):
            if not str(it.get(k, "")).strip():
                raise UserError(f"{path} item {i + 1} is missing '{k}'")
        if ID_PLACEHOLDER not in it["prompt"]:
            raise UserError(f"{path} item {i + 1} has no {ID_PLACEHOLDER} placeholder "
                            "(was it already appended?)")


def cmd_append(args):
    settings = load_settings()
    path = Path(args.file)
    prompts = load_json(path)
    if isinstance(prompts, dict) and prompts.get("appended") and not args.dry_run:
        ids = [it.get("id") for it in prompts.get("items", [])]
        raise UserError(f"{path} was already appended on {prompts.get('appended_at')} as IDs {ids}. "
                        "Refusing to append twice.")
    _validate_prompts_file(prompts, path)

    _, main_ws, used_ws = open_tabs(settings)
    main_headers = with_retry(lambda: main_ws.row_values(1), "read main headers")
    used_headers = with_retry(lambda: used_ws.row_values(1), "read used headers")
    main_map = header_map(main_headers, MAIN_COLS, main_ws.title)
    used_map = header_map(used_headers, USED_COLS, used_ws.title)
    today = local_now(settings).date().isoformat()

    max_id = read_max_id(main_ws, main_map)  # read right before writing
    start = max_id + 1
    main_rows, used_rows, assigned = build_rows(
        prompts, start, len(main_headers), main_map, len(used_headers), used_map, today)
    last = start + len(main_rows) - 1

    if args.dry_run:
        print(f"DRY RUN - nothing written. Current max ID {max_id}; would assign IDs {start}-{last}.")
        print(f"\n{main_ws.title} rows ({len(main_headers)} columns, other columns left empty):")
        for row in main_rows:
            preview = {main_headers[i].strip() or f"col{i + 1}": (v if not (isinstance(v, str) and len(v) > 160)
                       else v[:160] + f"... [{len(v)} chars]") for i, v in enumerate(row) if v != ""}
            print(json.dumps(preview, ensure_ascii=False, indent=2))
        print(f"\n{used_ws.title} rows:")
        for row in used_rows:
            print(json.dumps({used_headers[i].strip(): v for i, v in enumerate(row) if v != ""},
                             ensure_ascii=False))
        print("\nFirst prompt with ID filled in:\n")
        print(assigned[0]["prompt"])
        return 0

    def ids_present():
        col = main_ws.col_values(main_map["ID"] + 1)
        present = {parse_id(v) for v in col[1:]}
        return start in present

    if with_retry(ids_present, "pre-write check"):
        raise UserError(f"ID {start} already exists in the sheet; another writer is active. Try again.")

    with_retry(lambda: main_ws.append_rows(main_rows, value_input_option="RAW",
                                           insert_data_option="INSERT_ROWS", table_range="A1"),
               f"append {len(main_rows)} rows to {main_ws.title}", already_done=ids_present)

    def used_present():
        col = used_ws.col_values(used_map["Prompt_ID"] + 1)
        return start in {parse_id(v) for v in col[1:]}

    with_retry(lambda: used_ws.append_rows(used_rows, value_input_option="RAW",
                                           insert_data_option="INSERT_ROWS", table_range="A1"),
               f"append {len(used_rows)} rows to {used_ws.title}", already_done=used_present)

    # verify
    col = with_retry(lambda: main_ws.col_values(main_map["ID"] + 1), "verify IDs")
    present = {parse_id(v) for v in col[1:]}
    missing = [a["id"] for a in assigned if a["id"] not in present]
    if missing:
        raise UserError(f"Append finished but IDs {missing} are not visible in {main_ws.title}. Check the sheet.")

    for item, a in zip(prompts["items"], assigned):
        item["id"] = a["id"]
        item["prompt_final"] = a["prompt"]
    prompts["appended"] = True
    prompts["appended_at"] = local_now(settings).isoformat(timespec="seconds")
    prompts["id_range"] = [start, last]
    save_json(path, prompts)
    print(f"Appended {len(main_rows)} prompts to {main_ws.title} as IDs {start}-{last} "
          f"and {len(used_rows)} rows to {used_ws.title}.")
    return 0


def cmd_login(args):
    settings = load_settings()
    relogin(settings)
    sh = open_spreadsheet(settings)
    print(f"Login OK. Spreadsheet: {sh.title}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test")
    sub.add_parser("max-id")
    sub.add_parser("login")
    u = sub.add_parser("used")
    u.add_argument("--niche", required=True)
    u.add_argument("--limit", type=int)
    u.add_argument("--out")
    a = sub.add_parser("append")
    a.add_argument("--file", required=True)
    a.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    return {"test": cmd_test, "max-id": cmd_max_id, "used": cmd_used, "append": cmd_append,
            "login": cmd_login}[args.cmd](args)


if __name__ == "__main__":
    run_main(main)
