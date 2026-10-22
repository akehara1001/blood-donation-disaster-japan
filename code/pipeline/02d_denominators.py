"""
タスク2-2: 分母の導出

population_age.csv から次を計算する。
  pop_total   総人口
  pop_15_69   15歳から69歳の合計
  pop_65plus  65歳以上

前提として先に検証すること
  1. 階級の単純合計が「総数」と一致するか（一致しなければ原因を記録し、断定しない）
  2. 平成17年基準表の 04017（80歳以上）と 04018（85歳以上）のどちらに実値があるか
     両方に値があるなら 04017 は合計から除外する（80-84 との二重計上を避けるため）

単位は e-Stat が返すとおり千人である。換算しない。unit 列に記録する。

出力: data/processed/population_denominators.csv
      output/population_reconciliation.csv （合計と総数の突合結果）
"""
from __future__ import annotations

import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROCESSED_DIR, OUTPUT_DIR, now_iso  # noqa: E402

HEADER_NOTE = (
    "# pop_15_69 は「15歳から69歳」の合計である。献血可能年齢の下限は16歳だが、"
    "人口推計の5歳階級の最小単位が 15-19 であるため 16-69 は構成できない。"
    "按分は行っていない。按分の是非は解析段階の選択として残す。\n"
    "# 単位は千人（e-Stat が返す単位のまま。換算していない）。\n"
)

AGE_15_69 = ["01004", "01005", "01006", "01007", "01008", "01009",
             "01010", "01011", "01012", "01013", "01014"]
AGE_65PLUS_FULL = ["01014", "01015", "01016", "01017", "04018"]
AGE_65PLUS_ALT = ["01014", "01015", "01016", "04017"]  # 80歳以上でしか取れない場合


def detail_codes_of(present: set[str]) -> list[str]:
    """
    そのセルで「明細」として合計してよい階級コードを決める。

    04017（80歳以上）は集計値とは限らない。
    平成17年基準表では 2005年と2006年に限り 01017（80-84歳）と 04018（85歳以上）が
    存在せず、04017 が最上位の明細階級として機能している。
    2007年以降は 01017 と 04018 に分割され、04017 は消える。
    したがって集計値かどうかはセルごとに判定する必要がある。
    """
    d = set(present) - {"01000"}          # 総数は常に集計値
    if "01017" in d and "04018" in d:     # 80-84 と 85+ が揃っていれば
        d.discard("04017")                # 80+ は集計値なので除く
    return sorted(d)


def main() -> int:
    src = PROCESSED_DIR / "population_age.csv"
    with io.open(src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"読み込み: {src} ({len(rows)} 行)")

    # 総人口 かつ 男女計 に限定
    sel = [r for r in rows if r["population_type"] == "総人口" and r["sex"] == "男女計"]
    print(f"  総人口 かつ 男女計: {len(sel)} 行")

    # (year, pref_code) -> {age_code: value}
    cube: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    meta: dict[tuple[int, str], dict[str, str]] = {}
    for r in sel:
        key = (int(r["year"]), r["pref_code"])
        if r["population"] != "":
            cube[key][r["age_band_code"]] = float(r["population"])
        meta[key] = {"pref_name": r["pref_name"], "unit": r["unit"],
                     "basis": r["basis"], "statsDataId": r["statsDataId"],
                     "基準": r["基準"]}

    # --- 検証1: 04017 / 04018 の実在 ---
    print("\n--- 検証1: 高齢階級コードの実在（表別） ---")
    by_table: dict[str, set[str]] = defaultdict(set)
    for r in sel:
        if r["population"] != "":
            by_table[r["statsDataId"]].add(r["age_band_code"])
    for sid, codes in sorted(by_table.items()):
        has17 = "04017" in codes
        has18 = "04018" in codes
        print(f"  {sid}: 04017(80歳以上)={'あり' if has17 else 'なし'} / "
              f"04018(85歳以上)={'あり' if has18 else 'なし'}  階級数={len(codes)}")

    # --- 検証2: 明細の合計と総数の突合 ---
    # 値の単位は千人であり、各階級が独立に丸められている。
    # したがって明細の単純合計は総数と数千人単位でずれうる。これは誤りではない。
    # 階級数 n に対する丸め誤差の理論上限 n*0.5 千人を許容幅とし、
    # これを超えるものだけを構造的不一致として扱う。
    print("\n--- 検証2: 明細階級の合計 vs 総数 ---")
    recon_rows = []
    n_exact = n_round = n_struct = 0
    for key in sorted(cube):
        year, pref = key
        d = cube[key]
        total_reported = d.get("01000")
        detail = detail_codes_of(set(d))
        sum_detail = sum(d[c] for c in detail)
        tol = 0.5 * len(detail)
        diff = None if total_reported is None else round(sum_detail - total_reported, 6)

        if diff is None:
            verdict = "総数なし"
        elif abs(diff) < 1e-9:
            verdict = "完全一致"
            n_exact += 1
        elif abs(diff) <= tol:
            verdict = "丸め誤差の範囲"
            n_round += 1
        else:
            verdict = "構造的不一致"
            n_struct += 1

        recon_rows.append({
            "year": year, "pref_code": pref,
            "pref_name": meta[key]["pref_name"],
            "総数": "" if total_reported is None else total_reported,
            "明細合計": sum_detail,
            "差": "" if diff is None else diff,
            "許容幅": tol,
            "判定": verdict,
            "明細階級数": len(detail),
            "明細階級": "+".join(detail),
            "unit": meta[key]["unit"],
            "statsDataId": meta[key]["statsDataId"],
        })
    print(f"  組合せ数 {len(recon_rows)}")
    print(f"    完全一致       {n_exact}")
    print(f"    丸め誤差の範囲 {n_round}  （単位が千人であることによる。誤りではない）")
    print(f"    構造的不一致   {n_struct}")
    if n_struct:
        print("  構造的不一致の例（最大20件）:")
        for r in [x for x in recon_rows if x["判定"] == "構造的不一致"][:20]:
            print(f"    {r['year']} {r['pref_name']}: 総数={r['総数']} "
                  f"明細合計={r['明細合計']} 差={r['差']} 許容={r['許容幅']}")
    maxdiff = max((abs(float(r["差"])) for r in recon_rows if r["差"] != ""), default=0)
    print(f"  差の絶対値の最大: {maxdiff} 千人")

    out_recon = OUTPUT_DIR / "population_reconciliation.csv"
    with out_recon.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recon_rows[0].keys()))
        w.writeheader()
        w.writerows(recon_rows)
    print(f"  書き出し: {out_recon}")

    # --- 分母の導出 ---
    den_rows = []
    n_na = 0
    for key in sorted(cube):
        year, pref = key
        d = cube[key]
        m = meta[key]

        def total_of(codes):
            present = [c for c in codes if c in d]
            if len(present) != len(codes):
                return None, present
            return sum(d[c] for c in present), present

        pop_total = d.get("01000")
        p1569, c1569 = total_of(AGE_15_69)
        p65, c65 = total_of(AGE_65PLUS_FULL)
        used65 = AGE_65PLUS_FULL
        if p65 is None:
            p65, c65 = total_of(AGE_65PLUS_ALT)
            used65 = AGE_65PLUS_ALT

        if pop_total is None or p1569 is None or p65 is None:
            n_na += 1

        den_rows.append({
            "year": year,
            "pref_code": pref,
            "pref_name": m["pref_name"],
            "pop_total": "" if pop_total is None else pop_total,
            "pop_15_69": "" if p1569 is None else p1569,
            "pop_65plus": "" if p65 is None else p65,
            "unit": m["unit"],
            "basis": m["basis"],
            "基準": m["基準"],
            "components_pop_total": "01000(総数)",
            "components_pop_15_69": "+".join(c1569),
            "components_pop_65plus": "+".join(c65),
            "note_65plus": ("85歳以上まで明細あり" if used65 is AGE_65PLUS_FULL
                            else "85歳以上が無く80歳以上で代用"),
            "statsDataId": m["statsDataId"],
            "retrieved_at": now_iso(),
        })

    out = PROCESSED_DIR / "population_denominators.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        f.write(HEADER_NOTE)
        w = csv.DictWriter(f, fieldnames=list(den_rows[0].keys()))
        w.writeheader()
        w.writerows(den_rows)
    print(f"\n書き出し: {out}")
    print(f"  行数 {len(den_rows)} / いずれかが NA の行 {n_na}")

    note_kinds = defaultdict(int)
    for r in den_rows:
        note_kinds[r["note_65plus"]] += 1
    for k, v in note_kinds.items():
        print(f"  note_65plus '{k}': {v} 行")

    # 参考表示
    print("\n--- 福島県の分母（単位: 千人） ---")
    print(f"  {'年':<6}{'pop_total':>12}{'pop_15_69':>12}{'pop_65plus':>12}  basis")
    for r in den_rows:
        if r["pref_code"] == "07000":
            print(f"  {r['year']:<6}{r['pop_total']:>12}{r['pop_15_69']:>12}"
                  f"{r['pop_65plus']:>12}  {r['basis']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
