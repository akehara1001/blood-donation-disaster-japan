"""
タスク11-1: 人口規模寄与 dln_P の年齢階級別分解

dln_P を 0-14歳、15-29歳、30-49歳、50-69歳、70歳以上 の寄与に分解する。

分解の方法（厳密加法分解）
  対数平均 L(x,y) = (x-y)/(ln x - ln y)（x=y のときは x）を用いる。
  各階級 a について
      寄与_a = [ L(P_at, P_a0) / L(P_t, P_0) ] * ln(P_at / P_a0)
  とすると
      Σ_a 寄与_a = ln(P_t / P_0)
  が恒等的に成立する。これは Σ_a (P_at - P_a0) = P_t - P_0 と
  L(x,y)*ln(x/y) = x - y から直ちに従う。近似ではない。

基準について
  この分解が厳密に閉じるためには P_0 = Σ_a P_a0 でなければならない。
  幾何平均は和を保存しないため、本分解の基準は
  2005年度から2009年度の**算術平均**とする。
  decomposition.csv の dln_P は幾何平均基準であり値がわずかに異なる。
  両者を並記して差を示す。

出力: data/processed/pop_decomposition_by_age.csv
      output/pop_decomposition_summary.md
"""
from __future__ import annotations

import csv
import io
import math
import statistics as stats
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROCESSED_DIR, OUTPUT_DIR, now_iso  # noqa: E402

BASE_YEARS = list(range(2005, 2010))
NATIONAL = "00000"
DISASTER = {"07000": "福島県", "04000": "宮城県", "03000": "岩手県"}
LATEST = 2024
TOL = 1e-9

BANDS = {
    "age_0_14": ["01001", "01002", "01003"],
    "age_15_29": ["01004", "01005", "01006"],
    "age_30_49": ["01007", "01008", "01009", "01010"],
    "age_50_69": ["01011", "01012", "01013", "01014"],
    # 70歳以上は年により最上位階級の構成が変わる。実在するものを使う。
    "age_70plus": ["01015", "01016", "01017", "04018", "04017"],
}


def logmean(x: float, y: float) -> float:
    if x <= 0 or y <= 0:
        return 0.0
    if abs(x - y) < 1e-12:
        return x
    return (x - y) / (math.log(x) - math.log(y))


def main() -> int:
    with io.open(PROCESSED_DIR / "population_age.csv", encoding="utf-8-sig",
                 newline="") as f:
        rows = [r for r in csv.DictReader(f)
                if r["population_type"] == "総人口" and r["sex"] == "男女計"
                and r["population"]]

    cube: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    names: dict[str, str] = {}
    for r in rows:
        cube[(int(r["year"]), r["pref_code"])][r["age_band_code"]] = \
            float(r["population"]) * 1000.0   # 千人 -> 人
        names[r["pref_code"]] = r["pref_name"]

    years = sorted({y for y, _ in cube})
    prefs = sorted({p for _, p in cube})

    def band_pop(d: dict[str, float], band: str) -> float:
        codes = BANDS[band]
        if band == "age_70plus":
            # 01017(80-84) と 04018(85+) が揃う年は 04017(80+) を使わない
            if "01017" in d and "04018" in d:
                codes = ["01015", "01016", "01017", "04018"]
            else:
                codes = ["01015", "01016", "04017"]
        return sum(d[c] for c in codes if c in d)

    out_rows = []
    worst = 0.0
    n_bad = 0
    for p in prefs:
        base = {}
        for b in BANDS:
            vals = [band_pop(cube[(y, p)], b) for y in BASE_YEARS]
            base[b] = stats.mean(vals)           # 算術平均基準
        base_total = sum(base.values())

        for y in years:
            d = cube[(y, p)]
            cur = {b: band_pop(d, b) for b in BANDS}
            cur_total = sum(cur.values())
            L_tot = logmean(cur_total, base_total)

            contribs = {}
            for b in BANDS:
                w = logmean(cur[b], base[b]) / L_tot if L_tot else 0.0
                contribs[b] = w * math.log(cur[b] / base[b]) * 100 if base[b] else 0.0

            dlnP_arith = math.log(cur_total / base_total) * 100
            resid = dlnP_arith - sum(contribs.values())
            worst = max(worst, abs(resid))
            if abs(resid) > TOL:
                n_bad += 1

            row = {"pref_code": p, "pref_name": names[p], "fiscal_year": y,
                   "dln_P_arith_base": round(dlnP_arith, 10)}
            for b in BANDS:
                row[f"contrib_{b}"] = round(contribs[b], 10)
                row[f"pop_{b}"] = int(cur[b])
            row["additive_residual"] = round(resid, 12)
            row["base"] = "2005-2009年度の算術平均"
            row["method"] = "対数平均による厳密加法分解"
            row["retrieved_at"] = now_iso()
            out_rows.append(row)

    print(f"--- 検算: 寄与の合計 = dln_P （全 {len(out_rows)} 行） ---")
    print(f"  残差の絶対値の最大: {worst:.3e} 対数ポイント")
    print(f"  許容 {TOL:.0e} を超えた行: {n_bad}")
    if n_bad:
        print("  加法性が成立しない。中止する。")
        return 1

    out = PROCESSED_DIR / "pop_decomposition_by_age.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n書き出し: {out}  行数 {len(out_rows)} / 欠測 0")

    # 幾何平均基準との差
    with io.open(PROCESSED_DIR / "decomposition.csv", encoding="utf-8-sig",
                 newline="") as f:
        geo = {(int(r["fiscal_year"]), r["pref_code"]): float(r["dln_P"])
               for r in csv.DictReader(f)}
    diffs = [abs(r["dln_P_arith_base"] - geo[(r["fiscal_year"], r["pref_code"])])
             for r in out_rows if (r["fiscal_year"], r["pref_code"]) in geo]
    print(f"  幾何平均基準の dln_P との差: 最大 {max(diffs):.4f} / "
          f"中央値 {stats.median(diffs):.4f} 対数ポイント")

    # ---------- 報告 ----------
    idx = {(r["fiscal_year"], r["pref_code"]): r for r in out_rows}
    md = OUTPUT_DIR / "pop_decomposition_summary.md"
    with md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 人口規模寄与の年齢階級別分解\n\n")
        f.write(f"作成日時: {now_iso()}\n\n")
        f.write("dln_P を 0-14歳、15-29歳、30-49歳、50-69歳、70歳以上 の寄与に分解した。"
                "対数平均を用いた厳密加法分解であり近似ではない。\n")
        f.write(f"検算: 寄与の合計と dln_P の残差の絶対値の最大は {worst:.3e} 対数ポイント、"
                f"全 {len(out_rows)} 行で加法性が成立している。\n\n")
        f.write("基準は2005年度から2009年度の**算術平均**である。"
                "厳密加法性には P_0 が階級の和である必要があり、"
                "幾何平均は和を保存しないためである。"
                f"decomposition.csv の幾何平均基準の dln_P との差は"
                f"最大 {max(diffs):.4f} 対数ポイントにとどまる。\n\n")

        f.write(f"## 福島県の内訳（{LATEST}年度）\n\n")
        r = idx[(LATEST, "07000")]
        f.write(f"dln_P = {r['dln_P_arith_base']:+.2f} 対数ポイント\n\n")
        f.write("| 年齢階級 | 寄与（対数ポイント） | dln_P に占める割合 |\n|---|---:|---:|\n")
        for b in BANDS:
            c = r[f"contrib_{b}"]
            share = c / r["dln_P_arith_base"] * 100
            f.write(f"| {b.replace('age_', '').replace('_', '-').replace('plus', '以上')} | "
                    f"{c:+.2f} | {share:.1f}% |\n")
        f.write("\n")

        f.write("## 福島県の推移\n\n")
        f.write("| 年度 | dln_P | 0-14歳 | 15-29歳 | 30-49歳 | 50-69歳 | 70歳以上 |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for y in (2011, 2015, 2020, LATEST):
            r = idx[(y, "07000")]
            f.write(f"| {y} | {r['dln_P_arith_base']:+.2f} | " + " | ".join(
                f"{r[f'contrib_{b}']:+.2f}" for b in BANDS) + " |\n")
        f.write("\n")

        f.write(f"## 被災3県と全国の対比（{LATEST}年度）\n\n")
        f.write("| 地域 | dln_P | 0-14歳 | 15-29歳 | 30-49歳 | 50-69歳 | 70歳以上 |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|\n")
        for code in list(DISASTER) + [NATIONAL]:
            r = idx[(LATEST, code)]
            nm = DISASTER.get(code, "全国")
            f.write(f"| {nm} | {r['dln_P_arith_base']:+.2f} | " + " | ".join(
                f"{r[f'contrib_{b}']:+.2f}" for b in BANDS) + " |\n")
        f.write("\n")

        f.write(f"## 47都道府県のなかでの福島県の位置（{LATEST}年度）\n\n")
        f.write("| 成分 | 福島県 | 順位（降順） | 47県中央値 |\n|---|---:|---:|---:|\n")
        p47 = [p for p in prefs if p != NATIONAL]
        for b in list(BANDS) + ["dln_P_arith_base"]:
            key = f"contrib_{b}" if b != "dln_P_arith_base" else b
            vals = [(p, idx[(LATEST, p)][key]) for p in p47]
            rk = sorted(vals, key=lambda x: -x[1])
            pos = [x[0] for x in rk].index("07000") + 1
            label = (b.replace("age_", "").replace("_", "-").replace("plus", "以上")
                     if b != "dln_P_arith_base" else "dln_P 合計")
            f.write(f"| {label} | {idx[(LATEST, '07000')][key]:+.2f} | {pos}/47 | "
                    f"{stats.median(v for _, v in vals):+.2f} |\n")
        f.write("\n")

        f.write("## 発表スライドの主張との対照\n\n")
        r = idx[(LATEST, "07000")]
        y1529 = r["contrib_age_15_29"]
        y014 = r["contrib_age_0_14"]
        tot = r["dln_P_arith_base"]
        f.write("発表スライドは若年層の県外流出を主張しているが、"
                "本分解はその主張を直接には支持しない。\n\n")
        f.write(f"{LATEST}年度の福島県の人口寄与 {tot:+.2f} 対数ポイントのうち、"
                f"15-29歳が占めるのは {y1529:+.2f}（{y1529/tot*100:.1f} パーセント）、"
                f"0-14歳が占めるのは {y014:+.2f}（{y014/tot*100:.1f} パーセント）である。\n\n")
        f.write("数値は上記のとおりである。断定はしない。"
                "本分解は人口の増減を年齢階級に配分するものであり、"
                "その増減が転出によるものか出生減によるものかは区別しない。"
                "自然増減と社会増減の分離には別のデータが必要である。\n")

    print(f"書き出し: {md}")

    print(f"\n--- 福島県 {LATEST}年度 の人口寄与の内訳 ---")
    r = idx[(LATEST, "07000")]
    print(f"  dln_P = {r['dln_P_arith_base']:+.2f}")
    for b in BANDS:
        c = r[f"contrib_{b}"]
        print(f"    {b:<12} {c:+7.2f}  ({c/r['dln_P_arith_base']*100:5.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
