"""
タスク12: 厚生労働省アーカイブの取得

WebFetch は使わない。requests で直接取得し data/raw/mhlw/ に保存する。
再実行時はキャッシュがあれば取得しない。

まず指定された2本のみを取得する。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from estat_client import PROJECT_ROOT, now_iso  # noqa: E402

RAW = PROJECT_ROOT / "data" / "raw" / "mhlw"
RAW.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "transfusion-supply-study/1.0 (academic research)"}

TARGETS = [
    ("mhlw_2012-09-12_kenketsu.pdf",
     "https://www.mhlw.go.jp/stf/shingi/2r9852000002krnp-att/2r9852000002krsx.pdf",
     "2012年9月12日開催分。平成23年度の年齢別、性別、採血種類別献血者数を含むとされる。"),
    ("mhlw_2013-09-30_kenketsu.pdf",
     "https://www.mhlw.go.jp/file/05-Shingikai-11121000-Iyakushokuhinkyoku-Soumuka/0000035352.pdf",
     "2013年9月30日開催分。献血場所別の表を含むとされる。"),
]


def main() -> int:
    for name, url, note in TARGETS:
        path = RAW / name
        if path.exists():
            print(f"cached      {name}  {path.stat().st_size:,} bytes")
            continue
        try:
            time.sleep(1.2)
            r = requests.get(url, timeout=90, headers=UA)
            r.raise_for_status()
            path.write_bytes(r.content)
            ctype = r.headers.get("content-type", "")
            print(f"downloaded  {name}  {len(r.content):,} bytes  {ctype}")
        except Exception as e:
            print(f"FAIL        {name}  {type(e).__name__}: {str(e)[:140]}")
            print(f"            {url}")
    print(f"\n保存先: {RAW}")
    print(f"取得日時: {now_iso()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
