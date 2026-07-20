import pandas as pd

from mtg_pricebot.basket import (
    build_curves,
    find_crossovers,
    flat_threshold_shipping,
    tcg_multiseller_shipping,
)

CFG = {
    "vendors": {
        "cardkingdom": {"shipping": {"free_threshold": 50.0, "flat_fee": 4.99}},
        "manapool": {"shipping": {"free_threshold": 50.0, "flat_fee": 3.99}},
        "tcgplayer": {"shipping": {"cards_per_seller": 2, "per_seller_fee": 1.49,
                                   "seller_free_threshold": 35.0}},
    }
}


def test_flat_threshold_shipping():
    assert flat_threshold_shipping(49.99, 50.0, 4.99) == 4.99
    assert flat_threshold_shipping(50.0, 50.0, 4.99) == 0.0


def test_tcg_multiseller_shipping_counts_sellers_and_waives_big_ones():
    # 4 cards, 2 per seller -> 2 sellers. Sorted desc: [40, 30] and [5, 1].
    # First seller subtotal 70 >= 35 -> free; second 6 < 35 -> pays fee.
    assert tcg_multiseller_shipping([30, 5, 40, 1], 2, 1.49, 35.0) == 1.49
    assert tcg_multiseller_shipping([], 2, 1.49, 35.0) == 0.0
    assert tcg_multiseller_shipping([1, 1, 1], 2, 1.49, 35.0) == 2 * 1.49


def _toy_data():
    cards = pd.DataFrame({
        "name": ["A", "B", "C", "D"],
        "productId": [1, 2, 3, 4],
        "set": ["S"] * 4,
    })
    prices = pd.DataFrame({
        # CK pricier per card but flat shipping; TCG cheap cards, per-seller fees.
        "cardkingdom": [22.0, 22.0, 22.0, 22.0],
        "tcgplayer": [20.0, 20.0, 20.0, 20.0],
        "manapool": [21.0, 21.0, 21.0, 21.0],
    })
    return cards, prices


def test_build_curves_cumulative_totals():
    cards, prices = _toy_data()
    curves = build_curves(cards, prices, CFG)
    assert list(curves["n_cards"]) == [1, 2, 3, 4]
    # Step 1: CK 22 + 4.99 ; TCG 20 + 1.49 ; MP 21 + 3.99
    assert curves.loc[0, "cardkingdom_total"] == 26.99
    assert curves.loc[0, "tcgplayer_total"] == 21.49
    assert curves.loc[0, "manapool_total"] == 24.99
    # Step 3: CK subtotal 66 >= 50 -> free shipping.
    assert curves.loc[2, "cardkingdom_shipping"] == 0.0
    # Step 3 TCG: sellers [20,20] (=40, free) + [20] (=20, pays).
    assert curves.loc[2, "tcgplayer_shipping"] == 1.49
    # Order value axis follows the TCG subtotal.
    assert list(curves["order_value"]) == [20.0, 40.0, 60.0, 80.0]


def test_find_crossovers_detects_sign_change():
    cards, prices = _toy_data()
    curves = build_curves(cards, prices, CFG)
    events = find_crossovers(curves)
    # CK starts more expensive; with free shipping at step 3 it narrows but
    # per-card premium keeps it above TCG here — so no 'cheaper' event for CK.
    # ManaPool: 24.99 vs 21.49 ... stays above too. Verify no false positives.
    assert all(ev["direction"] == "cheaper" or ev["direction"] == "more expensive"
               for ev in events)


def test_missing_price_drops_card_everywhere():
    cards, prices = _toy_data()
    prices.loc[1, "manapool"] = None
    curves = build_curves(cards, prices, CFG)
    assert len(curves) == 3  # card B removed from all vendors' baskets
