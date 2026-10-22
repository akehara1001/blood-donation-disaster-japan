"""
e-Stat API 3.0 共通クライアント

設計方針
  1. appId は環境変数 ESTAT_APP_ID（または ESTAT_APPID）か、このフォルダの estat_appid.txt から読む。コードに書かない。
  2. すべてのレスポンスを data/raw/estat/ に生 JSON で保存する。
  3. 再実行時はキャッシュがあれば API を叩かない（--refresh で強制再取得）。
  4. リクエスト間隔は 1 秒以上あける。
  5. 値の推定、補間、生成は一切行わない。取得できないものは取得できないと記録する。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import hashlib
import datetime
import urllib.parse
from pathlib import Path

import requests

API_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"
MIN_INTERVAL_SEC = 1.1

PROJECT_ROOT = Path(__file__).resolve().parents[2]   # 公開リポジトリの根（code/pipeline/ の2つ上）
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "estat"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "output"
LOG_DIR = PROJECT_ROOT / "logs"

for _d in (RAW_DIR, PROCESSED_DIR, OUTPUT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

_last_request_ts = 0.0


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


# appId の探索順。いずれもコード内に鍵そのものを書かない。
APPID_ENV_VARS = ("ESTAT_APP_ID", "ESTAT_APPID")
APPID_FILE_CANDIDATES = (
    Path(__file__).resolve().parent / "estat_appid.txt",
)


def get_app_id() -> str:
    for var in APPID_ENV_VARS:
        v = os.environ.get(var, "").strip()
        if v:
            return v
    for f in APPID_FILE_CANDIDATES:
        if f.exists():
            v = f.read_text(encoding="utf-8").strip()
            if v:
                return v
    sys.stderr.write(
        "ERROR: e-Stat の appId が見つかりません。\n"
        "       環境変数 ESTAT_APP_ID を設定するか、code/pipeline/estat_appid.txt を置いてください。\n"
        "       PowerShell 例:  $env:ESTAT_APP_ID = '<your app id>'\n"
    )
    raise SystemExit(2)


def _slugify(text: str, maxlen: int = 60) -> str:
    """ファイル名に使える形へ。日本語は残さずハッシュで一意性を担保する。"""
    ascii_part = re.sub(r"[^0-9A-Za-z._-]+", "_", text).strip("_")[:maxlen]
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{ascii_part}_{h}" if ascii_part else h


def cache_path(endpoint: str, params: dict) -> Path:
    """appId を除いたパラメータでキャッシュキーを作る。"""
    key_params = {k: v for k, v in sorted(params.items()) if k != "appId"}
    key = urllib.parse.urlencode(key_params, encoding="utf-8")
    return RAW_DIR / f"{endpoint}__{_slugify(key)}.json"


def api_get(endpoint: str, params: dict, refresh: bool = False,
            label: str | None = None) -> dict:
    """
    e-Stat API を1回呼ぶ。キャッシュがあればそれを返す。
    endpoint: 'getStatsList' | 'getMetaInfo' | 'getStatsData'
    """
    global _last_request_ts

    path = cache_path(endpoint, params)
    if path.exists() and not refresh:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    full_params = dict(params)
    full_params["appId"] = get_app_id()

    elapsed = time.time() - _last_request_ts
    if elapsed < MIN_INTERVAL_SEC:
        time.sleep(MIN_INTERVAL_SEC - elapsed)

    url = f"{API_BASE}/{endpoint}"
    resp = requests.get(url, params=full_params, timeout=90)
    _last_request_ts = time.time()
    resp.raise_for_status()
    payload = resp.json()

    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    log_line = {
        "retrieved_at": now_iso(),
        "endpoint": endpoint,
        "params": {k: v for k, v in params.items() if k != "appId"},
        "cache_file": path.name,
        "label": label,
    }
    with (LOG_DIR / "api_calls.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_line, ensure_ascii=False) + "\n")

    return payload


def api_status(payload: dict, root_key: str) -> tuple[int, str]:
    """e-Stat のアプリ層ステータス（HTTP 200 でもエラーを返すことがある）。"""
    root = payload.get(root_key, {})
    result = root.get("RESULT", {})
    return int(result.get("STATUS", -1)), str(result.get("ERROR_MSG", ""))


def as_list(x):
    """e-Stat は要素が1件のとき配列でなく dict を返す。常に list に正規化する。"""
    if x is None:
        return []
    return x if isinstance(x, list) else [x]
