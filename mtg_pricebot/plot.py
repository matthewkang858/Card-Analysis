"""Plot cumulative all-in cost curves per vendor and mark crossovers."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .basket import VENDORS

# Validated categorical palette (slots 1-3) + chart chrome, light mode.
COLORS = {"cardkingdom": "#2a78d6", "tcgplayer": "#008300", "manapool": "#e87ba4"}
LABELS = {"cardkingdom": "Card Kingdom", "tcgplayer": "TCGplayer", "manapool": "ManaPool"}
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#898781", "#e1e0d9"


def plot_pct_diff(curves: pd.DataFrame, crossovers: list[dict], out_path: Path,
                  x_col: str = "n_cards", baseline: str = "tcgplayer") -> Path:
    """All-in cost as % difference vs the baseline vendor (0 = baseline)."""
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    x = curves[x_col]
    base_total = curves[f"{baseline}_total"]
    ax.axhline(0, color=COLORS[baseline], linewidth=2)
    ax.annotate(f"{LABELS[baseline]} (baseline)", (x.iloc[-1], 0),
                xytext=(6, 5), textcoords="offset points",
                color=COLORS[baseline], fontsize=9, fontweight="bold", va="bottom")

    for v in VENDORS:
        if v == baseline:
            continue
        pct = (curves[f"{v}_total"] / base_total - 1) * 100
        ax.plot(x, pct, color=COLORS[v], linewidth=2, label=LABELS[v])
        ax.annotate(LABELS[v], (x.iloc[-1], pct.iloc[-1]),
                    xytext=(6, 0), textcoords="offset points",
                    color=COLORS[v], fontsize=9, fontweight="bold", va="center")

    for ev in crossovers:
        if ev["direction"] != "cheaper" or ev.get("baseline") != baseline:
            continue
        xv = ev["n_cards"] if x_col == "n_cards" else ev["order_value"]
        ax.axvline(xv, color=MUTED, linewidth=1, linestyle="--", alpha=0.7)
        y0, y1 = ax.get_ylim()
        ax.annotate(f'{LABELS[ev["vendor"]]} cheaper\nfrom ~{ev["n_cards"]} cards '
                    f'(${ev["order_value"]:,.0f})',
                    (xv, y0 + 0.05 * (y1 - y0)),
                    color=INK, fontsize=8, ha="left", va="bottom",
                    xytext=(4, 0), textcoords="offset points")

    xlabel = ("Cards in basket" if x_col == "n_cards"
              else "Order value — cumulative TCGplayer subtotal ($)")
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(f"All-in cost vs {LABELS[baseline]} (%)  —  below 0 = cheaper", color=MUTED)
    ax.set_title("How far is each vendor from TCGplayer's all-in cost?\n"
                 "Basket = top TCGplayer sellers by dollar volume, added one at a time",
                 color=INK, fontsize=11)
    ax.grid(True, color=GRID, linewidth=0.75)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.legend(loc="upper right", frameon=False, labelcolor=INK)
    ax.margins(x=0.12)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def plot_single_card(merged: pd.DataFrame, cfg: dict, out_path: Path) -> Path:
    """Absolute all-in cost of buying ONE card at each vendor.

    Dots = individual cards; lines = mean total per $2 price bin. All-in
    cost: the card's price at that vendor plus its single-order shipping.
    """
    from .basket import flat_threshold_shipping

    ck_cfg = cfg["vendors"]["cardkingdom"]["shipping"]
    mp_cfg = cfg["vendors"]["manapool"]["shipping"]
    tcg_cfg = cfg["vendors"]["tcgplayer"]["shipping"]

    d = merged.dropna(subset=VENDORS).copy()
    d["tcgplayer_total"] = d["tcgplayer"] + d["tcgplayer"].apply(
        lambda p: flat_threshold_shipping(p, tcg_cfg["seller_free_threshold"],
                                          tcg_cfg["per_seller_fee"]))
    d["cardkingdom_total"] = d["cardkingdom"] + d["cardkingdom"].apply(
        lambda p: flat_threshold_shipping(p, ck_cfg["free_threshold"], ck_cfg["flat_fee"]))
    d["manapool_total"] = d["manapool"] + d["manapool"].apply(
        lambda p: flat_threshold_shipping(p, mp_cfg["free_threshold"], mp_cfg["flat_fee"]))

    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    x = d["tcgplayer"]
    bins = np.arange(0, x.max() + 2, 2)
    d["bin"] = pd.cut(d["tcgplayer"], bins)
    for v in ("cardkingdom", "manapool", "tcgplayer"):
        total = d[f"{v}_total"]
        ax.scatter(x, total, s=14, color=COLORS[v], alpha=0.3, linewidths=0)
        binned = total.groupby(d["bin"], observed=True).mean()
        centers = [iv.mid for iv in binned.index]
        ax.plot(centers, binned.values, color=COLORS[v], linewidth=2, label=LABELS[v])
        ax.annotate(LABELS[v], (centers[-1], binned.values[-1]),
                    xytext=(6, 0), textcoords="offset points",
                    color=COLORS[v], fontsize=9, fontweight="bold", va="center")

    ax.set_xlabel("Card price on TCGplayer ($)", color=MUTED)
    ax.set_ylabel("Total cost to buy this one card ($)", color=MUTED)
    ax.set_title("Buying a single card: all-in cost (card + shipping) by vendor\n"
                 "Dots = individual cards; lines = mean per $2 price bin",
                 color=INK, fontsize=11)
    ax.grid(True, color=GRID, linewidth=0.75)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.legend(loc="upper left", frameon=False, labelcolor=INK)
    ax.margins(x=0.1)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def plot_mc_band(mc: pd.DataFrame, out_path: Path, n_samples: int,
                 baseline: str = "tcgplayer") -> Path:
    """Mean vendor gap vs baseline with a 10th-90th percentile band."""
    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    x = mc["n_cards"]
    ax.axhline(0, color=COLORS[baseline], linewidth=2)
    ax.annotate(f"{LABELS[baseline]} (baseline)", (x.iloc[-1], 0),
                xytext=(6, 5), textcoords="offset points",
                color=COLORS[baseline], fontsize=9, fontweight="bold", va="bottom")

    for v in VENDORS:
        if v == baseline:
            continue
        ax.fill_between(x, mc[f"{v}_gap_p10"], mc[f"{v}_gap_p90"],
                        color=COLORS[v], alpha=0.15, linewidth=0)
        ax.plot(x, mc[f"{v}_gap_mean"], color=COLORS[v], linewidth=2,
                label=f"{LABELS[v]} — all-in (cards + shipping)")
        if f"{v}_subgap_mean" in mc.columns:
            ax.plot(x, mc[f"{v}_subgap_mean"], color=COLORS[v], linewidth=1.5,
                    linestyle="--", alpha=0.8, label=f"{LABELS[v]} — cards only")
        ax.annotate(LABELS[v], (x.iloc[-1], mc[f"{v}_gap_mean"].iloc[-1]),
                    xytext=(6, 0), textcoords="offset points",
                    color=COLORS[v], fontsize=9, fontweight="bold", va="center")

    ax.set_xlabel("Cards in basket", color=MUTED)
    ax.set_ylabel(f"Cost vs {LABELS[baseline]} (%)  —  below 0 = cheaper", color=MUTED)
    ax.set_title(f"Cost gap vs {LABELS[baseline]}: card prices vs shipping "
                 f"({n_samples} sampled baskets per size)\n"
                 "Solid = all-in cost gap; dashed = card prices only — "
                 "the space between is shipping",
                 color=INK, fontsize=11)
    ax.grid(True, color=GRID, linewidth=0.75)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.legend(loc="upper right", frameon=False, labelcolor=INK)
    ax.margins(x=0.12)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return out_path


def plot_curves(curves: pd.DataFrame, crossovers: list[dict], out_path: Path,
                x_col: str = "order_value") -> Path:
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    x = curves[x_col]
    for v in VENDORS:
        ax.plot(x, curves[f"{v}_total"], color=COLORS[v], linewidth=2, label=LABELS[v])
        # Direct label at the line's end.
        ax.annotate(LABELS[v], (x.iloc[-1], curves[f"{v}_total"].iloc[-1]),
                    xytext=(6, 0), textcoords="offset points",
                    color=COLORS[v], fontsize=9, fontweight="bold", va="center")

    for ev in crossovers:
        if ev["direction"] != "cheaper":
            continue
        if x_col == "n_cards":
            xv = ev["n_cards"]
            note = f'{LABELS[ev["vendor"]]} cheaper\nfrom ~{ev["n_cards"]} cards (${ev["order_value"]:,.0f})'
        else:
            xv = ev["order_value"]
            note = f'{LABELS[ev["vendor"]]} cheaper\nfrom ~${ev["order_value"]:,.0f}'
        ax.axvline(xv, color=MUTED, linewidth=1, linestyle="--", alpha=0.7)
        y0, y1 = ax.get_ylim()
        ax.annotate(note, (xv, y0 + 0.05 * (y1 - y0)),
                    color=INK, fontsize=8, ha="left", va="bottom",
                    xytext=(4, 0), textcoords="offset points")

    xlabel = ("Order value — cumulative TCGplayer subtotal ($)"
              if x_col == "order_value" else "Cards in basket")
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel("All-in cost: cards + shipping ($)", color=MUTED)
    ax.set_title("Where does each vendor become cheapest?\n"
                 "Basket = top TCGplayer sellers by dollar volume, added one at a time",
                 color=INK, fontsize=11)
    ax.grid(True, color=GRID, linewidth=0.75)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.legend(loc="upper left", frameon=False, labelcolor=INK)
    ax.margins(x=0.12)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor=SURFACE)
    plt.close(fig)
    return out_path
