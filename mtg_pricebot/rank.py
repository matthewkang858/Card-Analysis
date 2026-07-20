"""Rank cards by real TCGplayer sales volume.

Input is the product-level sales export (mtg_results.xlsx) with columns:
productId, name, set, isSealed, category, units, transactions, gmv_sale, ...
"""

from pathlib import Path

import pandas as pd


def load_sales(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix in (".xlsx", ".xlsm"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def rank_cards(
    sales: pd.DataFrame,
    metric: str = "gmv",
    top_n: int = 100,
    max_avg_price: float | None = 250.0,
    min_units: int = 10,
) -> pd.DataFrame:
    """Return the top-N singles ranked by sales volume.

    metric: "gmv" (dollar volume, recommended) or "units".
    max_avg_price filters out ultra-expensive outliers (reserved list etc.)
    so the basket reflects what a typical buyer actually orders.
    """
    singles = sales[(sales["isSealed"] == 0) & (sales["units"] >= min_units)].copy()
    singles["avg_price"] = singles["gmv_sale"] / singles["units"]

    if max_avg_price is not None:
        singles = singles[singles["avg_price"] <= max_avg_price]

    sort_col = "gmv_sale" if metric == "gmv" else "units"
    ranked = singles.sort_values(sort_col, ascending=False).head(top_n).reset_index(drop=True)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))

    cols = ["rank", "productId", "name", "set", "category", "units", "transactions",
            "gmv_sale", "avg_price"]
    return ranked[[c for c in cols if c in ranked.columns]]
