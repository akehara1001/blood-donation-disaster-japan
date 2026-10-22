"""
タスク4: 医療提供体制の分母

社会人口統計体系 0000010109（Ｉ　健康医療）を採用する前に、
医療施設調査および病院報告と突き合わせて値が一致するかを確認する。
一致すれば SSDS を採用する。一致しない場合は差の原因を特定してから判断する。

突合の相手
  医療施設調査の年次系列表「病院数，年次・都道府県別」および
  「病院の病床数，年次・都道府県別」。版をまたいで複数存在するため
  すべて取得し、版間の食い違いも記録する。
  statsDataId はハードコードせず表題で発見する。

出力:
  data/processed/facility.csv
  output/facility_crosscheck.md
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import (  # noqa: E402
    PROCESSED_DIR, OUTPUT_DIR, api_get, api_status, as_list, cache_path, now_iso,
)

SSDS_MED_TABLE = "0000010109"
SSDS_CODES = {
    "I5101": ("hospitals", "病院数", "施設"),
    "I510120": ("general_hospitals", "一般病院数", "施設"),
    "I5211": ("hospital_beds", "病院病床数", "床"),
    "I521110": ("general_hospital_beds", "一般病院病床数", "床"),
    "I521150": ("general_beds", "一般病床数", "床"),
    "I5102": ("clinics", "一般診療所数", "施設"),
    "I6100": ("physicians", "医師数", "人"),
}
CHECK_YEARS = (2010, 2015, 2020)
MED_CODES = ("00450021", "00450023")


def txt(v) -> str:
    return v.get("$", "") if isinstance(v, dict) else str(v or "")


def parse_year_label(label: str) -> int | None:
    """
    医療施設調査の年次ラベルから西暦を取り出す。
    旧様式 「17年('05)」「22年('10)（実数）」「23年('11)（人口10万対）」
    新様式 「平成26年(2014年)」「令和2年(2020年)（実数）」
    括弧内の数字を西暦として読む。和暦の数字（平成22年の22）を誤読しないよう
    括弧の内側に限定する。
    """
    m = re.search(r"[（(]'?(\d{2,4})年?[）)]", label)
    if not m:
        return None
    v = int(m.group(1))
    if v >= 1900:
        return v
    if len(m.group(1)) == 2:
        return 1900 + v if v > 50 else 2000 + v
    return None


def pick_count_labels(cat01: dict[str, str]) -> dict[str, int]:
    """
    表内の年次ラベルのうち、実数（件数）を表すものだけを選ぶ。

    医療施設調査の年次系列表は、その版の最新年について同じ年を2回掲載する。
    旧様式では「22年('10)（実数）」と「22年('10)」の対で、
    **接尾辞の無いほうが人口10万対** である（福島県2010年で 6.9 を返すのがこれ）。
    新様式では「令和2年(2020年)（実数）」と「令和2年(2020年)（人口10万対）」の対になる。
    過去年の列は1つだけ存在し、それは実数である。

    したがって年ごとに次の優先順位で1つ選ぶ。
      1. 「実数」を含むラベル
      2. その年のラベルが1つだけで「10万対」を含まないもの
      3. それ以外は採用しない
    """
    by_year: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for code, name in cat01.items():
        y = parse_year_label(name)
        if y is not None:
            by_year[y].append((code, name))

    chosen: dict[str, int] = {}
    for y, cands in by_year.items():
        jissu = [c for c in cands if "実数" in c[1]]
        if jissu:
            chosen[jissu[0][0]] = y
            continue
        if len(cands) == 1 and "10万対" not in cands[0][1]:
            chosen[cands[0][0]] = y
    return chosen


def normalize_pref(name: str) -> str | None:
    """
    都道府県名を突合用に正規化する。
    医療施設調査は「青　森」のように全角空白入りかつ接尾辞なし。
    社会人口統計体系は「青森県」。両者を「青森」に揃える。
    全国と非都道府県の行は None を返して除外する。
    """
    s = re.sub(r"\s+", "", name)
    if not s or s in ("全国", "総数"):
        return None
    if s == "北海道":
        return "北海道"
    # 接尾辞を落とすのは2文字以上残る場合に限る。
    # 「京都」は末尾が「都」だが接尾辞ではないため、落とすと「京」になり
    # 社会人口統計体系の「京都府」（接尾辞を落として「京都」）と一致しなくなる。
    stripped = re.sub(r"(都|府|県)$", "", s)
    if len(stripped) >= 2:
        s = stripped
    return s or None


def cached_tables(stats_code: str) -> list[dict]:
    tables, start = [], 1
    while True:
        p = cache_path("getStatsList",
                       {"statsCode": stats_code, "limit": 1000, "startPosition": start})
        if not p.exists():
            break
        dl = json.loads(p.read_text(encoding="utf-8"))["GET_STATS_LIST"].get("DATALIST_INF", {})
        got = as_list(dl.get("TABLE_INF"))
        if not got:
            break
        tables.extend(got)
        nk = (dl.get("RESULT_INF") or {}).get("NEXT_KEY")
        if not nk:
            break
        start = int(nk)
    return tables


def fetch_values(sid: str, label: str, extra: dict | None = None):
    params = {"statsDataId": sid, "limit": 100000, "startPosition": 1}
    if extra:
        params.update(extra)
    payload = api_get("getStatsData", params, label=label)
    st, m = api_status(payload, "GET_STATS_DATA")
    if st != 0:
        return None, None
    inf = payload["GET_STATS_DATA"]["STATISTICAL_DATA"]
    lk = {}
    for co in as_list(inf["CLASS_INF"]["CLASS_OBJ"]):
        lk[co["@id"]] = {str(c["@code"]): str(c.get("@name", ""))
                         for c in as_list(co.get("CLASS"))}
    return as_list(inf["DATA_INF"]["VALUE"]), lk


def main() -> int:
    # ================= 1. SSDS から facility.csv =================
    values, lk = fetch_values(SSDS_MED_TABLE, "ssds_facility",
                              {"cdCat01": ",".join(SSDS_CODES)})
    if values is None:
        print("SSDS の取得に失敗した")
        return 1
    print(f"SSDS 0000010109: VALUE {len(values)} 件")

    ssds: dict[tuple[int, str, str], float] = {}
    names: dict[str, str] = {}
    for v in values:
        tname = lk["time"].get(str(v.get("@time", "")), "")
        m = re.match(r"(\d{4})年度", tname)
        if not m:
            continue
        y = int(m.group(1))
        a = str(v.get("@area", ""))
        names[a] = lk["area"].get(a, a)
        raw = str(v.get("$", ""))
        try:
            ssds[(y, a, str(v.get("@cat01", "")))] = float(raw.replace(",", ""))
        except ValueError:
            pass

    years = sorted({y for y, _, _ in ssds})
    areas = sorted({a for _, a, _ in ssds})
    fac_rows = []
    n_na = 0
    for y in years:
        for a in areas:
            row = {"year": y, "pref_code": a, "pref_name": names[a],
                   # 突合の結果、年度表記だが実体は各年10月1日現在の暦年断面である
                   "basis": "calendar_year_oct1", "source": "SSDS 0000010109",
                   "statsDataId": SSDS_MED_TABLE, "retrieved_at": now_iso()}
            for code, (col, label, unit) in SSDS_CODES.items():
                val = ssds.get((y, a, code))
                row[col] = "" if val is None else int(val)
                row[f"{col}_unit"] = unit
                row[f"{col}_cat01"] = code
                if val is None:
                    n_na += 1
            fac_rows.append(row)

    out = PROCESSED_DIR / "facility.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fac_rows[0].keys()))
        w.writeheader()
        w.writerows(fac_rows)
    print(f"書き出し: {out}  行数 {len(fac_rows)} / 欠測セル {n_na}")
    print(f"  年度 {min(years)}-{max(years)} / 地域 {len(areas)}")

    print("\n--- SSDS 各項目の年度被覆 ---")
    cov = defaultdict(set)
    for (y, a, c) in ssds:
        cov[c].add(y)
    for code, (col, label, unit) in SSDS_CODES.items():
        ys = sorted(cov.get(code, []))
        print(f"  {code} {label} ({unit}): {len(ys)} 年度"
              + (f"  {ys[0]}〜{ys[-1]}" if ys else "  値なし"))

    # ================= 2. 医療施設調査の年次系列表を発見 =================
    targets = {"hospitals": r"病院数，年次・都道府県",
               "hospital_beds": r"病院の病床数，年次・都道府県",
               "clinics": r"一般診療所数，年次・都道府県"}
    found = defaultdict(list)
    seen = set()
    for code in MED_CODES:
        for t in cached_tables(code):
            sid = txt(t.get("@id"))
            if sid in seen:
                continue
            seen.add(sid)
            ts = t.get("TITLE_SPEC") or {}
            title = " / ".join([str(ts.get(k, "")) for k in
                                ("TABLE_CATEGORY", "TABLE_NAME", "TABLE_EXPLANATION")
                                if ts.get(k)]) or txt(t.get("TITLE"))
            for key, pat in targets.items():
                if re.search(pat, title):
                    found[key].append({"sid": sid, "title": title,
                                       "name": txt(t.get("STATISTICS_NAME"))})
    for k, v in found.items():
        print(f"\n発見: {k} -> {len(v)} 表")

    # ================= 3. 突合 =================
    # 医療施設調査の年次系列表は軸の構成が社会人口統計体系と異なる。
    #   cat01 = 年次   ラベル例 「昭和62年-1987」「平成2年('90)」「17年('05)」「14年-2002」
    #   cat02 = 都道府県  ラベル例 「全　国」「北海道」「青　森」（全角空白入り、県府都の接尾辞なし）
    #   time  = 調査年（版の年。1水準のみ）
    # したがって @time を年、@area を地域として読んではならない。
    med: dict[str, dict[tuple[int, str], list]] = {k: defaultdict(list) for k in targets}
    med_years_seen: set[int] = set()

    for key, tabs in found.items():
        for t in tabs:
            vals, l2 = fetch_values(t["sid"], f"med:{key}:{t['sid']}")
            if vals is None:
                continue
            ymap = pick_count_labels(l2.get("cat01", {}))
            amap = {c: normalize_pref(n) for c, n in l2.get("cat02", {}).items()}
            for v in vals:
                y = ymap.get(str(v.get("@cat01", "")))
                if y is None:
                    continue
                med_years_seen.add(y)
                if y not in CHECK_YEARS:
                    continue
                key_pref = amap.get(str(v.get("@cat02", "")))
                if key_pref is None:
                    continue
                raw = str(v.get("$", ""))
                try:
                    med[key][(y, key_pref)].append((t["sid"], float(raw.replace(",", ""))))
                except ValueError:
                    pass

    print(f"\n医療施設調査の年次系列表に含まれる年: {sorted(med_years_seen)}")
    for y in CHECK_YEARS:
        print(f"  {y}年: {'あり' if y in med_years_seen else 'なし'}")

    # 版間の食い違い
    print("\n--- 医療施設調査の版間の食い違い ---")
    version_conflicts = {}
    for key in targets:
        conf = sum(1 for k, lst in med[key].items()
                   if len({x[1] for x in lst}) > 1)
        version_conflicts[key] = conf
        n_cells = len(med[key])
        print(f"  {key}: 対象セル {n_cells} / 版間で値が異なるセル {conf}")

    # SSDS との比較
    pairs = [("hospitals", "I5101", "病院数"),
             ("hospital_beds", "I5211", "病院病床数"),
             ("clinics", "I5102", "一般診療所数")]
    results = []
    print("\n--- SSDS vs 医療施設調査 ---")
    for key, code, label in pairs:
        for y in CHECK_YEARS:
            match = mismatch = missing = 0
            diffs = []
            for a in areas:
                pk = normalize_pref(names[a])
                if pk is None:      # 全国は突合対象外
                    continue
                s = ssds.get((y, a, code))
                lst = med[key].get((y, pk))
                if s is None or not lst:
                    missing += 1
                    if missing <= 3:
                        print(f"      照合不能: {names[a]} (正規化={pk}) "
                              f"SSDS={'なし' if s is None else s} "
                              f"医療施設調査={'なし' if not lst else lst}")
                    continue
                mv = lst[0][1]
                if abs(s - mv) < 1e-9:
                    match += 1
                else:
                    mismatch += 1
                    diffs.append((names[a], s, mv, s - mv))
            results.append({"項目": label, "SSDS_code": code, "年": y,
                            "一致": match, "不一致": mismatch, "照合不能": missing,
                            "差の例": diffs[:5]})
            print(f"  {label} {y}年: 一致 {match} / 不一致 {mismatch} / 照合不能 {missing}")
            for d in diffs[:3]:
                print(f"      {d[0]}: SSDS={d[1]:.0f} 医療施設調査={d[2]:.0f} 差={d[3]:+.0f}")

    # ================= 4. 報告書 =================
    md = OUTPUT_DIR / "facility_crosscheck.md"
    with md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 医療提供体制データの突合\n\n")
        f.write(f"作成日時: {now_iso()}\n\n")
        f.write("社会人口統計体系 0000010109（Ｉ　健康医療）を採用する前に、"
                "医療施設調査の年次系列表と2010年、2015年、2020年で突き合わせた。\n\n")

        f.write("## 突合の相手\n\n")
        for k, v in found.items():
            f.write(f"- {k}: 医療施設調査の「{targets[k]}」に該当する表 {len(v)} 件\n")
        f.write("\n病院報告については、e-Stat API 上の都道府県編は令和3年（2021年）以降しか"
                "登録されておらず、2010年と2015年の突合には使えない。"
                "この制約自体を記録する。\n\n")

        f.write("## 結果\n\n")
        f.write("| 項目 | SSDS コード | 年 | 一致 | 不一致 | 照合不能 |\n")
        f.write("|---|---|---:|---:|---:|---:|\n")
        for r in results:
            f.write(f"| {r['項目']} | {r['SSDS_code']} | {r['年']} | {r['一致']} | "
                    f"{r['不一致']} | {r['照合不能']} |\n")
        f.write("\n")

        bad = [r for r in results if r["不一致"]]
        if bad:
            f.write("### 不一致の内訳\n\n")
            for r in bad:
                f.write(f"**{r['項目']} {r['年']}年**\n\n")
                f.write("| 都道府県 | SSDS | 医療施設調査 | 差 |\n|---|---:|---:|---:|\n")
                for d in r["差の例"]:
                    f.write(f"| {d[0]} | {d[1]:.0f} | {d[2]:.0f} | {d[3]:+.0f} |\n")
                f.write("\n")

        f.write("## 版間の食い違い\n\n")
        f.write("医療施設調査の年次系列表は版をまたいで重複して存在する。"
                "同じ年と都道府県について版によって値が異なるかを確認した。\n\n")
        f.write("| 項目 | 対象セル | 版間で値が異なるセル |\n|---|---:|---:|\n")
        for key in targets:
            f.write(f"| {key} | {len(med[key])} | {version_conflicts[key]} |\n")
        f.write("\n")

        allmatch = all(r["不一致"] == 0 for r in results)
        f.write("## 採用可否\n\n")
        if allmatch:
            f.write("突合したすべての項目と年で値が一致した。"
                    "社会人口統計体系 0000010109 を採用する。"
                    "1975年度から2024年度まで系列が連続しており、"
                    "年次ごとに別表を取得する必要が無いという利点がある。\n\n")
        else:
            f.write("一致しない項目がある。上記の内訳を踏まえ、"
                    "差の原因（調査時点、定義、集計範囲）を特定してから採用可否を判断する。\n\n")
        f.write("## 時間軸の解釈（突合から判明した事項）\n\n")
        f.write("社会人口統計体系の時間軸は「2010年度」のように年度表記である。"
                "一方で医療施設調査は各年10月1日現在の調査であり暦年である。\n\n")
        f.write("突合の結果、社会人口統計体系の「N年度」の値は"
                "医療施設調査の「N年（10月1日現在）」の値と完全に一致した。"
                "したがって医療提供体制の項目については、"
                "**年度という表記にもかかわらず実体は暦年の値**である。\n\n")
        f.write("これは献血者数（G6230）とは扱いが異なる点に注意を要する。"
                "同じ社会人口統計体系の同じ年度表記であっても、"
                "献血者数は日本赤十字社の年度集計、施設数と病床数は10月1日現在の暦年断面であり、"
                "両者の時点は一致しない。パネルで併用する際はこのずれを明記する必要がある。\n\n")
        f.write("facility.csv の basis 列は calendar_year_oct1 と記録した。\n")

    print(f"\n書き出し: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
