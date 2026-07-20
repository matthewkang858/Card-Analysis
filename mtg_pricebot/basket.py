"""Incremental basket builder: cumulative all-in cost per vendor + crossovers.

The core algorithm from the design discussion:

    FOR each card in ranked_card_list:
        ADD card to basket
        cost_vendor = sum(card prices) + vendor shipping model
        RECORD (order_value, cost per vendor)
"""

import math

import numpy as np
import pandas as pd

VENDORS = ["cardkingdom", "tcgplayer", "manapool"]


def flat_threshold_shipping(subtotal: float, free_threshold: float, flat_fee: float) -> float:
    """Single-warehouse vendor (Card Kingdom, ManaPool): flat fee until free."""
    return 0.0 if subtotal >= free_threshold else flat_fee


def tcg_multiseller_shipping(prices: list[float], cards_per_seller: int,
                             per_seller_fee: float, seller_free_threshold: float) -> float:
    """Marketplace model: the basket is split across ceil(n / cards_per_seller)
    sellers. Expensive cards are grouped first so high-value sellers hit their
    free-shipping threshold the way a real buyer would consolidate.
    """
    if not prices:
        return 0.0
    ordered = sorted(prices, reverse=True)
    n_sellers = math.ceil(len(ordered) / cards_per_seller)
    fee = 0.0
    for i in range(n_sellers):
        chunk = ordered[i * cards_per_seller:(i + 1) * cards_per_seller]
        if sum(chunk) < seller_free_threshold:
            fee += per_seller_fee
    return fee


def build_curves(cards: pd.DataFrame, prices: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """One row per basket size, cumulative subtotal / shipping / total per vendor.

    Cards with a missing price at any vendor are dropped (with a note) so all
    three curves price the identical basket — otherwise the comparison lies.
    """
    merged = cards.join(prices)
    priced = merged.dropna(subset=VENDORS)
    dropped = len(merged) - len(priced)
    if dropped:
        print(f"  [basket] dropped {dropped} card(s) missing a price at >=1 vendor")

    ck_cfg = cfg["vendors"]["cardkingdom"]["shipping"]
    mp_cfg = cfg["vendors"]["manapool"]["shipping"]
    tcg_cfg = cfg["vendors"]["tcgplayer"]["shipping"]

    rows = []
    tcg_prices_so_far: list[float] = []
    cum = {v: 0.0 for v in VENDORS}
    for _, card in priced.iterrows():
        for v in VENDORS:
            cum[v] += card[v]
        tcg_prices_so_far.append(card["tcgplayer"])

        ship = {
            "cardkingdom": flat_threshold_shipping(
                cum["cardkingdom"], ck_cfg["free_threshold"], ck_cfg["flat_fee"]),
            "manapool": flat_threshold_shipping(
                cum["manapool"], mp_cfg["free_threshold"], mp_cfg["flat_fee"]),
            "tcgplayer": tcg_multiseller_shipping(
                tcg_prices_so_far, tcg_cfg["cards_per_seller"],
                tcg_cfg["per_seller_fee"], tcg_cfg["seller_free_threshold"]),
        }
        row = {
            "n_cards": len(tcg_prices_so_far),
            "card_added": card["name"],
            # X-axis: order value = the basket's TCG subtotal (the "market" size
            # of the order, independent of any one vendor's markup).
            "order_value": round(cum["tcgplayer"], 2),
        }
        for v in VENDORS:
            row[f"{v}_subtotal"] = round(cum[v], 2)
            row[f"{v}_shipping"] = round(ship[v], 2)
            row[f"{v}_total"] = round(cum[v] + ship[v], 2)
        rows.append(row)

    return pd.DataFrame(rows)


def find_crossovers(curves: pd.DataFrame, baseline: str = "tcgplayer") -> list[dict]:
    """Where does each vendor's total cross below/above the baseline's?

    Returns one record per sign change, with the order value interpolated
    between the two basket steps that straddle it.
    """
    events = []
    x = curves["order_value"].to_numpy()
    base = curves[f"{baseline}_total"].to_numpy()
    for vendor in VENDORS:
        if vendor == baseline:
            continue
        diff = curves[f"{vendor}_total"].to_numpy() - base
        sign = np.sign(diff)
        for i in range(1, len(sign)):
            if sign[i] != sign[i - 1] and sign[i] != 0:
                # Linear interpolation of the zero crossing between steps.
                d0, d1 = diff[i - 1], diff[i]
                frac = abs(d0) / (abs(d0) + abs(d1)) if (abs(d0) + abs(d1)) else 0.0
                events.append({
                    "vendor": vendor,
                    "baseline": baseline,
                    "direction": "cheaper" if sign[i] < 0 else "more expensive",
                    "order_value": round(x[i - 1] + frac * (x[i] - x[i - 1]), 2),
                    "n_cards": int(curves["n_cards"].iloc[i]),
                })
    return events


def cheapest_vendor_summary(curves: pd.DataFrame) -> pd.DataFrame:
    """Which vendor is cheapest at each basket step."""
    totals = curves[[f"{v}_total" for v in VENDORS]]
    out = curves[["n_cards", "order_value"]].copy()
    out["cheapest"] = totals.idxmin(axis=1).str.replace("_total", "", regex=False)
    out["savings_vs_next"] = (totals.apply(sorted, axis=1).str[1] - totals.min(axis=1)).round(2)
    return out
