"""
タスク18-2: 固定年齢スケジュール w_a の抽出

図からの読み取りは行わない。数値表のみを用いる。

組A 2012年9月12日資料 p4「平成23年度 年齢別、性別、採血種類別献血者数（献血率）」
     全国、各歳（16歳から69歳）、男女別
     検証条件: 男性計 3,609,847、女性計 1,641,018

組B 現行『献血の現状』p7「令和6年度 都道府県別、年代別献血者数及び献血率」の全国行
     検証条件: 47都道府県の合計が全国行と一致すること
     （ブロック行は集計の重複であり除外する）

組C 2012年9月12日資料 p5「平成22年度 年代別、採血種類別献血者数」の男女計
     検証条件: 計 5,329,676

年代の区分について
  日本赤十字社の年代（10代から60代）は人口推計の5歳階級と完全には対応しない。
  対応可能な最も粗い共通区分は次の6区分であり、按分は行わない。
    10代 -> 15-19歳（01004）
    20代 -> 20-24 + 25-29
    30代 -> 30-34 + 35-39
    40代 -> 40-44 + 45-49
    50代 -> 50-54 + 55-59
    60代 -> 60-64 + 65-69
  献血の下限は16歳だが人口の最小単位は15-19歳である。
  10代の w は15-19歳人口を分母とする率として定義する。
  この定義を E の算出でも同一に用いるため、水準のずれは相殺され標準化に影響しない。

出力: data/processed/age_schedule.csv
      output/age_schedule.md
"""
from __future__ import annotations

import csv
import io
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROJECT_ROOT, PROCESSED_DIR, OUTPUT_DIR, now_iso  # noqa: E402

RAW = PROJECT_ROOT / "data" / "raw" / "mhlw"
NATIONAL = "00000"
GROUPS = ["10代", "20代", "30代", "40代", "50代", "60代"]
POP_CODES = {
    "10代": ["01004"],
    "20代": ["01005", "01006"],
    "30代": ["01007", "01008"],
    "40代": ["01009", "01010"],
    "50代": ["01011", "01012"],
    "60代": ["01013", "01014"],
}


def norm(p) -> str:
    return unicodedata.normalize("NFKC", p.extract_text() or "")


def national_pop_by_group(fy: int) -> dict[str, float]:
    with io.open(PROCESSED_DIR / "population_age.csv", encoding="utf-8-sig",
                 newline="") as f:
        d = {}
        for r in csv.DictReader(f):
            if (r["population_type"] == "総人口" and r["sex"] == "男女計"
                    and r["pref_code"] == NATIONAL and int(r["year"]) == fy
                    and r["population"]):
                d[r["age_band_code"]] = float(r["population"]) * 1000.0
    return {g: sum(d[c] for c in cs) for g, cs in POP_CODES.items()}


def set_a():
    """組A 各歳から6区分へ集約する。"""
    with pdfplumber.open(str(RAW / "mhlw_2012-09-12_kenketsu.pdf")) as pdf:
        t = norm(pdf.pages[3])
    counts = defaultdict(float)
    male = female = 0.0
    n_age = 0
    for line in t.split("\n"):
        # 各歳の行は 年齢 + 男（200,400,血漿,血小板,計,人口 の6数値と率）
        # + 女（同じ6数値と率）で構成される。
        m = re.match(
            r"^(\d{1,2})\s+((?:[\d,]+\s+){6}[\d.]+%\s+(?:[\d,]+\s+){6}[\d.]+%)\s*$",
            line.strip())
        if not m:
            continue
        age = int(m.group(1))
        if not 16 <= age <= 69:
            continue
        nums = [float(x.replace(",", "")) for x in m.group(2).split()
                if not x.endswith("%")]
        m_tot, f_tot = nums[4], nums[10]
        male += m_tot
        female += f_tot
        n_age += 1
        g = ("10代" if age < 20 else f"{age // 10 * 10}代")
        counts[g] += m_tot + f_tot
    checks = [("組A 男性計", male, 3609847), ("組A 女性計", female, 1641018),
              ("組A 年齢行数", n_age, 54)]
    return dict(counts), checks, 2011


def set_b():
    """組B 全国行をそのまま使う。47都道府県の合計と一致するかを検証する。"""
    with pdfplumber.open(str(RAW / "mhlw_kenketsu_no_genjo_current.pdf")) as pdf:
        txt = [norm(pdf.pages[i]) for i in (5, 6)]
    nat, pref_sum = {}, defaultdict(float)
    n_pref = 0
    for t in txt:
        if "令和6年度" not in t.split("\n")[0]:
            continue
        for line in t.split("\n"):
            line = line.strip()
            m = re.match(r"^(\S[^\d]*?)\s+((?:[\d,]+\s+[\d.]+%\s+[\d.]+%\s*){6})$", line)
            if not m:
                continue
            name = re.sub(r"\s+", "", m.group(1))
            vals = re.findall(r"([\d,]+)\s+[\d.]+%\s+[\d.]+%", m.group(2))
            if len(vals) != 6:
                continue
            nums = [float(x.replace(",", "")) for x in vals]
            if name == "全国":
                nat = dict(zip(GROUPS, nums))
            elif "ブロック" in name:
                continue          # 集計の重複
            else:
                n_pref += 1
                for g, v in zip(GROUPS, nums):
                    pref_sum[g] += v
    checks = [("組B 都道府県数", n_pref, 47)]
    for g in GROUPS:
        checks.append((f"組B {g} 47県計 vs 全国行", pref_sum[g], nat.get(g, -1)))
    return nat, checks, 2024


def set_c():
    """組C 平成22年度の年代別（男女計）。"""
    with pdfplumber.open(str(RAW / "mhlw_2012-09-12_kenketsu.pdf")) as pdf:
        t = norm(pdf.pages[4])
    seg = t.split("平成22年度 年代別")[1].split("平成23年度 年代別")[0]
    counts, total = {}, 0.0
    for line in seg.split("\n"):
        m = re.match(r"^(\d0代)\s+((?:[\d,]+\s+){14}[\d,]+)\s*$", line.strip())
        if m:
            nums = [float(x.replace(",", "")) for x in m.group(2).split()]
            counts[m.group(1)] = nums[4]      # 男女計の「計」
        mt = re.match(r"^計\s+((?:[\d,]+\s+){14}[\d,]+)\s*$", line.strip())
        if mt:
            total = float(mt.group(1).split()[4].replace(",", ""))
    checks = [("組C 年代数", len(counts), 6),
              ("組C 計", total, 5329676),
              ("組C 年代の合計 vs 計", sum(counts.values()), total)]
    return counts, checks, 2010


def main() -> int:
    all_checks, rows = [], []
    for label, fn in (("A", set_a), ("B", set_b), ("C", set_c)):
        try:
            counts, checks, fy = fn()
        except Exception as e:
            print(f"組{label}: 抽出失敗 {type(e).__name__}: {e}")
            all_checks.append((f"組{label} 抽出", 0, 1))
            continue
        all_checks.extend(checks)
        if not counts or len(counts) != 6:
            print(f"組{label}: 6区分が揃わなかった（{sorted(counts)}）")
            continue
        pop = national_pop_by_group(fy)
        for g in GROUPS:
            rows.append({
                "schedule": label, "source_fiscal_year": fy, "age_group": g,
                "donors_national": int(counts[g]),
                "population_national": int(pop[g]),
                "w_rate": counts[g] / pop[g],
                "note": "w = 全国の当該年代の延べ献血者数 / 全国の当該年代の人口。"
                        "10代の分母は15-19歳（按分なし）",
            })
        print(f"組{label}（{fy}年度）: " +
              "  ".join(f"{g}={counts[g] / pop[g] * 100:.3f}%" for g in GROUPS))

    print("\n--- 検証 ---")
    n_bad = 0
    for name, got, exp in all_checks:
        ok = abs(got - exp) < 0.5
        if not ok:
            n_bad += 1
        print(f"  [{'OK' if ok else '**NG**':>6}] {name}: {got:,.0f} 対 {exp:,.0f}")
    if n_bad:
        print(f"\n検証に失敗した項目が {n_bad} 件ある。中止する。")
        return 1

    out = PROCESSED_DIR / "age_schedule.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("# 固定年齢スケジュール w_a。年度によらず一定。\n")
        f.write("# 10代の分母は15-19歳人口（按分なし）。E の算出でも同一定義を用いる。\n")
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n書き出し: {out} ({len(rows)} 行)")

    md = OUTPUT_DIR / "age_schedule.md"
    with md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 固定年齢スケジュールの抽出\n\n")
        f.write(f"作成日時: {now_iso()}\n\n")
        f.write("図からの読み取りは行っていない。数値表のみを用いた。\n\n")
        f.write("## 集約した年代区分とその理由\n\n")
        f.write("日本赤十字社の年代（10代から60代）は人口推計の5歳階級と"
                "完全には対応しない。対応可能な最も粗い共通区分は次の6区分である。"
                "**按分は行っていない。**\n\n")
        f.write("| 年代 | 人口推計の5歳階級 |\n|---|---|\n")
        f.write("| 10代 | 15-19歳 |\n| 20代 | 20-24 と 25-29 |\n")
        f.write("| 30代 | 30-34 と 35-39 |\n| 40代 | 40-44 と 45-49 |\n")
        f.write("| 50代 | 50-54 と 55-59 |\n| 60代 | 60-64 と 65-69 |\n\n")
        f.write("献血の下限は16歳だが人口の最小単位は15-19歳である。"
                "10代の w は15-19歳人口を分母とする率として定義した。"
                "**この定義は E の算出でも同一に用いるため、"
                "水準のずれは SDR の比のなかで相殺され、標準化の結論に影響しない。**\n\n")
        f.write("## 抽出した3組\n\n")
        f.write("| 組 | 出所 | 年度 |\n|---|---|---|\n")
        f.write("| A | 2012年9月12日資料 p4 年齢別、性別、採血種類別献血者数 | 2011年度 |\n")
        f.write("| B | 献血の現状（令和7年7月11日）p7 全国行 | 2024年度 |\n")
        f.write("| C | 2012年9月12日資料 p5 年代別、採血種類別献血者数 | 2010年度 |\n\n")
        f.write("## w_a の値（パーセント）\n\n")
        f.write("| 年代 | 組A（2011年度） | 組B（2024年度） | 組C（2010年度） |\n")
        f.write("|---|---:|---:|---:|\n")
        by = defaultdict(dict)
        for r in rows:
            by[r["age_group"]][r["schedule"]] = r["w_rate"] * 100
        for g in GROUPS:
            f.write(f"| {g} | " + " | ".join(
                f"{by[g][s]:.3f}" if s in by[g] else "—" for s in "ABC") + " |\n")
        f.write("\n")
        f.write("## 検証\n\n| 項目 | 実測 | 期待 | 判定 |\n|---|---:|---:|---|\n")
        for name, got, exp in all_checks:
            f.write(f"| {name} | {got:,.0f} | {exp:,.0f} | "
                    f"{'OK' if abs(got - exp) < 0.5 else '**NG**'} |\n")
        f.write("\n全項目が一致した。\n\n")
        f.write("## 限界\n\n")
        f.write("**年齢スケジュールを1年に固定しているため、完全な間接標準化ではない。**"
                "年代別献血率そのものが期間内に変化した分は捉えられない。"
                "捉えられるのは、年代別献血率が一定であったと仮定したときに"
                "人口の年齢構成の変化だけで生じたはずの変化である。\n\n")
        f.write("したがって「年齢構成の変化の影響を統制した」とは書けるが、"
                "**「年齢標準化を行った」とは書かない。**\n")
    print(f"書き出し: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
