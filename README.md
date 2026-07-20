# MTG Vendor Price-Crossover Bot

Answers one question: **at what order value does each vendor (Card Kingdom,
TCGplayer, ManaPool) become the cheapest all-in option — cards + shipping?**

The algorithm (from the design discussion):

1. **Rank cards by real demand** — TCGplayer dollar sales volume (`gmv_sale`)
   from the sales export in `data/raw/mtg_results.xlsx`. Unit-volume ranking is
   available via `ranking.metric: units` in `config.yaml`.
2. **Build baskets incrementally** — add the #1 card, then #2, ... up to
   `top_n`. After each addition, compute every vendor's cumulative
   subtotal + shipping.
3. **Plot three curves** — x = order value (cumulative TCG subtotal),
   y = all-in cost, one line per vendor.
4. **Find the crossovers** — where one vendor's curve crosses below another's.

## Quick start

```bash
pip install -r requirements.txt

# Offline demo: TCG price = real average sale price from the export;
# CK / ManaPool modeled as multipliers (see config.yaml -> demo).
python -m mtg_pricebot run --demo

# Live prices (needs normal internet access):
python -m mtg_pricebot run
```

Outputs land in `output/`:

| File | What it is |
|---|---|
| `crossover_chart*.png` | The three cost curves + crossover markers (x = cards in basket) |
| `crossover_zoom*.png` | Zoom on the first 25 cards, where shipping thresholds bite |
| `crossover_by_value*.png` | Same curves with order value ($) on the x-axis |
| `basket_curves*.csv` | Every basket step: subtotal / shipping / total per vendor |
| `data/top_cards.csv` | The ranked basket (from `rank` step) |

## Live data sources

| Vendor | Source | Matching |
|---|---|---|
| TCGplayer | [tcgcsv.com](https://tcgcsv.com) daily mirror of the official price feed | exact, by the `productId` already in the sales export |
| Card Kingdom | their public [pricelist API](https://api.cardkingdom.com/api/pricelist) | normalized name, then base name w/o variant tags (cheapest in-stock non-foil) |
| ManaPool | their [public API](https://manapool.com/api) | normalized base name. **Endpoint unverified** — written from their docs; adjust `mtg_pricebot/fetchers/manapool.py` if it 404s, and add credentials in `config.yaml` if required |

Fetched pricelists are cached in `output/cache/` for 6 h so re-runs don't
hammer anyone.

## Shipping models (the part that decides the answer)

All thresholds/fees live in `config.yaml` and are **assumptions — verify them
against current vendor policy before trusting the crossover numbers**:

- **Card Kingdom / ManaPool** (single warehouse): flat fee, free above a
  dollar threshold.
- **TCGplayer** (marketplace): the basket is split across
  `ceil(n_cards / cards_per_seller)` sellers, expensive cards grouped first;
  each seller charges `per_seller_fee` unless their chunk clears
  `seller_free_threshold`. This approximates the real "optimize across
  sellers" problem, which can't be solved exactly without seller-level
  inventory (TCGplayer's Mass Entry tool has it; public feeds don't).

Cards missing a price at *any* vendor are dropped from *all* baskets, so the
three curves always price an identical basket.

## Interpreting the demo run

The demo uses your real sales data for the ranking and for TCGplayer prices
(gmv ÷ units = actual average sale price), so basket composition and curve
shape are real. The CK/ManaPool price levels are modeled multipliers, so in
demo mode the *crossover mechanics* (who wins at small vs large orders, where
free-shipping kicks in) are meaningful but the exact dollar figures are not —
run live for those.

`ranking.max_avg_price` (default $25) keeps $250+ reserved-list cards out of
the basket; without it the very first card blows past every free-shipping
threshold and the interesting $0–150 region never gets sampled.

## Tests

```bash
python -m pytest tests/
```
