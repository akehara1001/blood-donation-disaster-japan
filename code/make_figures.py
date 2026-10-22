"""
Draw Figures 2 to 5, S1 and S2 of the paper from output/figure_data/ (written by code/reproduce_tables.py) and
data/decomposition.csv. Figure 1 (the map) is not drawn here.

Usage: python code/make_figures.py [output directory]     (default: output/figures)
Text is Times New Roman, at least 8 pt at the saved size; PNG at 600 dpi and PDF.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import statistics as st
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIG = ROOT / "output" / "figure_data"
DPI = 600
MIN_PT = 8.0          # 図の中の字の下限（最終寸法）

mpl.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Nimbus Roman", "DejaVu Serif", "serif"],
    "mathtext.fontset": "stix",
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
    # v13（31a）: font.size 7、axes.labelsize 7.5、tick 7。すべて 8 に
    "font.size": 8,
    "axes.titlesize": 8,
    "axes.labelsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "axes.spines.right": False,
    "axes.spines.top": False,
    "axes.linewidth": 0.7,
    "axes.edgecolor": "#4D4D4D",
    "xtick.color": "#4D4D4D",
    "ytick.color": "#4D4D4D",
    "xtick.major.width": 0.7,
    "ytick.major.width": 0.7,
    "xtick.major.size": 2.6,
    "ytick.major.size": 2.6,
    "legend.frameon": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

# 31a のパレット（nature-figure の既定パレットから採ったもの）
NEU_L = "#CFCECE"
NEU_M = "#767676"
NEU_D = "#4D4D4D"
INK = "#272727"
SIG = "#B64342"
ACC = "#42949E"
DEEP = "#0F4D92"
MID = "#3775BA"
SOFT = "#8BCF8B"
MINUS = "−"
HALO = [pe.withStroke(linewidth=2.0, foreground="white")]
DIAMOND_LAYERS = ((5.9, NEU_D), (4.9, "white"), (4.0, INK))
FS = MIN_PT           # 注記の字号（v13 は 5.9〜6.8）


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(name: str) -> list[dict]:
    with io.open(FIG / name, encoding="utf-8-sig", newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    return list(csv.DictReader(io.StringIO("".join(lines))))


def draw_totals(ax, xs, ys, zorder=6):
    for ms, col in DIAMOND_LAYERS:
        ax.plot(xs, ys, "D", ls="none", color=col, ms=ms, zorder=zorder, clip_on=False)


def panel_tag(ax, tag, dx=-0.16, dy=1.06):
    ax.text(dx, dy, tag, transform=ax.transAxes, fontsize=9, fontweight="bold", va="top", ha="left", color=INK)


def signed(v: float, nd: int = 2) -> str:
    return f"{v:+.{nd}f}".replace("-", MINUS)


# ------------------------------------------------------------------ Figure 2（31a figure1_national_trend）
def figure2_national_rate():
    rows = read("figure2.csv")
    yr = [int(r["fiscal_year"]) for r in rows]
    med = [float(r["median47_dln_r"]) for r in rows]
    nat = [float(r["national_dln_r"]) for r in rows]
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    ax.axhspan(-4.5, 0, color=NEU_L, alpha=0.28, zorder=0, lw=0)
    ax.axhline(0, color=NEU_D, lw=0.8, zorder=3)
    ax.plot(yr, nat, "-", color=NEU_M, lw=1.0, zorder=3)
    ax.plot(yr, med, "-o", color=DEEP, lw=1.5, ms=3.0, mec="white", mew=0.5, zorder=5)
    ax.annotate("47-prefecture median", (2021, med[yr.index(2021)]), xytext=(-2, 8),
                textcoords="offset points", fontsize=FS, color=DEEP, fontweight="bold", ha="center")
    ax.annotate("National", (2015, nat[yr.index(2015)]), xytext=(6, 9), textcoords="offset points",
                fontsize=FS, color=NEU_M, ha="left", va="bottom")
    for y, col in ((2011, SIG), (2015, INK)):
        v = med[yr.index(y)]
        ax.plot([y], [v], "o", ms=6.2, mfc="none", mec=col, mew=1.3, zorder=7)
        ax.annotate(f"FY{y}\n" + signed(v), (y, v), textcoords="offset points",
                    xytext=(5, 9 if y == 2011 else -23), fontsize=FS, color=col, fontweight="bold")
    # 帯の右下の注記。8 pt にすると右端の軸を越えるので、左へ 0.9 年ずらした（値と帯は不変）
    ax.annotate("below pre-disaster baseline", (2017.8, -4.05), fontsize=FS, color=NEU_D, style="italic")
    ax.set_xlabel("Fiscal year")
    ax.set_ylabel("Rate component $\\Delta$ln $r$,\nchange from baseline (log points)")
    ax.set_xticks(range(2005, 2025, 5))
    ax.set_ylim(-4.5, 11)
    ax.grid(color=NEU_L, lw=0.45, zorder=1)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ Figure 3（v13 figure3_decomposition_v13）
def figure3_decomposition():
    rows = read("figure3.csv")
    prefs = ["Fukushima", "Miyagi", "Iwate"]
    comps = ((NEU_M, "dln_P", "Population size"),
             (ACC, "dln_s", "Eligible-age share"),
             (SIG, "dln_r", "Rate component ($\\Delta$ln $r$)"))
    fig, axes = plt.subplots(1, 2, figsize=(6.9, 3.1), sharey=True)
    for ax, fy, tag in zip(axes, (2011, 2024), ("a", "b")):
        sub = {r["prefecture"]: r for r in rows if int(r["fiscal_year"]) == fy}
        w = 0.24
        for k, (col, key, lab) in enumerate(comps):
            vals = [float(sub[p][key]) for p in prefs]
            ax.bar([i + (k - 1) * w for i in range(3)], vals, w, color=col, edgecolor="white", linewidth=0.5,
                   zorder=3)
        tot = [float(sub[p]["dln_D"]) for p in prefs]
        draw_totals(ax, list(range(3)), tot)
        for i, v in enumerate(tot):
            ax.annotate(signed(v), (i, v), textcoords="offset points", xytext=(11, -1), ha="left", va="center",
                        fontsize=FS, color=INK, zorder=7, path_effects=HALO)
        ax.axhline(0, color=NEU_D, lw=0.8, zorder=4)
        ax.set_xticks(range(3))
        ax.set_xticklabels(prefs)
        ax.set_xlim(-0.55, 2.75)
        ax.set_ylim(-22, 12)
        ax.set_yticks(range(-20, 12, 5))
        ax.grid(axis="y", color=NEU_L, lw=0.45, zorder=0)
        ax.set_axisbelow(True)
        ax.set_title(f"FY{fy}", loc="center", fontsize=8, color=INK, pad=6)
        panel_tag(ax, tag, dx=-0.13 if tag == "a" else -0.05)
    # 直接ラベル。8 pt で行が詰まるので行の間隔を 2.05 → 2.4 に広げた（位置の起点は同じ）
    step = 2.4
    for j, (col, key, lab) in enumerate(comps):
        axes[0].text(-0.42, 10.0 - j * step, lab, color=col, fontsize=FS, fontweight="bold", va="center",
                     ha="left", zorder=8)
    draw_totals(axes[0], [-0.33], [10.0 - 3 * step], zorder=8)
    axes[0].text(-0.20, 10.0 - 3 * step, "Total ($\\Delta$ln $D$)", color=INK, fontsize=FS, va="center",
                 ha="left", zorder=8)
    axes[0].set_ylabel("Change from FY2005$-$2009 baseline (log points)")
    fig.tight_layout(w_pad=1.2)
    return fig


# ------------------------------------------------------------------ Figure 4（v13 figure4_deviation_v13）
def figure4_deviation():
    rows = read("figure4.csv")
    blocks = [
        ("Great East Japan Earthquake\nmost affected", "Great East Japan Earthquake", "core", DEEP),
        ("Great East Japan Earthquake\nintermediate exposure", "Great East Japan Earthquake", "intermediate",
         NEU_D),
        ("Kumamoto Earthquake", "Kumamoto Earthquake", "core", MID),
        ("Heavy rain, July 2018\n(non-seismic)", "July 2018 heavy rain", "rain", SOFT),
        ("Other earthquakes", None, "small", NEU_L),
    ]
    ordered, bands = [], []
    for title, ev, grp, col in blocks:
        sel = [r for r in rows if r["group"] == grp and (ev is None or r["event"] == ev)]
        sel.sort(key=lambda r: float(r["deviation"]))
        bands.append((title, col, len(ordered), len(ordered) + len(sel)))
        ordered += [(r, col) for r in sel]
    fig, ax = plt.subplots(figsize=(6.9, 4.0))
    lo, hi = -24, 16
    for i, (r, col) in enumerate(ordered):
        d = float(r["deviation"])
        ax.barh(i, d, 0.6, color=col, edgecolor="white", lw=0.5, zorder=3)
        strong = r["is_core"] == "yes"
        ax.annotate(signed(d), (d + (0.7 if d > 0 else -0.7), i), va="center", ha="left" if d > 0 else "right",
                    fontsize=FS, color=INK if strong else NEU_D, fontweight="bold" if strong else "normal",
                    zorder=7)
    ax.set_yticks(range(len(ordered)))
    ax.set_yticklabels([f"{r['prefecture']}  FY{r['first_post_event_fy']}" for r, _ in ordered], fontsize=FS)
    ax.invert_yaxis()
    ax.axvline(0, color=NEU_D, lw=0.8, zorder=4)
    ax.set_xlim(lo, hi)
    ax.set_ylim(len(ordered) - 0.4, -1.3)
    ax.set_xlabel("Deviation in the first post-event fiscal year from the median of the comparison prefectures\n"
                  "(two-year change in $\\Delta$ln $r$, log points)")
    ax.grid(axis="x", color=NEU_L, lw=0.45, zorder=0)
    ax.set_axisbelow(True)
    for title, col, a, b in bands:
        ax.annotate(title, xy=(hi - 0.4, (a + b - 1) / 2), ha="right", va="center", fontsize=FS,
                    color=col if col != NEU_L else NEU_M, fontweight="bold", linespacing=1.25)
        if a > 0:
            ax.axhline(a - 0.5, color=NEU_L, lw=0.6, zorder=2)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ Figure 5（v13 figure5_age_schedule_v13）
def figure5_age_schedule():
    sch = read("figure5.csv")
    groups = ["10s", "20s", "30s", "40s", "50s", "60s"]
    glab = ["10s", "20s", "30s", "40s", "50s", "60s"]
    fig, ax = plt.subplots(figsize=(3.9, 2.9))
    for s_, col, lab, xy in (("2011", NEU_M, "FY2011", (1.05, 7.78)), ("2024", SIG, "FY2024", (4.26, 8.05))):
        v = {r["age_group"]: float(r["rate_pct"]) for r in sch if r["schedule_fy"] == s_}
        ax.plot(range(6), [v[g] for g in groups], "-o", color=col, lw=1.6, ms=3.6, mec="white", mew=0.5, zorder=4)
        ax.annotate(lab, xy, fontsize=FS, color=col, fontweight="bold")
    ax.set_xticks(range(6))
    ax.set_xticklabels(glab)
    ax.set_xlabel("Age group")
    ax.set_ylabel("National donation rate (%)")
    ax.grid(color=NEU_L, lw=0.45, zorder=1)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ Figure S1（31a figure_s1）
def figure_s1():
    rows = read("figure_s1.csv")
    yr = [int(r["fiscal_year"]) for r in rows]
    ser = [("fukushima", "Fukushima", SIG, "-", 1.7, True),
           ("iwate", "Iwate", DEEP, "-", 1.7, True),
           ("miyagi", "Miyagi", ACC, "-", 1.2, True),
           ("national", "National", NEU_D, (0, (5, 2)), 1.0, False),
           ("median47_index", "47-prefecture median", NEU_M, (0, (1, 1.6)), 1.0, False)]
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    ax.axhline(100, color=NEU_L, lw=0.9, zorder=1)
    ax.annotate("baseline = 100", (2025.6, 100.0), xytext=(0, 2), textcoords="offset points", fontsize=FS,
                color=NEU_M, style="italic", va="bottom")
    # 右端で終点が近い2組は上下に振る。福島と岩手は v13 の ±1.15 を 8 pt の字の高さに合わせて ±1.6 に、
    # 宮城と47県中央値（1.2 指数ポイント差）は 8 pt で字が接するので ±0.9 を足した（v13 は振っていない）
    nudge = {"Iwate": 1.6, "Fukushima": -1.6, "Miyagi": 0.9, "47-prefecture median": -0.9}
    for key, lab, col, ls, lw, mk in ser:
        v = [float(r[key]) for r in rows]
        ax.plot(yr, v, ls=ls, color=col, lw=lw, zorder=4, marker="o" if mk else None, ms=2.6, mec="white", mew=0.4)
        y_lab = v[-1] + nudge.get(lab, 0.0)
        ax.annotate(lab, (2024.35, y_lab), fontsize=FS, color=col, va="center",
                    fontweight="bold" if mk else "normal")
        if lab in nudge:
            ax.plot([2024.0, 2024.28], [v[-1], y_lab], lw=0.5, color=col, zorder=3)
    fk = {int(r["fiscal_year"]): float(r["fukushima"]) for r in rows}
    iw = {int(r["fiscal_year"]): float(r["iwate"]) for r in rows}
    span = list(range(2012, 2024))
    assert all(iw[y] <= fk[y] for y in span), "FY2012-FY2023 の前提が崩れている"
    ax.fill_between(span, [iw[y] for y in span], [fk[y] for y in span], color=NEU_L, alpha=0.45, lw=0, zorder=2)
    gap = max((fk[y] - iw[y], y) for y in span)
    ax.annotate("Shaded: Iwate at or below Fukushima in every year,\nFY2012" + MINUS + "FY2023 (largest gap "
                + f"{gap[0]:.1f} index points, FY{gap[1]})", xy=(2005.0, 76.2), fontsize=FS, color=NEU_D,
                ha="left", va="bottom", linespacing=1.35)
    ax.set_ylim(75.5, 113.5)
    ax.set_xlabel("Fiscal year")
    ax.set_ylabel("Index of blood donations\n(FY2005$-$2009 geometric mean = 100)")
    ax.set_xticks(range(2005, 2025, 5))
    ax.set_xlim(2004.4, 2029.5)
    ax.grid(color=NEU_L, lw=0.45, zorder=0)
    ax.set_axisbelow(True)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ Figure S2（v13 figure_s2、字は v13 で 8 pt 以上）
CORE = {"03000": "Iwate", "04000": "Miyagi", "07000": "Fukushima"}
MIDDLE = {"02000": "Aomori", "08000": "Ibaraki", "12000": "Chiba"}
AKITA = "05000"


def read_decomposition():
    p = ROOT / "data" / "decomposition.csv"
    with io.open(p, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["pref_code"] != "00000"]
    assert len(rows) == 940, len(rows)
    return rows, p


def en_names() -> dict[str, str]:
    rows, _ = read_decomposition()
    return {r["pref_code"]: r["pref_name"] for r in rows}


def place_labels(fig, ax, pts, codes, names, colour=None, first=None, vlines=(), hlines=()):
    """点の名前を、印にも他の名前にも重ならない位置に置く（近い候補から順に試す）。"""
    from matplotlib.text import Text
    colour = colour or {}
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    px_per_pt = fig.dpi / 72.0

    def rad(code):
        s_ = 34 if code in CORE else 30 if code in MIDDLE else 13
        return ((s_ / 3.1416) ** 0.5 + 0.8) * px_per_pt
    centres = [(*ax.transData.transform(xy), rad(c)) for c, xy in pts.items()]
    placed = []
    cand = []
    for dist, leader in ((6, False), (14, True), (22, True), (30, True), (40, True), (52, True)):
        for deg in range(0, 360, 30):
            c_, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
            ha = "left" if c_ > 0.3 else "right" if c_ < -0.3 else "center"
            va = "bottom" if s_ > 0.3 else "top" if s_ < -0.3 else "center"
            cand.append((round(c_ * dist, 2), round(s_ * dist, 2), ha, va, leader))
    axbox = ax.get_window_extent(rend)
    first = first or {}
    for code in codes:
        xy = pts[code]
        done = False
        mine = [first[code]] if code in first else []
        for dx, dy, ha, va, leader in mine + [c for c in cand if c not in mine]:
            kw = dict(arrowprops=dict(arrowstyle="-", lw=0.5, color=colour.get(code, "black"), shrinkA=0,
                                      shrinkB=3)) if leader else {}
            t = ax.annotate(names[code], xy, xytext=(dx, dy), textcoords="offset points", ha=ha, va=va,
                            fontsize=8, color=colour.get(code, "black"), zorder=6, **kw)
            t.update_positions(rend)
            bb = Text.get_window_extent(t, rend).expanded(1.04, 1.10)
            ok = (bb.x0 >= axbox.x0 and bb.x1 <= axbox.x1 and bb.y0 >= axbox.y0 and bb.y1 <= axbox.y1)
            ok = ok and all(not (bb.x0 - rr < cx < bb.x1 + rr and bb.y0 - rr < cy < bb.y1 + rr)
                            for cx, cy, rr in centres)
            ok = ok and all(not bb.overlaps(o) for o in placed)
            for vx_ in vlines:
                X = ax.transData.transform((vx_, 0))[0]
                ok = ok and not (bb.x0 - 1 < X < bb.x1 + 1)
            for hy_ in hlines:
                Y = ax.transData.transform((0, hy_))[1]
                ok = ok and not (bb.y0 - 1 < Y < bb.y1 + 1)
            if ok and leader:
                px0, py0 = ax.transData.transform(xy)
                qx = min(max(px0, bb.x0), bb.x1)
                qy = min(max(py0, bb.y0), bb.y1)
                for cx, cy, rr in centres:
                    if abs(cx - px0) < 1e-6 and abs(cy - py0) < 1e-6:
                        continue
                    vx, vy = qx - px0, qy - py0
                    L2 = vx * vx + vy * vy or 1.0
                    u = max(0.0, min(1.0, ((cx - px0) * vx + (cy - py0) * vy) / L2))
                    dx_, dy_ = px0 + u * vx - cx, py0 + u * vy - cy
                    if dx_ * dx_ + dy_ * dy_ < (rr + 3.0 * px_per_pt) ** 2:
                        ok = False
                        break
            if ok:
                placed.append(bb)
                done = True
                break
            t.remove()
        if not done:
            raise RuntimeError(f"{names[code]} の置き場所が無い")


def figure_s2(outdir: Path):
    rows, src = read_decomposition()
    names = en_names()
    data = outdir / "figS2_data.csv"
    with io.open(data, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        f.write(f"# Figure S2 input. Source: data/decomposition.csv (sha256 {sha(src)})\n")
        f.write("# demographic = dln_P + dln_s (log points). group: core = three most affected prefectures, "
                "intermediate = three intermediate-exposure prefectures, other = 41 other prefectures\n")
        w.writerow(["pref_code", "pref_name", "fiscal_year", "group", "dln_P", "dln_s", "demographic",
                    "dln_r", "dln_D"])
        for r in rows:
            g = "core" if r["pref_code"] in CORE else "intermediate" if r["pref_code"] in MIDDLE else "other"
            dem = float(r["dln_P"]) + float(r["dln_s"])
            w.writerow([r["pref_code"], r["pref_name"], r["fiscal_year"], g, r["dln_P"], r["dln_s"],
                        f"{dem:.10g}", r["dln_r"], r["dln_D"]])
    with mpl.rc_context({"font.size": 8, "axes.labelsize": 8.5, "xtick.labelsize": 8, "ytick.labelsize": 8}):
        BLACK, GREY, GREY_D = "#000000", "#A8A8A8", "#5A5A5A"
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 4.4), gridspec_kw={"width_ratios": [1.25, 1]})
        y24 = [r for r in rows if r["fiscal_year"] == "2024"]
        for r in y24:
            code = r["pref_code"]
            x = float(r["dln_P"]) + float(r["dln_s"])
            y = float(r["dln_r"])
            if code in CORE:
                ax1.scatter(x, y, s=34, color=BLACK, zorder=5, linewidths=0)
            elif code in MIDDLE:
                ax1.scatter(x, y, s=30, facecolors="white", edgecolors=BLACK, linewidths=0.9, zorder=5)
            else:
                ax1.scatter(x, y, s=13, color=GREY, zorder=3, linewidths=0)
        ax1.axhline(0, color=GREY_D, lw=0.7, ls=(0, (1, 1.5)), zorder=2)
        ax1.axvline(-20, color=GREY_D, lw=0.7, ls=(0, (1, 1.5)), zorder=2)
        labelled = [AKITA] + list(CORE) + list(MIDDLE)
        pts = {r["pref_code"]: (float(r["dln_P"]) + float(r["dln_s"]), float(r["dln_r"])) for r in y24}
        ax1.set_xlim(-40, 8.5)
        ax1.set_xlabel("Demographic component, $\\Delta$ln $P$ + $\\Delta$ln $s$ (log points)")
        ax1.set_ylabel("Donation-rate component, $\\Delta$ln $r$ (log points)")
        ax1.set_axisbelow(True)
        years = sorted({int(r["fiscal_year"]) for r in rows})
        by = {(r["pref_code"], int(r["fiscal_year"])): float(r["dln_r"]) for r in rows}
        comp = sorted({r["pref_code"] for r in rows} - set(CORE))
        assert len(comp) == 44
        med, q1, q3, lo, hi = [], [], [], [], []
        for yv in years:
            v = sorted(by[(c, yv)] for c in comp)
            q = st.quantiles(v, n=4)
            med.append(st.median(v))
            q1.append(q[0])
            q3.append(q[2])
            lo.append(v[0])
            hi.append(v[-1])
        ax2.fill_between(years, lo, hi, color="#E2E2E2", lw=0, zorder=1)
        ax2.fill_between(years, q1, q3, color="#B4B4B4", lw=0, zorder=2)
        ax2.plot(years, med, color="#6E6E6E", lw=1.2, zorder=3)
        ax2.axhline(0, color=GREY_D, lw=0.7, ls=(0, (1, 1.5)), zorder=2)
        styles = {"07000": "-", "04000": (0, (4, 1.6)), "03000": (0, (1, 1.2))}
        for code, ls in styles.items():
            ax2.plot(years, [by[(code, yv)] for yv in years], color=BLACK, lw=1.3, ls=ls, zorder=5)
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        handles = [Line2D([], [], color=BLACK, lw=1.3, ls=styles[c]) for c in ("07000", "04000", "03000")]
        handles += [Line2D([], [], color="#6E6E6E", lw=1.2), Patch(color="#B4B4B4", lw=0),
                    Patch(color="#E2E2E2", lw=0)]
        ax2.legend(handles, ["Fukushima", "Miyagi", "Iwate", "Median", "IQR", "Range"], loc="upper left", ncol=2,
                   fontsize=8, frameon=False, handlelength=2.4, columnspacing=1.4, borderaxespad=0.2)
        ax2.set_ylim(-32, 48)
        ax2.set_xlim(2004.4, 2024.6)
        ax2.set_xticks(range(2005, 2025, 5))
        ax2.set_xlabel("Fiscal year")
        ax2.set_ylabel("Donation-rate component, $\\Delta$ln $r$ (log points)")
        ax2.set_axisbelow(True)
        for ax in (ax1, ax2):
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
        fig.tight_layout(w_pad=2.0)
        place_labels(fig, ax1, pts, labelled, names, colour={AKITA: GREY_D},
                     first={"02000": (-8, -10, "right", "top", True), AKITA: (-6, 0, "right", "center", False),
                            "03000": (-6, 0, "right", "center", False), "07000": (16, -44, "right", "top", True)},
                     vlines=(-20,), hlines=(0,))
        for ax, tag in ((ax1, "a"), (ax2, "b")):
            ax.text(-0.17 if tag == "a" else -0.15, 1.04, tag, transform=ax.transAxes, fontsize=9,
                    fontweight="bold", va="bottom", ha="left")
    return fig


# ------------------------------------------------------------------ 書き出しと検査
def min_font_pt(fig) -> float:
    """図に描いた字（軸の目盛り、軸名、注記、凡例）の最小の字号（pt）。"""
    fig.canvas.draw()
    sizes = [t.get_fontsize() for t in fig.findobj(mpl.text.Text) if t.get_visible() and t.get_text().strip()]
    return min(sizes)


def export(fig, outdir: Path, name: str, align: bool = False) -> dict:
    if align:
        sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "nature-figure" / "scripts"))
        from audit_panel_alignment import require_matplotlib_panel_alignment
        require_matplotlib_panel_alignment(fig, json_out=str(outdir / f"{name}.alignment.json"),
                                           tolerance_pt=1.5, gutter_tolerance_pt=1.5, strict=False)
    mn = min_font_pt(fig)
    if mn < MIN_PT:
        raise RuntimeError(f"{name}: 最小の字 {mn} pt < {MIN_PT}")
    fig.savefig(outdir / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(outdir / f"{name}.png", dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}.pdf / {name}.png ({DPI} dpi)  最小の字 {mn:.1f} pt")
    return {"figure": name, "min_font_pt": mn}


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "output" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    rep = [export(figure2_national_rate(), out, "fig2_national_rate"),
           export(figure3_decomposition(), out, "fig3_decomposition", align=True),
           export(figure4_deviation(), out, "fig4_deviation"),
           export(figure5_age_schedule(), out, "fig5_age_schedule"),
           export(figure_s1(), out, "figS1_index"),
           export(figure_s2(out), out, "figS2_47pref", align=True)]
    with io.open(out / "font_sizes.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["figure", "min_font_pt"])
        w.writeheader()
        w.writerows(rep)


if __name__ == "__main__":
    main()
