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


def _parse_price(payload) -> float | None:
    """Pull a non-foil market price out of one product's price payload."""
    if isinstance(payload, dict):
        for k in ("data", "results", "prices"):
            if k in payload:
                return _parse_price(payload[k])
        for k in ("marketPrice", "market_price", "midPrice", "price",
                  "lowPrice", "low_price"):
            v = payload.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
    if isinstance(payload, list):
        rows = [r for r in payload if isinstance(r, dict)]
        normal = [r for r in rows if r.get("subTypeName", "Normal") == "Normal"]
        for r in normal or rows:
            v = _parse_price(r)
            if v:
                return v
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
