"""Monte Carlo basket sampling: the aggregate vendor gap, not one path's noise.

The incremental (add-one-card-at-a-time) curve traces a single arbitrary
ordering, so each step inherits the quirks of whichever card lands there.
Here we instead ask, for each basket size n: across MANY plausible n-card
baskets, what is the distribution of each vendor's all-in cost vs TCGplayer?

Baskets are sampled from the ranked card pool weighted by real units sold,
so a sampled basket resembles what buyers actually order.
"""

import numpy as np
import pandas as pd

from .basket import VENDORS, flat_threshold_shipping, tcg_multiseller_shipping


def simulate(cards: pd.DataFrame, prices: pd.DataFrame, cfg: dict,
             sizes: list[int] | None = None, n_samples: int = 300,
             seed: int = 7) -> pd.DataFrame:
    """Return one row per basket size with mean / percentile gap stats.

    Gap = (vendor all-in total / TCGplayer all-in total - 1) * 100.
    """
    pool = cards.join(prices).dropna(subset=VENDORS).reset_index(drop=True)
    weights = pool["units"].to_numpy(dtype=float)
    weights = weights / weights.sum()

    if sizes is None:
        max_n = min(len(pool) - 1, 100)
        sizes = [n for n in range(1, max_n + 1)
                 if n <= 30 or n % 5 == 0]

    ck_cfg = cfg["vendors"]["cardkingdom"]["shipping"]
    mp_cfg = cfg["vendors"]["manapool"]["shipping"]
    tcg_cfg = cfg["vendors"]["tcgplayer"]["shipping"]

    p = {v: pool[v].to_numpy() for v in VENDORS}
    rng = np.random.default_rng(seed)
    rows = []
    for n in sizes:
        gaps = {v: [] for v in VENDORS if v != "tcgplayer"}
        subgaps = {v: [] for v in VENDORS if v != "tcgplayer"}
        order_values = []
        for _ in range(n_samples):
            idx = rng.choice(len(pool), size=n, replace=False, p=weights)
            tcg_sub = p["tcgplayer"][idx].sum()
            tcg_total = tcg_sub + tcg_multiseller_shipping(
                p["tcgplayer"][idx].tolist(), tcg_cfg["cards_per_seller"],
                tcg_cfg["per_seller_fee"], tcg_cfg["seller_free_threshold"])
            ck_sub = p["cardkingdom"][idx].sum()
            ck_total = ck_sub + flat_threshold_shipping(
                ck_sub, ck_cfg["free_threshold"], ck_cfg["flat_fee"])
            mp_sub = p["manapool"][idx].sum()
            mp_total = mp_sub + flat_threshold_shipping(
                mp_sub, mp_cfg["free_threshold"], mp_cfg["flat_fee"])

            order_values.append(tcg_sub)
            gaps["cardkingdom"].append((ck_total / tcg_total - 1) * 100)
            gaps["manapool"].append((mp_total / tcg_total - 1) * 100)
            # Cards-only gap: same baskets, shipping excluded on both sides.
            # The spread between this and the all-in gap IS the shipping effect.
            subgaps["cardkingdom"].append((ck_sub / tcg_sub - 1) * 100)
            subgaps["manapool"].append((mp_sub / tcg_sub - 1) * 100)

        row = {"n_cards": n, "order_value_mean": float(np.mean(order_values))}
        for v, g in gaps.items():
            g = np.asarray(g)
            row[f"{v}_gap_mean"] = float(g.mean())
            row[f"{v}_gap_p10"] = float(np.percentile(g, 10))
            row[f"{v}_gap_p90"] = float(np.percentile(g, 90))
            row[f"{v}_subgap_mean"] = float(np.mean(subgaps[v]))
        rows.append(row)
    return pd.DataFrame(rows)
