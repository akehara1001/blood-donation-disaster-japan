"""
タスク18-3、18-4: 固定年齢スケジュール法による年齢構成効果の分離

  E_it   = Σ_a ( w_a × P_iat )        期待献血者数（w_a は年度によらず固定）
  SDR_it = D_it / E_it                年齢構成を統制した献血回数率
  Δln r  = Δln SDR + Δln( E / P1569 ) 恒等式

基準は2005-2009年度の幾何平均（時系列分解と同一）。

**これは完全な間接標準化ではない。**
年齢スケジュールを1年に固定しているため、
年代別献血率そのものが期間内に変化した分は捉えられない。

出力: data/processed/age_standardized.csv
      output/age_standardization.md
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

NATIONAL = "00000"
BASE_YEARS = list(range(2005, 2010))
GROUPS = ["10代", "20代", "30代", "40代", "50代", "60代"]
POP_CODES = {
    "10代": ["01004"], "20代": ["01005", "01006"], "30代": ["01007", "01008"],
    "40代": ["01009", "01010"], "50代": ["01011", "01012"],
    "60代": ["01013", "01014"],
}
FK, MG, IW = "07000", "04000", "03000"
TOL = 1e-10


def read_csv(p: Path, skip=False) -> list[dict]:
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        if skip:
            lines = [ln for ln in f if not ln.startswith("#")]
            return list(csv.DictReader(io.StringIO("".join(lines))))
        return list(csv.DictReader(f))


def main() -> int:
    don = read_csv(PROCESSED_DIR / "donors.csv")
    D = {(int(r["fiscal_year"]), r["pref_code"]): float(r["donors"])
         for r in don if r["donors"]}
    names = {r["pref_code"]: r["pref_name"] for r in don}

    age = [r for r in read_csv(PROCESSED_DIR / "population_age.csv")
           if r["population_type"] == "総人口" and r["sex"] == "男女計" and r["population"]]
    cube = defaultdict(dict)
    for r in age:
        cube[(int(r["year"]), r["pref_code"])][r["age_band_code"]] = \
            float(r["population"]) * 1000.0

    Pg, P69 = {}, {}
    for k, d in cube.items():
        if all(c in d for cs in POP_CODES.values() for c in cs):
            Pg[k] = {g: sum(d[c] for c in cs) for g, cs in POP_CODES.items()}
            P69[k] = sum(Pg[k].values())

    sched = defaultdict(dict)
    for r in read_csv(PROCESSED_DIR / "age_schedule.csv", skip=True):
        sched[r["schedule"]][r["age_group"]] = float(r["w_rate"])
    schedules = sorted(sched)
    print(f"年齢スケジュール: {schedules}")

    years = sorted({y for y, _ in D})
    prefs = sorted({p for _, p in D if p != NATIONAL})

    rows = []
    worst = 0.0
    n_bad = 0
    res = defaultdict(dict)          # (sched, comp) -> {(y,p): value}
    for s in schedules:
        w = sched[s]
        E, SDR, ratio = {}, {}, {}
        for p in prefs + [NATIONAL]:
            for y in years:
                k = (y, p)
                if k not in D or k not in Pg:
                    continue
                E[k] = sum(w[g] * Pg[k][g] for g in GROUPS)
                SDR[k] = D[k] / E[k]
                ratio[k] = E[k] / P69[k]
        for p in prefs + [NATIONAL]:
            if not all((y, p) in SDR for y in BASE_YEARS):
                continue
            bS = sum(math.log(SDR[(y, p)]) for y in BASE_YEARS) / 5
            bR = sum(math.log(ratio[(y, p)]) for y in BASE_YEARS) / 5
            br = sum(math.log(D[(y, p)] / P69[(y, p)]) for y in BASE_YEARS) / 5
            for y in years:
                k = (y, p)
                if k not in SDR:
                    continue
                dSDR = (math.log(SDR[k]) - bS) * 100
                dAGE = (math.log(ratio[k]) - bR) * 100
                dr = (math.log(D[k] / P69[k]) - br) * 100
                resid = dr - (dSDR + dAGE)
                worst = max(worst, abs(resid))
                if abs(resid) > TOL:
                    n_bad += 1
                res[(s, "dln_SDR")][k] = dSDR
                res[(s, "dln_age")][k] = dAGE
                res[(s, "dln_r")][k] = dr
                rows.append({
                    "schedule": s, "pref_code": p, "pref_name": names[p],
                    "fiscal_year": y,
                    "D_donors": int(D[k]), "E_expected": round(E[k], 4),
                    "SDR": round(SDR[k], 10),
                    "E_over_P1569": round(ratio[k], 10),
                    "dln_SDR": round(dSDR, 10),
                    "dln_age_structure": round(dAGE, 10),
                    "dln_r_crude": round(dr, 10),
                    "additive_residual": round(resid, 12),
                    "base": "2005-2009年度の幾何平均",
                    "note": "固定年齢スケジュール法。完全な間接標準化ではない。",
                })

    print(f"\n--- 検算: Δln r = Δln SDR + Δln(E/P1569) ---")
    print(f"  残差の絶対値の最大: {worst:.3e} 対数ポイント / 許容 {TOL:.0e} 超過 {n_bad}")
    if n_bad:
        print("  恒等式が成立しない。中止する。")
        return 1

    out = PROCESSED_DIR / "age_standardized.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("# 固定年齢スケジュール法。基準は2005-2009年度の幾何平均。\n")
        f.write("# Δln r = Δln SDR + Δln(E/P1569) が恒等的に成立する。\n")
        w_ = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w_.writeheader()
        w_.writerows(rows)
    print(f"\n書き出し: {out} ({len(rows)} 行)")

    # 献血者数の指数の比較に用いる Δln D を decomposition.csv から読む
    dlnD_map = {(int(r["fiscal_year"]), r["pref_code"]): float(r["dln_D"])
                for r in read_csv(PROCESSED_DIR / "decomposition.csv")}

    # ---------- 18-4 判定 ----------
    def g(s, comp, y, p):
        return res[(s, comp)].get((y, p))

    md = OUTPUT_DIR / "age_standardization.md"
    with md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 年齢構成の変化の影響を統制した結果\n\n")
        f.write(f"作成日時: {now_iso()}\n\n")
        f.write("固定年齢スケジュール法による。基準は2005-2009年度の幾何平均。\n")
        f.write(f"恒等式 Δln r = Δln SDR + Δln(E/P1569) の残差の絶対値の最大は "
                f"{worst:.3e} 対数ポイントであり、全 {len(rows)} 行で成立している。\n\n")
        f.write("**これは完全な間接標準化ではない。**"
                "年齢スケジュールを1年に固定しているため、"
                "年代別献血率そのものが期間内に変化した分は捉えられない。"
                "したがって「年齢構成の変化の影響を統制した」とは書けるが、"
                "**「年齢標準化を行った」とは書かない。**\n\n")

        f.write("## 1. 長期の結論（2024年度）\n\n")
        f.write("| 県 | 粗の Δln r | " + " | ".join(
            f"Δln SDR（組{s}）" for s in schedules) + " | 年齢構成効果（組A） |\n")
        f.write("|---|---:|" + "---:|" * (len(schedules) + 1) + "\n")
        for c, nm in ((FK, "福島県"), (MG, "宮城県"), (IW, "岩手県")):
            cells = [f"{g(schedules[0], 'dln_r', 2024, c):+.2f}"]
            cells += [f"**{g(s, 'dln_SDR', 2024, c):+.2f}**" for s in schedules]
            cells.append(f"{g(schedules[0], 'dln_age', 2024, c):+.2f}")
            f.write(f"| {nm} | " + " | ".join(cells) + " |\n")
        f.write("\n")
        pos = all(g(s, "dln_SDR", 2024, c) > 0 for s in schedules
                  for c in (FK, MG, IW))
        f.write(f"2024年度の被災3県の Δln SDR は"
                f"{'**すべての組で正のままである**' if pos else '**組により符号が変わる**'}。\n\n")

        f.write("## 2. 急性期（2011年度の福島県）\n\n")
        f.write("| 指標 | " + " | ".join(f"組{s}" for s in schedules) + " |\n")
        f.write("|---|" + "---:|" * len(schedules) + "\n")
        f.write("| 粗の Δln r | " + " | ".join(
            f"{g(s, 'dln_r', 2011, FK):+.2f}" for s in schedules) + " |\n")
        f.write("| Δln SDR | " + " | ".join(
            f"**{g(s, 'dln_SDR', 2011, FK):+.2f}**" for s in schedules) + " |\n")
        f.write("| 年齢構成効果 | " + " | ".join(
            f"{g(s, 'dln_age', 2011, FK):+.2f}" for s in schedules) + " |\n")
        f.write("| 差（SDR マイナス 粗） | " + " | ".join(
            f"{g(s, 'dln_SDR', 2011, FK) - g(s, 'dln_r', 2011, FK):+.2f}"
            for s in schedules) + " |\n\n")

        f.write("## 3. 福島と岩手の水準（2024年度の献血者数の指数）\n\n")
        f.write("粗ベースの指数は 福島 83.3、岩手 83.8 であった（幾何平均基準）。\n\n")
        f.write("年齢構成効果を取り除いた指数は次で定義される。\n\n")
        f.write("    調整後の指数 = exp( ( Δln D マイナス Δln(E/P1569) ) / 100 ) × 100\n\n")
        f.write("Δln D = Δln P + Δln s + Δln SDR + Δln(E/P1569) が成立するため、"
                "右辺から年齢構成効果を差し引くことで、"
                "15-69歳内部の構成が基準期のままであった場合の献血者数の指数が得られる。\n\n")
        f.write("| 県 | 粗ベースの指数 | " + " | ".join(
            f"調整後（組{s}）" for s in schedules) + " |\n")
        f.write("|---|---:|" + "---:|" * len(schedules) + "\n")
        for c, nm in ((FK, "福島県"), (IW, "岩手県"), (MG, "宮城県")):
            dD = dlnD_map[(2024, c)]
            cells = [f"{math.exp(dD / 100) * 100:.1f}"]
            cells += [f"**{math.exp((dD - g(s, 'dln_age', 2024, c)) / 100) * 100:.1f}**"
                      for s in schedules]
            f.write(f"| {nm} | " + " | ".join(cells) + " |\n")
        f.write("\n")
        gaps = []
        for s in schedules:
            a = math.exp((dlnD_map[(2024, FK)] - g(s, "dln_age", 2024, FK)) / 100) * 100
            b = math.exp((dlnD_map[(2024, IW)] - g(s, "dln_age", 2024, IW)) / 100) * 100
            gaps.append(abs(a - b))
        f.write(f"福島と岩手の差は、粗ベースで 0.5 指数ポイント、"
                f"調整後で {min(gaps):.1f} から {max(gaps):.1f} 指数ポイントである。\n\n")
        f.write("参考として、献血回数率 r および SDR そのものの指数も示す。"
                "これは献血者数の指数とは別の量である。\n\n")
        f.write("| 県 | r の指数 | " + " | ".join(
            f"SDR の指数（組{s}）" for s in schedules) + " |\n")
        f.write("|---|---:|" + "---:|" * len(schedules) + "\n")
        for c, nm in ((FK, "福島県"), (IW, "岩手県")):
            cells = [f"{math.exp(g(schedules[0], 'dln_r', 2024, c) / 100) * 100:.1f}"]
            cells += [f"{math.exp(g(s, 'dln_SDR', 2024, c) / 100) * 100:.1f}"
                      for s in schedules]
            f.write(f"| {nm} | " + " | ".join(cells) + " |\n")
        f.write("\n")

        f.write("## 4. 重みの選択に対する頑健性\n\n")
        f.write("| 比較 | 2024年度の Δln SDR の差の最大 | 2011年度の差の最大 |\n")
        f.write("|---|---:|---:|\n")
        for i in range(len(schedules)):
            for j in range(i + 1, len(schedules)):
                a, b = schedules[i], schedules[j]
                d24 = max(abs(g(a, "dln_SDR", 2024, p) - g(b, "dln_SDR", 2024, p))
                          for p in prefs)
                d11 = max(abs(g(a, "dln_SDR", 2011, p) - g(b, "dln_SDR", 2011, p))
                          for p in prefs)
                f.write(f"| 組{a} と 組{b} | {d24:.3f} | {d11:.3f} |\n")
        f.write("\n")

        f.write("## 5. 47都道府県における差の分布\n\n")
        f.write("Δln SDR と 粗の Δln r の差（すなわち年齢構成効果の符号を反転したもの）。\n\n")
        f.write("| 年度 | 組 | 中央値 | 四分位 | 絶対値の最大 |\n")
        f.write("|---|---|---:|---|---:|\n")
        for y in (2011, 2024):
            for s in schedules:
                dd = [g(s, "dln_SDR", y, p) - g(s, "dln_r", y, p) for p in prefs]
                q = stats.quantiles(dd, n=4)
                f.write(f"| {y} | {s} | {stats.median(dd):+.2f} | "
                        f"{q[0]:+.2f} から {q[2]:+.2f} | {max(abs(x) for x in dd):.2f} |\n")
        f.write("\n")

        f.write("## 6. 11-5 との整合\n\n")
        f.write("11-5 では young_share の対数変化と Δln r の47都道府県横断の順位相関が"
                "中央値 -0.12 と弱く、15-69歳内部の構成変化による混入は小さいと界定した。\n\n")
        dd24 = [g(schedules[0], "dln_SDR", 2024, p) - g(schedules[0], "dln_r", 2024, p)
                for p in prefs]
        f.write(f"本タスクの結果では、2024年度の差は中央値 {stats.median(dd24):+.2f} "
                f"対数ポイント、絶対値の最大 {max(abs(x) for x in dd24):.2f} である。\n\n")
        f.write("両者が整合するかは上記の数値から読み取れる。\n")

    print(f"書き出し: {md}")

    # ---------- コンソール ----------
    s0 = schedules[0]
    print(f"\n--- 2024年度 Δln SDR（粗の Δln r との対比） ---")
    for c, nm in ((FK, "福島県"), (MG, "宮城県"), (IW, "岩手県")):
        print(f"  {nm}: 粗 {g(s0,'dln_r',2024,c):+7.2f}  ->  " +
              "  ".join(f"組{s} {g(s,'dln_SDR',2024,c):+7.2f}" for s in schedules) +
              f"   年齢構成効果(組A) {g(s0,'dln_age',2024,c):+7.2f}")
    print(f"\n--- 2011年度 福島県 ---")
    print(f"  粗 {g(s0,'dln_r',2011,FK):+.2f}  ->  " +
          "  ".join(f"組{s} {g(s,'dln_SDR',2011,FK):+.2f}" for s in schedules))
    print(f"\n--- 2024年度の指数（r および SDR ベース） ---")
    for c, nm in ((FK, "福島県"), (IW, "岩手県")):
        print(f"  {nm}: 粗 {math.exp(g(s0,'dln_r',2024,c)/100)*100:.1f}  " +
              "  ".join(f"組{s} {math.exp(g(s,'dln_SDR',2024,c)/100)*100:.1f}"
                        for s in schedules))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
