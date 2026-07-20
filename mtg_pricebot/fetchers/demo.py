"""Offline demo price source — no network required.

TCGplayer price is the card's REAL average sale price from the sales export
(gmv_sale / units). Card Kingdom and ManaPool are modeled as configurable
multipliers on that real price, so curve *shapes* and shipping dynamics are
realistic even though absolute vendor spreads are assumptions.
"""

import numpy as np
import pandas as pd


def fetch_all(cards: pd.DataFrame, demo_cfg: dict) -> pd.DataFrame:
    tcg = (cards["gmv_sale"] / cards["units"]).clip(lower=demo_cfg["min_price"])
    # Deterministic per-card jitter so the modeled vendors aren't a perfect
    # scalar multiple of TCG (which would make the curves trivially parallel).
    rng = np.random.default_rng(seed=42)
    ck_noise = rng.normal(1.0, 0.05, len(cards))
    mp_noise = rng.normal(1.0, 0.03, len(cards))
    return pd.DataFrame({
        "tcgplayer": tcg.round(2),
        "cardkingdom": (tcg * demo_cfg["cardkingdom_multiplier"] * ck_noise)
        .clip(lower=demo_cfg["min_price"]).round(2),
        "manapool": (tcg * demo_cfg["manapool_multiplier"] * mp_noise)
        .clip(lower=demo_cfg["min_price"]).round(2),
    }, index=cards.index)
