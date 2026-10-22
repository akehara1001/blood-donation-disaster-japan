"""
Reproduce every table, and the plotted values of every figure, of the paper from the files in data/.

Usage: python code/reproduce_tables.py            (writes output/tables/*.csv and output/figure_data/*.csv)

Definitions follow the Methods and Supplementary Methods S2 of the paper:
  * log points: 100 x the difference in natural logarithms from the FY2005-FY2009 geometric-mean baseline
    (columns dln_* of data/decomposition.csv);
  * two-year deviation: a prefecture's change in dln_r over two fiscal years minus the median change of the
    comparison prefectures over the same years (all prefectures other than those most affected by the event);
  * rank: position of the prefecture's two-year change among itself and its comparison prefectures, lowest = 1;
  * empirical percentile: 100 x (n_lower + 0.5 n_equal) / 940 over dln_r in all 940 prefecture-years;
  * standardised value: (d - mean) / SD (divisor m) of the same two-year deviation in the fiscal years before
    the fiscal year of the event, within the five fiscal years before it; not formed when m < 2.
Values are printed with the rounding and signs used in the paper.
"""
from __future__ import annotations

import csv
import io
import math
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "output"
MINUS = "−"
YEARS = list(range(2005, 2025))


def read(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8") as f:
        return list(csv.DictReader(io.StringIO("".join(ln for ln in f if not ln.startswith("#")))))


def write(sub: str, name: str, header: list[str], rows: list[list]) -> None:
    d = OUT / sub
    d.mkdir(parents=True, exist_ok=True)
    with open(d / name, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def sgn(v: float, nd: int = 2) -> str:
    """Signed, as in the paper: +3.28, -19.19 (minus sign U+2212)."""
    s = f"{v:+.{nd}f}"
    if float(s) == 0:
        s = s.replace("-", "+")
    return s.replace("-", MINUS)


def neg(v: float, nd: int = 2) -> str:
    """Minus sign only for negative values: 5.655, -18.246."""
    return f"{v:.{nd}f}".replace("-", MINUS)


# ------------------------------------------------------------------ data
DEC = [r for r in read("decomposition.csv")]
NAME = {r["pref_code"]: r["pref_name"] for r in DEC}
CODE = {v: k for k, v in NAME.items()}
PREFS = sorted({r["pref_code"] for r in DEC} - {"00000"})
assert len(PREFS) == 47
X = {(r["pref_code"], int(r["fiscal_year"])): r for r in DEC}


def v(col: str, p: str, y: int) -> float:
    return float(X[(p, y)][col])


def events() -> list[dict]:
    rows = read("ts_events.csv")
    out = {}
    for r in rows:
        e = out.setdefault(r["event"], {"event": r["event"], "event_fy": int(r["event_fiscal_year"][2:]),
                                        "first_fy": int(r["first_post_event_fy"][2:]), "most": [], "inter": []})
        (e["most"] if r["class"] == "most affected" else e["inter"]).append(CODE[r["prefecture"]])
    return list(out.values())


EVENTS = events()
OBS = [(e, p) for e in EVENTS for p in e["most"] + e["inter"]]   # 13 prefecture-event observations
assert len(OBS) == 13


def comparison(e: dict, strict: bool = False) -> list[str]:
    drop = set(e["most"]) | (set(e["inter"]) if strict else set())
    return [p for p in PREFS if p not in drop]


def two_year(series, p: str, t: int, b: int) -> float:
    return series(p, t) - series(p, b)


def deviation(e, p, t, b, series=lambda p, y: v("dln_r", p, y), strict=False):
    comp = comparison(e, strict)
    own = two_year(series, p, t, b)
    med = st.median(two_year(series, c, t, b) for c in comp)
    # rank among the prefecture and its comparison set; an intermediate-exposure prefecture is itself a member
    rank = 1 + sum(two_year(series, c, t, b) < own for c in comp if c != p)
    return own, med, own - med, rank, len(comp)


def pre_event(e, p):
    """Two-year deviations in the five fiscal years before the fiscal year of the event, where they exist."""
    ys = [y for y in range(e["event_fy"] - 5, e["event_fy"]) if y - 2 >= 2005]
    return [deviation(e, p, y, y - 2)[2] for y in ys]


def standardised(e, p, d):
    pre = pre_event(e, p)
    if len(pre) < 2:
        return None, len(pre)
    m = st.mean(pre)
    sd = math.sqrt(sum((x - m) ** 2 for x in pre) / len(pre))
    return (d - m) / sd, len(pre)


ALL_R = sorted(v("dln_r", p, y) for p in PREFS for y in YEARS)


def percentile(x: float) -> float:
    lo = sum(1 for a in ALL_R if a < x)
    eq = sum(1 for a in ALL_R if a == x)
    return 100 * (lo + 0.5 * eq) / len(ALL_R)


# ------------------------------------------------------------------ Table 1
def table1():
    rows = []
    for e in EVENTS:
        for p in e["most"]:
            if e["event"] not in ("Great East Japan Earthquake", "Kumamoto Earthquake"):
                continue
            t = e["first_fy"]
            own, med, d, rank, n = deviation(e, p, t, t - 2)
            z, m = standardised(e, p, d)
            rows.append([NAME[p], str(t), neg(v("dln_r", p, t), 3), f"{percentile(v('dln_r', p, t)):.3f}",
                         neg(d, 2), neg(z, 2), str(m)])
    order = ["Fukushima", "Miyagi", "Iwate", "Kumamoto"]
    rows.sort(key=lambda r: order.index(r[0]))
    write("tables", "table1.csv", ["Prefecture", "First post-event FY", "Cumulative dln r", "Empirical percentile",
                                   "Deviation from comparison median", "Standardised vs own pre-event",
                                   "Pre-event n"], rows)
    return rows


# ------------------------------------------------------------------ Table 2
AGE = read("age_standardized.csv")
SDR = {(r["schedule"], r["pref_code"], int(r["fiscal_year"])): r for r in AGE}


def rank_desc(col: str, p: str, y: int) -> str:
    vals = sorted((v(col, q, y) for q in PREFS), reverse=True)
    return f"{1 + sum(x > v(col, p, y) for x in vals)}/47"


def table2():
    rows = []
    for name in ("Fukushima", "Miyagi", "Iwate"):
        p, y = CODE[name], 2024
        dD, dP, ds, dr = (v(c, p, y) for c in ("dln_D", "dln_P", "dln_s", "dln_r"))
        sdr = {k: float(SDR[(k, p, y)]["dln_SDR"]) for k in "ABC"}
        age_a = float(SDR[("A", p, y)]["dln_age_structure"])
        rows.append([name, neg(dD, 3), neg(dP, 3), neg(ds, 3), neg(dr, 3), neg(dP + ds, 3), rank_desc("dln_D", p, y),
                     rank_desc("dln_r", p, y), neg(sdr["A"]), neg(sdr["B"]), neg(sdr["C"]),
                     f"{math.exp(dD / 100) * 100:.1f}", f"{math.exp((dD - age_a) / 100) * 100:.1f}"])
    write("tables", "table2.csv", ["Prefecture", "dln D", "dln P", "dln s", "dln r", "Demographic part",
                                   "Rank dln D", "Rank dln r", "dln SDR (FY2011 sch.)", "dln SDR (FY2024 sch.)",
                                   "dln SDR (FY2010 sch.)", "Index crude", "Index adjusted"], rows)
    return rows


# ------------------------------------------------------------------ Table S2
def table_s2():
    a = {int(r["fiscal_year"]): float(r["actual_donors_national"]) for r in read("actual_donors_national.csv")}
    q = {}
    for y in (2023, 2024):
        D, P, P69 = v("D_donors", "00000", y), v("P_persons", "00000", y), v("P1569_persons", "00000", y)
        q[y] = {"D": D, "P": P, "s": P69 / P, "q": a[y] / P69, "f": D / a[y], "A": a[y]}
    ch = {k: 100 * math.log(q[2024][k] / q[2023][k]) for k in "DPsqf"}
    rows = [["Donations, D", f"{q[2023]['D']:,.0f}", f"{q[2024]['D']:,.0f}", sgn(ch["D"], 3)],
            ["Population, P", f"{q[2023]['P']:,.0f}", f"{q[2024]['P']:,.0f}", sgn(ch["P"], 3)],
            ["Share aged 15 to 69, s", f"{100 * q[2023]['s']:.3f}%", f"{100 * q[2024]['s']:.3f}%", sgn(ch["s"], 3)],
            ["Residents aged 15 to 69 who donated, q = A/P15-69", f"{100 * q[2023]['q']:.3f}%",
             f"{100 * q[2024]['q']:.3f}%", sgn(ch["q"], 3)],
            ["Donations per donor, f = D/A", f"{q[2023]['f']:.3f}", f"{q[2024]['f']:.3f}", sgn(ch["f"], 3)],
            ["Individual donors, A", f"{q[2023]['A']:,.0f}", f"{q[2024]['A']:,.0f}", "—"]]
    write("tables", "table_s2.csv", ["Quantity", "FY2023", "FY2024", "Change (log points)"], rows)
    return rows


# ------------------------------------------------------------------ Table S3
def p1519() -> dict:
    out = {}
    for r in read("population_age.csv"):
        if (r["population_type"] == "total population" and r["sex"] == "both sexes" and r["age_band_code"] == "01004"
                and r["population"]):
            out[(r["pref_code"], int(r["year"]))] = float(r["population"]) * 1000
    return out


P1519 = p1519()
LN_BASE_2069 = {}


def r2069(p: str, y: int) -> float:
    """dln r with the population aged 20 to 69 as the denominator (same baseline definition)."""
    rate = lambda yy: v("D_donors", p, yy) / (v("P1569_persons", p, yy) - P1519[(p, yy)])  # noqa: E731
    if p not in LN_BASE_2069:
        LN_BASE_2069[p] = st.mean(math.log(rate(yy)) for yy in range(2005, 2010))
    return 100 * (math.log(rate(y)) - LN_BASE_2069[p])


def fitted_2010(p: str) -> float:
    """dln r in FY2010 replaced by the value fitted from the prefecture's own FY2006-FY2009 linear trend."""
    xs = list(range(2006, 2010))
    ys = [v("dln_r", p, x) for x in xs]
    mx, my = st.mean(xs), st.mean(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return my + b * (2010 - mx)


def table_s3():
    order = ["Fukushima", "Miyagi", "Iwate", "Ibaraki", "Chiba", "Aomori", "Kumamoto", "Hokkaido", "Ishikawa",
             "Niigata", "Okayama", "Hiroshima", "Ehime"]
    obs = sorted(OBS, key=lambda o: order.index(NAME[o[1]]))
    rows = []

    def add(var, role, e, p, t, b, series=None, strict=False):
        kw = {"strict": strict}
        if series:
            kw["series"] = series
        own, med, d, rank, n = deviation(e, p, t, b, **kw)
        rows.append([var, role, NAME[p], f"FY{t}", f"FY{b}", str(n), sgn(own), sgn(med), sgn(d)])

    for e, p in obs:
        add("a", "main", e, p, e["first_fy"], e["first_fy"] - 2)
    for e, p in obs:
        add("b", "sensitivity", e, p, e["first_fy"], e["first_fy"] - 1)
    for e, p in obs:
        add("c", "sensitivity", e, p, e["first_fy"], e["event_fy"] - 1)
    for e, p in obs:
        t = e["first_fy"]
        if t == 2011:
            ser = lambda q, y: fitted_2010(q) if y == 2010 else v("dln_r", q, y)  # noqa: E731
            add("d", "sensitivity", e, p, t, t - 1, series=ser)
        else:
            add("d", "sensitivity", e, p, t, t - 1)
    for e, p in obs:
        if e["event"] == "Great East Japan Earthquake":
            add("e", "sensitivity", e, p, e["first_fy"], e["first_fy"] - 2, strict=True)
    for e, p in obs:
        add("f", "sensitivity", e, p, e["first_fy"], e["first_fy"] - 2, series=r2069)
    write("tables", "table_s3.csv", ["Variant", "Role", "Prefecture", "First post-event FY",
                                     "Base year of the difference", "Comparison n", "Own difference (log pts)",
                                     "Comparison median (log pts)", "Deviation (log pts)"], rows)
    # FY2024 rate component with the population aged 20 to 69 (note to Table S3)
    f24 = [[n, sgn(r2069(CODE[n], 2024))] for n in ("Fukushima", "Miyagi", "Iwate")]
    write("tables", "table_s3_note_fy2024_20_69.csv", ["Prefecture", "dln r FY2024, denominator 20 to 69"], f24)
    # evacuee adjustment, FY2011, counts as of 22 September 2011
    ev = {r["fiscal_year"] + r["series"]: r for r in read("evacuees_outside_prefecture.csv")}["2011B_midyear"]
    erows = []
    for name, col in (("Fukushima", "outside_fukushima"), ("Miyagi", "outside_miyagi")):
        p, y = CODE[name], 2011
        n_ev = float(ev[col])
        D, P69, s = v("D_donors", p, y), v("P1569_persons", p, y), v("s_share_15_69", p, y)
        base = st.mean(math.log(v("r_donations_per_capita_15_69", p, yy)) for yy in range(2005, 2010))
        adj = lambda k: 100 * (math.log(D / (P69 - k * n_ev)) - base)  # noqa: E731
        import datetime as _dt
        day = _dt.date.fromisoformat(ev["as_of"][6:])
        erows.append(["Evacuees removed from the denominator", name, f"{n_ev:,.0f} ({day.day} {day:%b %Y})",
                      neg(v("dln_r", p, y)), neg(adj(s)), neg(adj(1.0))])
    write("tables", "table_s3_evacuees.csv", ["Adjustment", "Prefecture", "Evacuees outside the prefecture",
                                              "r unadjusted", "r removed, own age composition",
                                              "r removed, all aged 15 to 69"], erows)
    return rows, f24, erows


# ------------------------------------------------------------------ Table S5
def table_s5():
    order = ["Fukushima", "Miyagi", "Iwate", "Kumamoto", "Ibaraki", "Chiba", "Aomori", "Okayama", "Hiroshima",
             "Ehime", "Hokkaido", "Ishikawa", "Niigata"]
    rows = []
    for e, p in sorted(OBS, key=lambda o: order.index(NAME[o[1]])):
        group = "core" if (p in e["most"] and e["event"] in ("Great East Japan Earthquake",
                                                               "Kumamoto Earthquake")) else "other"
        t = e["first_fy"]
        _, _, d, rank, n = deviation(e, p, t, t - 2)
        t2 = e["event_fy"] + 1
        _, _, d2, rank2, _ = deviation(e, p, t2, t2 - 2)
        size = n if p in comparison(e) else n + 1
        rows.append([NAME[p], e["event"], group, f"FY{t}", sgn(d), f"{rank}/{size}", f"FY{t2}", sgn(d2),
                     f"{rank2}/{size}"])
    write("tables", "table_s5.csv", ["Prefecture", "Event", "Group", "Main rule: first post-event FY",
                                     "Main rule: deviation (log pts)", "Main rule: rank",
                                     "Alternative: first post-event FY", "Alternative: deviation (log pts)",
                                     "Alternative: rank"], rows)
    return rows


# ------------------------------------------------------------------ Table S6
def table_s6():
    order = ["Fukushima", "Miyagi", "Iwate", "Kumamoto", "Ibaraki", "Chiba", "Aomori", "Okayama", "Hiroshima",
             "Ehime", "Hokkaido", "Ishikawa", "Niigata"]
    rows = []
    for e, p in sorted(OBS, key=lambda o: order.index(NAME[o[1]])):
        group = "core" if (p in e["most"] and e["event"] in ("Great East Japan Earthquake",
                                                               "Kumamoto Earthquake")) else "other"
        ys = [y for y in range(e["event_fy"] - 5, e["event_fy"]) if y >= 2005]
        comp = comparison(e)
        series = [v("dln_r", p, y) - st.median(v("dln_r", c, y) for c in comp) for y in ys]
        mx, my = st.mean(ys), st.mean(series)
        sxx = sum((x - mx) ** 2 for x in ys)
        b = sum((x - mx) * (y - my) for x, y in zip(ys, series)) / sxx
        ss_tot = sum((y - my) ** 2 for y in series)
        ss_res = sum((y - (my + b * (x - mx))) ** 2 for x, y in zip(ys, series))
        r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
        d = deviation(e, p, e["first_fy"], e["first_fy"] - 2)[2]
        contrib = 2 * b
        # R2 is rounded once, to 2 decimals (Okayama: 0.85503... -> 0.86)
        rows.append([NAME[p], group, str(len(ys)), f"FY{ys[0]}-FY{ys[-1]}", sgn(b, 3), f"{r2:.2f}",
                     sgn(contrib),
                     sgn(d), sgn(d - contrib) if len(ys) > 2 else "–"])
    write("tables", "table_s6.csv", ["Prefecture", "Group", "Pre-event points", "Window", "Slope (log pts / year)",
                                     "R2", "Two-year contribution (log pts)",
                                     "Deviation in first post-event FY (log pts)", "Deviation less contribution"],
          rows)
    return rows


# ------------------------------------------------------------------ Table S7
def table_s7():
    order = ["Fukushima", "Miyagi", "Iwate", "Kumamoto", "Ibaraki", "Chiba", "Aomori", "Okayama", "Hiroshima",
             "Ehime", "Hokkaido", "Ishikawa", "Niigata"]
    rows = []
    for e, p in sorted(OBS, key=lambda o: order.index(NAME[o[1]])):
        t = e["first_fy"]
        d = deviation(e, p, t, t - 2)[2]
        z, m = standardised(e, p, d)
        rows.append([NAME[p], e["event"], str(t), sgn(d), sgn(z) if z is not None else "–", str(m)])
    write("tables", "table_s7.csv", ["Prefecture", "Event", "First post-event FY",
                                     "Deviation in first post-event FY (log pts)", "Standardised vs own pre-event",
                                     "Pre-event n"], rows)
    pdec = {r["pref_code"] + r["fiscal_year"]: r for r in read("pop_decomposition_by_age.csv")}["070002024"]
    bands = [neg(float(pdec[c])) for c in ("contrib_age_0_14", "contrib_age_15_29", "contrib_age_30_49",
                                            "contrib_age_50_69", "contrib_age_70plus")]
    write("tables", "table_s7_agebands.csv", ["Series", "0 to 14", "15 to 29", "30 to 49", "50 to 69",
                                              "70 and over"], [["Fukushima, FY2024"] + bands])
    return rows, bands


# ------------------------------------------------------------------ Supplementary Methods S2 (b)
def rates():
    out = {}
    for r in read("age_schedule.csv"):
        out.setdefault(int(r["source_fiscal_year"]), {})[r["age_group"]] = 100 * float(r["w_rate"])
    rows = [[y] + [f"{out[y][g]:.2f}" for g in ("10s", "20s", "30s", "40s", "50s", "60s")] for y in (2010, 2011, 2024)]
    write("tables", "methods_s2_rates.csv", ["Fiscal year", "16 to 19", "20s", "30s", "40s", "50s", "60s"], rows)
    return rows


# ------------------------------------------------------------------ figure data
def figures():
    med = {y: st.median(v("dln_r", p, y) for p in PREFS) for y in YEARS}
    write("figure_data", "figure2.csv", ["fiscal_year", "median47_dln_r", "national_dln_r"],
          [[y, f"{med[y]:.4f}", f"{v('dln_r', '00000', y):.4f}"] for y in YEARS])
    write("figure_data", "figure3.csv", ["prefecture", "fiscal_year", "dln_D", "dln_P", "dln_s", "dln_r"],
          [[n, y] + [f"{v(c, CODE[n], y):.4f}" for c in ("dln_D", "dln_P", "dln_s", "dln_r")]
           for y in (2011, 2024) for n in ("Fukushima", "Miyagi", "Iwate")])
    def group(e, p):
        if e["event"] in ("Great East Japan Earthquake", "Kumamoto Earthquake") and p in e["most"]:
            return "core"
        if p in e["inter"]:
            return "intermediate"
        return "rain" if e["event"] == "July 2018 heavy rain" else "small"
    write("figure_data", "figure4.csv", ["prefecture", "event", "first_post_event_fy", "deviation", "group",
                                         "is_core"],
          [[NAME[p], e["event"], e["first_fy"], f"{deviation(e, p, e['first_fy'], e['first_fy'] - 2)[2]:.6f}",
            group(e, p), "yes" if group(e, p) == "core" else "no"] for e, p in OBS])
    write("figure_data", "figure5.csv", ["schedule_fy", "age_group", "rate_pct"],
          [[r["source_fiscal_year"], r["age_group"], f"{100 * float(r['w_rate']):.4f}"] for r in read("age_schedule.csv")
           if r["source_fiscal_year"] in ("2011", "2024")])
    idx = {y: st.median(float(X[(p, y)]["index_geo_base"]) for p in PREFS) for y in YEARS}
    write("figure_data", "figure_s1.csv", ["fiscal_year", "fukushima", "miyagi", "iwate", "national", "median47_index"],
          [[y] + [X[(CODE[n], y)]["index_geo_base"] for n in ("Fukushima", "Miyagi", "Iwate")]
           + [X[("00000", y)]["index_geo_base"], f"{idx[y]:.3f}"] for y in YEARS])
    write("figure_data", "figure_s2.csv", ["pref_code", "prefecture", "fiscal_year", "demographic", "dln_r", "dln_D"],
          [[p, NAME[p], y, f"{v('dln_P', p, y) + v('dln_s', p, y):.4f}", f"{v('dln_r', p, y):.4f}",
            f"{v('dln_D', p, y):.4f}"] for p in PREFS for y in YEARS])
    return med, idx


def main():
    t1 = table1()
    t2 = table2()
    s2 = table_s2()
    s3 = table_s3()
    s5 = table_s5()
    s6 = table_s6()
    s7 = table_s7()
    rt = rates()
    figures()
    for name, rows in (("Table 1", t1), ("Table 2", t2), ("Table S2", s2), ("Table S5", s5), ("Table S6", s6)):
        print(name, len(rows), "rows")
    print("Table S3", len(s3[0]), "rows; Table S7", len(s7[0]), "rows; rates", len(rt), "rows")


if __name__ == "__main__":
    main()
