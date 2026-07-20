"""Card Kingdom prices via their public pricelist feed.

https://api.cardkingdom.com/api/pricelist returns every product CK sells
(name, edition, variation, foil flag, retail price, qty in stock) in one
JSON document. No auth required; be polite and cache it — it's ~20 MB.
"""

import json
import time
from pathlib import Path

import pandas as pd

from .base import get_json, make_session, normalize, normalize_base

CACHE_MAX_AGE_S = 6 * 3600


def _load_pricelist(url: str, cache_dir: Path) -> list[dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / "cardkingdom_pricelist.json"
    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_MAX_AGE_S:
        return json.loads(cache.read_text())["data"]
    payload = get_json(make_session(), url, timeout=120)
    cache.write_text(json.dumps(payload))
    return payload["data"]


def fetch(cards: pd.DataFrame, cfg: dict, cache_dir: Path = Path("output/cache")) -> pd.Series:
    """Return a price per card (indexed like `cards`), NaN when unmatched.

    Matching strategy, in order of preference:
      1. exact normalized name (variant tags included), in-stock, non-foil
      2. base name with variant tags stripped, in-stock — cheapest printing
    """
    rows = _load_pricelist(cfg["pricelist_url"], cache_dir)

    by_name: dict[str, float] = {}
    by_base: dict[str, float] = {}
    for r in rows:
        if r.get("is_foil") in (True, "true", 1):
            continue
        try:
            price = float(r["price_retail"])
        except (KeyError, TypeError, ValueError):
            continue
        if int(r.get("qty_retail") or 0) <= 0:
            continue
        n = normalize(r.get("name", ""))
        b = normalize_base(r.get("name", ""))
        if n and (n not in by_name or price < by_name[n]):
            by_name[n] = price
        if b and (b not in by_base or price < by_base[b]):
            by_base[b] = price

    def lookup(name: str) -> float | None:
        return by_name.get(normalize(name)) or by_base.get(normalize_base(name))

    return pd.Series([lookup(n) for n in cards["name"]], index=cards.index,
                     name="cardkingdom", dtype=float)
