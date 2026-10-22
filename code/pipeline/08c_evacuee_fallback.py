"""
抽出できなかった公表回について、同一年度の次に近い公表回で代替する。

これは推定ではない。別の実際の公表回の実測値を使い、
公表日が基準からどれだけ離れたかを記録する。
代替でも抽出できない場合は NA のままとする。

失敗の原因は該当ページが画像であること（テキスト層が無い）である。
OCR は行わない。読めなかったという事実を記録する。

出力
  data/processed/evacuees_outside_prefecture.csv （代替行を含めて更新）
  output/evacuee_extraction_log.md               （更新）
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROJECT_ROOT, PROCESSED_DIR, OUTPUT_DIR, now_iso  # noqa: E402

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "ex", Path(__file__).resolve().parent / "08b_extract_evacuees.py")
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)

PDF_DIR = PROJECT_ROOT / "data" / "raw" / "reconstruction" / "pdf"
UA = {"User-Agent": "transfusion-supply-study/1.0 (academic research)"}
MAX_ALTERNATIVES = 6


def read_csv(p: Path) -> list[dict]:
    with io.open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    cur = read_csv(PROCESSED_DIR / "evacuees_outside_prefecture.csv")
    idx = read_csv(OUTPUT_DIR / "reconstruction_publication_index.csv")

    failed = [r for r in cur if r["outside_fukushima"] == ""]
    print(f"抽出不能: {len(failed)} 件")

    by_fy: dict[int, list] = {}
    for r in idx:
        by_fy.setdefault(int(r["fiscal_year"]), []).append(r)

    for r in failed:
        fy = int(r["fiscal_year"])
        anchor = dt.date(fy + 1, 3, 11) if r["series"] == "A_nearest_0311" \
            else dt.date(fy, 10, 1)
        used = r["publish_date"]
        cands = sorted(
            (c for c in by_fy.get(fy, []) if c["publish_date"] != used),
            key=lambda c: abs((dt.date.fromisoformat(c["publish_date"]) - anchor).days))

        print(f"\n{fy}年度 {r['series']} (基準 {anchor}, 失敗 {used}) の代替を探す")
        resolved = False
        for c in cands[:MAX_ALTERNATIVES]:
            gap = (dt.date.fromisoformat(c["publish_date"]) - anchor).days
            fname = f"fy{fy}_{r['series']}_ALT_{c['publish_date']}.pdf"
            path = PDF_DIR / fname
            if not path.exists():
                try:
                    time.sleep(1.2)
                    resp = requests.get(c["url"], timeout=60, headers=UA)
                    resp.raise_for_status()
                    path.write_bytes(resp.content)
                except Exception as e:
                    print(f"  {c['publish_date']}: 取得失敗 {type(e).__name__}")
                    continue
            text, method = ex.read_text(path)
            vals, scope = ex.extract_outside(text)
            val = ex.extract_validation(text)
            got = sum(1 for v in vals.values() if v is not None)
            print(f"  {c['publish_date']} (基準との差 {gap:+4d} 日, 文字数 {len(text):>6}): "
                  f"{'成功' if got == 3 else f'{got}/3'}  福島={vals['fukushima']}")
            if got == 3:
                r.update({
                    "publish_date": c["publish_date"],
                    "as_of": val["as_of"],
                    "outside_fukushima": vals["fukushima"],
                    "outside_miyagi": vals["miyagi"],
                    "outside_iwate": vals["iwate"],
                    "national_total": "" if val["national_total"] is None
                    else val["national_total"],
                    "national_total_text": val["national_total_approx_text"],
                    "prefectures_hosting": "" if val["prefectures"] is None
                    else val["prefectures"],
                    "municipalities_hosting": "" if val["municipalities"] is None
                    else val["municipalities"],
                    "extraction_status": f"代替公表回で抽出（当初 {used} は画像のため読めず）",
                    "matched_scope": scope,
                    "text_method": method,
                    "source_file": fname,
                    "retrieved_at": now_iso(),
                })
                resolved = True
                break
        if not resolved:
            r["extraction_status"] = (
                f"NA（当初 {used} を含め代替 {min(len(cands), MAX_ALTERNATIVES)} 件すべて"
                f"該当ページが画像でテキスト層なし。OCR は行わない。推定しない）")
            print("  代替でも抽出できなかった。NA のままとする。")

    # 2026年度は公表回が1件しかなく A と B が同一文書になる。縮退として明示する。
    seen: dict[tuple, list] = {}
    for r in cur:
        seen.setdefault((r["fiscal_year"], r["publish_date"]), []).append(r)
    for k, lst in seen.items():
        if len(lst) > 1:
            for r in lst:
                r["extraction_status"] += "／同一年度の公表が1件のみでAとBが同一文書（縮退）"

    out = PROCESSED_DIR / "evacuees_outside_prefecture.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cur[0].keys()))
        w.writeheader()
        w.writerows(cur)

    n_ok = sum(1 for r in cur if r["outside_fukushima"] != "")
    print(f"\n書き出し: {out} ({len(cur)} 行)")
    print(f"  値あり {n_ok} / NA {len(cur) - n_ok}")

    print("\n--- 福島県の自県外避難者数（物理的不在者数の下限） ---")
    print(f"  {'年度':<7}{'系列':<17}{'公表日':<13}{'福島':>9}{'宮城':>8}{'岩手':>8}")
    for r in sorted(cur, key=lambda x: (int(x["fiscal_year"]), x["series"])):
        print(f"  {r['fiscal_year']:<7}{r['series']:<17}{r['publish_date']:<13}"
              f"{r['outside_fukushima'] or 'NA':>9}{r['outside_miyagi'] or 'NA':>8}"
              f"{r['outside_iwate'] or 'NA':>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
