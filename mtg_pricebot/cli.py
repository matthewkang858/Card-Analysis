"""Pipeline CLI.

  python -m mtg_pricebot rank                 # rank cards from the sales export
  python -m mtg_pricebot run --demo           # full pipeline, offline demo prices
  python -m mtg_pricebot run                  # full pipeline, live vendor prices
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from . import basket, plot, rank
from .config import load_config
from .fetchers import cardkingdom, demo, manapool, tcgplayer

DEFAULT_SALES = "data/raw/mtg_results.xlsx"


def cmd_rank(cfg: dict, args) -> pd.DataFrame:
    print(f"Ranking cards from {args.sales} ...")
    sales = rank.load_sales(args.sales)
    r = cfg["ranking"]
    cards = rank.rank_cards(sales, metric=r["metric"], top_n=r["top_n"],
                            max_avg_price=r["max_avg_price"], min_units=r["min_units"])
    out = Path("data/top_cards.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    cards.to_csv(out, index=False)
    print(f"  wrote {out} ({len(cards)} cards, metric={r['metric']}, "
          f"max_avg_price={r['max_avg_price']})")
    return cards


def fetch_prices(cards: pd.DataFrame, cfg: dict, use_demo: bool) -> pd.DataFrame:
    if use_demo:
        print("Fetching prices: DEMO mode (no network; TCG price = real avg sale price)")
        return demo.fetch_all(cards, cfg["demo"])

    cache = Path(cfg["output_dir"]) / "cache"
    prices = pd.DataFrame(index=cards.index)
    print("Fetching TCGplayer prices (tcgcsv.com, exact productId match) ...")
    prices["tcgplayer"] = tcgplayer.fetch(cards, cfg["vendors"]["tcgplayer"], cache)
    print("Fetching Card Kingdom pricelist ...")
    prices["cardkingdom"] = cardkingdom.fetch(cards, cfg["vendors"]["cardkingdom"], cache)
    print("Fetching ManaPool prices ...")
    prices["manapool"] = manapool.fetch(cards, cfg["vendors"]["manapool"], cache)
    for v in basket.VENDORS:
        n = prices[v].notna().sum()
        print(f"  {v}: matched {n}/{len(cards)} cards")
    return prices


def cmd_run(cfg: dict, args):
    cards = cmd_rank(cfg, args)
    prices = fetch_prices(cards, cfg, args.demo)

    print("Building incremental baskets ...")
    curves = basket.build_curves(cards, prices, cfg)
    crossovers = basket.find_crossovers(curves)
    cheapest = basket.cheapest_vendor_summary(curves)

    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_demo" if args.demo else ""

    curves_path = out_dir / f"basket_curves{suffix}.csv"
    curves.to_csv(curves_path, index=False)
    chart_path = plot.plot_pct_diff(curves, crossovers,
                                    out_dir / f"crossover_chart{suffix}.png")
    chart_v_path = plot.plot_curves(curves, crossovers,
                                    out_dir / f"crossover_by_value{suffix}.png")
    # Zoomed view of the small-basket region where shipping thresholds bite.
    zoom = curves[curves["n_cards"] <= 25]
    if len(zoom) >= 3:
        zoom_events = [ev for ev in crossovers if ev["n_cards"] <= 25]
        plot.plot_pct_diff(zoom, zoom_events, out_dir / f"crossover_zoom{suffix}.png")

    print(f"\nWrote {curves_path}\nWrote {chart_path}\nWrote {chart_v_path}\n")
    print("=== Crossovers vs TCGplayer (all-in cost) ===")
    if not crossovers:
        print("  none — one vendor stays cheapest across the whole range")
    for ev in crossovers:
        print(f"  {plot.LABELS[ev['vendor']]} becomes {ev['direction']} than TCGplayer "
              f"at ~${ev['order_value']:,.2f} order value ({ev['n_cards']} cards)")

    final = curves.iloc[-1]
    print("\n=== Full basket ({} cards, ${:,.2f} order value) ===".format(
        int(final["n_cards"]), final["order_value"]))
    for v in basket.VENDORS:
        print(f"  {plot.LABELS[v]:13s} ${final[f'{v}_subtotal']:>9,.2f} cards "
              f"+ ${final[f'{v}_shipping']:>5.2f} ship = ${final[f'{v}_total']:>9,.2f}")
    share = cheapest["cheapest"].value_counts()
    print("\nCheapest vendor share of basket steps: "
          + ", ".join(f"{plot.LABELS[k]} {v}/{len(cheapest)}" for k, v in share.items()))


def main(argv=None):
    p = argparse.ArgumentParser(prog="mtg_pricebot")
    p.add_argument("--config", default=None, help="path to config.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("rank", help="rank cards by sales volume")
    pr.add_argument("--sales", default=DEFAULT_SALES)

    pu = sub.add_parser("run", help="rank + fetch prices + build curves + plot")
    pu.add_argument("--sales", default=DEFAULT_SALES)
    pu.add_argument("--demo", action="store_true",
                    help="offline mode: model vendor prices from real sale prices")

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    if args.command == "rank":
        cmd_rank(cfg, args)
    else:
        cmd_run(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
