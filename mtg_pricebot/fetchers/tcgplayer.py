"""TCGplayer prices via tcgcsv.com's daily mirror of the official price feed.

tcgcsv.com republishes TCGplayer's prices keyed by the same productId that
appears in the sales export, so matching is exact — no name fuzzing needed.

Endpoints (Magic = category 1):
  GET {base}/{cat}/groups            -> every set with its groupId
  GET {base}/{cat}/{groupId}/prices  -> prices for every product in that set
"""

import time
from pathlib import Path

import pandas as pd

from .base import get_json, make_session, normalize

REQUEST_DELAY_S = 0.3  # be polite: tcgcsv is a free community mirror


def fetch(cards: pd.DataFrame, cfg: dict, cache_dir: Path = Path("output/cache")) -> pd.Series:
    """Return a price per card by productId. NaN when the feed has no price."""
    base = cfg["tcgcsv_base"].rstrip("/")
    cat = cfg["category_id"]
    price_field = cfg.get("price_field", "marketPrice")
    session = make_session()

    groups = get_json(session, f"{base}/{cat}/groups")["results"]
    group_by_name = {normalize(g["name"]): g["groupId"] for g in groups}

    # Only fetch the sets our basket actually needs.
    wanted_sets = {normalize(s) for s in cards["set"].unique()}
    group_ids = {group_by_name[s] for s in wanted_sets if s in group_by_name}
    missing = sorted(s for s in wanted_sets if s not in group_by_name)
    if missing:
        print(f"  [tcgplayer] no tcgcsv group for sets: {missing[:10]}"
              + (" ..." if len(missing) > 10 else ""))

    prices: dict[int, float] = {}
    for gid in sorted(group_ids):
        results = get_json(session, f"{base}/{cat}/{gid}/prices")["results"]
        for p in results:
            if p.get("subTypeName") == "Foil":
                continue  # prefer the Normal printing; fall back below
            v = p.get(price_field) or p.get("marketPrice") or p.get("lowPrice")
            if v:
                prices[int(p["productId"])] = float(v)
        # Foil-only products (no Normal row) — take the foil price.
        for p in results:
            pid = int(p["productId"])
            if pid not in prices:
                v = p.get(price_field) or p.get("marketPrice") or p.get("lowPrice")
                if v:
                    prices[pid] = float(v)
        time.sleep(REQUEST_DELAY_S)

    return pd.Series([prices.get(int(pid)) for pid in cards["productId"]],
                     index=cards.index, name="tcgplayer", dtype=float)
