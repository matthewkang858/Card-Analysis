"""ManaPool prices via their public API (verified live 2026-07-20).

GET {api_base}/prices/singles requires NO auth and returns every single
they sell: name, set_code, scryfall_id, available_quantity, and prices in
cents by condition/finish (price_cents = cheapest available, price_cents_nm
= near mint, price_market = their market estimate, ...). ~50 MB, so it's
cached. OpenAPI spec: https://manapool.com/api/docs/v1/openapi.json

Matching is by normalized base card name, taking the cheapest in-stock
non-foil printing — consistent with how the Card Kingdom fetcher matches.
"""

import json
import time
from pathlib import Path

import pandas as pd

from .base import get_json, make_session, normalize_base

ENDPOINT = "/prices/singles"
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

    payload = get_json(session, cfg["api_base"].rstrip("/") + ENDPOINT, timeout=180)
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    cache.write_text(json.dumps(rows))
    return rows


def _row_price(r: dict) -> float | None:
    """Cheapest usable non-foil price in dollars: NM preferred, then LP+,
    then any condition."""
    if not r.get("available_quantity"):
        return None
    for k in ("price_cents_nm", "price_cents_lp_plus", "price_cents"):
        cents = r.get(k)
        if cents:
            return cents / 100
    return None


def _extract_prices(rows: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in rows:
        name = r.get("name")
        price = _row_price(r)
        if not name or not price:
            continue
        key = normalize_base(name)
        if key not in out or price < out[key]:
            out[key] = price
    return out


def fetch(cards: pd.DataFrame, cfg: dict, cache_dir: Path = Path("output/cache")) -> pd.Series:
    prices = _extract_prices(_load_prices(cfg, cache_dir))
    return pd.Series([prices.get(normalize_base(n)) for n in cards["name"]],
                     index=cards.index, name="manapool", dtype=float)
