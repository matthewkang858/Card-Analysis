"""ManaPool prices via their public API.

ManaPool documents a public API at https://manapool.com/api. This module
could not be verified against the live API from the development environment
(network-restricted), so the endpoint path and response shape below follow
their published docs at the time of writing — if a request 404s, check the
docs and adjust ENDPOINT / the parsing in _extract_prices().

Auth (only if the docs say the endpoint requires it): set `email` and
`access_token` in config.yaml; they are sent as X-ManaPool-Email /
X-ManaPool-Access-Token headers.
"""

import json
import time
from pathlib import Path

import pandas as pd

from .base import get_json, make_session, normalize_base

ENDPOINT = "/prices"  # relative to api_base, e.g. https://manapool.com/api/v1/prices
CACHE_MAX_AGE_S = 6 * 3600


def _load_prices(cfg: dict, cache_dir: Path) -> list[dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / "manapool_prices.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_MAX_AGE_S:
        return json.loads(cache.read_text())

    session = make_session()
    if cfg.get("email") and cfg.get("access_token"):
        session.headers["X-ManaPool-Email"] = cfg["email"]
        session.headers["X-ManaPool-Access-Token"] = cfg["access_token"]

    payload = get_json(session, cfg["api_base"].rstrip("/") + ENDPOINT, timeout=120)
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    cache.write_text(json.dumps(rows))
    return rows


def _extract_prices(rows: list[dict]) -> dict[str, float]:
    """Map normalized base card name -> cheapest non-foil price in dollars."""
    out: dict[str, float] = {}
    for r in rows:
        name = r.get("name") or r.get("card_name")
        if not name:
            continue
        # Docs show prices in cents (price_cents / low_price_cents); fall back
        # to a dollar field if present.
        cents = r.get("price_cents") or r.get("low_price_cents")
        price = cents / 100 if cents else r.get("price") or r.get("low_price")
        if not price:
            continue
        key = normalize_base(name)
        if key not in out or price < out[key]:
            out[key] = float(price)
    return out


def fetch(cards: pd.DataFrame, cfg: dict, cache_dir: Path = Path("output/cache")) -> pd.Series:
    prices = _extract_prices(_load_prices(cfg, cache_dir))
    return pd.Series([prices.get(normalize_base(n)) for n in cards["name"]],
                     index=cards.index, name="manapool", dtype=float)
