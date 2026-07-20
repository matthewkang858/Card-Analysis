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


def _parse_variant(payload) -> dict | None:
    """Return the Normal (or best available) variant dict from a response."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data", payload)
    variants = data.get("prices", {}) if isinstance(data, dict) else {}
    if isinstance(variants, dict):
        normal = variants.get("Normal")
        if isinstance(normal, dict) and _variant_price(normal):
            return normal
        for variant in variants.values():
            if isinstance(variant, dict) and _variant_price(variant):
                return variant
    return None


def fetch_table(cards: pd.DataFrame, cache_dir: Path = Path("output/cache")) -> pd.DataFrame:
    """Market AND lowest-listing price per card (indexed like `cards`)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "tcgapis_prices_full.csv"
    cached: dict[int, tuple] = {}
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_MAX_AGE_S:
        df = pd.read_csv(cache_file)
        cached = {int(r.productId): (r.market, r.low) for r in df.itertuples()}

    session = make_session()
    session.headers["x-api-key"] = _load_key()

    out: dict[int, tuple] = {}
    first_error_shown = False
    for pid in (int(p) for p in cards["productId"]):
        if pid in cached:
            out[pid] = cached[pid]
            continue
        try:
            resp = session.get(f"{BASE_URL}/prices/{pid}", timeout=30)
            resp.raise_for_status()
            variant = _parse_variant(resp.json())
            if variant:
                market = variant.get("marketPrice") or variant.get("midPrice")
                low = variant.get("lowPrice") or variant.get("directLowPrice") or market
                out[pid] = (float(market) if market else None,
                            float(low) if low else None)
            time.sleep(REQUEST_DELAY_S)
        except Exception as err:  # noqa: BLE001
            if not first_error_shown:
                body = getattr(getattr(err, "response", None), "text", "")[:500]
                print(f"  [tcgapis] request failed for productId {pid}: {err}\n"
                      f"  first response body: {body!r}")
                first_error_shown = True

    pd.DataFrame([{"productId": k, "market": v[0], "low": v[1]} for k, v in out.items()]) \
        .to_csv(cache_file, index=False)
    return pd.DataFrame({
        "tcg_market": [out.get(int(p), (None, None))[0] for p in cards["productId"]],
        "tcg_low": [out.get(int(p), (None, None))[1] for p in cards["productId"]],
    }, index=cards.index)


def fetch(cards: pd.DataFrame, cfg: dict, cache_dir: Path = Path("output/cache")) -> pd.Series:
    table = fetch_table(cards, cache_dir)
    return table["tcg_market"].rename("tcgplayer")
