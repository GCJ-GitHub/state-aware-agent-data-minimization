"""Build vector PDF/SVG figures and PNG previews for the method section."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parent / "figures"
INK = "#14263a"
MUTED = "#43586d"
LINE = "#a6b6c6"
LIGHT = "#f4f7fa"
BLUE = "#174d89"
BLUE_BG = "#edf4fd"
TEAL = "#075d54"
TEAL_BG = "#e8f5f1"
RED = "#992e3b"
RED_BG = "#fbecef"

plt.rcParams.update({"pdf.fonttype": 42, "svg.fonttype": "none", "font.family": "DejaVu Sans"})


def canvas(height, ymax):
    fig, ax = plt.subplots(figsize=(7.02, height))
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)
    ax.set(xlim=(0, 100), ylim=(0, ymax))
    ax.axis("off")
    return fig, ax


def label(ax, x, y, value, size=8, *, color=INK, weight="normal", align="center"):
    ax.text(x, y, value, size=size, color=color, weight=weight, ha=align, va="center", zorder=5)


def box(ax, x, y, w, h, fill, edge, *, dashed=False):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=.95",
        facecolor=fill, edgecolor=edge, linewidth=.72,
        linestyle=(0, (4, 3)) if dashed else "-", zorder=1,
    ))


def arrow(ax, start, end, color=MUTED, *, dashed=False):
    ax.annotate("", xy=end, xytext=start, arrowprops={
        "arrowstyle": "-|>", "color": color, "lw": .84, "mutation_scale": 8,
        "shrinkA": 0, "shrinkB": 0, "linestyle": "--" if dashed else "-",
    }, zorder=4)


def save(fig, stem):
    for extension in ("pdf", "svg", "png"):
        fig.savefig(OUT / f"{stem}.{extension}", dpi=220, facecolor="white")
    plt.close(fig)


def architecture():
    fig, ax = canvas(3.56, 54)
    box(ax, 3, 44, 94, 8.5, LIGHT, LINE)
    label(ax, 6, 49.5, "Agent", 10, weight="bold", align="left")
    label(ax, 6, 46.7, "Proposes a route and requests fields", align="left")
    label(ax, 94, 49.4, "SHARED TOOL INTERFACE", 7, color=MUTED, weight="bold", align="right")
    label(ax, 94, 46.7, "Same authorization, preferences and recovery", 7.7, align="right")

    box(ax, 1, 1, 98, 37.4, "white", LINE, dashed=True)
    label(ax, 3, 40.7, "TRUSTED CONNECTOR", 7.2, color=MUTED, weight="bold", align="left")
    label(ax, 50, 41.2, "read request", 7.3, color=MUTED)
    arrow(ax, (35, 44), (35, 36.2), BLUE)
    arrow(ax, (65, 44), (65, 36.2), TEAL)

    columns = [
        (4, BLUE, BLUE_BG, "T   Refreshed route table", (
            "Compose route recipes",
            "Refresh state at every read",
            "Check current route, step and fields",
        )),
        (52, TEAL, TEAL_BG, "C   Contract verifier", (
            "Derive step inputs from tool contracts",
            "Bind grant to scope and versions",
            "Check current eligibility and grant",
        )),
    ]
    for x, color, fill, title, lines in columns:
        box(ax, x, 17.2, 44, 19, fill, color)
        label(ax, x + 2.3, 33, title, 9.7, color=color, weight="bold", align="left")
        ax.hlines(30.7, x + 2.2, x + 41.8, color=color, alpha=.4, linewidth=.64)
        for y, line in zip((27.5, 24, 20.5), lines):
            label(ax, x + 2.3, y, line, 8.1, align="left")
        arrow(ax, (x + 22, 17.2), (x + 22, 14.8), color)

    box(ax, 4, 9, 92, 5.8, LIGHT, LINE)
    label(ax, 6.2, 11.9, "Release decision", 8.6, weight="bold", align="left")
    label(ax, 93.8, 11.9, "Required raw values  /  Value-free denial + recovery", 8, align="right")
    ax.plot((4, 2, 2), (11.9, 11.9, 48), color=MUTED, lw=.82, zorder=3)
    arrow(ax, (2, 48), (3, 48))
    box(ax, 4, 2.6, 92, 4.5, "white", LINE)
    label(ax, 50, 4.8, "Shared sources: trusted status, field store, verification records and committed effects", 7.7, color=MUTED)

    save(fig, "backend-comparison")


def sequence():
    fig, ax = canvas(4.25, 66)
    lanes = [(9, 13, "Agent"), (61, 18, "Trusted connector"), (91, 17, "Business state")]
    for x, width, title in lanes:
        box(ax, x - width / 2, 60.1, width, 4.6, LIGHT, LINE)
        label(ax, x, 62.4, title, 7.2, weight="bold")
        ax.vlines(x, 1.6, 60.1, color=LINE, linestyles=(0, (2, 2)), linewidth=.75, zorder=.5)

    def message(y, start, end, value, color=MUTED):
        arrow(ax, (start, y), (end, y), color)
        label(ax, (start + end) / 2, y + 1.42, value, 7.65, color=color)

    message(55.4, 61, 9, "Status: wallet unavailable, bank available")
    message(50.4, 9, 61, "Propose bank; prepare account verification")
    message(45.4, 61, 9, "Preparation accepted under wallet version v1")
    ax.hlines(41.5, 1.3, 99.2, color=RED, alpha=.46, linestyle=(0, (4, 3)), linewidth=.8)
    message(41.5, 91, 61, "Wallet recovers (v2)", RED)
    message(36.3, 9, 61, "Read account and owner references")

    box(ax, 42.5, 23.5, 49, 11, "white", LINE)
    label(ax, 44.5, 32.1, "T   Table refresh", 7.8, color=BLUE, weight="bold", align="left")
    label(ax, 44.5, 29.7, "Wallet now outranks bank", 7.4, align="left")
    label(ax, 44.5, 27.1, "C   Contract revalidation", 7.8, color=TEAL, weight="bold", align="left")
    label(ax, 44.5, 24.75, "Bank grant binds v1; current version is v2", 7.4, align="left")

    message(20.3, 61, 9, "Deny bank fields; provide safe next options", RED)
    message(14.6, 9, 61, "Refresh status; propose wallet; request its reference", TEAL)
    message(9.5, 61, 9, "Release wallet reference", TEAL)
    message(4.4, 9, 61, "Confirm and execute wallet refund", TEAL)
    label(ax, 91, 4.4, "Refund\ncommitted", 7.3, color=TEAL, weight="bold")
    arrow(ax, (61, 4.4), (83, 4.4), TEAL, dashed=True)

    save(fig, "refund-sequence")


if __name__ == "__main__":
    architecture()
    sequence()
