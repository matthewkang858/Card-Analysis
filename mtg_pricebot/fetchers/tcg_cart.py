"""Simulate a real TCGplayer multi-seller cart from live listings.

tcgapis GET /api/v2/livelistings/{productId} returns actual listings:
price, per-listing shipping, sellerName/sellerId, condition, quantity.
From those we approximate what Mass Entry does:

  1. take each card's cheapest listings as candidates
  2. assign each card its cheapest listing
  3. consolidation pass: move a card to a seller already in the cart when
     the price difference is smaller than the shipping saved
  4. cart total = item prices + one shipping charge per seller (the max of
     that seller's listing shipping values — sellers charge shipping once
     per order, not per card)

This is a lower bound on optimality but mirrors how a careful buyer (or
the Mass Entry optimizer) actually behaves.
"""

import json
import time
from pathlib import Path

import pandas as pd

from .base import make_session
from .tcgapis import BASE_URL, REQUEST_DELAY_S, _load_key

CACHE_MAX_AGE_S = 6 * 3600
CANDIDATES_PER_CARD = 12


def _extract_listings(payload: dict) -> list[dict]:
    """Flatten data.allListings[condition][printing][standard|custom]."""
    out = []
    data = payload.get("data", {})
    for condition, printings in (data.get("allListings") or {}).items():
        for printing, kinds in (printings or {}).items():
            if printing not in ("Normal",):
                continue
            for kind, rows in (kinds or {}).items():
                for r in rows or []:
                    price = r.get("price")
                    if not isinstance(price, (int, float)) or price <= 0:
                        continue
                    out.append({
                        "price": float(price),
                        "shipping": float(r.get("shipping") or 0),
                        "seller": r.get("sellerId") or r.get("sellerName"),
                        "condition": condition,
                    })
    out.sort(key=lambda x: x["price"])
    return out[:CANDIDATES_PER_CARD]


def fetch_listings(cards: pd.DataFrame, cache_dir: Path = Path("output/cache")) -> dict[int, list[dict]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "tcgapis_listings.json"
    cached: dict[str, list] = {}
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_MAX_AGE_S:
        cached = json.loads(cache_file.read_text())

    session = make_session()
    session.headers["x-api-key"] = _load_key()

    out: dict[int, list[dict]] = {}
    for pid in (int(p) for p in cards["productId"]):
        if str(pid) in cached:
            out[pid] = cached[str(pid)]
            continue
        try:
            resp = session.get(f"{BASE_URL}/livelistings/{pid}", timeout=30)
            resp.raise_for_status()
            out[pid] = _extract_listings(resp.json())
            time.sleep(REQUEST_DELAY_S)
        except Exception as err:  # noqa: BLE001
            print(f"  [tcg_cart] listings failed for {pid}: {err}")
            out[pid] = []

    cache_file.write_text(json.dumps({str(k): v for k, v in out.items()}))
    return out


def cart_total(product_ids: list[int], listings: dict[int, list[dict]]) -> tuple[float, float, int]:
    """(items_total, shipping_total, n_sellers) for one simulated cart."""
    chosen: dict[int, dict] = {}
    for pid in product_ids:
        cands = listings.get(pid) or []
        if cands:
            chosen[pid] = cands[0]
    if not chosen:
        return 0.0, 0.0, 0

    def seller_shipping(assignment: dict[int, dict]) -> dict:
        by_seller: dict = {}
        for lst in assignment.values():
            s = lst["seller"]
            by_seller[s] = max(by_seller.get(s, 0.0), lst["shipping"])
        return by_seller

    # Consolidation: try moving each card to a seller already carrying
    # another card, when the price bump is less than the shipping saved.
    improved = True
    while improved:
        improved = False
        sellers_in_cart = {lst["seller"] for lst in chosen.values()}
        for pid, current in list(chosen.items()):
            if current["seller"] in sellers_in_cart and \
               sum(1 for l in chosen.values() if l["seller"] == current["seller"]) > 1:
                continue
            for cand in (listings.get(pid) or []):
                if cand is current or cand["seller"] not in sellers_in_cart:
                    continue
                old_ship = sum(seller_shipping(chosen).values())
                trial = dict(chosen); trial[pid] = cand
                new_ship = sum(seller_shipping(trial).values())
                if cand["price"] + new_ship < current["price"] + old_ship:
                    chosen[pid] = cand
                    improved = True
                    break

    items = sum(l["price"] for l in chosen.values())
    ship_map = seller_shipping(chosen)
    return items, sum(ship_map.values()), len(ship_map)
