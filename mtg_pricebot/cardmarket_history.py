"""Backfill Cardmarket daily price history for Magic via MTGJSON.

MTGJSON's AllPrices feed is the one free source of Cardmarket's daily
"avg sell price" series (the line drawn on each cardmarket.com product
page), keyed by MTGJSON UUID. It keeps a rolling window (~90 days) — that
is the maximum backfill available; extend it forward with a daily snapshot.

Files (https://mtgjson.com/api/v5/):
  Meta.json              - version + date, cheap reachability check
  AllIdentifiers.json.gz - uuid -> {name, setCode, identifiers{tcgplayerProductId, scryfallId}}
  AllPrices.json.gz      - uuid -> paper.cardmarket.retail.{normal,foil}.{YYYY-MM-DD: eur}

Prices are EUR. Requires mtgjson.com on the network allow-list.

Usage:
  python -m mtg_pricebot.cardmarket_history                 # all Magic cards
  python -m mtg_pricebot.cardmarket_history --product-ids data/unified_pool.csv
"""

import argparse
import gzip
import sys
from pathlib import Path

import ijson
import pandas as pd
import requests

BASE = "https://mtgjson.com/api/v5"
CACHE = Path("output/cache")


def _download(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / name
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  using cached {dest}")
        return dest
    url = f"{BASE}/{name}"
    print(f"  downloading {url} ...")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    print(f"  saved {dest} ({dest.stat().st_size/1e6:.0f} MB)")
    return dest


def check_reachable() -> bool:
    try:
        m = requests.get(f"{BASE}/Meta.json", timeout=30).json()
        print(f"MTGJSON reachable. version {m.get('meta', m).get('version')} "
              f"date {m.get('meta', m).get('date')}")
        return True
    except Exception as err:  # noqa: BLE001
        print(f"MTGJSON NOT reachable ({err}). Add mtgjson.com to the network "
              f"allow-list, then re-run.")
        return False


def _open_gz(path: Path):
    return gzip.open(path, "rb")


def build_identifier_map(want_pids: set[int] | None):
    """uuid -> (name, tcgplayerProductId). Streamed to bound memory."""
    path = _download("AllIdentifiers.json.gz")
    out = {}
    with _open_gz(path) as f:
        for uuid, card in ijson.kvitems(f, "data"):
            ids = card.get("identifiers", {}) or {}
            pid = ids.get("tcgplayerProductId")
            pid = int(pid) if pid and str(pid).isdigit() else None
            if want_pids is not None and (pid is None or pid not in want_pids):
                continue
            out[uuid] = (card.get("name"), pid)
    print(f"  identifier map: {len(out)} cards")
    return out


def extract_cardmarket(id_map: dict, want_all: bool):
    """Return tidy rows: date, productId, name, uuid, eur, eur_foil."""
    path = _download("AllPrices.json.gz")
    rows = []
    keep = None if want_all else set(id_map)
    with _open_gz(path) as f:
        for uuid, pdata in ijson.kvitems(f, "data"):
            if keep is not None and uuid not in keep:
                continue
            cm = (((pdata or {}).get("paper") or {}).get("cardmarket") or {})
            retail = cm.get("retail") or {}
            normal = retail.get("normal") or {}
            foil = retail.get("foil") or {}
            if not normal and not foil:
                continue
            name, pid = id_map.get(uuid, (None, None))
            for date in sorted(set(normal) | set(foil)):
                rows.append({
                    "date": date, "productId": pid, "name": name, "uuid": uuid,
                    "cardmarket_eur": normal.get(date),
                    "cardmarket_eur_foil": foil.get(date),
                })
    return pd.DataFrame(rows)


def main(argv=None):
    p = argparse.ArgumentParser(prog="cardmarket_history")
    p.add_argument("--product-ids", default=None,
                   help="CSV with a productId column to restrict to (else all Magic cards)")
    p.add_argument("--out", default="data/cardmarket_history_mtg.csv")
    args = p.parse_args(argv)

    if not check_reachable():
        return 1

    want_pids = None
    if args.product_ids:
        df = pd.read_csv(args.product_ids)
        want_pids = {int(x) for x in df["productId"].dropna()}
        print(f"restricting to {len(want_pids)} productIds from {args.product_ids}")

    id_map = build_identifier_map(want_pids)
    hist = extract_cardmarket(id_map, want_all=(want_pids is None))
    if hist.empty:
        print("No Cardmarket history extracted — check the file format / crosswalk.")
        return 2

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    hist.to_csv(args.out, index=False)
    span = f"{hist.date.min()} .. {hist.date.max()}"
    print(f"\nWrote {args.out}: {len(hist):,} rows, {hist.name.nunique()} cards, "
          f"date range {span} ({hist.date.nunique()} days)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
