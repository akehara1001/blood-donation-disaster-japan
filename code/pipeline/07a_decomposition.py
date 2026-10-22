"""
タスク7-1: 献血者数の3成分分解

  D = P * s * r        （恒等式。統計モデルではない）
    P     総人口
    s     P1569 / P          年齢構成
    r     D / P1569          献血強度
  ln D = ln P + ln s + ln r  （完全に加法的）

r の意味について（確定事項）

  D（G6230_献血者数）は**延べ人数**である。厚生労働省 薬事食品衛生審議会
  血液事業部会 献血推進調査会の参考資料「献血の現状」（日本赤十字社提出資料）に
  「実献血者数」が別系列として掲載されていることが根拠である。

  したがって r = D / P1569 は**献血回数率**であって参加率ではない。
  同一人物が年に複数回献血すれば r は上昇する。
  r の上昇を「献血に参加する住民が増えた」と読んではならない。
  献血者の増加か同一献血者の頻回化かを分離するには、
  年代別平均献血回数と実献血者数が必要である（未取得）。

基準の取り方について（重要）

  基準は 2005-2009年度である。ただし基準値に算術平均を使うと分解は厳密に成立しない。
  算術平均は積を保存しないため mean(D) != mean(P)*mean(s)*mean(r) となるからである。

  対数の平均、すなわち幾何平均を基準にすると
      geomean(D) = geomean(P) * geomean(s) * geomean(r)
  が厳密に成立し、dln_D = dln_P + dln_s + dln_r が誤差なしで閉じる。

  したがって本スクリプトの基準は 2005-2009年度の幾何平均である。
  recovery_by_pref.md の指数は算術平均基準なので、対照できるよう
  算術平均基準の指数も index_arith_base 列に併記し、両者の差も出力する。

単位の扱い
  人口推計の単位は千人である。P と P1569 は1000倍して人に換算した。
  s は比率のため単位に依存しない。r は 人 / 人 である。
  換算は単位の統一であって値の生成ではない。

出力: data/processed/decomposition.csv
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
from estat_client import PROCESSED_DIR, now_iso  # noqa: E402

BASE_YEARS = list(range(2005, 2010))
NATIONAL = "00000"
TOL_IDENTITY = 1e-6   # D = P*s*r の相対許容
TOL_ADDITIVE = 1e-9   # dln_D = dln_P+dln_s+dln_r の許容（対数ポイント）


def main() -> int:
    # ---------- 読み込み ----------
    with io.open(PROCESSED_DIR / "donors.csv", encoding="utf-8-sig", newline="") as f:
        donors = {(int(r["fiscal_year"]), r["pref_code"]): float(r["donors"])
                  for r in csv.DictReader(f) if r["donors"]}

    with io.open(PROCESSED_DIR / "population_denominators.csv",
                 encoding="utf-8", newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    den = list(csv.DictReader(io.StringIO("".join(lines))))

    P: dict[tuple[int, str], float] = {}
    P1569: dict[tuple[int, str], float] = {}
    names: dict[str, str] = {}
    for r in den:
        k = (int(r["year"]), r["pref_code"])
        if r["pop_total"]:
            P[k] = float(r["pop_total"]) * 1000.0      # 千人 -> 人
        if r["pop_15_69"]:
            P1569[k] = float(r["pop_15_69"]) * 1000.0  # 千人 -> 人
        names[r["pref_code"]] = r["pref_name"]

    keys = sorted(set(donors) & set(P) & set(P1569))
    years = sorted({y for y, _ in keys})
    prefs = sorted({p for _, p in keys})
    print(f"照合できたセル: {len(keys)}  年度 {years[0]}-{years[-1]}  地域 {len(prefs)}")
    print(f"  献血 {len(donors)} / 総人口 {len(P)} / 15-69歳 {len(P1569)}")

    # ---------- 検算1: D = P * s * r ----------
    worst = 0.0
    worst_key = None
    n_bad = 0
    for k in keys:
        d, p, p69 = donors[k], P[k], P1569[k]
        s = p69 / p
        r = d / p69
        recomposed = p * s * r
        rel = abs(recomposed - d) / d if d else 0.0
        if rel > worst:
            worst, worst_key = rel, k
        if rel > TOL_IDENTITY:
            n_bad += 1
    print(f"\n--- 検算1: D = P * s * r （全 {len(keys)} セル） ---")
    print(f"  相対誤差の最大: {worst:.3e}  （{worst_key}）")
    print(f"  許容 {TOL_IDENTITY:.0e} を超えたセル: {n_bad}")
    if n_bad:
        print("  恒等式が成立しないセルがある。処理を中止する。")
        return 1

    # ---------- 分解 ----------
    rows = []
    n_add_bad = 0
    worst_add = 0.0
    for pref in prefs:
        yrs = [y for y in years if (y, pref) in donors]
        base_ok = all((y, pref) in donors for y in BASE_YEARS)
        if not base_ok:
            print(f"  警告: {pref} は基準年が揃わないため分解しない")
            continue

        lnD = {y: math.log(donors[(y, pref)]) for y in yrs}
        lnP = {y: math.log(P[(y, pref)]) for y in yrs}
        lns = {y: math.log(P1569[(y, pref)] / P[(y, pref)]) for y in yrs}
        lnr = {y: math.log(donors[(y, pref)] / P1569[(y, pref)]) for y in yrs}

        bD = stats.mean(lnD[y] for y in BASE_YEARS)   # = ln(幾何平均)
        bP = stats.mean(lnP[y] for y in BASE_YEARS)
        bs = stats.mean(lns[y] for y in BASE_YEARS)
        br = stats.mean(lnr[y] for y in BASE_YEARS)

        arith_base_D = stats.mean(donors[(y, pref)] for y in BASE_YEARS)

        for y in yrs:
            dD = (lnD[y] - bD) * 100
            dP = (lnP[y] - bP) * 100
            ds = (lns[y] - bs) * 100
            dr = (lnr[y] - br) * 100
            resid = dD - (dP + ds + dr)
            if abs(resid) > worst_add:
                worst_add = abs(resid)
            if abs(resid) > TOL_ADDITIVE:
                n_add_bad += 1
            rows.append({
                "pref_code": pref,
                "pref_name": names[pref],
                "fiscal_year": y,
                "D_donors": int(donors[(y, pref)]),
                "D_count_type": "延べ人数",
                "P_persons": int(P[(y, pref)]),
                "P1569_persons": int(P1569[(y, pref)]),
                "s_share_15_69": round(P1569[(y, pref)] / P[(y, pref)], 12),
                # 延べ献血件数 / 15-69歳人口。参加率ではなく献血回数率である。
                "r_donations_per_capita_15_69": round(
                    donors[(y, pref)] / P1569[(y, pref)], 12),
                "dln_D": round(dD, 10),
                "dln_P": round(dP, 10),
                "dln_s": round(ds, 10),
                "dln_r": round(dr, 10),
                "additive_residual": round(resid, 10),
                "index_geo_base": round(math.exp(lnD[y] - bD) * 100, 3),
                "index_arith_base": round(donors[(y, pref)] / arith_base_D * 100, 3),
                "base": "2005-2009年度の幾何平均",
                "unit_note": "P と P1569 は千人を1000倍して人に換算",
                "retrieved_at": now_iso(),
            })

    print(f"\n--- 検算2: dln_D = dln_P + dln_s + dln_r （全 {len(rows)} 行） ---")
    print(f"  残差の絶対値の最大: {worst_add:.3e} 対数ポイント")
    print(f"  許容 {TOL_ADDITIVE:.0e} を超えた行: {n_add_bad}")
    if n_add_bad:
        print("  加法性が成立しない行がある。処理を中止する。")
        return 1

    out = PROCESSED_DIR / "decomposition.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n書き出し: {out}  行数 {len(rows)} / 欠測 0")

    # 幾何平均基準と算術平均基準の差
    gaps = [abs(r["index_geo_base"] - r["index_arith_base"]) for r in rows]
    print(f"  指数の基準差（幾何 vs 算術）: 最大 {max(gaps):.3f} ポイント / "
          f"中央値 {stats.median(gaps):.3f} ポイント")

    # 福島の内訳を表示
    print("\n--- 福島県の3成分（対数ポイント、基準 2005-2009年度） ---")
    print(f"  {'年度':<7}{'dln_D':>9}{'dln_P':>9}{'dln_s':>9}{'dln_r':>9}   検算")
    for r in rows:
        if r["pref_code"] == "07000":
            print(f"  {r['fiscal_year']:<7}{r['dln_D']:>9.2f}{r['dln_P']:>9.2f}"
                  f"{r['dln_s']:>9.2f}{r['dln_r']:>9.2f}   {r['additive_residual']:+.1e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
