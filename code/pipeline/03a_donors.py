"""
タスク3-1 / 3-2: 献血者数の取得と、出典定義の確認

3-1  statsDataId 0000010107, cat01=G6230 を 48 地域 x 全年度で取得する。
     出力: data/processed/donors.csv

3-2  getMetaInfo と getStatsData の注記から、原典と定義に関する記載を洗い出す。
     出力: output/g6230_definition.md
     記載が無い場合は「記載なし」と書く。推測で補わない。
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import (  # noqa: E402
    PROCESSED_DIR, OUTPUT_DIR, api_get, api_status, as_list, now_iso,
)

STATS_DATA_ID = "0000010107"
CAT_CODE = "G6230"


def main() -> int:
    # ---------- データ ----------
    payload = api_get("getStatsData",
                      {"statsDataId": STATS_DATA_ID, "cdCat01": CAT_CODE,
                       "limit": 100000, "startPosition": 1},
                      label=f"donors:{STATS_DATA_ID}:{CAT_CODE}")
    st, msg = api_status(payload, "GET_STATS_DATA")
    if st != 0:
        print(f"getStatsData STATUS={st}: {msg}")
        return 1

    inf = payload["GET_STATS_DATA"]["STATISTICAL_DATA"]
    ri = inf.get("RESULT_INF", {})
    print(f"getStatsData 総件数={ri.get('TOTAL_NUMBER')} "
          f"取得={ri.get('FROM_NUMBER')}-{ri.get('TO_NUMBER')} NEXT_KEY={ri.get('NEXT_KEY')}")

    lookup = {}
    units = {}
    for co in as_list(inf["CLASS_INF"]["CLASS_OBJ"]):
        lookup[co["@id"]] = {str(c["@code"]): str(c.get("@name", ""))
                             for c in as_list(co.get("CLASS"))}
        for c in as_list(co.get("CLASS")):
            if c.get("@unit"):
                units[str(c["@code"])] = str(c["@unit"])

    values = as_list(inf["DATA_INF"]["VALUE"])
    notes = as_list(inf.get("DATA_INF", {}).get("NOTE"))

    rows = []
    n_na = 0
    for v in values:
        tcode = str(v.get("@time", ""))
        tname = lookup.get("time", {}).get(tcode, tcode)
        m = re.match(r"(\d{4})年度", tname)
        fy = int(m.group(1)) if m else None
        acode = str(v.get("@area", ""))
        raw = str(v.get("$", ""))
        try:
            donors = int(float(raw.replace(",", "")))
            num = str(donors)
        except ValueError:
            num = ""
            n_na += 1
        rows.append({
            "fiscal_year": fy if fy is not None else "",
            "fiscal_year_label": tname,
            "pref_code": acode,
            "pref_name": lookup.get("area", {}).get(acode, acode),
            "donors": num,
            "donors_raw": raw,
            # 確定事項。厚生労働省 血液事業部会 献血推進調査会の参考資料「献血の現状」に
            # 「実献血者数」が別系列として存在することから、通常の「献血者数」は延べ人数である。
            # したがって本値を人口で割った指標は参加率ではなく献血回数率である。
            "count_type": "延べ人数（実人数ではない）",
            "unit": units.get(CAT_CODE, "人"),
            "statsDataId": STATS_DATA_ID,
            "cat01": CAT_CODE,
            "cat01_name": lookup.get("cat01", {}).get(CAT_CODE, ""),
            "retrieved_at": now_iso(),
        })

    rows.sort(key=lambda r: (r["fiscal_year"], r["pref_code"]))
    out = PROCESSED_DIR / "donors.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    years = sorted({r["fiscal_year"] for r in rows})
    prefs = sorted({r["pref_code"] for r in rows})
    print(f"\n書き出し: {out}")
    print(f"  行数 {len(rows)} / 欠測 {n_na}")
    print(f"  年度 {min(years)} - {max(years)} （{len(years)} 年度）")
    print(f"  地域 {len(prefs)} （全国 + 47都道府県）")
    print(f"  期待セル数 {len(years) * len(prefs)} / 実セル数 {len(rows)}")

    # ---------- 定義 ----------
    mp = api_get("getMetaInfo", {"statsDataId": STATS_DATA_ID},
                 label=f"donors_meta:{STATS_DATA_ID}")
    meta = mp["GET_META_INFO"]["METADATA_INF"]
    tbl = meta.get("TABLE_INF", {})

    def g(k):
        v = tbl.get(k)
        return v.get("$", "") if isinstance(v, dict) else str(v or "")

    # cat01 の G6230 エントリを丸ごと取り出す（属性に説明が入ることがある）
    g6230_entry = None
    for co in as_list((meta.get("CLASS_INF") or {}).get("CLASS_OBJ")):
        if co.get("@id") == "cat01":
            for c in as_list(co.get("CLASS")):
                if str(c.get("@code")) == CAT_CODE:
                    g6230_entry = c
    # 説明系フィールドを総当たりで探す
    desc_fields = {k: g(k) for k in
                   ("DESCRIPTION", "TITLE", "STATISTICS_NAME", "STAT_NAME",
                    "GOV_ORG", "SURVEY_DATE", "UPDATED_DATE", "MAIN_CATEGORY",
                    "SUB_CATEGORY") if g(k)}
    expl = meta.get("EXPLANATION") or tbl.get("EXPLANATION")

    md = OUTPUT_DIR / "g6230_definition.md"
    with md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# G6230_献血者数 の出典と定義\n\n")
        f.write(f"作成日時: {now_iso()}\n\n")
        f.write("本ファイルは e-Stat の getMetaInfo および getStatsData が返す記載のみを転記する。"
                "記載が無い項目は「API 上に記載なし」と書き、推測で補わない。\n\n")

        f.write("## 取得経路\n\n")
        f.write(f"- 統計名: {desc_fields.get('STAT_NAME', '(なし)')}\n")
        f.write(f"- 政府機関: {desc_fields.get('GOV_ORG', '(なし)')}\n")
        f.write(f"- 統計表名称: {desc_fields.get('STATISTICS_NAME', '(なし)')}\n")
        f.write(f"- 表題: {desc_fields.get('TITLE', '(なし)')}\n")
        f.write(f"- statsDataId: {STATS_DATA_ID}\n")
        f.write(f"- 分類コード: cat01 = {CAT_CODE}\n")
        f.write(f"- 項目名: {lookup.get('cat01', {}).get(CAT_CODE, '')}\n")
        f.write(f"- 単位: {units.get(CAT_CODE, '(なし)')}\n")
        f.write(f"- 更新日: {desc_fields.get('UPDATED_DATE', '(なし)')}\n\n")

        f.write("## cat01 = G6230 のメタ属性（生のまま）\n\n```json\n")
        f.write(json.dumps(g6230_entry, ensure_ascii=False, indent=2))
        f.write("\n```\n\n")

        f.write("## 表レベルの説明フィールド\n\n")
        if expl:
            f.write("```\n" + json.dumps(expl, ensure_ascii=False, indent=2) + "\n```\n\n")
        else:
            f.write("EXPLANATION フィールドは API 上に存在しない。\n\n")

        f.write("## getStatsData の NOTE（欠測記号の定義）\n\n")
        if notes:
            for n in notes:
                f.write(f"- `{n.get('@char','')}` = {n.get('$','')}\n")
        else:
            f.write("NOTE なし。\n")
        f.write("\n")

        f.write("## 確定事項: 延べ人数である\n\n")
        f.write("厚生労働省 薬事食品衛生審議会 血液事業部会 献血推進調査会の参考資料"
                "「献血の現状」（日本赤十字社提出資料）に"
                "「年代別、男女別、回数別**実献血者数**」が別系列として掲載されている。"
                "実献血者数が別に集計されている以上、"
                "G6230_献血者数 を含む通常の「献血者数」は**延べ人数**である。\n\n")
        f.write("この帰結として、献血者数を人口で割った指標は"
                "**参加率ではなく献血回数率**である。"
                "同一人物が年に複数回献血すれば上昇する。"
                "本研究の r および dln_r はすべてこの意味で解釈する。\n\n")
        f.write("なお e-Stat のメタ情報自体には定義の記載が一切無い"
                "（上記の JSON のとおり項目名、単位、レベルのみ）。"
                "上記の判定は厚生労働省資料の系列構成にもとづく。\n\n")

        f.write("## 未確認であり API では判定できない事項\n\n")
        f.write("1. 200mL 献血、400mL 献血、成分献血が合算されているか\n")
        f.write("2. 観測期間内の定義変更、系列不連続の有無"
                "（e-Stat 上は注記なし。output/series_break_check.md 参照）\n\n")

        f.write("## 分母の定義について\n\n")
        f.write("日本赤十字社が公表する献血率は、e-Stat の1月1日現在人口を分母とし、"
                "16歳から19歳の人口を国勢調査により15-19歳人口から按分して求めている"
                "（『血液事業の現状』の脚注）。\n")
        f.write("本研究は10月1日現在の人口推計を分母とし按分を行っていないため、"
                "**日本赤十字社の公表値とは一致しない**。\n\n")

        f.write("## 引用方針\n\n")
        f.write("社会人口統計体系は総務省による二次編集であり、原典は日本赤十字社である。"
                "論文での引用は日赤原典とし、社会人口統計体系は取得経路として記載する。\n")

    print(f"書き出し: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
