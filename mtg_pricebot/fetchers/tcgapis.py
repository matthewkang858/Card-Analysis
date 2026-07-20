"""TCGplayer prices via tcgapis.com (third-party TCGplayer API service).

Auth: an API key, supplied via the TCGAPIS_KEY environment variable (a
gitignored .env file works — never commit the key). The key is sent both as
a Bearer token and an X-Api-Key header, which covers the common conventions.

NOTE: this module was written while tcgapis.com was unreachable from the
development environment, so the endpoint path and response parsing follow
common REST conventions and are marked below. On the first live run, if the
request 404s, check https://tcgapis.com/docs and adjust ENDPOINT_TEMPLATE /
_parse_response(); the diagnostic print shows the raw response to make that
a one-line fix.
"""

import os
from pathlib import Path

import pandas as pd

from .base import make_session

# UNVERIFIED endpoint convention — confirm against https://tcgapis.com/docs.
ENDPOINT_TEMPLATE = "https://tcgapis.com/api/v1/prices/{product_id}"
BATCH_SIZE = 100


def _load_key() -> str:
    key = os.environ.get("TCGAPIS_KEY")
    if not key:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("TCGAPIS_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        raise RuntimeError(
            "TCGAPIS_KEY not set. Export it or put 'TCGAPIS_KEY=...' in .env "
            "(gitignored). Never commit the key.")
    return key


def _parse_response(payload) -> float | None:
    """Pull a usable non-foil price out of one product's price payload."""
    if isinstance(payload, dict):
        for k in ("marketPrice", "market_price", "price", "lowPrice", "low_price"):
            v = payload.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        for k in ("data", "results", "prices"):
            if k in payload:
                return _parse_response(payload[k])
    if isinstance(payload, list):
        # Prefer the Normal (non-foil) subtype when rows carry one.
        rows = [r for r in payload if isinstance(r, dict)]
        normal = [r for r in rows if r.get("subTypeName", "Normal") == "Normal"]
        for r in normal or rows:
            v = _parse_response(r)
            if v:
                return v
    return None


def fetch(cards: pd.DataFrame, cfg: dict, cache_dir: Path = Path("output/cache")) -> pd.Series:
    key = _load_key()
    session = make_session()
    session.headers["Authorization"] = f"Bearer {key}"
    session.headers["X-Api-Key"] = key

    prices: dict[int, float] = {}
    first_error_shown = False
    for pid in cards["productId"].astype(int):
        try:
            resp = session.get(ENDPOINT_TEMPLATE.format(product_id=pid), timeout=30)
            resp.raise_for_status()
            v = _parse_response(resp.json())
            if v:
                prices[pid] = v
        except Exception as err:  # noqa: BLE001 - diagnose the first failure loudly
            if not first_error_shown:
                body = getattr(getattr(err, "response", None), "text", "")[:500]
                print(f"  [tcgapis] request failed for productId {pid}: {err}\n"
                      f"  first response body: {body!r}\n"
                      f"  -> check https://tcgapis.com/docs and adjust "
                      f"ENDPOINT_TEMPLATE/_parse_response in fetchers/tcgapis.py")
                first_error_shown = True

    return pd.Series([prices.get(int(pid)) for pid in cards["productId"]],
                     index=cards.index, name="tcgplayer", dtype=float)
