"""
復興庁 PDF から「自県外に避難等している者の数」を抽出する。

方針（指示どおり）
  表の再構成は行わない。数値と都道府県名が別のテキストストリームに分かれ、
  0 の列があるとセルが連結する（377 0 0 -> 37700）ため、
  extract_text による素朴な表解析は必ず誤対応する。

  必要な数値は本文中の一文にある。
    「自県外に避難等している者の数は、福島県から40,710人、宮城県から5,699人、
      岩手県から1,366人となっている。」

  注意点
    1. 全角数字が混在するため NFKC 正規化してから抽出する
    2. 表記が年次で変化する（自県外に避難等している者の数 / 自県外への避難者数）ため
       パターンは緩く書く
    3. 抽出できなかった公表回は NA とする。推定しない
    4. 妥当性検証として同一文書内の全国合計と所在市区町村数も併せて記録する

出力
  data/processed/evacuees_outside_prefecture.csv
  output/evacuee_extraction_log.md
"""
from __future__ import annotations

import csv
import io
import re
import sys
import unicodedata
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROJECT_ROOT, PROCESSED_DIR, OUTPUT_DIR, now_iso  # noqa: E402

PDF_DIR = PROJECT_ROOT / "data" / "raw" / "reconstruction" / "pdf"

# 対象3県。表記ゆれに備え県名は「県」を任意にする。
TARGETS = [("福島", "fukushima"), ("宮城", "miyagi"), ("岩手", "iwate")]

NUM = r"([0-9][0-9,，\s]*)"


def to_int(s: str) -> int | None:
    t = re.sub(r"[,，\s]", "", s)
    return int(t) if t.isdigit() else None


def read_text(path: Path) -> tuple[str, str]:
    """pypdf で読み、失敗したら pdfplumber で読む。使った方法も返す。"""
    try:
        rd = PdfReader(str(path))
        t = "".join(pg.extract_text() or "" for pg in rd.pages)
        if t.strip():
            return unicodedata.normalize("NFKC", t), "pypdf"
    except Exception:
        pass
    try:
        with pdfplumber.open(str(path)) as pdf:
            t = "".join(pg.extract_text() or "" for pg in pdf.pages)
        return unicodedata.normalize("NFKC", t), "pdfplumber"
    except Exception as e:
        return "", f"FAIL:{type(e).__name__}"


def extract_outside(text: str) -> tuple[dict, str]:
    """
    自県外避難者数を抽出する。
    文全体を捉えてから県ごとに読むのではなく、
    「自県外」を含む近傍で県名と数値の対を拾う。表記ゆれに強くするため。
    """
    flat = re.sub(r"\s+", "", text)
    # 「自県外」から句点までを候補領域とする。見つからなければ全文を対象にする。
    m = re.search(r"自県外[^。]{0,400}。", flat)
    scope = m.group(0) if m else ""
    used = "自県外の文" if scope else ""
    if not scope:
        # 表記が異なる年度に備えた予備パターン
        m2 = re.search(r"(県外へ(の)?避難|他県へ(の)?避難)[^。]{0,400}。", flat)
        if m2:
            scope, used = m2.group(0), "県外避難の文（予備パターン）"

    out = {}
    for jp, en in TARGETS:
        val = None
        if scope:
            mm = re.search(rf"{jp}県?から{NUM}人", scope)
            if mm:
                val = to_int(mm.group(1))
        out[en] = val
    return out, (used or "該当文なし")


def extract_validation(text: str) -> dict:
    """全国合計と所在市区町村数。抽出値の妥当性検証に使う。"""
    flat = re.sub(r"\s+", "", text)
    v = {"national_total_approx_text": "", "national_total": None,
         "municipalities": None, "prefectures": None, "as_of": ""}

    m = re.search(r"全国の避難者等?の数は[、,]?約?([0-9万千百]+)人", flat)
    if m:
        v["national_total_approx_text"] = m.group(1)
    m = re.search(r"全国([0-9]{1,2})都道府県[、,]([0-9,，]+)の?市区町村", flat)
    if m:
        v["prefectures"] = to_int(m.group(1))
        v["municipalities"] = to_int(m.group(2))
    m = re.search(r"合計[^0-9]{0,10}([0-9][0-9,，]{4,})", flat)
    if m:
        v["national_total"] = to_int(m.group(1))
    m = re.search(r"(平成|令和)[0-9元]{1,2}年[0-9]{1,2}月[0-9]{1,2}日現在", flat)
    if m:
        v["as_of"] = m.group(0)
    return v


CANONICAL = re.compile(
    r"^fy(\d{4})_(A_nearest_0311|B_midyear)_(\d{4}-\d{2}-\d{2})\.pdf$")


def main() -> int:
    # 08c が代替公表回として保存する ..._ALT_YYYY-MM-DD.pdf は走査対象から除く。
    # これらは 08c が自ら取得して自ら読むものであり、本スクリプトの入力ではない。
    # 除外しないと命名規則に合致せず fiscal_year が空の行が混入し、
    # 08c が int("") で失敗する（パイプラインが冪等でなくなる）。
    all_pdfs = sorted(PDF_DIR.glob("*.pdf"))
    files = [p for p in all_pdfs if CANONICAL.match(p.name)]
    skipped = [p for p in all_pdfs if not CANONICAL.match(p.name)]
    print(f"対象 PDF: {len(files)} 件")
    if skipped:
        print(f"走査対象外（08c が生成した代替公表回）: {len(skipped)} 件")
        for p in skipped:
            print(f"    {p.name}")
    print()

    rows, log = [], []
    n_ok = n_partial = n_na = 0
    for p in files:
        m = CANONICAL.match(p.name)
        fy, series, pub = int(m.group(1)), m.group(2), m.group(3)

        text, method = read_text(p)
        vals, scope_used = extract_outside(text)
        val = extract_validation(text)

        got = sum(1 for v in vals.values() if v is not None)
        if got == 3:
            n_ok += 1
            status = "抽出成功"
        elif got > 0:
            n_partial += 1
            status = f"一部のみ（{got}/3）"
        else:
            n_na += 1
            status = "抽出不能（NA）"

        rows.append({
            "fiscal_year": fy, "series": series, "publish_date": pub,
            "as_of": val["as_of"],
            "outside_fukushima": "" if vals["fukushima"] is None else vals["fukushima"],
            "outside_miyagi": "" if vals["miyagi"] is None else vals["miyagi"],
            "outside_iwate": "" if vals["iwate"] is None else vals["iwate"],
            "national_total": "" if val["national_total"] is None else val["national_total"],
            "national_total_text": val["national_total_approx_text"],
            "prefectures_hosting": "" if val["prefectures"] is None else val["prefectures"],
            "municipalities_hosting": "" if val["municipalities"] is None
            else val["municipalities"],
            "extraction_status": status,
            "matched_scope": scope_used,
            "text_method": method,
            "source_file": p.name,
            "value_meaning": "自県外に避難等している者の数（物理的不在者数の下限）",
            "caveat": "地方公共団体の報告にもとづくため自主避難者の捕捉漏れがある。補正しない。",
            "retrieved_at": now_iso(),
        })
        log.append((p.name, status, method, scope_used, vals, val))
        print(f"  {p.name:<42} {status:<16} {method:<11} "
              f"福島={vals['fukushima']} 宮城={vals['miyagi']} 岩手={vals['iwate']}")

    out = PROCESSED_DIR / "evacuees_outside_prefecture.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n書き出し: {out} ({len(rows)} 行)")
    print(f"  抽出成功 {n_ok} / 一部のみ {n_partial} / 抽出不能 {n_na}")

    md = OUTPUT_DIR / "evacuee_extraction_log.md"
    with md.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# 復興庁 避難者数の抽出ログ\n\n")
        f.write(f"作成日時: {now_iso()}\n\n")
        f.write("表の再構成は行っていない。本文中の一文から正規表現で抽出した。\n")
        f.write("全角数字に対応するため NFKC 正規化を行い、"
                "表記ゆれに備えてパターンを緩く書いた。\n")
        f.write("抽出できなかった公表回は NA とし、推定していない。\n\n")
        f.write(f"- 対象 PDF {len(rows)} 件\n")
        f.write(f"- 抽出成功 {n_ok} 件\n- 一部のみ {n_partial} 件\n- 抽出不能 {n_na} 件\n\n")
        f.write("## 抽出結果\n\n")
        f.write("| 年度 | 系列 | 公表日 | 現在日 | 福島 | 宮城 | 岩手 | 全国合計 | 市区町村数 | 状態 |\n")
        f.write("|---|---|---|---|---:|---:|---:|---:|---:|---|\n")
        for r in rows:
            f.write(f"| {r['fiscal_year']} | {r['series']} | {r['publish_date']} | "
                    f"{r['as_of']} | {r['outside_fukushima']} | {r['outside_miyagi']} | "
                    f"{r['outside_iwate']} | {r['national_total']} | "
                    f"{r['municipalities_hosting']} | {r['extraction_status']} |\n")
        f.write("\n## 値の意味と限界\n\n")
        f.write("自県外に避難等している者の数は、当該県の住民のうち県外に所在する者の数であり、"
                "県内に物理的に不在の人数を表す。\n\n")
        f.write("この値は地方公共団体の報告にもとづくため、"
                "**自主避難者の捕捉漏れ**が指摘されている。"
                "したがって物理的不在者数の**下限**として扱う。"
                "捕捉漏れを見込んだ推定による補正は行わない。\n")
    print(f"書き出し: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
