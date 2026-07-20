"""Shared helpers for vendor fetchers: polite HTTP session + name matching."""

import re
import time

import requests

USER_AGENT = "mtg-pricebot/0.1 (personal price research; contact via repo)"

# Trailing parenthetical variant tags TCGplayer appends to product names,
# e.g. "Force of Will (JP Alternate Art) (Silver Scroll Foil)".
_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
_NORM_RE = re.compile(r"[^a-z0-9 ]+")


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def get_json(session: requests.Session, url: str, retries: int = 3, backoff: float = 2.0,
             timeout: int = 60, **kwargs):
    """GET a JSON document with simple exponential-backoff retries."""
    last_err = None
    for attempt in range(retries):
        try:
            resp = session.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as err:
            last_err = err
            time.sleep(backoff * (2 ** attempt))
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def strip_variant(name: str) -> str:
    """Remove trailing parenthetical variant tags, keeping the base card name."""
    prev = None
    while prev != name:
        prev = name
        name = _PAREN_RE.sub("", name)
    return name


def normalize(name: str) -> str:
    """Lowercase, drop punctuation — for fuzzy-ish cross-vendor name matching."""
    return _NORM_RE.sub("", name.lower()).strip()


def normalize_base(name: str) -> str:
    return normalize(strip_variant(name))
