"""Same-printing multi-vendor prices via tcgapis trend-prices (Business+ plan).

POST /api/v2/trendprices/bulk with up to 200 productIds returns, per product
(= per TCGplayer printing), a `prices` array with retail/buylist prices from
tcgplayer, cardkingdom, manapool, cardmarket, cardhoarder for each finish.

Because every vendor's price is keyed to the SAME productId, this gives a
true same-printing comparison with no name/set crosswalk — the fix for the
printing-substitution bias. We take paper / normal-finish / retail prices.
"""

import json
import time
from pathlib import Path

import pandas as pd

from .base import make_session
from .tcgapis import _load_key

BULK_URL = "https://api.tcgapis.com/api/v2/trendprices/bulk"
BATCH = 200
VENDOR_KEYS = {"tcgplayer": "tcgplayer", "cardkingdom": "cardkingdom", "manapool": "manapool"}
CACHE_MAX_AGE_S = 12 * 3600


def _pick(prices: list[dict], provider: str) -> float | None:
    """paper / normal / retail price for one provider, cheapest if multiple."""
    best = None
    for p in prices:
        if (p.get("priceProvider") == provider
                and p.get("providerListing") == "retail"
                and p.get("cardFinish") == "normal"
                and p.get("gameAvailability") == "paper"
                and p.get("currency") == "USD"):
            v = p.get("price")
            if isinstance(v, (int, float)) and v > 0 and (best is None or v < best):
                best = float(v)
    return best


def fetch(product_ids: list[int], cache_dir: Path = Path("output/cache"),
          cache_name: str = "trendprices.csv") -> pd.DataFrame:
    """Return a frame indexed by productId with tcgplayer/cardkingdom/manapool
    retail prices for that exact printing."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / cache_name
    cached: dict[int, dict] = {}
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_MAX_AGE_S:
        df = pd.read_csv(cache_file)
        cached = {int(r.productId): {"tcgplayer": r.tcgplayer,
                                     "cardkingdom": r.cardkingdom,
                                     "manapool": r.manapool} for r in df.itertuples()}

    session = make_session()
    session.headers["x-api-key"] = _load_key()
    session.headers["Content-Type"] = "application/json"

    todo = [int(p) for p in product_ids if int(p) not in cached]
    out = dict(cached)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        for attempt in range(3):
            try:
                resp = session.post(BULK_URL, data=json.dumps({"productIds": chunk}), timeout=60)
                resp.raise_for_status()
                for row in resp.json().get("data", []):
                    pid = int(row["productId"])
                    prices = row.get("prices", [])
                    out[pid] = {v: _pick(prices, k) for v, k in VENDOR_KEYS.items()}
                break
            except Exception as err:  # noqa: BLE001
                if attempt == 2:
                    print(f"  [trendprices] batch {i//BATCH} failed: {err}")
                else:
                    time.sleep(2 * (attempt + 1))
        if (i // BATCH) % 5 == 0:
            print(f"  [trendprices] {min(i+BATCH, len(todo))}/{len(todo)} fetched")

    pd.DataFrame([{"productId": k, **v} for k, v in out.items()]).to_csv(cache_file, index=False)
    return pd.DataFrame.from_dict(out, orient="index")[["tcgplayer", "cardkingdom", "manapool"]]
