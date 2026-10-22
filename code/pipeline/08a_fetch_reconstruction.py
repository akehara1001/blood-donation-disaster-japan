"""
復興庁「全国の避難者等の数」の取得

WebFetch は使わない。requests で直接取得し、生ファイルを data/raw/reconstruction/ に保存する。
再実行時はキャッシュがあれば取得しない。

取得の規則（指示どおり）
  各年度について次の2時点を取る。
    A 震災発生日（3月11日）に最も近い公表
      年度 t は t年4月から t+1年3月なので、対象は t+1年3月11日に最も近い公表
    B 年度中央に最も近い公表（t年10月1日に最も近い公表）
  どちらを採用したかを実際の公表日とともに記録する。
  公表日は年度によって不揃いであるため、時点を揃えたことにしない。

出力
  data/raw/reconstruction/html/*.html   年度別一覧ページ
  data/raw/reconstruction/pdf/*.pdf     選定した公表回の PDF
  output/reconstruction_publication_index.csv  全公表回の一覧（取得の有無も記録）
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROJECT_ROOT, OUTPUT_DIR, now_iso  # noqa: E402

INDEX_URL = ("https://www.reconstruction.go.jp/topics/cat-11/cat-29/cat-150/hinanshasuu/")
RAW = PROJECT_ROOT / "data" / "raw" / "reconstruction"
HTML_DIR = RAW / "html"
PDF_DIR = RAW / "pdf"
for d in (HTML_DIR, PDF_DIR):
    d.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "transfusion-supply-study/1.0 (academic research; contact via institution)"}
SLEEP = 1.2

ERA = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}


def polite_get(url: str, cache: Path) -> bytes:
    if cache.exists():
        return cache.read_bytes()
    time.sleep(SLEEP)
    r = requests.get(url, timeout=60, headers=UA)
    r.raise_for_status()
    cache.write_bytes(r.content)
    return r.content


def wareki_to_date(text: str) -> dt.date | None:
    """「平成29年3月28日」「令和2年10月1日」を西暦に。元年にも対応する。"""
    t = unicodedata.normalize("NFKC", text)
    m = re.search(r"(明治|大正|昭和|平成|令和)\s*(元|\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", t)
    if not m:
        return None
    era, y, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
    yy = 1 if y == "元" else int(y)
    try:
        return dt.date(ERA[era] + yy, mo, d)
    except ValueError:
        return None


def wareki_year_to_fy(text: str) -> int | None:
    """「平成28年度公表分」を西暦年度に。"""
    t = unicodedata.normalize("NFKC", text)
    m = re.search(r"(明治|大正|昭和|平成|令和)\s*(元|\d{1,2})\s*年度", t)
    if not m:
        return None
    yy = 1 if m.group(2) == "元" else int(m.group(2))
    return ERA[m.group(1)] + yy


def main() -> int:
    # ---------- 1. 年度別一覧ページの発見 ----------
    idx = polite_get(INDEX_URL, HTML_DIR / "index.html")
    soup = BeautifulSoup(idx.decode("utf-8", "replace"), "html.parser")
    year_pages = []
    for a in soup.find_all("a", href=True):
        t = unicodedata.normalize("NFKC", a.get_text(" ", strip=True))
        if "公表分" in t:
            fy = wareki_year_to_fy(t)
            if fy is not None:
                year_pages.append({"fy": fy, "label": t, "url": a["href"]})
    year_pages.sort(key=lambda x: x["fy"])
    print(f"年度別ページ: {len(year_pages)} 件  "
          f"{year_pages[0]['fy']}年度 〜 {year_pages[-1]['fy']}年度")

    # ---------- 2. 各年度の公表回を列挙 ----------
    pubs = []
    for yp in year_pages:
        cache = HTML_DIR / f"fy{yp['fy']}.html"
        try:
            html = polite_get(yp["url"], cache)
        except Exception as e:
            print(f"  {yp['fy']}年度: 取得失敗 {type(e).__name__}")
            continue
        s = BeautifulSoup(html.decode("utf-8", "replace"), "html.parser")
        n = 0
        for a in s.find_all("a", href=True):
            h = a["href"]
            if ".pdf" not in h.lower():
                continue
            t = unicodedata.normalize("NFKC", a.get_text(" ", strip=True))
            d = wareki_to_date(t)
            if d is None:
                continue
            n += 1
            pubs.append({"fiscal_year": yp["fy"], "publish_date": d.isoformat(),
                         "link_text": t, "url": h})
        print(f"  {yp['fy']}年度: 公表回 {n} 件")

    print(f"\n公表回の総数: {len(pubs)}")

    # ---------- 3. 各年度で2時点を選定 ----------
    by_fy: dict[int, list] = {}
    for p in pubs:
        by_fy.setdefault(p["fiscal_year"], []).append(p)

    selected = {}
    for fy, lst in by_fy.items():
        lst.sort(key=lambda x: x["publish_date"])
        anchor_a = dt.date(fy + 1, 3, 11)   # 震災発生日に相当する時点
        anchor_b = dt.date(fy, 10, 1)       # 年度中央
        for tag, anchor in (("A_nearest_0311", anchor_a), ("B_midyear", anchor_b)):
            best = min(lst, key=lambda x: abs(
                (dt.date.fromisoformat(x["publish_date"]) - anchor).days))
            gap = (dt.date.fromisoformat(best["publish_date"]) - anchor).days
            selected[(fy, tag)] = {**best, "series": tag,
                                   "anchor": anchor.isoformat(), "gap_days": gap}

    # ---------- 4. 選定分のみダウンロード ----------
    print("\n選定した公表回をダウンロードする")
    rows = []
    for (fy, tag), s in sorted(selected.items()):
        fname = f"fy{fy}_{tag}_{s['publish_date']}.pdf"
        path = PDF_DIR / fname
        status = "cached" if path.exists() else ""
        if not path.exists():
            try:
                polite_get(s["url"], path)
                status = "downloaded"
            except Exception as e:
                status = f"FAIL:{type(e).__name__}"
        size = path.stat().st_size if path.exists() else 0
        rows.append({
            "fiscal_year": fy, "series": tag, "anchor_date": s["anchor"],
            "publish_date": s["publish_date"], "gap_days": s["gap_days"],
            "link_text": s["link_text"], "url": s["url"],
            "local_file": fname if path.exists() else "",
            "bytes": size, "status": status, "retrieved_at": now_iso(),
        })
        print(f"  {fy}年度 {tag:<15} 公表 {s['publish_date']} "
              f"(基準 {s['anchor']} との差 {s['gap_days']:+4d} 日)  "
              f"{size:>8,} bytes  {status}")

    # ---------- 5. 全公表回の台帳 ----------
    picked = {(r["fiscal_year"], r["publish_date"]) for r in rows}
    idx_rows = []
    for p in sorted(pubs, key=lambda x: (x["fiscal_year"], x["publish_date"])):
        idx_rows.append({**p,
                         "selected": "yes" if (p["fiscal_year"], p["publish_date"]) in picked
                         else "no",
                         "note": "選定外のため未取得" if (p["fiscal_year"], p["publish_date"])
                         not in picked else ""})
    out = OUTPUT_DIR / "reconstruction_publication_index.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(idx_rows[0].keys()))
        w.writeheader()
        w.writerows(idx_rows)
    print(f"\n書き出し: {out} ({len(idx_rows)} 行、うち選定 {len(rows)} 件)")

    out2 = OUTPUT_DIR / "reconstruction_selected.csv"
    with out2.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"書き出し: {out2} ({len(rows)} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
