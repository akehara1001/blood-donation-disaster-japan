"""
タスク6-1: パネル結合

47都道府県 × 2005年度から直近年度 の全組合せを骨格として先に生成し、
取得できた変数を左結合する。行は落とさない。

年度と暦年の対応（タスク2-3で確定した規則）
  既定  年度 t の献血者数には暦年 t の10月1日人口を対応させる。
        年度 t の中点が暦年 t の10月1日であることが理由。
  ただし選択を解析段階に残すため次の3系列をすべて持たせる。
        pop_*_oct1_year_t        （既定）
        pop_*_oct1_year_t_plus_1
        pop_*_oct1_mean_t_t1

未取得の変数は列だけ用意し値は NA のままにする。
  供給本数、使用量、献血量、製剤別内訳、献血種別、採血場所
  いずれも日本赤十字社の資料が必要であり本タスクでは投入しない。

出力: data/processed/panel.csv
      data/processed/panel_dictionary.csv
"""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROCESSED_DIR, now_iso  # noqa: E402

FY_MIN, FY_MAX = 2005, 2024
NATIONAL = "00000"


def read_csv(path: Path, skip_comments: bool = False) -> list[dict]:
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        if skip_comments:
            lines = [ln for ln in f if not ln.startswith("#")]
            return list(csv.DictReader(io.StringIO("".join(lines))))
        return list(csv.DictReader(f))


def main() -> int:
    donors = {(int(r["fiscal_year"]), r["pref_code"]): r
              for r in read_csv(PROCESSED_DIR / "donors.csv")}
    den = {(int(r["year"]), r["pref_code"]): r
           for r in read_csv(PROCESSED_DIR / "population_denominators.csv", True)}
    dec = {(int(r["fiscal_year"]), r["pref_code"]): r
           for r in read_csv(PROCESSED_DIR / "decomposition.csv")}
    fac = {(int(r["year"]), r["pref_code"]): r
           for r in read_csv(PROCESSED_DIR / "facility.csv")}

    # 復興庁「全国の避難者等の数」本文からの抽出値。
    # 本文が数値を挙げているのは福島、宮城、岩手の3県のみである。
    # 他の44県は公表資料に記載が無いため NA とする（ゼロではない）。
    EV_COL = {"07000": "outside_fukushima", "04000": "outside_miyagi",
              "03000": "outside_iwate"}
    ev: dict[tuple[int, str], dict] = {}
    for r in read_csv(PROCESSED_DIR / "evacuees_outside_prefecture.csv"):
        ev[(int(r["fiscal_year"]), r["series"])] = r

    prefs = sorted({p for _, p in donors if p != NATIONAL})
    names = {r["pref_code"]: r["pref_name"] for r in read_csv(PROCESSED_DIR / "donors.csv")}
    print(f"骨格: {len(prefs)} 都道府県 × {FY_MAX - FY_MIN + 1} 年度 "
          f"= {len(prefs) * (FY_MAX - FY_MIN + 1)} 行")

    # 未取得の変数（列だけ用意する）
    NA_COLS = [
        "donation_volume_liters",
        "donors_200ml", "donors_400ml", "donors_apheresis",
        "supply_units_rbc", "supply_units_platelet", "supply_units_plasma",
        "supply_units_total",
        "used_units_rbc", "used_units_platelet", "used_units_plasma",
        "used_units_total",
        "collection_site_room", "collection_site_mobile",
        "donors_age_10s", "donors_age_20s", "donors_age_30s",
        "donors_age_40s", "donors_age_50s", "donors_age_60s",
    ]

    rows = []
    n_donor_na = n_pop_na = n_fac_na = 0
    for p in prefs:
        for fy in range(FY_MIN, FY_MAX + 1):
            d = donors.get((fy, p))
            dn_t = den.get((fy, p))
            dn_t1 = den.get((fy + 1, p))
            dc = dec.get((fy, p))
            fc = fac.get((fy, p))

            def dv(rec, key, mult=1.0):
                if not rec or not rec.get(key):
                    return ""
                return str(float(rec[key]) * mult)

            pt = dv(dn_t, "pop_total", 1000)
            pt1 = dv(dn_t1, "pop_total", 1000)
            p69 = dv(dn_t, "pop_15_69", 1000)
            p69_1 = dv(dn_t1, "pop_15_69", 1000)

            def mean2(a, b):
                if a == "" or b == "":
                    return ""
                return str((float(a) + float(b)) / 2)

            row = {
                "fiscal_year": fy,
                "pref_code": p,
                "pref_name": names.get(p, p),
                # --- 献血（実値） ---
                "donors": d["donors"] if d else "",
                "donors_unit": "人",
                "donors_count_type": "延べ人数（実人数ではない）",
                "donors_basis": "年度（4月から翌年3月）",
                # --- 分母（3系列。既定は _year_t） ---
                "pop_total_oct1_year_t": pt,
                "pop_total_oct1_year_t_plus_1": pt1,
                "pop_total_mean_t_t1": mean2(pt, pt1),
                "pop_15_69_oct1_year_t": p69,
                "pop_15_69_oct1_year_t_plus_1": p69_1,
                "pop_15_69_mean_t_t1": mean2(p69, p69_1),
                "pop_65plus_oct1_year_t": dv(dn_t, "pop_65plus", 1000),
                "pop_unit": "人（人口推計の千人を1000倍して換算）",
                "pop_basis": dn_t["basis"] if dn_t else "",
                "pop_census_base": dn_t["基準"] if dn_t else "",
                # --- 分解（基準 2005-2009年度の幾何平均） ---
                "s_share_15_69": dc["s_share_15_69"] if dc else "",
                "r_donations_per_capita_15_69":
                    dc["r_donations_per_capita_15_69"] if dc else "",
                "dln_D": dc["dln_D"] if dc else "",
                "dln_P": dc["dln_P"] if dc else "",
                "dln_s": dc["dln_s"] if dc else "",
                "dln_r": dc["dln_r"] if dc else "",
                # --- 医療提供体制（暦年10月1日現在） ---
                "hospitals": fc["hospitals"] if fc else "",
                "general_hospitals": fc["general_hospitals"] if fc else "",
                "hospital_beds": fc["hospital_beds"] if fc else "",
                "general_hospital_beds": fc["general_hospital_beds"] if fc else "",
                "general_beds": fc["general_beds"] if fc else "",
                "clinics": fc["clinics"] if fc else "",
                "physicians": fc["physicians"] if fc else "",
                "facility_basis": fc["basis"] if fc else "",
                # --- 自県外避難者数（復興庁 PDF 本文からの抽出） ---
                "evacuees_outside_pref_mar11": (
                    ev.get((fy, "A_nearest_0311"), {}).get(EV_COL[p], "")
                    if p in EV_COL else ""),
                "evacuees_outside_pref_midyear": (
                    ev.get((fy, "B_midyear"), {}).get(EV_COL[p], "")
                    if p in EV_COL else ""),
                "evacuees_publish_date_mar11": (
                    ev.get((fy, "A_nearest_0311"), {}).get("publish_date", "")
                    if p in EV_COL else ""),
                "evacuees_publish_date_midyear": (
                    ev.get((fy, "B_midyear"), {}).get("publish_date", "")
                    if p in EV_COL else ""),
                "evacuees_note": (
                    "地方公共団体の報告にもとづく。自主避難者の捕捉漏れがあり"
                    "物理的不在者数の下限。補正しない。" if p in EV_COL
                    else "復興庁の公表本文が数値を挙げるのは福島、宮城、岩手のみ。"
                         "他県は記載が無いため NA（ゼロではない）。"),
                "retrieved_at": now_iso(),
            }
            for c in NA_COLS:
                row[c] = ""   # NA。日本赤十字社の資料が必要であり本タスクでは投入しない。
            rows.append(row)

            if row["donors"] == "":
                n_donor_na += 1
            if pt == "":
                n_pop_na += 1
            if row["hospitals"] == "":
                n_fac_na += 1

    out = PROCESSED_DIR / "panel.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n書き出し: {out}  行数 {len(rows)}")
    print(f"  donors 欠測: {n_donor_na}")
    print(f"  pop_total_oct1_year_t 欠測: {n_pop_na}")
    print(f"  hospitals 欠測: {n_fac_na}")
    n_t1 = sum(1 for r in rows if r["pop_total_oct1_year_t_plus_1"] == "")
    print(f"  pop_total_oct1_year_t_plus_1 欠測: {n_t1}"
          f"  （2024年度は2025年10月1日人口が未公表のため）")
    print(f"  NA 固定列: {len(NA_COLS)} 列 × {len(rows)} 行 = "
          f"{len(NA_COLS) * len(rows)} セルすべて NA")

    # ---------- 変数辞書 ----------
    dic = [
        ("fiscal_year", "年度", "2005-2024", "", "骨格"),
        ("pref_code", "都道府県コード", "47県", "", "骨格"),
        ("donors", "献血者数（延べ人数）", "2005-2024", "人",
         "SSDS 0000010107 cat01=G6230。原典は日本赤十字社。年度基準。"
         "**延べ人数であり実人数ではない。**実献血者数は別系列として"
         "厚生労働省 献血推進調査会資料に存在する（未取得）。"),
        ("r_donations_per_capita_15_69", "献血回数率", "2005-2024", "件/人",
         "延べ献血件数を15-69歳人口で割った値。**参加率ではない。**"
         "同一人物の頻回化でも上昇する。"),
        ("pop_total_oct1_year_t", "総人口（暦年 t の10月1日）", "2005-2024", "人",
         "**既定の分母**。人口推計。千人を1000倍して換算。"),
        ("pop_total_oct1_year_t_plus_1", "総人口（暦年 t+1 の10月1日）", "2005-2023", "人",
         "対照用。2024年度は未公表のため NA。"),
        ("pop_total_mean_t_t1", "総人口（t と t+1 の平均）", "2005-2023", "人",
         "年度中の平均に相当する近似。対照用。"),
        ("pop_15_69_oct1_year_t", "15-69歳人口（暦年 t の10月1日）", "2005-2024", "人",
         "献血可能年齢の近似。下限は16歳だが5歳階級の最小単位が15-19のため按分していない。"),
        ("pop_65plus_oct1_year_t", "65歳以上人口", "2005-2024", "人",
         "2005-2006年度は85歳以上が無く80歳以上で代用。"),
        ("dln_D", "献血者数の対数差", "2005-2024", "対数ポイント",
         "基準は2005-2009年度の幾何平均。dln_D = dln_P + dln_s + dln_r が厳密に成立。"),
        ("dln_P", "人口規模の寄与", "2005-2024", "対数ポイント", ""),
        ("dln_s", "年齢構成の寄与", "2005-2024", "対数ポイント",
         "15-69歳シェアの変化。15-69歳内部の高齢化は捉えられず dln_r に混入する。"),
        ("dln_r", "献血回数率の寄与（残差）", "2005-2024", "対数ポイント",
         "参加率ではなく献血回数率の変化。頻回化と参加者増を分離できない。"),
        ("evacuees_outside_pref_mar11", "自県外避難者数（3月11日近傍の公表）",
         "2011-2024", "人",
         "復興庁『全国の避難者等の数』本文からの抽出。福島、宮城、岩手のみ。"
         "物理的不在者数の**下限**。自主避難者の捕捉漏れがある。補正しない。"),
        ("evacuees_outside_pref_midyear", "自県外避難者数（年度中央の公表）",
         "2011-2024", "人", "同上。"),
        ("hospitals", "病院数", "2005-2023", "施設",
         "SSDS 0000010109 I5101。年度表記だが実体は各年10月1日現在の暦年。"
         "医療施設調査と2010年2015年2020年で47県全件一致。"),
        ("hospital_beds", "病院病床数", "2005-2023", "床", "SSDS I5211。同上。"),
        ("general_beds", "一般病床数", "2005-2023", "床", "SSDS I521150。1996年度以降。"),
        ("physicians", "医師数", "2005-2022", "人", "SSDS I6100。隔年。"),
    ] + [(c, "未取得", "なし", "", "日本赤十字社の資料が必要。本タスクでは投入していない。")
         for c in NA_COLS]

    outd = PROCESSED_DIR / "panel_dictionary.csv"
    with outd.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variable", "説明", "被覆年", "単位", "備考"])
        w.writerows(dic)
    print(f"書き出し: {outd} ({len(dic)} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
