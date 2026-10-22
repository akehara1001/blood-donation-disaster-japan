"""
タスク14の判定 と タスク15: 4項分解の実行範囲の確定

タスク14
  「献血率の推移（年代別）」が何年度分を数値表として提供するかを判定する。
  図しかない場合は値を読み取らない。

タスク15
  実献血者数 A が得られる年度について、全国レベルで
    D = P * s * q * f      q = A / P1569（参加率）、f = D / A（平均献血回数）
    ln D = ln P + ln s + ln q + ln f
  を実施する。加法性を検算する。

出力: data/processed/actual_donors_national.csv
      output/four_term_decomposition.md
"""
from __future__ import annotations

import csv
import io
import math
import re
import sys
import unicodedata
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROJECT_ROOT, PROCESSED_DIR, OUTPUT_DIR, now_iso  # noqa: E402

PDF = PROJECT_ROOT / "data" / "raw" / "mhlw" / "mhlw_kenketsu_no_genjo_current.pdf"
WAREKI = {"令和": 2018, "平成": 1988}


def read_csv(p: Path) -> list[dict]:
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fy_of(title: str) -> int | None:
    m = re.search(r"(令和|平成)\s*(元|\d{1,2})\s*年度", title)
    if not m:
        return None
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return WAREKI[m.group(1)] + n


def main() -> int:
    # ---------- 実献血者数の抽出 ----------
    actual = {}
    with pdfplumber.open(str(PDF)) as pdf:
        pages = [unicodedata.normalize("NFKC", p.extract_text() or "") for p in pdf.pages]

    for t in pages:
        head = t.split("\n")[0] if t else ""
        if "年代別" in head and "回数別実献血者数" in head:
            fy = fy_of(head)
            m = re.search(r"合計\s+([\d,]+)(?:\s+[\d,]+){7}\s+([\d,]+)", t)
            if fy and m:
                actual[fy] = {"once_plus": int(m.group(1).replace(",", "")),
                              "total": int(m.group(2).replace(",", ""))}
    print("実献血者数の数値表が存在する年度:", sorted(actual))
    for fy, v in sorted(actual.items()):
        print(f"  {fy}年度: 実献血者数 合計 {v['total']:,} 人")

    if not actual:
        print("実献血者数の表を抽出できなかった。")
        return 1

    rows = [{"fiscal_year": fy, "actual_donors_national": v["total"],
             "source": "日本赤十字社 献血の現状（令和7年7月11日）年代別、男女別、回数別実献血者数",
             "source_file": PDF.name, "scope": "全国のみ。都道府県別の内訳は無い。",
             "retrieved_at": now_iso()}
            for fy, v in sorted(actual.items())]
    out = PROCESSED_DIR / "actual_donors_national.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n書き出し: {out} ({len(rows)} 行)")

    # ---------- 4項分解 ----------
    dec = {int(r["fiscal_year"]): r for r in read_csv(PROCESSED_DIR / "decomposition.csv")
           if r["pref_code"] == "00000"}

    calc = {}
    for fy in sorted(actual):
        if fy not in dec:
            continue
        D = float(dec[fy]["D_donors"])
        P = float(dec[fy]["P_persons"])
        P69 = float(dec[fy]["P1569_persons"])
        A = actual[fy]["total"]
        s = P69 / P
        q = A / P69
        f_ = D / A
        recomposed = P * s * q * f_
        calc[fy] = {"D": D, "P": P, "P69": P69, "A": A, "s": s, "q": q, "f": f_,
                    "rel_err": abs(recomposed - D) / D}

    print("\n--- 検算: D = P * s * q * f ---")
    for fy, c in sorted(calc.items()):
        print(f"  {fy}年度: 相対誤差 {c['rel_err']:.3e}")
    worst = max(c["rel_err"] for c in calc.values())

    yrs = sorted(calc)
    md = OUTPUT_DIR / "four_term_decomposition.md"
    with md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 4項分解の実行範囲と結果\n\n")
        f.write(f"作成日時: {now_iso()}\n\n")

        f.write("## タスク14の判定: 年代別献血率の系列は数値表として得られない\n\n")
        f.write("『献血の現状』（令和7年7月11日、日本赤十字社血液事業本部、全23ページ）を検査した。\n\n")
        f.write("p3 の「献血率の推移（年代別）」は**図のみであり数値表が無い**。"
                "横軸は平成28年度から令和6年度、系列は 16歳から19歳、20歳代、30歳代、"
                "40歳代、50歳から69歳、全体である。"
                "本文に「令和6年度の献血率は全体で6.2パーセント」「10代については4.7パーセント」"
                "との記載があるのみで、年度別の数値は表になっていない。\n\n")
        f.write("**指示どおり図から値を読み取っていない。**"
                "したがってこの資料からは2005年度から2024年度の年代別献血率は得られない。\n\n")
        f.write("同様に p11「実献血者数（年代別、総数）」と p14「年代別平均献血回数」も"
                "図のみである。図中にデータラベルの文字は存在するが、"
                "年度と系列の対応を機械的に確定できないため使用していない。\n\n")

        f.write("### この資料に数値表として存在するもの\n\n")
        f.write("| 内容 | 粒度 | 被覆年度 |\n|---|---|---|\n")
        f.write("| 都道府県別、年代別献血者数及び献血率 | **都道府県 × 年代** | "
                "令和5年度、令和6年度 |\n")
        f.write("| 年代別、男女別、回数別実献血者数 | 全国 × 年代 × 性別 × 回数 | "
                "令和5年度、令和6年度 |\n")
        f.write("| 職業別、採血種別延べ献血者数（10代、20代、30代） | 全国 × 職業 | "
                "平成25年度から令和6年度 |\n")
        f.write("| 16歳から18歳 初回献血者 | 全国 × 年齢 × 性別 | 令和2年度から令和6年度 |\n\n")
        f.write("**前回の粒度判定の訂正。** 2012年と2013年の資料には"
                "都道府県別の年代別献血者数が無いと判定したが、"
                "現行の『献血の現状』には**都道府県別かつ年代別**の献血者数と献血率が"
                "令和5年度と令和6年度について数値表で存在する。"
                "粒度は資料と年度によって異なる。\n\n")
        f.write("したがって年度別索引の網羅的な特定が必要である。"
                "タスク14の条件「揃った場合はこの探索は不要」は満たされていない。\n\n")

        f.write("## タスク15: 4項分解\n\n")
        f.write("実献血者数 A が数値表として得られたのは "
                f"{', '.join(f'{y}年度' for y in yrs)} のみである。\n\n")
        f.write("| 年度 | 延べ献血者数 D | 実献血者数 A | 15-69歳人口 P1569 | "
                "参加率 q = A/P1569 | 平均献血回数 f = D/A |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for fy in yrs:
            c = calc[fy]
            f.write(f"| {fy} | {int(c['D']):,} | {int(c['A']):,} | "
                    f"{int(c['P69']):,} | {c['q']*100:.3f}% | {c['f']:.4f} |\n")
        f.write("\n")
        f.write(f"検算 D = P × s × q × f の相対誤差の最大は {worst:.3e} であり、"
                f"恒等式は成立している。\n\n")

        if len(yrs) >= 2:
            a, b = yrs[-2], yrs[-1]
            ca, cb = calc[a], calc[b]
            dq = math.log(cb["q"] / ca["q"]) * 100
            df = math.log(cb["f"] / ca["f"]) * 100
            dP = math.log(cb["P"] / ca["P"]) * 100
            ds = math.log(cb["s"] / ca["s"]) * 100
            dD = math.log(cb["D"] / ca["D"]) * 100
            resid = dD - (dP + ds + dq + df)
            f.write(f"### {a}年度から{b}年度への変化（対数ポイント）\n\n")
            f.write("| 成分 | 値 |\n|---|---:|\n")
            f.write(f"| dln D | {dD:+.3f} |\n")
            f.write(f"| dln P 人口規模 | {dP:+.3f} |\n")
            f.write(f"| dln s 年齢構成 | {ds:+.3f} |\n")
            f.write(f"| **dln q 参加率** | **{dq:+.3f}** |\n")
            f.write(f"| **dln f 平均献血回数** | **{df:+.3f}** |\n")
            f.write(f"| 加法残差 | {resid:+.2e} |\n\n")

        f.write("## 目的に対する到達度\n\n")
        f.write("**当初の目的は達成できない。**\n\n")
        f.write("全国の dln_r が2020年度以降に +6.78 から +9.38 へ上昇した要因が"
                "参加率 q の回復か頻度 f の上昇かを判定するには、"
                "少なくとも2020年度の実献血者数が必要である。"
                f"しかし数値表として得られたのは {yrs[0]}年度以降のみである。\n\n")
        f.write("図（p11 実献血者数の推移、p14 年代別平均献血回数）は"
                "平成25年度あるいは平成28年度から令和6年度を扱っているため、"
                "**必要な情報は資料の中に図としては存在する。**"
                "数値表を含む年度別資料を特定できれば判定は可能になる。\n\n")
        f.write("### 実施できない範囲（明記）\n\n")
        f.write("1. **都道府県別の4項分解は実施できない。** "
                "実献血者数は全国値のみである。\n")
        f.write("2. **2011年度の4項分解は実施できない。** "
                "当該年度の実献血者数が得られていない。"
                "したがって急性期の減少が参加者の喪失か献血頻度の低下かは"
                "**現時点では判定できない**。\n")
        f.write("3. 2020年度以降の上昇の要因分解も同じ理由で保留である。"
                "報告書では引き続きこの上昇を「回復」と記述しない。\n")

    print(f"書き出し: {md}")

    if len(yrs) >= 2:
        a, b = yrs[-2], yrs[-1]
        ca, cb = calc[a], calc[b]
        print(f"\n--- {a}年度 -> {b}年度（全国、対数ポイント） ---")
        print(f"  dln D {math.log(cb['D']/ca['D'])*100:+.3f}")
        print(f"  dln P {math.log(cb['P']/ca['P'])*100:+.3f}")
        print(f"  dln s {math.log(cb['s']/ca['s'])*100:+.3f}")
        print(f"  dln q {math.log(cb['q']/ca['q'])*100:+.3f}  （参加率）")
        print(f"  dln f {math.log(cb['f']/ca['f'])*100:+.3f}  （平均献血回数）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
