"""
Build the public data files (English labels) from the authors' derived data (Japanese labels).

Usage: python code/translate_data.py <directory with the authors' data/processed files> <output data directory>

Only labels, notes and comment lines are translated. Every column whose values are all numeric (or empty)
is copied unchanged, and the script verifies this by comparing the SHA-256 of each numeric column before and
after translation. The script stops if any Japanese character remains in the output.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import sys
from pathlib import Path

JP = re.compile(r"[　-ヿ㐀-鿿＀-￯]")

PREF = {
    "00000": "Japan", "01000": "Hokkaido", "02000": "Aomori", "03000": "Iwate", "04000": "Miyagi", "05000": "Akita",
    "06000": "Yamagata", "07000": "Fukushima", "08000": "Ibaraki", "09000": "Tochigi", "10000": "Gunma",
    "11000": "Saitama", "12000": "Chiba", "13000": "Tokyo", "14000": "Kanagawa", "15000": "Niigata",
    "16000": "Toyama", "17000": "Ishikawa", "18000": "Fukui", "19000": "Yamanashi", "20000": "Nagano",
    "21000": "Gifu", "22000": "Shizuoka", "23000": "Aichi", "24000": "Mie", "25000": "Shiga", "26000": "Kyoto",
    "27000": "Osaka", "28000": "Hyogo", "29000": "Nara", "30000": "Wakayama", "31000": "Tottori",
    "32000": "Shimane", "33000": "Okayama", "34000": "Hiroshima", "35000": "Yamaguchi", "36000": "Tokushima",
    "37000": "Kagawa", "38000": "Ehime", "39000": "Kochi", "40000": "Fukuoka", "41000": "Saga",
    "42000": "Nagasaki", "43000": "Kumamoto", "44000": "Oita", "45000": "Miyazaki", "46000": "Kagoshima",
    "47000": "Okinawa",
}
CENSUS = {"平成17年": "2005 census", "平成22年": "2010 census", "平成27年": "2015 census", "令和２年": "2020 census",
          "令和2年": "2020 census"}
ERA = {"平成": 1988, "令和": 2018}

VALUES = {
    "人": "persons",
    "千人": "thousand persons",
    "延べ人数（実人数ではない）": "donations (donation events, not individual donors)",
    "延べ人数": "donations (donation events, not individual donors)",
    "年度（4月から翌年3月）": "fiscal year (April to March)",
    "人（人口推計の千人を1000倍して換算）": "persons (Population Estimates in thousands multiplied by 1,000)",
    "復興庁の公表本文が数値を挙げるのは福島、宮城、岩手のみ。他県は記載が無いため NA（ゼロではない）。":
        "The Reconstruction Agency bulletins give counts for Fukushima, Miyagi and Iwate only; other prefectures "
        "are NA (not zero).",
    "地方公共団体の報告にもとづく。自主避難者の捕捉漏れがあり物理的不在者数の下限。補正しない。":
        "Based on reports from local governments; self-evacuees may be missed, so the count is a lower bound of "
        "persons physically absent. Not corrected.",
    "2005-2009年度の幾何平均": "geometric mean of FY2005-FY2009",
    "2005-2009年度の算術平均": "arithmetic mean of FY2005-FY2009",
    "P と P1569 は千人を1000倍して人に換算": "P and P1569 converted from thousands to persons (x 1,000)",
    "固定年齢スケジュール法。完全な間接標準化ではない。": "Fixed age-schedule method; not a full indirect standardisation.",
    "01000(総数)": "01000(total)",
    "85歳以上が無く80歳以上で代用": "no 85+ band; the 80+ band is used",
    "85歳以上まで明細あり": "bands up to 85+ available",
    "代替公表回で抽出（当初 2012-03-14 は画像のため読めず）":
        "extracted from an alternative bulletin (the 2012-03-14 bulletin is an image and could not be read)",
    "代替公表回で抽出（当初 2017-02-28 は画像のため読めず）":
        "extracted from an alternative bulletin (the 2017-02-28 bulletin is an image and could not be read)",
    "抽出成功": "extracted",
    "抽出成功／同一年度の公表が1件のみでAとBが同一文書（縮退）":
        "extracted; only one bulletin in the fiscal year, so series A and B are the same document",
    "自県外の文": "sentence on evacuees outside their prefecture",
    "自県外に避難等している者の数（物理的不在者数の下限）":
        "persons evacuated outside their prefecture (lower bound of persons physically absent)",
    "地方公共団体の報告にもとづくため自主避難者の捕捉漏れがある。補正しない。":
        "Based on reports from local governments, so self-evacuees may be missed. Not corrected.",
    "w = 全国の当該年代の延べ献血者数 / 全国の当該年代の人口。10代の分母は15-19歳（按分なし）":
        "w = national donations in the age group / national population in the age group; the denominator for "
        "the 10s is the population aged 15-19 (no apportioning)",
    "対数平均による厳密加法分解": "exact additive decomposition by logarithmic mean",
    "日本赤十字社 献血の現状（令和7年7月11日）年代別、男女別、回数別実献血者数":
        "Japanese Red Cross Society, Current state of blood donation (11 July 2025): individual donors by age, sex "
        "and number of donations",
    "全国のみ。都道府県別の内訳は無い。": "national only; no breakdown by prefecture",
    "男女計": "both sexes", "男": "male", "女": "female",
    "総人口": "total population", "日本人人口": "Japanese nationals",
    "総数": "total", "80歳以上": "80+", "85歳以上": "85+",
    "10代": "10s", "20代": "20s", "30代": "30s", "40代": "40s", "50代": "50s", "60代": "60s",
}

DICT_DESC = {
    "年度": "fiscal year", "都道府県コード": "prefecture code", "献血者数（延べ人数）": "number of donations",
    "献血回数率": "donation rate (donations per resident aged 15-69)",
    "総人口（暦年 t の10月1日）": "total population on 1 October of calendar year t",
    "総人口（暦年 t+1 の10月1日）": "total population on 1 October of calendar year t+1",
    "総人口（t と t+1 の平均）": "total population, mean of t and t+1",
    "15-69歳人口（暦年 t の10月1日）": "population aged 15-69 on 1 October of calendar year t",
    "65歳以上人口": "population aged 65 and over",
    "献血者数の対数差": "change in donations, log points",
    "人口規模の寄与": "population-size component",
    "年齢構成の寄与": "eligible-age-share component",
    "献血回数率の寄与（残差）": "donation-rate component",
    "自県外避難者数（3月11日近傍の公表）": "evacuees outside the prefecture (bulletin nearest 11 March)",
    "自県外避難者数（年度中央の公表）": "evacuees outside the prefecture (mid-year bulletin)",
    "病院数": "hospitals", "病院病床数": "hospital beds", "一般病床数": "general beds", "医師数": "physicians",
    "未取得": "not obtained",
    "47県": "47 prefectures", "なし": "none",
    "件/人": "donations per person", "対数ポイント": "log points", "施設": "facilities", "床": "beds",
    "骨格": "key variable",
    "SSDS 0000010107 cat01=G6230。原典は日本赤十字社。年度基準。**延べ人数であり実人数ではない。**実献血者数は別系列として厚生労働省 献血推進調査会資料に存在する（未取得）。":
        "System of Social and Demographic Statistics 0000010107, item G6230; original source Japanese Red Cross "
        "Society; fiscal year. Counts donations, not individual donors. Counts of individual donors exist as a "
        "separate series in Ministry of Health, Labour and Welfare committee documents (not obtained).",
    "延べ献血件数を15-69歳人口で割った値。**参加率ではない。**同一人物の頻回化でも上昇する。":
        "Donations divided by the population aged 15-69. Not the proportion of residents who donated; it also "
        "rises when the same people donate more often.",
    "**既定の分母**。人口推計。千人を1000倍して換算。":
        "Default denominator. Population Estimates; thousands multiplied by 1,000.",
    "対照用。2024年度は未公表のため NA。": "For comparison only; NA for FY2024 (not yet published).",
    "年度中の平均に相当する近似。対照用。": "Approximation to the mean during the fiscal year; for comparison only.",
    "献血可能年齢の近似。下限は16歳だが5歳階級の最小単位が15-19のため按分していない。":
        "Approximates the donation-eligible ages. The minimum donation age is 16, but the smallest 5-year band "
        "is 15-19, so no apportioning was applied.",
    "2005-2006年度は85歳以上が無く80歳以上で代用。": "For FY2005-FY2006 there is no 85+ band, so the 80+ band is used.",
    "基準は2005-2009年度の幾何平均。dln_D = dln_P + dln_s + dln_r が厳密に成立。":
        "Baseline: geometric mean of FY2005-FY2009. dln_D = dln_P + dln_s + dln_r holds exactly.",
    "15-69歳シェアの変化。15-69歳内部の高齢化は捉えられず dln_r に混入する。":
        "Change in the share aged 15-69. Changes in age composition within ages 15-69 are not captured here and "
        "fall into dln_r.",
    "参加率ではなく献血回数率の変化。頻回化と参加者増を分離できない。":
        "Change in donations per resident aged 15-69, not in the proportion who donate; more frequent donation "
        "and more donors cannot be separated.",
    "復興庁『全国の避難者等の数』本文からの抽出。福島、宮城、岩手のみ。物理的不在者数の**下限**。自主避難者の捕捉漏れがある。補正しない。":
        "Extracted from the text of the Reconstruction Agency bulletins on the number of evacuees. Fukushima, "
        "Miyagi and Iwate only. A lower bound of persons physically absent; self-evacuees may be missed. Not "
        "corrected.",
    "同上。": "As above.",
    "SSDS 0000010109 I5101。年度表記だが実体は各年10月1日現在の暦年。医療施設調査と2010年2015年2020年で47県全件一致。":
        "System of Social and Demographic Statistics 0000010109, item I5101. Labelled by fiscal year but refers "
        "to 1 October of each calendar year. Matches the Survey of Medical Institutions for all 47 prefectures in "
        "2010, 2015 and 2020.",
    "SSDS I5211。同上。": "System of Social and Demographic Statistics, item I5211. As above.",
    "SSDS I521150。1996年度以降。": "System of Social and Demographic Statistics, item I521150. From FY1996.",
    "SSDS I6100。隔年。": "System of Social and Demographic Statistics, item I6100. Every second year.",
    "日本赤十字社の資料が必要。本タスクでは投入していない。":
        "Requires Japanese Red Cross Society material; not entered in this dataset.",
}

COLUMN_RENAME = {"基準": "census_base", "説明": "description", "被覆年": "coverage", "単位": "unit", "備考": "notes"}

COMMENTS = {
    "age_standardized.csv": ["# Fixed age-schedule method. Baseline: geometric mean of FY2005-FY2009.",
                             "# Identity: dln_r = dln_SDR + dln(E/P1569) holds exactly."],
    "population_denominators.csv": [
        "# pop_15_69 is the population aged 15 to 69. The minimum donation age is 16, but the smallest 5-year band "
        "of the Population Estimates is 15-19, so ages 16-69 cannot be formed. No apportioning was applied.",
        "# Unit: thousand persons (as returned by e-Stat; not converted)."],
    "age_schedule.csv": ["# Fixed age schedule w_a, the same in every fiscal year.",
                         "# The denominator for the 10s is the population aged 15-19 (no apportioning); the same "
                         "definition is used for E."],
    "event_counterfactual.csv": [
        "# Event comparisons with two comparison sets (and a strict sensitivity).",
        "# non_affected = median of the prefectures other than those most affected by the event (main).",
        "# all47 = median of all 47 prefectures (includes the affected prefectures).",
        "# non_affected_strict = also excludes the intermediate-exposure prefectures (2011 earthquake only, 41)."],
}


def era_date(s: str) -> str:
    m = re.fullmatch(r"(平成|令和)(元|\d+)年(\d+)月(\d+)日現在", s)
    if not m:
        raise ValueError(s)
    y = ERA[m.group(1)] + (1 if m.group(2) == "元" else int(m.group(2)))
    return f"as of {y}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"


def man_sen(s: str) -> str:
    m = re.fullmatch(r"(\d+)万(\d)千", s)
    return f"{int(m.group(1)) * 10 + int(m.group(2))} thousand" if m else s


def age_band(s: str) -> str:
    m = re.fullmatch(r"(\d+)～(\d+)歳", s)
    return f"{m.group(1)}-{m.group(2)}" if m else VALUES[s]


def tr_value(col: str, v: str, row: dict) -> str:
    if not v or not JP.search(v):
        return v
    if col == "pref_name":
        return PREF[row["pref_code"]]
    if col in ("pop_census_base", "基準"):
        return CENSUS[v]
    if col == "as_of":
        return era_date(v)
    if col == "national_total_text":
        return man_sen(v)
    if col == "age_band":
        return age_band(v)
    if col in ("説明", "被覆年", "単位", "備考"):
        return DICT_DESC.get(v) or VALUES[v]
    return VALUES[v]


def is_numeric(values) -> bool:
    ok = False
    for v in values:
        if v == "":
            continue
        try:
            float(v)
            ok = True
        except ValueError:
            return False
    return ok


def col_hash(rows, c) -> str:
    return hashlib.sha256("\n".join(r[c] for r in rows).encode("utf-8")).hexdigest()


def translate(src: Path, dst: Path) -> dict:
    raw = src.read_text(encoding="utf-8-sig").splitlines()
    comments = [ln for ln in raw if ln.startswith("#")]
    body = [ln for ln in raw if not ln.startswith("#")]
    rows = list(csv.DictReader(io.StringIO("\n".join(body))))
    cols = list(rows[0].keys())
    numeric = [c for c in cols if is_numeric(r[c] for r in rows)]
    before = {c: col_hash(rows, c) for c in numeric}
    out_rows = [{COLUMN_RENAME.get(c, c): tr_value(c, r[c], r) for c in cols} for r in rows]
    out_cols = [COLUMN_RENAME.get(c, c) for c in cols]
    after = {c: col_hash(out_rows, COLUMN_RENAME.get(c, c)) for c in numeric}
    bad = [c for c in numeric if before[c] != after[c]]
    if bad:
        raise RuntimeError(f"{src.name}: numeric columns changed: {bad}")
    new_comments = COMMENTS.get(src.name, [])
    if len(new_comments) != len(comments):
        raise RuntimeError(f"{src.name}: {len(comments)} comment lines but {len(new_comments)} translations")
    buf = io.StringIO()
    for c in new_comments:
        buf.write(c + "\n")
    w = csv.DictWriter(buf, fieldnames=out_cols, lineterminator="\n")
    w.writeheader()
    w.writerows(out_rows)
    text = buf.getvalue()
    if JP.search(text):
        raise RuntimeError(f"{src.name}: Japanese characters remain")
    dst.write_text(text, encoding="utf-8", newline="")
    return {"file": src.name, "rows": len(rows), "numeric_columns": len(numeric),
            "numeric_sha256_identical": "yes", "comment_lines": len(comments)}


FILES = ["panel.csv", "panel_dictionary.csv", "decomposition.csv", "age_standardized.csv",
         "population_denominators.csv", "population_age.csv", "evacuees_outside_prefecture.csv",
         "age_schedule.csv", "event_counterfactual.csv", "pop_decomposition_by_age.csv",
         "actual_donors_national.csv"]

if __name__ == "__main__":
    src_dir, dst_dir = Path(sys.argv[1]), Path(sys.argv[2])
    dst_dir.mkdir(parents=True, exist_ok=True)
    report = [translate(src_dir / f, dst_dir / f) for f in FILES]
    with open(dst_dir.parent / "code" / "translate_report.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(report)
    for r in report:
        print(r)
