"""
タスク2-1: 年齢階級別人口の取得

人口推計「都道府県，年齢（5歳階級），男女別人口」を 2005年から直近年まで取得する。
人口推計は国勢調査のたびに基準が切り替わるため、基準ごとの4表を結合する。

statsDataId はハードコードせず発見規則で選ぶ（02b と同一規則）。

注意点として実装に反映したこと:
  1. 年齢階級には集計値が混在する。
     01000 = 総数
     04017 = 80歳以上   （平成17年基準表にのみ存在）
     04018 = 85歳以上
     平成17年基準表は 04017 と 04018 の両方を持つため、
     全階級を単純合計すると 80-84歳 が二重計上される。
     is_aggregate 列で明示的に区別し、合計には detail のみを使う。
  2. 平成27年基準表と令和2年基準表には cat03（総人口 / 日本人人口）がある。
     総人口 のみを採用し、日本人人口 は population_type 列で区別して保持する。
  3. 単位（人 / 千人）は表ごとに異なりうる。勝手に換算せず、
     API が返す単位をそのまま unit 列に記録する。
  4. basis は国勢調査年（2005, 2010, 2015, 2020）を census、それ以外を estimate とする。
     各基準表の初年度が当該国勢調査年にあたる。

出力: data/processed/population_age.csv
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

STATS_CODE = "00200524"
YEAR_MIN, YEAR_MAX = 2005, 9999
CENSUS_YEARS = {1995, 2000, 2005, 2010, 2015, 2020}

# 集計値（合計してはならない階級コード）
AGGREGATE_AGE_CODES = {"01000", "04017"}


def txt(v) -> str:
    return v.get("$", "") if isinstance(v, dict) else str(v or "")


def load_cached_tables() -> list[dict]:
    tables, start = [], 1
    while True:
        p = cache_path("getStatsList",
                       {"statsCode": STATS_CODE, "limit": 1000, "startPosition": start})
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


def discover() -> list[dict]:
    seen, out = set(), []
    for t in load_cached_tables():
        sid = txt(t.get("@id"))
        if sid in seen:
            continue
        name = txt(t.get("STATISTICS_NAME"))
        ts = t.get("TITLE_SPEC") or {}
        title = " / ".join([str(ts.get(k, "")) for k in
                            ("TABLE_CATEGORY", "TABLE_NAME", "TABLE_EXPLANATION")
                            if ts.get(k)]) or txt(t.get("TITLE"))
        if ("各年10月1日現在人口" in name and "国勢調査基準" in name and "統計表" in name
                and "都道府県" in title and "男女別人口" in title
                and re.search(r"年齢[（(]\s*[5５]\s*歳階級", title)):
            seen.add(sid)
            m = re.search(r"(平成\d+年|令和\d+年|平成７年)国勢調査基準", name)
            out.append({"statsDataId": sid, "基準": m.group(1) if m else "", "表題": title})
    return out


def fetch_values(sid: str) -> tuple[list[dict], dict, str]:
    """getStatsData を全ページ取得し、(VALUE, コード名称対応, 単位) を返す。"""
    values, lookup, start = [], {}, 1
    unit = ""
    while True:
        payload = api_get("getStatsData",
                          {"statsDataId": sid, "limit": 100000, "startPosition": start},
                          label=f"pop:{sid}")
        st, m = api_status(payload, "GET_STATS_DATA")
        if st != 0:
            print(f"    STATUS={st}: {m}")
            break
        inf = payload["GET_STATS_DATA"]["STATISTICAL_DATA"]
        if not lookup:
            for co in as_list(inf["CLASS_INF"]["CLASS_OBJ"]):
                lookup[co["@id"]] = {
                    str(c["@code"]): {"name": str(c.get("@name", "")),
                                      "unit": str(c.get("@unit", ""))}
                    for c in as_list(co.get("CLASS"))
                }
            tabs = lookup.get("tab", {})
            unit = next((v["unit"] for v in tabs.values() if v["unit"]), "")
        got = as_list(inf["DATA_INF"]["VALUE"])
        values.extend(got)
        ri = inf.get("RESULT_INF", {})
        nk = ri.get("NEXT_KEY")
        if not nk:
            break
        start = int(nk)
    return values, lookup, unit


def main() -> int:
    cands = discover()
    print(f"発見した表: {len(cands)} 件")

    rows: list[dict] = []
    units_seen: set[str] = set()
    per_table_counts = []

    for c in cands:
        sid = c["statsDataId"]
        values, lookup, unit = fetch_values(sid)
        if not values:
            continue

        time_names = {k: v["name"] for k, v in lookup.get("time", {}).items()}
        area_names = {k: v["name"] for k, v in lookup.get("area", {}).items()}
        sex_names = {k: v["name"] for k, v in lookup.get("cat01", {}).items()}
        age_names = {k: v["name"] for k, v in lookup.get("cat02", {}).items()}
        pop_names = {k: v["name"] for k, v in lookup.get("cat03", {}).items()}
        # 値側に @unit が来る場合もある
        for v in values[:50]:
            if v.get("@unit"):
                units_seen.add(str(v["@unit"]))
        if unit:
            units_seen.add(unit)

        # 年の絞り込み（この表がカバーする年のうち 2005 以降）
        kept = 0
        for v in values:
            tcode = str(v.get("@time", ""))
            tname = time_names.get(tcode, tcode)
            m = re.match(r"(\d{4})年", tname)
            if not m:
                continue
            year = int(m.group(1))
            if year < YEAR_MIN or year > YEAR_MAX:
                continue

            acode = str(v.get("@area", ""))
            age_code = str(v.get("@cat02", ""))
            raw = str(v.get("$", ""))
            num = None
            try:
                num = float(raw.replace(",", ""))
            except ValueError:
                num = None

            pop_code = str(v.get("@cat03", "")) if "cat03" in lookup else ""
            rows.append({
                "year": year,
                "pref_code": acode,
                "pref_name": area_names.get(acode, acode),
                "sex": sex_names.get(str(v.get("@cat01", "")), ""),
                "age_band": age_names.get(age_code, age_code),
                "age_band_code": age_code,
                "is_aggregate": "1" if age_code in AGGREGATE_AGE_CODES else "0",
                "population": "" if num is None else (
                    str(int(num)) if num == int(num) else str(num)),
                "population_raw": raw,
                "population_type": pop_names.get(pop_code, "総人口") if pop_code else "総人口",
                "unit": str(v.get("@unit", "")) or unit,
                "statsDataId": sid,
                "基準": c["基準"],
                "basis": "census" if year in CENSUS_YEARS else "estimate",
                "retrieved_at": now_iso(),
            })
            kept += 1

        years = sorted({r["year"] for r in rows if r["statsDataId"] == sid})
        per_table_counts.append((sid, c["基準"], len(values), kept, years))
        print(f"  [{sid}] {c['基準']}基準: VALUE {len(values)} 件 -> 採用 {kept} 行  年={years}")

    print(f"\n単位として観測された値: {sorted(units_seen)}")

    fieldnames = ["year", "pref_code", "pref_name", "sex", "age_band", "age_band_code",
                  "is_aggregate", "population", "population_raw", "population_type",
                  "unit", "statsDataId", "基準", "basis", "retrieved_at"]
    out = PROCESSED_DIR / "population_age.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    n_missing = sum(1 for r in rows if r["population"] == "")
    print(f"\n書き出し: {out}")
    print(f"  総行数 {len(rows)} / 欠測（数値化できない値）{n_missing}")
    print(f"  年の範囲: {min(r['year'] for r in rows)} - {max(r['year'] for r in rows)}")
    print(f"  地域数: {len({r['pref_code'] for r in rows})}")
    print(f"  population_type: {sorted({r['population_type'] for r in rows})}")

    # 年ごとの被覆状況
    cov = defaultdict(set)
    for r in rows:
        cov[r["year"]].add(r["pref_code"])
    print("\n  年別の地域数:")
    for y in sorted(cov):
        print(f"    {y}: {len(cov[y])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
