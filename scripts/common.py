"""Shared helpers for the stock prompt engine scripts."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
RUNS = ROOT / "runs"
METADATA_DIR = ROOT / "metadata"
ID_PLACEHOLDER = "__ID__"

# Brand blocklist (case-insensitive, whole word). Shared by engine.py and metadata.py.
BRAND_PATTERN = (
    r"apple|iphone|ipad|google|microsoft|openai|chatgpt|gpt-\d|gemini|anthropic|claude|nvidia|"
    r"facebook|instagram|whatsapp|tiktok|tesla|amazon|aws|azure|bitcoin|btc|ethereum|binance|"
    r"coinbase|samsung|intel|amd|ibm|oracle|salesforce|github|docker|kubernetes|twitter|starlink|"
    r"spacex|netflix|youtube|meta quest|vision pro|playstation|xbox|huawei|cisco|crowdstrike"
)
# "gpt-\d" is matched as gpt-\d\w* so "gpt-4o" is caught too.
BRAND_RE = re.compile(
    r"\b(?:" + BRAND_PATTERN.replace(r"gpt-\d", r"gpt-\d\w*") + r")\b", re.IGNORECASE
)


class UserError(Exception):
    """An error with a plain message meant for the user (no traceback)."""


def utf8_stdout():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def load_json(path):
    path = Path(path)
    if not path.exists():
        raise UserError(f"File not found: {path}")
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise UserError(f"Invalid JSON in {path}: line {e.lineno}, column {e.colno}: {e.msg}")


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


LOCAL_SETTINGS = CONFIG / "settings.local.json"


def load_settings():
    """Public config/settings.json, overridden key by key by the git-ignored
    config/settings.local.json (personal values: sheet ID, OAuth file paths)."""
    settings = load_json(CONFIG / "settings.json")
    if LOCAL_SETTINGS.exists():
        local = load_json(LOCAL_SETTINGS)
        settings.update({k: v for k, v in local.items() if not k.startswith("_")})
    return settings


def is_placeholder(value):
    return not value or str(value).strip().upper().startswith("YOUR_")


def load_niches():
    return load_json(CONFIG / "niches.json")


def load_looks():
    return load_json(CONFIG / "looks.json")


def get_niche(niche_id, niches=None):
    niches = niches if niches is not None else load_niches()
    for n in niches:
        if int(n["niche_id"]) == int(niche_id):
            return n
    raise UserError(f"niche_id {niche_id} not found in config/niches.json")


def local_tz(settings=None):
    name = (settings or {}).get("timezone", "Asia/Karachi")
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        # Pakistan has no DST; fixed offset is a safe fallback if tzdata is missing.
        return dt.timezone(dt.timedelta(hours=5), "PKT")


def local_now(settings=None):
    return dt.datetime.now(local_tz(settings))


def find_brands(text):
    return sorted({m.group(0).lower() for m in BRAND_RE.finditer(text or "")})


def run_main(fn):
    """Run a CLI main() turning UserError into a clean message and exit code 1."""
    utf8_stdout()
    try:
        code = fn()
    except UserError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        sys.exit(130)
    sys.exit(code or 0)
