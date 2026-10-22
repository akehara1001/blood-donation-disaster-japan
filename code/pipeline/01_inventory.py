"""
タスク1: e-Stat に何が存在するかの棚卸し

取得も加工もしない。存在確認と一覧化のみ。

方式（3段構え）
  Phase A  政府統計コードの発見
           getStatsList(statsNameList=Y, searchWord=<調査名>) で statsCode を「発見」する。
           コードをハードコードしない、という原則を statsDataId 以外にも適用する。
           発見結果は output/estat_statscode_discovery.csv に残す。

  Phase B  血液事業の中核4語（献血 / 血液 / 輸血 / 血液製剤）
           searchWord による全件取得。打ち切りを一切かけない。
           本研究の主要曝露/アウトカムの存否判定がここで決まるため、
           取りこぼしを許さない。

  Phase C  大規模調査（人口推計 / 国勢調査 / 住民基本台帳人口移動報告 /
           医療施設調査 / 病院報告 / 患者調査）
           Phase A で発見した statsCode で範囲を絞り、その統計の全表を列挙する。
           searchWord による曖昧一致ではなく統計単位で確定させる。

いずれの Phase でも NEXT_KEY が返る限りページングし、行数の打ち切りはしない。
API 側の総件数（NUMBER）と実際に書き出した行数を並記し、両者が一致するか検証する。

出力:
  output/estat_inventory.csv
  output/estat_statscode_discovery.csv
  output/estat_inventory_summary.md
  data/raw/estat/getStatsList__*.json  (生レスポンス。以後の処理はここから)

注意:
  「都道府県別の有無」「年齢別の有無」は getStatsList のレスポンスに分類軸情報が
  含まれないため、表題と統計名の文字列からの推定である。detect_method 列に明記する。
  確定判定は getMetaInfo が必要で、タスク2以降で実際に使う候補表についてのみ行う。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import (  # noqa: E402
    OUTPUT_DIR, api_get, api_status, as_list, now_iso,
)

# Phase B: 全件取得を保証する。打ち切り禁止。
BLOOD_KEYWORDS = ["献血", "血液", "輸血", "血液製剤"]

# Phase C: statsCode を発見してから統計単位で列挙する。
SURVEY_NAMES = [
    "人口推計",
    "国勢調査",
    "住民基本台帳人口移動報告",
    "医療施設調査",
    "病院報告",
    "患者調査",
]

# 血液事業の中核変数に該当しうる表を見分けるための語
BLOOD_CORE_TERMS = [
    "献血", "輸血", "血液製剤", "血漿", "血しょう", "赤血球", "血小板",
    "供給本数", "使用本数", "血液事業",
]

PAGE_LIMIT = 1000  # ページ数を減らすため大きめ。NEXT_KEY が尽きるまで回す。

PREF_PAT = ("都道府県", "県別", "全国、都道府県", "都道府県別", "地域別", "全国・都道府県")
AGE_PAT = ("年齢", "歳階級", "５歳階級", "5歳階級", "年齢階級", "各歳")


def flag(text: str, patterns) -> str:
    return "有(表題推定)" if any(p in text for p in patterns) else "記載なし"


def txt(v) -> str:
    """e-Stat は {'@code':..,'$':..} 形式と素の文字列を混在させる。"""
    if isinstance(v, dict):
        return str(v.get("$", ""))
    return "" if v is None else str(v)


def code_of(v) -> str:
    if isinstance(v, dict):
        return str(v.get("@code", ""))
    return ""


# --------------------------------------------------------------------------
# Phase A: 政府統計コードの発見
# --------------------------------------------------------------------------

def discover_stats_codes(survey_name: str, refresh: bool) -> list[dict]:
    params = {"statsNameList": "Y", "searchWord": survey_name}
    payload = api_get("getStatsList", params, refresh=refresh,
                      label=f"discover:{survey_name}")
    status, msg = api_status(payload, "GET_STATS_LIST")
    if status != 0:
        print(f"  [{survey_name}] statsNameList STATUS={status}: {msg}")
        return []

    datalist = payload["GET_STATS_LIST"].get("DATALIST_INF", {})
    # statsNameList=Y のときは LIST_INF、通常時は TABLE_INF
    entries = as_list(datalist.get("LIST_INF")) or as_list(datalist.get("TABLE_INF"))

    out = []
    for e in entries:
        stat_name = e.get("STAT_NAME")
        out.append({
            "search_survey_name": survey_name,
            "statsCode": code_of(stat_name) or txt(e.get("@id")),
            "統計名": txt(stat_name),
            "政府機関": txt(e.get("GOV_ORG")),
            "統計表名称": txt(e.get("STATISTICS_NAME")),
            "exact_name_match": "YES" if txt(stat_name) == survey_name else "no",
            "retrieved_at": now_iso(),
        })
    return out


# --------------------------------------------------------------------------
# Phase B / C: 表の列挙（打ち切りなし）
# --------------------------------------------------------------------------

def fetch_tables(params_base: dict, label: str, refresh: bool) -> tuple[list[dict], int]:
    """NEXT_KEY が尽きるまで全ページ取得。戻り値: (TABLE_INF のリスト, API 総件数)"""
    rows: list[dict] = []
    start = 1
    total = -1

    while True:
        params = dict(params_base)
        params["limit"] = PAGE_LIMIT
        params["startPosition"] = start

        payload = api_get("getStatsList", params, refresh=refresh, label=label)
        status, msg = api_status(payload, "GET_STATS_LIST")
        if status != 0:
            # STATUS=100 は該当データなし。これは正当な「存在しない」という結果。
            print(f"  [{label}] STATUS={status}: {msg}")
            return rows, 0

        datalist = payload["GET_STATS_LIST"].get("DATALIST_INF", {})
        if total < 0:
            total = int(datalist.get("NUMBER", 0) or 0)

        tables = as_list(datalist.get("TABLE_INF"))
        if not tables:
            break
        rows.extend(tables)

        next_key = (datalist.get("RESULT_INF") or {}).get("NEXT_KEY")
        if not next_key:
            break
        start = int(next_key)

    return rows, (total if total >= 0 else len(rows))


def parse_table(t: dict, keyword: str, search_mode: str, stats_code: str) -> dict:
    stat_name = txt(t.get("STAT_NAME"))
    statistics_name = txt(t.get("STATISTICS_NAME"))
    title = txt(t.get("TITLE"))

    title_spec = t.get("TITLE_SPEC") or {}
    if isinstance(title_spec, dict):
        joined = " / ".join([v for v in (
            txt(title_spec.get("TABLE_CATEGORY")),
            txt(title_spec.get("TABLE_NAME")),
            txt(title_spec.get("TABLE_EXPLANATION")),
        ) if v])
        if joined:
            title = joined

    haystack = " ".join([statistics_name, title, stat_name])

    return {
        "keyword": keyword,
        "search_mode": search_mode,
        "statsCode": stats_code or code_of(t.get("STAT_NAME")),
        "statsDataId": txt(t.get("@id")),
        "統計名": stat_name,
        "表題": title,
        "政府機関": txt(t.get("GOV_ORG")),
        "調査年": txt(t.get("SURVEY_DATE")),
        "都道府県別の有無": flag(haystack, PREF_PAT),
        "年齢別の有無": flag(haystack, AGE_PAT),
        "detect_method": "title_text_heuristic",
        "統計表名称": statistics_name,
        "周期": txt(t.get("CYCLE")),
        "公開日": txt(t.get("OPEN_DATE")),
        "総件数": txt(t.get("OVERALL_TOTAL_NUMBER")),
        "血液事業中核語ヒット": ";".join(w for w in BLOOD_CORE_TERMS if w in haystack),
        "retrieved_at": now_iso(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="キャッシュを無視して再取得")
    args = ap.parse_args()

    all_rows: list[dict] = []
    summary: list[dict] = []

    # ---------------- Phase A ----------------
    print("=== Phase A: 政府統計コードの発見 (statsNameList=Y) ===")
    discovery: list[dict] = []
    for name in SURVEY_NAMES:
        found = discover_stats_codes(name, args.refresh)
        discovery.extend(found)
        exact = [d for d in found if d["exact_name_match"] == "YES"]
        print(f"  {name}: 候補 {len(found)} 件 / 完全一致 {len(exact)} 件"
              f" -> {[d['statsCode'] for d in exact] or [d['statsCode'] for d in found[:5]]}")

    disc_csv = OUTPUT_DIR / "estat_statscode_discovery.csv"
    with disc_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "search_survey_name", "statsCode", "統計名", "政府機関",
            "統計表名称", "exact_name_match", "retrieved_at"])
        w.writeheader()
        w.writerows(discovery)
    print(f"  書き出し: {disc_csv} ({len(discovery)} 行)\n")

    # ---------------- Phase B ----------------
    print("=== Phase B: 血液事業4語 searchWord 全件取得（打ち切りなし） ===")
    for kw in BLOOD_KEYWORDS:
        tables, total = fetch_tables({"searchWord": kw}, f"blood:{kw}", args.refresh)
        parsed = [parse_table(t, kw, "searchWord", "") for t in tables]
        all_rows.extend(parsed)
        hits = sum(1 for r in parsed if r["血液事業中核語ヒット"])
        complete = "OK" if len(parsed) == total else f"不一致(API={total})"
        summary.append({
            "対象": kw, "phase": "B", "search_mode": "searchWord", "statsCode": "",
            "api_total": total, "rows": len(parsed), "完全取得": complete,
            "血液中核語ヒット": hits,
        })
        print(f"  {kw}: API 総件数={total} / 取得={len(parsed)} / {complete} / 血液語ヒット={hits}")

    # ---------------- Phase C ----------------
    print("\n=== Phase C: statsCode による統計単位の全表列挙 ===")
    seen_codes: set[str] = set()
    for name in SURVEY_NAMES:
        cands = [d for d in discovery
                 if d["search_survey_name"] == name and d["exact_name_match"] == "YES"]
        if not cands:
            cands = [d for d in discovery if d["search_survey_name"] == name]
        if not cands:
            summary.append({
                "対象": name, "phase": "C", "search_mode": "statsCode", "statsCode": "",
                "api_total": 0, "rows": 0, "完全取得": "statsCode 未発見", "血液中核語ヒット": 0,
            })
            print(f"  {name}: statsCode を発見できず")
            continue

        for d in cands:
            code = d["statsCode"]
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            tables, total = fetch_tables({"statsCode": code}, f"survey:{name}:{code}",
                                         args.refresh)
            parsed = [parse_table(t, name, "statsCode", code) for t in tables]
            all_rows.extend(parsed)
            hits = sum(1 for r in parsed if r["血液事業中核語ヒット"])
            complete = "OK" if len(parsed) == total else f"不一致(API={total})"
            summary.append({
                "対象": name, "phase": "C", "search_mode": "statsCode", "statsCode": code,
                "api_total": total, "rows": len(parsed), "完全取得": complete,
                "血液中核語ヒット": hits,
            })
            print(f"  {name} [{code}] {d['統計名']}: API 総件数={total} / 取得={len(parsed)} / {complete}")

    # ---------------- 書き出し ----------------
    fieldnames = [
        "keyword", "search_mode", "statsCode", "statsDataId", "統計名", "表題",
        "政府機関", "調査年", "都道府県別の有無", "年齢別の有無", "detect_method",
        "統計表名称", "周期", "公開日", "総件数", "血液事業中核語ヒット", "retrieved_at",
    ]
    out_csv = OUTPUT_DIR / "estat_inventory.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\n書き出し: {out_csv}  ({len(all_rows)} 行)")

    out_md = OUTPUT_DIR / "estat_inventory_summary.md"
    with out_md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# e-Stat 棚卸し集計（タスク1）\n\n")
        f.write(f"生成日時: {now_iso()}\n\n")
        f.write("行数の打ち切りは行っていない。API が返す総件数と実際に書き出した行数を並記する。\n\n")
        f.write("| 対象 | Phase | 検索方式 | statsCode | API 総件数 | 取得行数 | 完全取得 | 血液中核語ヒット |\n")
        f.write("|---|---|---|---|---:|---:|---|---:|\n")
        for s in summary:
            f.write(f"| {s['対象']} | {s['phase']} | {s['search_mode']} | {s['statsCode']} | "
                    f"{s['api_total']} | {s['rows']} | {s['完全取得']} | {s['血液中核語ヒット']} |\n")
        f.write("\n注: 都道府県別および年齢別の判定は表題文字列からの推定である。"
                "確定判定には getMetaInfo が必要であり、実際に使用する候補表についてのみ後段で確認する。\n")
    print(f"書き出し: {out_md}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
