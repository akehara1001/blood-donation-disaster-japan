"""
反事実の参照集を2通りで算出する。

  基準1（主表）  当該イベントの非被災県の中央値
  基準2（感度）  47都道府県の中央値（処理群を含む。効果を保守的に評価する）

47県基準は誤りではない。処理群を中央値の構成に含めることは効果を
小さめに評価する方向に働くため保守的である。
原稿内で参照集が3種類（47、41、43）混在していた点だけを解消する。

中間曝露県（茨城、千葉、青森）は比較対象であって処理群ではないため
非被災県の集合に含める。これらも除いた41県基準を追加の感度として併記する。

出力: data/processed/event_counterfactual.csv
      output/counterfactual_revision.md
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

FK, MG, IW = "07000", "04000", "03000"
KM, HK, IS, NG = "43000", "01000", "17000", "15000"
IB, CB, AM = "08000", "12000", "02000"
OK, HS, EH = "33000", "34000", "38000"

# event, 被災県（参照集から除く）, 追加で除く県（41県感度）, 発生月
EVENTS = {
    "Great East Japan Earthquake": ([FK, MG, IW], [IB, CB, AM], 3, 2010),
    "Kumamoto Earthquake": ([KM], [], 4, 2016),
    "Hokkaido Iburi Earthquake": ([HK], [], 9, 2018),
    "Noto Peninsula Earthquake": ([IS], [], 1, 2023),
    "Niigata Chuetsu-oki Earthquake": ([NG], [], 7, 2007),
    "July 2018 heavy rain": ([OK, HS, EH], [], 7, 2018),
}
# 各県がどのイベントに属するか（中間曝露を含む）
MEMBER = {
    FK: "Great East Japan Earthquake", MG: "Great East Japan Earthquake",
    IW: "Great East Japan Earthquake", IB: "Great East Japan Earthquake",
    CB: "Great East Japan Earthquake", AM: "Great East Japan Earthquake",
    KM: "Kumamoto Earthquake", HK: "Hokkaido Iburi Earthquake",
    IS: "Noto Peninsula Earthquake", NG: "Niigata Chuetsu-oki Earthquake",
    OK: "July 2018 heavy rain", HS: "July 2018 heavy rain",
    EH: "July 2018 heavy rain",
}
EN = {FK: "Fukushima", MG: "Miyagi", IW: "Iwate", KM: "Kumamoto",
      HK: "Hokkaido", IS: "Ishikawa", NG: "Niigata", IB: "Ibaraki",
      CB: "Chiba", AM: "Aomori", OK: "Okayama", HS: "Hiroshima", EH: "Ehime"}
CORE = {FK, MG, IW, KM}          # 大規模地震の被災4県
MIDDLE = {IB, CB, AM}
RAIN = {OK, HS, EH}
SMALL = {HK, IS, NG}


def acute_rel(month: int) -> int:
    return 0 if 4 <= month <= 12 else 1


def read_csv(p: Path):
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
        return list(csv.DictReader(io.StringIO("".join(lines))))


def main() -> int:
    dec = read_csv(PROCESSED_DIR / "decomposition.csv")
    dlnr = {(int(r["fiscal_year"]), r["pref_code"]): float(r["dln_r"]) for r in dec}
    years = sorted({y for y, _ in dlnr})
    prefs = sorted({p for _, p in dlnr if p != NATIONAL})

    yoy = {(y, p): dlnr[(y, p)] - dlnr[(y - 1, p)]
           for p in prefs for y in years if (y - 1, p) in dlnr}

    def med(y, exclude):
        v = [yoy[(y, p)] for p in prefs
             if p not in exclude and (y, p) in yoy]
        return stats.median(v) if v else None

    BASES = {
        "non_affected": lambda ev: set(EVENTS[ev][0]),
        "all47": lambda ev: set(),
        "non_affected_strict": lambda ev: set(EVENTS[ev][0]) | set(EVENTS[ev][1]),
    }

    rows = []
    for code, ev in MEMBER.items():
        aff, extra, month, efy = EVENTS[ev]
        ar = acute_rel(month)
        ay = efy + ar
        for bname, excl_fn in BASES.items():
            excl = excl_fn(ev)
            if (ay, code) not in yoy:
                continue
            m = med(ay, excl)
            d = yoy[(ay, code)] - m
            pre = [yoy[(y, code)] - med(y, excl)
                   for y in range(efy - 5, efy)
                   if (y, code) in yoy and med(y, excl) is not None]
            sd = stats.pstdev(pre) if len(pre) > 1 else None
            z = ((d - stats.mean(pre)) / sd) if sd else None
            n_ref = len([p for p in prefs if p not in excl])
            rows.append({
                "event": ev, "pref_code": code, "pref_name_en": EN[code],
                "group": ("core" if code in CORE else
                          "intermediate" if code in MIDDLE else
                          "rain" if code in RAIN else "small"),
                "basis": bname, "n_reference": n_ref,
                "event_fiscal_year": efy, "acute_fiscal_year": ay,
                "yoy_dln_r": round(yoy[(ay, code)], 10),
                "median_reference": round(m, 10),
                "diff_from_median": round(d, 10),
                "pre_n": len(pre),
                "pre_min": round(min(pre), 10) if pre else "",
                "pre_mean": round(stats.mean(pre), 10) if pre else "",
                "pre_sd": round(sd, 10) if sd else "",
                "below_pre_min": ("yes" if pre and d < min(pre) else "no"),
                "standardized_vs_pre": round(z, 10) if z is not None else "",
            })

    out = PROCESSED_DIR / "event_counterfactual.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("# 反事実の参照集を2通り（+strict 感度）で算出したもの。\n")
        f.write("# non_affected = 当該イベントの被災県を除く中央値（主表）\n")
        f.write("# all47 = 47都道府県の中央値（処理群を含む。保守的）\n")
        f.write("# non_affected_strict = 中間曝露県も除く（東日本のみ 41県）\n")
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"書き出し: {out} ({len(rows)} 行)")

    def get(code, basis):
        return next(r for r in rows if r["pref_code"] == code
                    and r["basis"] == basis)

    # -------- 1-4 の3点を検証 --------
    print("\n--- 1-4 の確認 ---")
    checks = []

    for basis in ("non_affected", "all47"):
        below_core = [EN[c] for c in CORE if get(c, basis)["below_pre_min"] == "yes"]
        below_other = [EN[c] for c in list(MIDDLE) + list(RAIN) + list(SMALL)
                       if get(c, basis)["below_pre_min"] == "yes"]
        ok = len(below_core) == 4 and len(below_other) == 0
        checks.append((f"不連続性（{basis}）", ok,
                       f"大規模4県のうち下回る {len(below_core)}/4、"
                       f"他9県のうち下回る {len(below_other)}/9"))
        print(f"  [{'OK' if ok else '**NG**'}] 不連続性 {basis}: "
              f"大規模 {len(below_core)}/4 / 他 {len(below_other)}/9"
              + (f"  他で下回る: {below_other}" if below_other else ""))

    for basis in ("non_affected", "all47"):
        km = get(KM, basis)["diff_from_median"]
        fk = get(FK, basis)["diff_from_median"]
        ratio = abs(km / fk)
        ok = 0.4 <= ratio <= 1.6
        checks.append((f"熊本が福島と同規模（{basis}）", ok,
                       f"熊本 {km:+.2f} / 福島 {fk:+.2f} / 比 {ratio:.2f}"))
        print(f"  [{'OK' if ok else '**NG**'}] 熊本と福島の規模 {basis}: "
              f"熊本 {km:+.2f} 対 福島 {fk:+.2f}（比 {ratio:.2f}）")

    # 5尺度の順序（非被災県基準で再計算）
    tab2 = read_csv(OUTPUT_DIR / "figures" / "tab2_scale_sensitivity.csv")
    jp2en = {"福島県": FK, "宮城県": MG, "岩手県": IW, "熊本県": KM}
    scales = {}
    for r in tab2:
        c = jp2en[r["pref_name"]]
        if c == KM:
            continue
        scales.setdefault("cumulative", {})[c] = float(r["scale1_cumulative_dln_r"])
        scales.setdefault("percentile", {})[c] = float(r["scale2_percentile"])
    for basis in ("non_affected", "all47"):
        scales[f"yoy_diff_{basis}"] = {c: get(c, basis)["diff_from_median"]
                                       for c in (FK, MG, IW)}
        scales[f"std_{basis}"] = {c: get(c, basis)["standardized_vs_pre"]
                                  for c in (FK, MG, IW)}
    orders = {}
    for k, v in scales.items():
        orders[k] = [EN[c] for c in sorted(v, key=lambda x: v[x])]
    uniq = {tuple(o) for o in orders.values()}
    ok = len(uniq) > 1
    checks.append(("5尺度で順序が一致しない", ok,
                   f"{len(orders)} 尺度で {len(uniq)} 通りの順序"))
    print(f"  [{'OK' if ok else '**NG**'}] 尺度による順序の不一致: "
          f"{len(orders)} 尺度で {len(uniq)} 通り")
    for k, o in orders.items():
        print(f"        {k:<26} {' → '.join(o)}")

    n_ng = sum(1 for _, ok_, _ in checks if not ok_)

    # -------- 対照表 --------
    md = OUTPUT_DIR / "counterfactual_revision.md"
    with md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 反事実の参照集の統一\n\n")
        f.write(f"作成日時: {now_iso()}\n\n")
        f.write("## 何を変えたか\n\n")
        f.write("**47県基準は誤りではない。** 処理群を中央値の構成に含めることは、"
                "効果を小さめに評価する方向に働くため保守的である。\n\n")
        f.write("修正したのは、原稿内で参照集が3種類（主解析47県、中間曝露の比較41県、"
                "豪雨の比較43県）に分かれていた不整合である。\n\n")
        f.write("| イベント | 被災県（参照集から除外） | 参照集 |\n|---|---|---:|\n")
        for ev, (aff, extra, month, efy) in EVENTS.items():
            f.write(f"| {ev} | {', '.join(EN[c] for c in aff)} | "
                    f"{47 - len(aff)}県 |\n")
        f.write("\n中間曝露県（Ibaraki、Chiba、Aomori）は比較対象であって処理群ではないため"
                "除外しない。これらも除いた41県基準を追加の感度として併記する。\n\n")

        f.write("## 主要数値の対照\n\n")
        f.write("| 県 | 群 | 急性期 | 非被災県基準（主表） | 47県基準（感度） | 変化量 |\n")
        f.write("|---|---|---|---:|---:|---:|\n")
        for code in [FK, MG, IW, KM, IB, CB, AM, OK, HS, EH, HK, IS, NG]:
            a = get(code, "non_affected")
            b = get(code, "all47")
            f.write(f"| {EN[code]} | {a['group']} | FY{a['acute_fiscal_year']} | "
                    f"{a['diff_from_median']:+.2f} | {b['diff_from_median']:+.2f} | "
                    f"{a['diff_from_median'] - b['diff_from_median']:+.2f} |\n")
        f.write("\n非被災県基準では、被災県を中央値の構成から外すため"
                "乖離の絶対値は大きくなる方向に動く。\n\n")

        f.write("## 事前標準化値の対照\n\n")
        f.write("| 県 | 非被災県基準 | 47県基準 | 事前最小を下回る（非被災） | "
                "同（47県） |\n|---|---:|---:|---|---|\n")
        for code in [FK, MG, IW, KM, IB, CB, AM, OK, HS, EH, HK, IS, NG]:
            a, b = get(code, "non_affected"), get(code, "all47")
            f.write(f"| {EN[code]} | "
                    f"{a['standardized_vs_pre'] if a['standardized_vs_pre'] != '' else '—'} | "
                    f"{b['standardized_vs_pre'] if b['standardized_vs_pre'] != '' else '—'} | "
                    f"{a['below_pre_min']} | {b['below_pre_min']} |\n")
        f.write("\n")

        f.write("## 41県基準（中間曝露も除く）の感度\n\n")
        f.write("| 県 | 44県基準 | 41県基準 | 差 |\n|---|---:|---:|---:|\n")
        for code in [FK, MG, IW, IB, CB, AM]:
            a = get(code, "non_affected")
            c = get(code, "non_affected_strict")
            f.write(f"| {EN[code]} | {a['diff_from_median']:+.2f} | "
                    f"{c['diff_from_median']:+.2f} | "
                    f"{c['diff_from_median'] - a['diff_from_median']:+.2f} |\n")
        f.write("\n")

        f.write("## 結論の維持（1-4 の確認）\n\n")
        f.write("| 確認項目 | 判定 | 内容 |\n|---|---|---|\n")
        for nm, ok_, detail in checks:
            f.write(f"| {nm} | {'維持' if ok_ else '**維持されない**'} | {detail} |\n")
        f.write("\n### 尺度による順序\n\n")
        for k, o in orders.items():
            f.write(f"- {k}: {' → '.join(o)}（極端な順）\n")
        f.write(f"\n**{len(uniq)} 通りの順序が現れる。**"
                "尺度の選択により最も極端な県が変わるという所見は維持される。\n\n")
        f.write(f"**維持されない項目: {n_ng} 件**\n")

    print(f"\n書き出し: {md}")
    print(f"維持されない項目: {n_ng} 件")
    return 1 if n_ng else 0


if __name__ == "__main__":
    raise SystemExit(main())
