"""TCGplayer prices via tcgapis.com (docs: https://tcgapis.com/documentation,
markdown reference: https://tcgapis.com/tcgapis-ai-builder-docs.md).

Auth: API key in the `x-api-key` header, supplied via the TCGAPIS_KEY
environment variable or a gitignored .env file — never commit the key.

Endpoint: GET https://api.tcgapis.com/api/v2/prices/{productId}
(the same TCGplayer productId used in the sales export, so matching is
exact). Fetched prices are cached to CSV so re-runs don't re-spend quota.
"""

import os
import time
from pathlib import Path

import pandas as pd

from .base import make_session

BASE_URL = "https://api.tcgapis.com/api/v2"
REQUEST_DELAY_S = 0.15
CACHE_MAX_AGE_S = 6 * 3600


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


PRICE_FIELDS = ("marketPrice", "midPrice", "directLowPrice", "lowPrice")


def _variant_price(variant: dict) -> float | None:
    for k in PRICE_FIELDS:
        v = variant.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _parse_price(payload) -> float | None:
    """Pull a non-foil market price from a /v2/prices/{productId} response.

    Shape (verified live): {"success": true, "data": {"productId": ...,
    "prices": {"Normal": {marketPrice, midPrice, lowPrice, directLowPrice},
               "Foil": {...}, ...}}}
    Prefers the Normal variant; falls back to any variant with a price.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get("data", payload)
    variants = data.get("prices", {}) if isinstance(data, dict) else {}
    if isinstance(variants, dict):
        normal = variants.get("Normal")
        if isinstance(normal, dict):
            v = _variant_price(normal)
            if v:
                return v
        for variant in variants.values():
            if isinstance(variant, dict):
                v = _variant_price(variant)
                if v:
                    return v
    if isinstance(data, dict):
        return _variant_price(data)
    return None


def fetch(cards: pd.DataFrame, cfg: dict, cache_dir: Path = Path("output/cache")) -> pd.Series:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "tcgapis_prices.csv"
    cached: dict[int, float] = {}
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_MAX_AGE_S:
        df = pd.read_csv(cache_file)
        cached = dict(zip(df["productId"].astype(int), df["price"]))

    session = make_session()
    session.headers["x-api-key"] = _load_key()

    prices: dict[int, float] = {}
    first_error_shown = False
    wanted = [int(p) for p in cards["productId"]]
    for pid in wanted:
        if pid in cached:
            prices[pid] = cached[pid]
            continue
        try:
            resp = session.get(f"{BASE_URL}/prices/{pid}", timeout=30)
            resp.raise_for_status()
            v = _parse_price(resp.json())
            if v:
                prices[pid] = v
            time.sleep(REQUEST_DELAY_S)
        except Exception as err:  # noqa: BLE001 - diagnose the first failure loudly
            if not first_error_shown:
                body = getattr(getattr(err, "response", None), "text", "")[:500]
                print(f"  [tcgapis] request failed for productId {pid}: {err}\n"
                      f"  first response body: {body!r}")
                first_error_shown = True

    pd.DataFrame({"productId": list(prices), "price": list(prices.values())}) \
        .to_csv(cache_file, index=False)
    return pd.Series([prices.get(int(pid)) for pid in cards["productId"]],
                     index=cards.index, name="tcgplayer", dtype=float)
