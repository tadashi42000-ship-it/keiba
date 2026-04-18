"""
重賞レース予想Webアプリ

Streamlitを使用して、netkeiba.comから出馬表を取得し、
YouTube・Web検索から予想情報を収集・表示するWebアプリケーション。
サイドバーから直近の重賞レースを選択可能。
"""

import streamlit as st
import pandas as pd
import os
import sys
import subprocess
from datetime import datetime, date, timedelta
from pathlib import Path
import re
import json
import time  # 待機時間のために追加
import traceback
import unicodedata
import math
import itertools
import html
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin, parse_qs
from collections import defaultdict
from bs4 import BeautifulSoup
import requests
from dotenv import load_dotenv
try:
    import PyPDF2
    HAS_PDF_SUPPORT = True
except ImportError:
    HAS_PDF_SUPPORT = False
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google import genai as google_genai
from google.genai import types as genai_types

from race_catalog import (
    RaceInfo,
    get_upcoming_races,
    resolve_race_id,
    ensure_data_dir,
    clear_fetch_graded_races_cache,
    clear_resolve_race_id_cache,
)
from get_keiba_info import fetch_race_csv

# .env ファイルからAPIキーを読み込む（app.py と同じフォルダに .env を置くこと）
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

load_dotenv()

# ====================
# ページ設定
# ====================

# ページの基本設定（タイトル、アイコン、レイアウト）
st.set_page_config(
    page_title="重賞予想アプリ",
    page_icon="🏇",
    layout="wide",  # ワイドレイアウトで表示
    initial_sidebar_state="expanded"  # サイドバーを最初から開く
)

# ====================
# 定数定義
# ====================

# APIキーを環境変数から取得（.env → st.secrets の順でフォールバック）
# キーは .env ファイルに記載。絶対にコードに直書きしないこと。
def _get_secret(key: str, default: str = "") -> str:
    """os.getenv → st.secrets の順でキーを探す"""
    val = os.getenv(key, "")
    if val:
        return val
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

YOUTUBE_API_KEY = _get_secret("YOUTUBE_API_KEY")
GEMINI_API_KEY = _get_secret("GEMINI_API_KEY")
GEMINI_MODEL = _get_secret("GEMINI_MODEL", "gemini-2.5-flash")
# YouTube解析専用モデル（未設定時は Gemini 3系Flash を優先）
# 例: GEMINI_MODEL_YOUTUBE=gemini-3.1-flash
GEMINI_MODEL_YOUTUBE = _get_secret("GEMINI_MODEL_YOUTUBE", _get_secret("YOUTUBE_GEMINI_MODEL", "gemini-3.1-flash"))
TAVILY_API_KEY = _get_secret("TAVILY_API_KEY")
X_BEARER_TOKEN = _get_secret("X_BEARER_TOKEN")

_TRAINING_KEYWORDS = re.compile(r'追切|追い切り|調教|時計|仕上がり|動き[がをは]|坂路|ウッド|CW')
_TRAINING_STRONG_CONTEXT_PAT = re.compile(
    r'追切|追い切り|調教|最終追い|最終追切|1週前追い|1週前追切|一週前追い|一週前追切|坂路|ウッド|CW|南W|北W|ポリ|併せ'
)
_TRAINING_WEAK_CONTEXT_PAT = re.compile(r'時計|仕上がり|動き[がをは]|終い|ラスト|ハロン')
_NON_TRAINING_RACE_CONTEXT_PAT = re.compile(
    r'予想|本命|対抗|単穴|連下|買い目|馬券|オッズ|人気|印|展開|ペース|先行|差し|追込|上がり|直線|脚質|枠順|血統|適性'
)
# 追切タイム抽出パターン（1:08.5 / 34.5 / 68.5秒 / 12-10.8 / C34.5 / F36.0 / 66秒5 など）
_TRAINING_TIME_PAT = re.compile(
    r'\d:\d{2}\.\d'               # 1:08.5 形式（総合タイム）
    r'|(?:[1-6]F|[FCWSBG])\d{2}\.\d'  # 4F52.3 / C34.5 / F36.0 など
    r'|\d{2}\.\d(?:秒)?'          # 34.5 / 68.5秒（ラップ・累計）
    r'|\d{2}-\d{2}\.\d'           # 12-10.8（2F区間）
    r'|\d{1,2}秒\d'               # 66秒5 / 9秒8 形式
    ,
    re.IGNORECASE
)
_TRAINING_PHASE_WEEK_PAT = re.compile(r'1週前|一週前|先週|前週')
_TRAINING_PHASE_LATEST_PAT = re.compile(r'最終|直前|今週|当週|最終追い|最終追切')
_TRAINING_PHASE_PREV_PAT = re.compile(r'前走最終|前走時|前走')
_TRAINING_INTENSITY_PAT = re.compile(
    r'一杯|強め|馬なり|軽め|終い重点|G前仕掛け|仕掛け|併せ先着|併せ遅れ|併せ同入'
)
_TRAINING_LAP_HINT_PAT = re.compile(r'終い|ラスト|[1-6][Ff]|ハロン')
_TRAINING_INTENSITY_LEVELS = [
    ("一杯", 4),
    ("強め", 3),
    ("G前仕掛け", 3),
    ("仕掛け", 2),
    ("終い重点", 2),
    ("馬なり", 1),
    ("軽め", 0),
]

WEB_SEARCH_ALLOWLIST = [
    "netkeiba.com",
    "keibalab.jp",
    "umanity.jp",
    "spaia-keiba.com",
    "sports.yahoo.co.jp",
]
TRAINING_FALLBACK_ALLOWLIST = [
    "umasiru.com",
    "netkeiba.com",
    "keibalab.jp",
    "umanity.jp",
    "spaia-keiba.com",
    "sports.yahoo.co.jp",
    "jra.jp",
    "race.sanspo.com",
    "pluskeiba.com",
]
TRAINING_PHASE_ORDER = ["直近", "1週前", "前走最終", "不明"]
MAX_ANALYZE_ARTICLES_PER_QUERY = 3
BET_STAKE_UNIT_YEN = 500
BET_MAX_POINTS = 10
BET_TYPES_ALL = ["単勝", "複勝", "ワイド", "馬連", "三連複", "三連単"]
BET_POINT_PROFILE_HIT = {"単勝": 2, "複勝": 4, "ワイド": 3, "馬連": 1, "三連複": 0, "三連単": 0}
BET_POINT_PROFILE_ROI = {"単勝": 1, "複勝": 0, "ワイド": 1, "馬連": 2, "三連複": 3, "三連単": 3}
BET_ODDS_TYPE_CODE_CANDIDATES = {
    # netkeibaのtypeコードは将来変更される可能性があるため複数候補を用意
    "複勝": ["b1"],
    "ワイド": ["b5", "b6"],
    "馬連": ["b4", "b5"],
    "三連複": ["b7", "b8"],
    "三連単": ["b8", "b9"],
}

UMANITY_BASE_URL = "https://umanity.jp"
UMANITY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": UMANITY_BASE_URL,
}
UMANITY_RACE_NAME_ALIASES = {
    "フェブラリーステークス": ["フェブラリーS"],
    "朝日杯フューチュリティステークス": ["朝日杯フューチュリティS"],
    "阪神ジュベナイルフィリーズ": ["阪神ジュベナイルF", "阪神JF"],
    "スプリンターズステークス": ["スプリンターズS"],
    "マイルチャンピオンシップ": ["マイルCS"],
    "ジャパンカップ": ["ジャパンC"],
    "チャンピオンズカップ": ["チャンピオンズC"],
    "NHKマイルカップ": ["NHKマイルC"],
    "エリザベス女王杯": ["エリザベス女王杯"],
}

# レース切替時にクリアするセッションステートキー
RACE_SESSION_KEYS = [
    'horse_df', 'youtube_videos', 'youtube_raw', 'youtube_summary_df',
    'web_articles', 'web_raw', 'race_characteristics', 'gates_saved',
    'race_characteristics_enriched', 'race_characteristics_last_attempt', 'race_characteristics_last_error',
    'yt_detail_analysis', 'yt_video_conclusions', 'doc_horse_raw', 'win_rates', 'latest_odds_error',
    'latest_odds', 'combined_keyword', 'yt_detail_keyword',
    'x_tweets', 'x_raw', 'x_newest_id',
    'training_items', 'training_time_rows',
    'bet_plan_settings', 'bet_plan_result', 'bet_type_odds',
]


# ====================
# レース設定ヘルパー関数
# ====================

def get_race_config() -> RaceInfo | None:
    """現在選択中のレースを取得する"""
    return st.session_state.get('selected_race')


def format_date_with_weekday(value: date) -> str:
    """YYYY/MM/DD(曜) 形式へ整形する。"""
    weekdays = ("月", "火", "水", "木", "金", "土", "日")
    return f"{value:%Y/%m/%d}({weekdays[value.weekday()]})"


def get_race_display_name() -> str:
    """'レース名 年' 形式の表示名を返す"""
    r = get_race_config()
    return f"{r.race_name} {r.date.year}" if r else "レース未選択"


def get_csv_path() -> str:
    """選択中レースのCSVパスを返す"""
    r = get_race_config()
    return r.csv_file if r else ""


def get_race_url() -> str:
    """選択中レースのnetkeiba出馬表URLを返す"""
    r = get_race_config()
    if r and r.race_id:
        return f"https://race.netkeiba.com/race/shutuba.html?race_id={r.race_id}"
    return ""


def _get_cache_path(race_key: str) -> str:
    """race_key をファイル名にサニタイズしたキャッシュパスを返す"""
    safe = _sanitize_race_key_for_cache(race_key)
    return os.path.join("data", "search_cache", f"{safe}.json")


def _sanitize_race_key_for_cache(race_key: str) -> str:
    """race_key をOS非依存で安全なファイル名へ正規化する。"""
    text = str(race_key or "").strip()
    # Windows禁止文字・制御文字をまとめて置換
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "unknown_race"


def _get_last_selected_race_path() -> str:
    """前回読み込んだレースキーを保存するJSONパスを返す。"""
    return os.path.join("data", "last_selected_race.json")


def _save_last_selected_race_key(race_key: str) -> None:
    """前回読み込んだレースキーを保存する。"""
    key = _to_text(race_key)
    if not key:
        return
    ensure_data_dir()
    path = _get_last_selected_race_path()
    tmp = path + ".tmp"
    payload = {
        "race_key": key,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)


def _load_last_selected_race_key() -> str:
    """保存済みの前回レースキーを読み込む。"""
    path = _get_last_selected_race_path()
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return ""
    return _to_text(data.get("race_key"))


def _raw_fingerprint(item: dict) -> str:
    """重複判定キー: source_url が空なら source_title+馬名をフォールバックに使う"""
    url = (item.get('source_url') or item.get('url') or '').strip()
    if url:
        return url
    # URLなし: タイトル＋馬名の複合キーで同タイトル別馬の誤重複を回避
    title = (item.get('source_title') or item.get('title') or '').strip()
    horse = (item.get('馬名') or '').strip()
    return f"{title}::{horse}" if title or horse else ""  # 全空 = "" → 常に追加扱い


def save_race_cache(race_key: str) -> None:
    """現在のセッションステートの検索結果をJSONキャッシュとして原子的に保存する"""
    cache_path = _get_cache_path(race_key)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    data = {
        "meta": {
            "race_key": race_key,
            "last_updated": datetime.now().isoformat(timespec='seconds'),
            "web_article_count": len(st.session_state.get('web_articles') or []),
            "youtube_video_count": len(st.session_state.get('youtube_videos') or []),
            "x_tweet_count": len(st.session_state.get('x_tweets') or []),
            "x_newest_id": st.session_state.get('x_newest_id'),
            "training_item_count": len(st.session_state.get('training_items') or []),
            "training_time_row_count": len(st.session_state.get('training_time_rows') or []),
            "yt_video_conclusion_count": len(st.session_state.get('yt_video_conclusions') or {}),
            "bet_plan_ticket_count": len((st.session_state.get('bet_plan_result') or {}).get('tickets') or []),
        },
        "web_raw": st.session_state.get('web_raw') or [],
        "youtube_raw": st.session_state.get('youtube_raw') or [],
        "web_articles": st.session_state.get('web_articles') or [],
        "race_characteristics": st.session_state.get('race_characteristics'),
        "doc_horse_raw": st.session_state.get('doc_horse_raw') or [],
        "x_raw": st.session_state.get('x_raw') or [],
        "x_tweets": st.session_state.get('x_tweets') or [],
        "training_items": st.session_state.get('training_items') or [],
        "training_time_rows": st.session_state.get('training_time_rows') or [],
        "yt_detail_analysis": st.session_state.get('yt_detail_analysis') or {},
        "yt_video_conclusions": st.session_state.get('yt_video_conclusions') or {},
        "latest_odds": st.session_state.get('latest_odds') or {},
        "latest_odds_error": st.session_state.get('latest_odds_error') or "",
        "bet_plan_settings": st.session_state.get('bet_plan_settings') or {},
        "bet_plan_result": st.session_state.get('bet_plan_result') or {},
        "bet_type_odds": st.session_state.get('bet_type_odds') or {},
    }
    tmp_path = cache_path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cache_path)  # 原子的リネーム（書き込み中断による破損防止）
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return

    # gitに自動コミット（キャッシュファイルのみ、失敗しても検索処理には影響しない）
    try:
        _repo_dir = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(
            ["git", "add", "--", cache_path],
            cwd=_repo_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
        )
        # cache_path のみをコミット（他のstaged変更を巻き込まない）
        subprocess.run(
            ["git", "commit", "-m", f"update search cache: {race_key}", "--", cache_path],
            cwd=_repo_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass


def load_race_cache(race_key: str) -> bool:
    """キャッシュファイルが存在すればセッションステートに復元し、horse_dfを再集計する"""
    cache_path = _get_cache_path(race_key)
    if not os.path.exists(cache_path):
        return False
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    st.session_state['web_raw'] = data.get('web_raw', [])
    st.session_state['youtube_raw'] = data.get('youtube_raw', [])
    st.session_state['web_articles'] = data.get('web_articles', [])
    st.session_state['doc_horse_raw'] = data.get('doc_horse_raw', [])
    st.session_state['x_raw'] = data.get('x_raw', [])
    st.session_state['x_tweets'] = data.get('x_tweets', [])
    st.session_state['yt_detail_analysis'] = data.get('yt_detail_analysis', {})
    st.session_state['yt_video_conclusions'] = data.get('yt_video_conclusions', {})
    st.session_state['training_time_rows'] = data.get('training_time_rows', [])
    st.session_state['latest_odds'] = data.get('latest_odds', {}) or {}
    st.session_state['bet_plan_settings'] = data.get('bet_plan_settings', {}) or {}
    st.session_state['bet_plan_result'] = data.get('bet_plan_result', {}) or {}
    st.session_state['bet_type_odds'] = data.get('bet_type_odds', {}) or {}
    if data.get('latest_odds_error'):
        st.session_state['latest_odds_error'] = data.get('latest_odds_error')
    else:
        st.session_state.pop('latest_odds_error', None)

    # 旧キャッシュ混在対策: 現在レースに未言及のX投稿はロード時に除外
    current_race = get_race_config()
    current_race_name = _to_text(getattr(current_race, "race_name", ""))
    if current_race_name and st.session_state['x_tweets']:
        filtered_tweets, _ = _filter_x_tweets_by_race_name(st.session_state['x_tweets'], current_race_name)
        st.session_state['x_tweets'] = filtered_tweets

    # since_id用の最新ID復元
    newest_id = data.get('meta', {}).get('x_newest_id')
    if newest_id:
        st.session_state['x_newest_id'] = newest_id

    # race_characteristics は値がある場合のみセット（None/欠損 → main()でAPIを再トリガー）
    rc = data.get('race_characteristics')
    if rc:
        st.session_state['race_characteristics'] = rc
    st.session_state['race_characteristics_enriched'] = _has_meaningful_race_characteristics(
        st.session_state.get('race_characteristics')
    )
    st.session_state.pop('race_characteristics_last_attempt', None)
    st.session_state.pop('race_characteristics_last_error', None)

    # horse_df を全rawデータから再集計
    horse_df = aggregate_horse_analysis(
        st.session_state['youtube_raw'],
        st.session_state['web_raw'],
        st.session_state['doc_horse_raw'],
        st.session_state.get('x_raw', []),
    )
    st.session_state['horse_df'] = horse_df

    # 追切データを再生成（yt_detail_analysis含む全ソースから）
    refresh_training_state(preserve_existing_time_rows=True)
    return True


def get_minimal_race_characteristics() -> dict:
    """Gemini失敗時のフォールバック: RaceInfoから最小限のレース特徴を組み立て"""
    r = get_race_config()
    if not r:
        return {}
    return {
        "コース特徴": f"{r.venue}競馬場 {r.surface}{r.distance}",
        "注目ポイント": f"{r.grade}レース",
    }


def _has_meaningful_race_characteristics(info: dict | None) -> bool:
    """レース特徴が最小フォールバックを超えて取得できているか判定する。"""
    if not isinstance(info, dict) or not info:
        return False
    important_keys = (
        "コース特徴",
        "過去の傾向",
        "勝ちやすい馬のタイプ",
        "苦手な馬のタイプ",
        "枠順有利",
        "枠順不利",
        "騎手厩舎傾向",
        "注目ポイント",
    )
    non_empty = sum(1 for key in important_keys if _to_text(info.get(key)))
    # 最小フォールバックは概ね2項目なので、3項目以上を「有意」とみなす
    return non_empty >= 3


def _to_text(value) -> str:
    """任意の値を表示/連結向けに安全に文字列化する。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False).strip()
    return str(value).strip()


def _find_balanced_json_block(text: str, opening: str, closing: str) -> str:
    """文字列中から最初のバランスしたJSONブロックを抽出する。"""
    if not text:
        return ""

    start = text.find(opening)
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]

            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    return text[start:idx + 1]

        start = text.find(opening, start + 1)

    return ""


def _parse_gemini_json_response(response_text: str, expected: str = "list"):
    """
    GeminiレスポンスからJSONを頑健に抽出・パースする。
    expected: 'list' or 'dict'
    """
    text = (response_text or "").strip()
    if not text:
        raise ValueError("Gemini response is empty")

    candidates: list[str] = []

    for pattern in (r"```json\s*(.*?)\s*```", r"```\s*(.*?)\s*```"):
        for match in re.finditer(pattern, text, re.DOTALL):
            body = (match.group(1) or "").strip()
            if body:
                candidates.append(body)

    candidates.append(text)

    if expected == "dict":
        block = _find_balanced_json_block(text, "{", "}")
    else:
        block = _find_balanced_json_block(text, "[", "]")
    if block:
        candidates.append(block)

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        if expected == "dict" and isinstance(parsed, dict):
            return parsed
        if expected == "list" and isinstance(parsed, list):
            return parsed

    raise ValueError(f"Could not parse {expected} JSON from Gemini response")


def _merge_video_conclusion(base: dict, extra: dict) -> dict:
    """動画結論dictを欠損補完しながらマージする。"""
    merged = dict(base or {})
    for k, v in (extra or {}).items():
        val = _to_text(v)
        if val:
            merged[k] = val
    return merged


def _is_unknown_like_text(text: str) -> bool:
    """「不明/なし」系のプレースホルダー文言かを判定する。"""
    normalized = unicodedata.normalize("NFKC", _to_text(text)).strip().lower()
    if not normalized:
        return True

    normalized = re.sub(r"[。．.!！?？\s]+$", "", normalized)
    unknown_tokens = {
        "不明", "不詳", "なし", "無し", "該当なし", "未記載", "未言及", "未定", "未発表",
        "n/a", "na", "-", "ー", "unknown", "none",
    }
    if normalized in unknown_tokens:
        return True
    if re.fullmatch(r"(不明|不詳|該当なし|未記載|未言及|未定|未発表)(です|でした)?", normalized):
        return True
    return False


def _has_meaningful_video_conclusion(conclusion: dict | None) -> bool:
    """本命/対抗などの印情報が1つでもあるか判定する。"""
    if not isinstance(conclusion, dict):
        return False
    pick_keys = ("本命", "対抗", "単穴", "連下", "危険な人気馬")
    return any(_to_text(conclusion.get(k)) for k in pick_keys)


def _normalize_youtube_analysis_rows(rows: list[dict], horse_names: list[str]) -> list[dict]:
    """YouTube抽出結果の行を正規化し、無効な行を除外する。"""
    normalized_rows = []
    seen = set()
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        horse_raw = _to_text(item.get("馬名"))
        plus = _to_text(item.get("プラス情報"))
        minus = _to_text(item.get("マイナス情報"))
        if not horse_raw or _is_unknown_like_text(horse_raw):
            continue
        if horse_raw in {"動画結論", "全体結論", "全体的な予想", "結論"}:
            continue
        if not plus and not minus:
            continue

        horse_name = _match_horse_name_from_text(horse_raw, horse_names) or horse_raw
        key = (horse_name, plus, minus)
        if key in seen:
            continue
        seen.add(key)
        normalized_rows.append({
            "馬名": horse_name,
            "プラス情報": plus or "特になし",
            "マイナス情報": minus or "特になし",
        })
    return normalized_rows


def _find_horses_in_text(text: str, horse_names: list[str], limit: int = 6) -> list[str]:
    """テキスト中に含まれる馬名を出現順に抽出する。"""
    raw = unicodedata.normalize("NFKC", _to_text(text))
    if not raw or not horse_names:
        return []

    hits = []
    for horse in sorted(horse_names, key=len, reverse=True):
        normalized_horse = unicodedata.normalize("NFKC", _to_text(horse))
        if normalized_horse and normalized_horse in raw:
            idx = raw.find(normalized_horse)
            hits.append((idx, horse))

    hits.sort(key=lambda x: x[0])
    ordered = []
    seen = set()
    for _, horse in hits:
        if horse in seen:
            continue
        seen.add(horse)
        ordered.append(horse)
        if len(ordered) >= limit:
            break
    return ordered


def _extract_video_conclusion_from_text(text: str, horse_names: list[str]) -> dict:
    """字幕/概要欄テキストから本命・対抗などの印をルールベース抽出する。"""
    raw = _to_text(text)
    if not raw or not horse_names:
        return {}

    label_patterns = {
        "本命": [r"(?:本命|◎)"],
        "対抗": [r"(?:対抗|○)"],
        "単穴": [r"(?:単穴|▲)"],
        "危険な人気馬": [r"(?:危険(?:な)?人気馬|危険馬|消し)"],
        "連下": [r"(?:連下|抑え|△)"],
    }
    extracted = {}

    for label, patterns in label_patterns.items():
        for pat in patterns:
            found = False
            for match in re.finditer(pat, raw):
                snippet = raw[max(0, match.start() - 8): min(len(raw), match.end() + 80)]
                if label == "連下":
                    horses = _find_horses_in_text(snippet, horse_names, limit=5)
                    if horses:
                        extracted[label] = "、".join(horses)
                        found = True
                        break
                else:
                    horse = _match_horse_name_from_text(snippet, horse_names)
                    if horse:
                        extracted[label] = horse
                        found = True
                        break
            if found:
                break

    return extracted


def _extract_video_conclusion_fields(payload: dict) -> dict:
    """Geminiの結論JSONから本命/対抗などの標準キーを抽出する。"""
    if not isinstance(payload, dict):
        return {}

    key_aliases = {
        "本命": ["本命", "◎", "honmei", "main_pick"],
        "対抗": ["対抗", "○", "taiko", "second_pick"],
        "単穴": ["単穴", "▲", "tanan", "third_pick", "穴"],
        "連下": ["連下", "抑え", "△", "renshita", "support"],
        "危険な人気馬": ["危険な人気馬", "危険馬", "消し", "danger_pick"],
        "買い目方針": ["買い目方針", "買い目", "馬券方針", "bet_plan", "結論サマリー", "結論"],
    }

    extracted = {}
    for canonical, aliases in key_aliases.items():
        value = ""
        for key in aliases:
            candidate = _to_text(payload.get(key))
            if not candidate or _is_unknown_like_text(candidate):
                continue
            value = candidate
            if value:
                break
        if value:
            extracted[canonical] = value
    return extracted


def _is_video_conclusion_item(item: dict) -> bool:
    """list形式レスポンス中の「動画結論」行かどうかを判定する。"""
    if not isinstance(item, dict):
        return False

    kind = _to_text(item.get("種別") or item.get("type")).lower()
    if kind in {"動画結論", "結論", "video_conclusion", "conclusion"}:
        return True

    horse_name = _to_text(item.get("馬名"))
    if horse_name in {"動画結論", "全体結論", "結論"}:
        return True

    has_pick_keys = any(_to_text(item.get(k)) for k in ("本命", "対抗", "単穴", "連下", "危険な人気馬", "買い目方針"))
    has_horse_fields = any(_to_text(item.get(k)) for k in ("馬名", "プラス情報", "マイナス情報"))
    return has_pick_keys and not has_horse_fields


def _extract_youtube_analysis_payload(response_text: str) -> tuple[list[dict], dict]:
    """
    YouTube解析レスポンスから
    - 馬別評価list
    - 動画結論dict（本命/対抗/単穴/連下/危険な人気馬/買い目方針）
    を抽出する。dict形式・list形式の両方に対応。
    """
    horse_names = get_all_horse_names()

    # 1) 推奨形式: dict
    try:
        parsed_dict = _parse_gemini_json_response(response_text, expected="dict")
    except ValueError:
        parsed_dict = None

    if isinstance(parsed_dict, dict):
        conclusion = {}
        for key in ("動画結論", "結論", "video_conclusion"):
            candidate = parsed_dict.get(key)
            if isinstance(candidate, dict):
                conclusion = _merge_video_conclusion(conclusion, _extract_video_conclusion_fields(candidate))
        # 結論がトップレベルに直接出てくる場合にも対応
        conclusion = _merge_video_conclusion(conclusion, _extract_video_conclusion_fields(parsed_dict))

        horse_list = []
        for key in ("馬別評価", "horses", "horse_analysis", "analysis", "items", "results"):
            candidate = parsed_dict.get(key)
            if isinstance(candidate, list):
                horse_list = [x for x in candidate if isinstance(x, dict)]
                break

        if not horse_list and any(k in parsed_dict for k in ("馬名", "プラス情報", "マイナス情報")):
            horse_list = [parsed_dict]

        cleaned = []
        for item in horse_list:
            if _is_video_conclusion_item(item):
                conclusion = _merge_video_conclusion(conclusion, _extract_video_conclusion_fields(item))
                continue
            cleaned.append(item)
        return _normalize_youtube_analysis_rows(cleaned, horse_names), conclusion

    # 2) 互換形式: list
    parsed_list = _parse_gemini_json_response(response_text, expected="list")
    conclusion = {}
    cleaned = []
    for item in parsed_list:
        if not isinstance(item, dict):
            continue
        if _is_video_conclusion_item(item):
            conclusion = _merge_video_conclusion(conclusion, _extract_video_conclusion_fields(item))
            continue
        cleaned.append(item)
    return _normalize_youtube_analysis_rows(cleaned, horse_names), conclusion


def _youtube_model_candidates() -> list[str]:
    """YouTube解析で利用するモデル候補を優先順で返す。"""
    models = []
    for model_name in (GEMINI_MODEL_YOUTUBE, GEMINI_MODEL):
        name = (model_name or "").strip()
        if name and name not in models:
            models.append(name)
    return models


def _generate_content_with_youtube_model(client, contents):
    """
    YouTube解析専用モデルで生成し、モデル未対応/一時障害時は共通モデルへフォールバックする。
    """
    candidates = _youtube_model_candidates()
    if not candidates:
        raise ValueError("Gemini model is not configured")

    last_error = None
    for idx, model_name in enumerate(candidates):
        try:
            return client.models.generate_content(
                model=model_name,
                contents=contents
            )
        except Exception as e:
            last_error = e
            msg = (str(e) or "").lower()
            is_model_error = any(token in msg for token in ("not found", "unknown model", "unsupported model", "404"))
            is_transient_error = _is_transient_gemini_error(msg)
            if idx < len(candidates) - 1 and (is_model_error or is_transient_error):
                if is_transient_error:
                    time.sleep(1.2)
                continue
            raise

    if last_error:
        raise last_error
    raise RuntimeError("Failed to generate content with YouTube model")

# ====================
# 全出走馬名取得
# ====================

@st.cache_data
def get_all_horse_names(csv_path=None):
    """CSVから全出走馬名リストを取得する（キャッシュ付き）"""
    if csv_path is None:
        csv_path = get_csv_path()
    try:
        if csv_path and os.path.exists(csv_path):
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
            if '馬名' in df.columns:
                return df['馬名'].dropna().tolist()
    except Exception:
        pass
    return []


# ====================
# YouTube関連関数
# ====================

@st.cache_data(ttl=3600)  # 1時間キャッシュ（API使用量を節約）
def search_youtube_videos(keyword, max_results=5):
    """
    YouTubeから指定したキーワードで動画を検索する関数

    引数:
        keyword (str): 検索キーワード
        max_results (int): 取得する動画の最大件数（デフォルト: 5）

    戻り値:
        list: 動画情報の辞書のリスト（エラー時は空のリスト）
    """
    # APIキーが設定されていない場合のエラーハンドリング
    if YOUTUBE_API_KEY == "YOUR_API_KEY_HERE" or not YOUTUBE_API_KEY:
        st.warning("⚠️ YouTube APIキーが設定されていません。app.pyの YOUTUBE_API_KEY を設定してください。")
        return []

    try:
        # YouTube Data API v3 クライアントを構築
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

        # 検索リクエストを実行
        # viewCount順は公式動画・レース映像が上位化しやすいため、relevance順を優先
        search_response = youtube.search().list(
            q=keyword,  # 検索キーワード
            part='id,snippet',  # 取得する情報（IDとスニペット）
            maxResults=max_results,  # 最大取得件数
            type='video',  # 動画のみ検索
            order='relevance',  # 関連度順
            regionCode='JP',  # 日本向けの結果を優先
            relevanceLanguage='ja'  # 日本語の動画を優先
        ).execute()

        videos = []

        # 検索結果から動画情報を抽出
        for item in search_response.get('items', []):
            video_id = item['id']['videoId']
            snippet = item['snippet']

            video_info = {
                'video_id': video_id,
                'title': snippet['title'],
                'description': snippet['description'],
                'channel_title': snippet['channelTitle'],
                'published_at': snippet['publishedAt'],
                'thumbnail_url': snippet['thumbnails']['high']['url'],
                'video_url': f"https://www.youtube.com/watch?v={video_id}"
            }

            videos.append(video_info)

        return videos

    except HttpError as e:
        st.error(f"❌ YouTube API エラー: {e}")
        return []
    except Exception as e:
        st.error(f"❌ 予期しないエラー: {e}")
        return []


def _normalize_text_for_match(text: str) -> tuple[str, str]:
    raw = unicodedata.normalize("NFKC", str(text or "")).lower()
    spaced = re.sub(r"\s+", " ", raw).strip()
    compact = re.sub(r"\s+", "", spaced)
    return spaced, compact


def _text_contains_term(text: str, term: str) -> bool:
    text_spaced, text_compact = _normalize_text_for_match(text)
    term_spaced, term_compact = _normalize_text_for_match(term)
    if not term_spaced:
        return False
    if term_spaced in text_spaced:
        return True
    if term_compact and term_compact in text_compact:
        return True
    if term_compact and f"#{term_compact}" in text_compact:
        return True
    return False


def _build_youtube_race_terms() -> list[str]:
    r = get_race_config()
    if not r:
        return []
    race_name = str(getattr(r, "race_name", "") or "").strip()
    if not race_name:
        return []

    normalized = unicodedata.normalize("NFKC", race_name)
    compact = re.sub(r"\s+", "", normalized)
    no_year = re.sub(r"(20\d{2}|令和\d+年?)", "", compact)
    no_round = re.sub(r"第\d+回", "", no_year)

    terms: list[str] = []
    for item in (normalized, compact, no_year, no_round):
        val = item.strip(" #")
        if not val or val in terms:
            continue
        terms.append(val)
    return terms[:8]


def _extract_race_like_mentions(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    pattern = re.compile(r"[A-Za-z0-9ぁ-ヿ㐀-鿿]{2,30}(?:賞|ステークス|カップ|記念|ジャンプ|トロフィー)")
    found = pattern.findall(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = re.sub(r"\s+", "", item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _title_has_non_target_race_mentions(title: str, race_terms: list[str]) -> bool:
    mentions = _extract_race_like_mentions(title)
    if not mentions:
        return False
    target_compacts = {_normalize_text_for_match(term)[1] for term in race_terms if term}
    target_compacts = {x for x in target_compacts if x}
    if not target_compacts:
        return False

    for mention in mentions:
        mention_compact = _normalize_text_for_match(mention)[1]
        if not mention_compact:
            continue
        if any(tc in mention_compact or mention_compact in tc for tc in target_compacts):
            continue
        return True
    return False


def filter_relevant_videos(videos):
    """
    予想に関係する動画を優先し、公式映像・レース中継系を除外する。
    レース名指定時は対象レースへの言及を必須化し、別レース混入を抑える。
    """
    if not videos:
        return []

    include_keywords = ["予想", "本命", "対抗", "穴", "買い目", "印", "展開", "見解", "考察", "馬券", "調教", "追い切り", "追切"]
    exclude_keywords = [
        "jra公式", "公式", "ライブ", "生中継", "レース映像", "レース動画",
        "ハイライト", "cm", "pv", "出走馬紹介", "パドック", "払戻", "結果速報"
    ]
    exclude_channel_tokens = ["jra", "日本中央競馬会", "netkeiba", "グリーンチャンネル", "tbs", "フジ"]

    race_terms = _build_youtube_race_terms()
    strict_race = bool(race_terms)
    if not race_terms:
        race_terms = ["競馬", "予想"]

    scored = []
    desc_only_candidates = []

    for v in videos:
        title_raw = str(v.get('title') or '')
        desc_raw = str(v.get('description') or '')[:800]
        channel = (v.get('channel_title') or '').lower()
        text = f"{title_raw} {desc_raw}"

        if any(token in channel for token in [t.lower() for t in exclude_channel_tokens]):
            continue

        title_has_target = any(_text_contains_term(title_raw, term) for term in race_terms)
        desc_has_target = any(_text_contains_term(desc_raw, term) for term in race_terms)
        text_has_target = title_has_target or desc_has_target

        if strict_race and not text_has_target:
            continue
        if strict_race and not title_has_target:
            if _title_has_non_target_race_mentions(title_raw, race_terms):
                continue
            if desc_has_target:
                desc_only_candidates.append((1, v))
            continue

        score = 0
        for k in include_keywords:
            if _text_contains_term(text, k):
                score += 2
        if title_has_target:
            score += 5
        if desc_has_target:
            score += 2
        for k in exclude_keywords:
            if _text_contains_term(text, k):
                score -= 3

        threshold = 3 if strict_race else 2
        if score >= threshold:
            scored.append((score, v))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return [v for _, v in scored]

    if strict_race and desc_only_candidates:
        desc_only_candidates.sort(key=lambda x: x[0], reverse=True)
        return [v for _, v in desc_only_candidates]

    relaxed = [v for v in videos if any(_text_contains_term(f"{v.get('title', '')} {v.get('description', '')}", term) for term in race_terms)]
    if relaxed:
        return relaxed
    return [] if strict_race else videos


@st.cache_data(ttl=3600)
def fetch_video_transcript(video_id, max_chars=2000):
    """
    YouTube動画の字幕（自動生成含む）を取得して文字列で返す。
    日本語字幕を優先し、なければ英語を試みる。
    取得失敗時は空文字列を返す（descriptionにフォールバック）。
    youtube-transcript-api v1.x 対応（api.fetch() / s.text を使用）。
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=['ja', 'en'])
        text = ' '.join(s.text for s in fetched)
        return text[:max_chars]
    except Exception:
        return ""


def extract_key_points(text, keywords):
    """
    テキストから指定したキーワードを含む文を抽出する関数

    引数:
        text (str): 抽出対象のテキスト
        keywords (list): 検索するキーワードのリスト

    戻り値:
        list: キーワードを含む文のリスト
    """
    if not text:
        return []

    # テキストを文単位に分割（句点で区切る）
    sentences = re.split(r'[。\n]', text)

    key_points = []

    # 各文をチェック
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # いずれかのキーワードが含まれているか確認
        for keyword in keywords:
            if keyword in sentence:
                # 重複を避けるため、まだリストにない場合のみ追加
                if sentence not in key_points:
                    key_points.append(sentence)
                break  # 1つの文に複数キーワードがあっても1回だけ追加

    return key_points


def extract_horse_names_from_text(text):
    """
    テキストから馬名を抽出する関数

    引数:
        text (str): 検索対象のテキスト

    戻り値:
        list: 抽出された馬名のリスト
    """
    if not text:
        return []

    found_horses = []

    # CSVの全出走馬名から検索
    for name in get_all_horse_names():
        if name in text:
            found_horses.append(name)

    return found_horses


def _build_youtube_fallback_payload(video: dict, transcript: str, description: str) -> tuple[list[dict], dict]:
    """
    Geminiが一時障害で失敗した場合の簡易フォールバック。
    字幕/概要欄/タイトルの馬名言及のみを抽出して最小限の結果を返す。
    """
    title = _to_text((video or {}).get('title'))
    transcript_text = _to_text(transcript)
    description_text = _to_text(description)
    source_text = "\n".join([x for x in (transcript_text, description_text, title) if x])

    horse_names = extract_horse_names_from_text(source_text)[:8]
    analysis_results = []
    for horse in horse_names:
        clues = []
        if transcript_text and horse in transcript_text:
            clues.append("字幕で言及")
        if description_text and horse in description_text:
            clues.append("概要欄で言及")
        if not clues:
            clues.append("タイトル/本文で言及")

        analysis_results.append({
            "馬名": horse,
            "プラス情報": "・".join(clues) + "（Gemini一時障害時の簡易抽出）",
            "マイナス情報": "特になし（Gemini復旧後の再解析を推奨）",
        })

    if analysis_results:
        conclusion = {"買い目方針": "Gemini一時障害のため、馬名言及ベースの簡易抽出結果です。"}
        return analysis_results, conclusion
    return [], {}


def _analyze_video_with_direct_url(video: dict, prompt: str) -> tuple[list[dict], dict]:
    """YouTube URL を Gemini に直接渡して解析する。"""
    video_url = _to_text((video or {}).get("video_url"))
    if not GEMINI_API_KEY or not video_url:
        return [], {}

    client = google_genai.Client(api_key=GEMINI_API_KEY)
    last_error = None
    for attempt in range(3):
        try:
            response = _generate_content_with_youtube_model(
                client,
                [
                    genai_types.Part(
                        file_data=genai_types.FileData(
                            file_uri=video_url,
                            mime_type='video/mp4'
                        )
                    ),
                    prompt
                ]
            )
            response_text = _to_text(response.text)
            if not response_text:
                raise ValueError("Empty response text from Gemini")
            return _extract_youtube_analysis_payload(response_text)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            break
        except Exception as e:
            last_error = e
            if _is_transient_gemini_error(str(e)) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            break

    if last_error and _is_transient_gemini_error(str(last_error)):
        raise RuntimeError(f"Gemini temporary error during direct video analysis: {type(last_error).__name__}")
    return [], {}


def analyze_video_with_gemini(video):
    """
    Gemini APIを使って動画のタイトルと概要欄を解析し、馬名とプラス/マイナス情報を抽出する関数

    引数:
        video (dict): 動画情報（title, description, video_urlを含む）

    戻り値:
        tuple: (馬別分析list, 動画結論dict)
    """
    # APIキーが設定されていない場合
    if GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE" or not GEMINI_API_KEY:
        return [], {}

    horse_names = get_all_horse_names()

    def _build_prompt(content_label: str, content: str) -> str:
        # Gemini に送るプロンプトを作成（前走成績・調教・調子を具体的に抽出）
        return f"""
あなたは競馬予想の専門家です。以下のYouTube動画のタイトルと{content_label}を読み、各馬の詳細な評価情報を抽出してください。

# 動画タイトル
{video['title']}

# {content_label}
{content}

# 注目すべき出走馬（これら以外の馬名が登場しても抽出してください）
{chr(10).join(['- ' + name for name in horse_names[:12]])}

# 抽出してほしい情報（各馬について）
プラス情報として以下を重点的に探してください：
- 前走・近走の成績（例：「前走G2優勝」「3連勝中」「重賞実績あり」）
- 調教・追切の様子（例：「最終追切で好時計」「動き抜群」「好調仕上がり」）
- 追切・調教タイム（例：「坂路4F52.3」「CW6F82.1」「終い11.4」）がある場合は数値を必ず残す
- 体調・調子（例：「状態上昇中」「気配良好」「充実期」）
- コース・距離適性（例：「東京ダート1600m得意」「左回り巧者」）
- 騎手・厩舎の強み（例：「ルメール騎手で信頼度高い」「名手とのコンビ」）
- その他の好材料

マイナス情報として以下を重点的に探してください：
- 前走・近走での敗因（例：「前走惨敗」「近走凡走続き」）
- 調教不安（例：「追切動き平凡」「仕上がり遅れ気味」）
- コース・距離の不安（例：「距離短縮が課題」「東京コースは初」）
- 枠順・展開の不安（例：「外枠で先行困難」）
- その他の懸念点

# 出力形式
以下のJSON形式で**必ず**出力してください（説明文は一切不要）：

```json
{{
  "動画結論": {{
    "本命": "馬名（なければ不明）",
    "対抗": "馬名（なければ不明）",
    "単穴": "馬名（なければ不明）",
    "連下": "馬名をカンマ区切り（なければ不明）",
    "危険な人気馬": "馬名（なければ不明）",
    "買い目方針": "馬券の組み立て方・結論要約（1～2文）"
  }},
  "馬別評価": [
    {{
      "馬名": "馬の名前",
      "プラス情報": "前走成績・調教・追切タイム・調子・適性など具体的な好材料を2～3文で詳しく記載",
      "マイナス情報": "具体的な懸念点・不安材料を記載（なければ「特になし」）"
    }}
  ]
}}
```

# 注意事項
- 概要欄に情報がなくても、タイトルから推測して記載してよい
- 馬名が全く見当たらない場合は「馬別評価」を空配列にしてよい
- プラス情報は「特になし」にせず、必ず何か記載すること
- JSONのみ出力し、前後に説明文を付けないこと
"""

    try:
        # 字幕を優先し、失敗時は概要欄へフォールバック
        transcript = fetch_video_transcript(video['video_id'])
        description = video.get('description', '') or ''
        title = video.get('title', '') or ''
        combined_text_hint = "\n".join([x for x in (transcript, description, title) if x])
        content_candidates = []
        if transcript:
            content_candidates.append(("字幕（音声内容）", transcript))
        if description:
            content_candidates.append(("概要欄", description))
        if not content_candidates:
            content_candidates.append(("タイトル", video.get('title', '') or ''))

        # 新しいSDK（google-genai）でクライアントを作成
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        # 各コンテンツ候補に対してリトライ付きで解析
        last_error = None
        best_analysis_results = []
        best_conclusion = {}
        for content_label, content in content_candidates:
            prompt = _build_prompt(content_label, content)
            for attempt in range(3):
                try:
                    response = _generate_content_with_youtube_model(client, prompt)
                    response_text = response.text
                    if not response_text:
                        break

                    analysis_results, video_conclusion = _extract_youtube_analysis_payload(response_text)
                    analysis_results = _normalize_youtube_analysis_rows(analysis_results, horse_names)
                    rule_conclusion = _extract_video_conclusion_from_text(content, horse_names)
                    video_conclusion = _merge_video_conclusion(video_conclusion, rule_conclusion)
                    for result in analysis_results:
                        result['video_url'] = video['video_url']
                        result['video_title'] = video['title']

                    if analysis_results and not best_analysis_results:
                        best_analysis_results = analysis_results
                    if video_conclusion:
                        best_conclusion = _merge_video_conclusion(best_conclusion, video_conclusion)

                    # 馬別情報、または本命/対抗などの印情報が取れたら成功扱い
                    if analysis_results or _has_meaningful_video_conclusion(video_conclusion):
                        return analysis_results, video_conclusion

                    # 空抽出は次候補へフォールバック
                    break
                except (json.JSONDecodeError, ValueError) as e:
                    # JSON解析失敗は次候補へフォールバック
                    last_error = e
                    break
                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    if _is_transient_gemini_error(error_msg) and attempt < 2:
                        time.sleep(3 * (attempt + 1))
                        continue
                    break

        # 字幕/概要欄ベースで印情報が弱い場合は、動画URLを直接解析して補完
        if _to_text(video.get('video_url')):
            direct_prompt = _build_prompt("動画メタ情報（補助）", description or title or get_race_display_name())
            direct_results, direct_conclusion = _analyze_video_with_direct_url(video, direct_prompt)
            direct_results = _normalize_youtube_analysis_rows(direct_results, horse_names)
            direct_conclusion = _merge_video_conclusion(
                direct_conclusion,
                _extract_video_conclusion_from_text(combined_text_hint, horse_names)
            )
            for result in direct_results:
                result['video_url'] = video['video_url']
                result['video_title'] = video['title']

            if direct_results:
                best_analysis_results = direct_results
            if direct_conclusion:
                best_conclusion = _merge_video_conclusion(best_conclusion, direct_conclusion)

            if direct_results or _has_meaningful_video_conclusion(direct_conclusion):
                return direct_results, direct_conclusion

        if best_analysis_results or best_conclusion:
            return best_analysis_results, best_conclusion

        if last_error and _is_transient_gemini_error(str(last_error)):
            fallback_results, fallback_conclusion = _build_youtube_fallback_payload(
                video=video,
                transcript=transcript,
                description=description,
            )
            fallback_results = _normalize_youtube_analysis_rows(fallback_results, horse_names)
            fallback_conclusion = _merge_video_conclusion(
                fallback_conclusion,
                _extract_video_conclusion_from_text(combined_text_hint, horse_names)
            )
            if fallback_results or fallback_conclusion:
                for result in fallback_results:
                    result['video_url'] = video['video_url']
                    result['video_title'] = video['title']
                return fallback_results, fallback_conclusion
            raise RuntimeError(f"Gemini temporary error after retries: {type(last_error).__name__}")
        return [], {}
    except Exception as e:
        error_msg = str(e)
        # 一時障害は呼び出し元で表示するため再送
        if _is_transient_gemini_error(error_msg):
            raise
        # それ以外の予期しないエラーのみ表示
        st.warning(f"⚠️ 動画の解析をスキップしました: {type(e).__name__}")
        return [], {}


def _analyze_one_video_worker(video, prompt_template):
    """
    1動画を解析するワーカー関数。ThreadPoolExecutorから呼ばれる。
    Streamlit APIは呼ばない（スレッドアンセーフのため）。
    """
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    for retry in range(3):
        try:
            response = _generate_content_with_youtube_model(
                client,
                [
                    genai_types.Part(
                        file_data=genai_types.FileData(
                            file_uri=video['video_url'],
                            mime_type='video/mp4'
                        )
                    ),
                    prompt_template
                ]
            )
            response_text = response.text or ""
            results = _parse_gemini_json_response(response_text, expected="list")
            for r in results:
                r['video_url'] = video['video_url']
                r['video_title'] = video['title']
            return results
        except (json.JSONDecodeError, ValueError):
            return []
        except Exception as e:
            error_msg = str(e)
            if _is_transient_gemini_error(error_msg):
                if retry < 2:
                    time.sleep(3 * (retry + 1))  # 3秒、6秒で再試行
                else:
                    return []
            else:
                return []
    return []


def analyze_all_videos_with_gemini(videos, horse_names=None, status_placeholder=None):
    """
    YouTube動画リストをGemini APIで解析する。
    各動画のURLをGeminiに直接渡して動画を視聴・解析させる（1動画1APIコール）。

    引数:
        videos (list): 動画情報のリスト
        horse_names (list): 全出走馬名リスト（Noneの場合はCSVから自動取得）
        status_placeholder: st.empty()のプレースホルダー（進捗表示用、省略可）

    戻り値:
        list: 抽出された情報のリスト（馬名、プラス情報、マイナス情報、video_url、video_titleを含む辞書）
    """
    if not videos or not GEMINI_API_KEY:
        return []

    if horse_names is None:
        horse_names = get_all_horse_names()

    race_name = get_race_display_name()
    all_horses_str = "\n".join([f"- {name}" for name in horse_names])

    prompt_template = f"""この動画は{race_name}の競馬予想動画です。
動画の内容を視聴し、以下の出走馬について評価情報を抽出してください。

# {race_name} 全出走馬リスト
{all_horses_str}

# 抽出してほしい情報（各馬について）
プラス情報: 前走・近走の成績、調教・追切の様子、追切タイム（数値を保持）、体調・調子、コース・距離適性、騎手・厩舎の強み
マイナス情報: 前走・近走での敗因、調教不安、コース・距離の不安、枠順・展開の不安

# 出力形式
```json
[
  {{
    "馬名": "馬の名前",
    "プラス情報": "具体的な好材料を2～3文で記載（追切タイムがあれば数値を含める）",
    "マイナス情報": "具体的な懸念点を記載（なければ「特になし」）"
  }}
]
```

# 注意事項
- 動画で言及されている馬のみ出力（言及のない馬は出力しない）
- 1本の動画に複数の馬が登場する場合は複数エントリーを出力
- JSONのみ出力し、前後に説明文を付けないこと
"""

    MAX_WORKERS = 2  # 2並列（レート制限リスクと速度のバランス）
    total = len(videos)
    all_results = []
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_video = {
            executor.submit(_analyze_one_video_worker, v, prompt_template): v
            for v in videos
        }
        for future in as_completed(future_to_video):
            completed += 1
            video = future_to_video[future]
            if status_placeholder:
                status_placeholder.info(
                    f"🎬 {completed}/{total}件完了 | 最新: {video['title'][:35]}..."
                )
            try:
                results = future.result()
                if results:
                    all_results.extend(results)
            except Exception:
                pass

    return all_results


def create_summary_dataframe(videos):
    """
    YouTube動画情報から馬名ごとに整理したデータフレームを作成する関数
    各動画のURLをGeminiに直接渡して動画を視聴・解析させる（1動画1APIコール）

    引数:
        videos (list): 動画情報のリスト

    戻り値:
        tuple: (DataFrame, list) — 動画別整理済みDF と 生の分析結果リスト
    """
    status_text = st.empty()
    horse_names = get_all_horse_names()

    n = len(videos)
    est_min = max(1, (n + 1) // 2) * 3  # 2並列、1動画3分として計算
    status_text.info(f"⏱️ {n}件を2並列で解析します（推定 {est_min}〜{est_min + 3} 分）")

    # 各動画のURLをGeminiに直接渡して2並列解析（1動画1APIコール）
    all_analysis_results = analyze_all_videos_with_gemini(
        videos, horse_names=horse_names, status_placeholder=status_text
    )

    status_text.empty()

    # 解析結果をデータフレーム形式に変換
    df_data = []
    for result in all_analysis_results:
        row = {
            '馬名': result.get('馬名', '不明'),
            'プラス情報': result.get('プラス情報', '特になし'),
            'プラス出典': f"[{result.get('video_title', '')[:40]}...]({result.get('video_url', '')})",
            'マイナス情報': result.get('マイナス情報', '特になし'),
            'マイナス出典': f"[{result.get('video_title', '')[:40]}...]({result.get('video_url', '')})"
        }
        df_data.append(row)

    if df_data:
        df = pd.DataFrame(df_data)
        st.success(f"✅ {len(videos)}本の動画の解析が完了しました！（合計 {len(df_data)} 件の情報を抽出）")
    else:
        df = pd.DataFrame(columns=['馬名', 'プラス情報', 'プラス出典', 'マイナス情報', 'マイナス出典'])
        st.warning("⚠️ 解析結果が空です。Gemini APIキーが設定されているか確認してください。")

    return df, all_analysis_results


@st.cache_data(ttl=3600)
def search_web_articles(query, max_articles=5):
    """
    GeminiのGoogle Searchグラウンディングを使ってWeb記事を検索する関数

    引数:
        query (str): 検索クエリ
        max_articles (int): 取得するソースURLの最大件数

    戻り値:
        list: 記事情報の辞書のリスト
    """
    if not GEMINI_API_KEY:
        return []
    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)
        grounding_tool = genai_types.Tool(google_search=genai_types.GoogleSearch())
        config = genai_types.GenerateContentConfig(tools=[grounding_tool])

        race_name = get_race_display_name()
        all_horse_names = get_all_horse_names()
        horses_str = "、".join(all_horse_names)
        prompt = f"""
{race_name}の予想・各馬分析記事を検索してください。
クエリ: {query}

出走馬: {horses_str}

上記全馬について、競馬評論家やメディアはどのような評価をしていますか？
プラス材料（好材料・強み）とマイナス材料（懸念点・不安材料）を中心に、
できるだけ多くの馬について評価を日本語で詳しくまとめてください。
"""
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )

        snippet_text = response.text or ""
        articles = []
        candidate = response.candidates[0] if response.candidates else None
        if candidate and hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
            chunks = candidate.grounding_metadata.grounding_chunks or []
            seen_urls = set()
            for chunk in chunks:
                if len(articles) >= max_articles:
                    break
                if hasattr(chunk, 'web') and chunk.web:
                    url = chunk.web.uri or ""
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    title = chunk.web.title or url
                    domain = urlparse(url).netloc
                    source_name = domain.replace("www.", "")
                    articles.append({
                        "title": title,
                        "url": url,
                        "source_name": source_name,
                        "snippet": snippet_text,
                        "source_type": "web"
                    })

        # grounding_chunksが取れなくても合成テキストだけ返す
        if not articles and snippet_text:
            articles.append({
                "title": f"Web検索結果: {query[:30]}",
                "url": "",
                "source_name": "Gemini Web Search",
                "snippet": snippet_text,
                "source_type": "web"
            })

        return articles

    except Exception as e:
        error_msg = str(e)
        if _is_transient_gemini_error(error_msg):
            raise
        st.warning(f"⚠️ Web記事の取得に失敗しました: {type(e).__name__} ({error_msg[:120]})")
        return []


def normalize_tavily_results(results, query):
    """
    Tavily検索結果を既存articleスキーマへ正規化する。
    """
    articles = []
    seen_urls = set()

    for item in results or []:
        url = (item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        title = (item.get("title") or "").strip() or url
        snippet = (
            (item.get("raw_content") or "").strip()[:3500]
            or (item.get("content") or "").strip()
            or f"Tavily検索結果: {query}"
        )
        snippet = re.sub(r'\s+', ' ', snippet).strip()
        domain = urlparse(url).netloc.replace("www.", "") if url else "tavily"

        articles.append({
            "title": title,
            "url": url,
            "source_name": domain,
            "snippet": snippet,
            "source_type": "web"
        })

    return articles


def _is_transient_gemini_error(error_msg: str) -> bool:
    """Geminiの一時障害とみなせるエラーかを判定する。"""
    msg = (error_msg or "").lower()
    transient_tokens = (
        "429",
        "resource_exhausted",
        "503",
        "500",
        "unavailable",
        "servererror",
        "internal server error",
        "backend error",
        "upstream",
        "high demand",
        "deadline exceeded",
        "timed out",
        "internal",
    )
    return any(token in msg for token in transient_tokens)


def _contains_japanese_text(text: str) -> bool:
    """文字列に日本語が含まれるかを判定する。"""
    return bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff]', _to_text(text)))


def _extract_query_tokens(query: str) -> list[str]:
    """検索クエリから関連度計算用のトークンを抽出する。"""
    text = _to_text(query)
    if not text:
        return []
    stopwords = {
        "競馬", "予想", "評価", "分析", "全頭", "診断", "記事", "ニュース",
        "レース", "重賞", "g1", "g2", "g3", "2024", "2025", "2026", "2027",
    }
    tokens = []
    seen = set()
    for raw in re.split(r'[\s　,、/・|]+', text):
        token = _to_text(raw).strip().lower()
        if not token:
            continue
        if len(token) <= 1:
            continue
        if token in stopwords:
            continue
        if re.fullmatch(r'\d{2,4}', token):
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens[:12]


def _select_articles_for_analysis(
    articles,
    race_name: str,
    horse_names: list[str],
    query: str = "",
    max_items: int = MAX_ANALYZE_ARTICLES_PER_QUERY,
):
    """
    解析候補記事を関連度で選別する。
    トップページ等より、レース/馬名言及のある記事を優先。
    """
    if not articles:
        return []

    race_tokens = [race_name, race_name.replace(" 2026", "").strip(), race_name.replace(" 2025", "").strip()]
    race_tokens = [t for t in race_tokens if t]
    horse_tokens = [h for h in (horse_names or [])[:12] if h]
    query_tokens = _extract_query_tokens(query)
    expect_ja = _contains_japanese_text(" ".join(race_tokens) + " " + query)

    scored = []
    for article in articles:
        title = str(article.get("title", "") or "")
        snippet = str(article.get("snippet", "") or "")
        url = str(article.get("url", "") or "")
        text = f"{title} {snippet}"
        text_l = text.lower()
        parsed = urlparse(url) if url else None
        host = (parsed.netloc or "").lower() if parsed else ""
        path = (parsed.path or "/") if parsed else "/"

        score = 0
        score += sum(1 for token in race_tokens if token in text) * 3
        score += sum(1 for horse in horse_tokens if horse in text) * 2
        score += sum(1 for token in query_tokens if token and token in text_l) * 2
        if "/db/race/" in url or "/race/" in url:
            score += 2
        if "/racedata/graderace/" in url or "/race_newsdet.php" in url:
            score += 2
        if "/library/detail.html" in url:
            score -= 2
        if "race_calendar" in url:
            score -= 4
        if path in ("", "/"):
            score -= 4
        if "日本最大の競馬情報サービス" in title:
            score -= 3
        if len(snippet) < 120:
            score -= 1
        if expect_ja and not _contains_japanese_text(text):
            score -= 5
        if "en.netkeiba.com" in host and expect_ja:
            score -= 6

        scored.append((score, article))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [article for score, article in scored if score >= 0][:max_items]
    if not selected:
        selected = [scored[0][1]]
    return selected


@st.cache_data(ttl=1800)
def search_web_articles_with_tavily(query, max_articles=5, include_domains=None):
    """
    Tavily APIでWeb記事を検索する関数。
    """
    if not TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not configured")

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": max_articles,
        "search_depth": "advanced",
        "include_answer": False,
        "include_raw_content": True,
        "topic": "general",
    }
    if include_domains:
        payload["include_domains"] = include_domains

    response = requests.post(
        "https://api.tavily.com/search",
        json=payload,
        timeout=25
    )
    if response.status_code != 200:
        raise RuntimeError(f"Tavily API error: {response.status_code} {response.text[:200]}")

    data = response.json()
    return normalize_tavily_results(data.get("results", []), query)


def analyze_web_article_with_gemini(article_info):
    """
    Web記事情報からGeminiで馬別のプラス/マイナス情報を抽出する関数

    引数:
        article_info (dict): 記事情報（title, snippet, url を含む）

    戻り値:
        list: 抽出された情報のリスト（馬名、プラス情報、マイナス情報を含む辞書）
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    title = _to_text(article_info.get('title', '')) if isinstance(article_info, dict) else ""
    snippet = _to_text(article_info.get('snippet', '')) if isinstance(article_info, dict) else ""
    source_url = _to_text(article_info.get('url', '')) if isinstance(article_info, dict) else ""
    source_title = title or "Web記事"
    if not title and not snippet:
        raise ValueError("Web article has no title/snippet")

    all_horse_names = get_all_horse_names()
    horse_list_str = "\n".join([f"- {name}" for name in all_horse_names])

    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""
あなたは競馬予想の専門家です。以下のWeb記事の情報を読み、各馬の詳細な評価情報を抽出してください。

# 記事タイトル
{source_title}

# 記事内容（要約）
{snippet}

# 注目すべき出走馬（これら以外の馬名が登場しても抽出してください）
{horse_list_str}

# 抽出してほしい情報（各馬について）
プラス情報として以下を重点的に探してください：
- 前走・近走の成績（例：「前走G2優勝」「3連勝中」「重賞実績あり」）
- 調教・追切の様子（例：「最終追切で好時計」「動き抜群」「好調仕上がり」）
- 追切・調教タイム（例：「坂路4F52.3」「CW6F82.1」「終い11.4」）がある場合は数値を必ず残す
- 体調・調子（例：「状態上昇中」「気配良好」「充実期」）
- コース・距離適性（例：「東京ダート1600m得意」「左回り巧者」）
- 騎手・厩舎の強み（例：「ルメール騎手で信頼度高い」「名手とのコンビ」）
- その他の好材料

マイナス情報として以下を重点的に探してください：
- 前走・近走での敗因（例：「前走惨敗」「近走凡走続き」）
- 調教不安（例：「追切動き平凡」「仕上がり遅れ気味」）
- コース・距離の不安（例：「距離短縮が課題」「東京コースは初」）
- 枠順・展開の不安（例：「外枠で先行困難」）
- その他の懸念点

# 出力形式
以下のJSON形式で**必ず**出力してください（説明文は一切不要）：

```json
[
  {{
    "馬名": "馬の名前",
    "プラス情報": "具体的な好材料を2～3文で詳しく記載（追切タイムがあれば数値を含める）",
    "マイナス情報": "具体的な懸念点・不安材料を記載（なければ「特になし」）"
  }}
]
```

# 注意事項
- 記事に情報がない馬は出力しない
- 馬名が全く見当たらない場合のみ「全体的な予想」として1件だけ出力
- JSONのみ出力し、前後に説明文を付けないこと
"""
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )

        response_text = response.text
        if not response_text:
            raise ValueError("Gemini response text is empty")

        analysis_results = _parse_gemini_json_response(response_text, expected="list")
        normalized_results = []
        for result in analysis_results:
            if not isinstance(result, dict):
                continue
            horse_name = _to_text(result.get('馬名'))
            plus_info = _to_text(result.get('プラス情報'))
            minus_info = _to_text(result.get('マイナス情報'))
            if not horse_name:
                continue
            if horse_name in {"全体的な予想", "全体評価", "総評", "全体", "不明"}:
                continue
            if not plus_info and not minus_info:
                continue
            normalized_results.append({
                "馬名": horse_name,
                "プラス情報": plus_info or "特になし",
                "マイナス情報": minus_info or "特になし",
                "source_url": source_url,
                "source_title": source_title,
                "source_type": "web",
            })

        if not normalized_results:
            raise ValueError("Gemini returned no horse-level web analysis rows")

        return normalized_results

    except (json.JSONDecodeError, ValueError):
        raise
    except Exception as e:
        error_msg = str(e)
        if _is_transient_gemini_error(error_msg):
            raise
        raise RuntimeError(f"Web article analysis failed: {type(e).__name__}: {error_msg[:200]}")


# ====================
# X (Twitter) 関連関数
# ====================

def _load_x_accounts_config() -> dict:
    """x_accounts.json を辞書で読み込む（不在/不正時は空dict）"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "x_accounts.json")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _get_x_default_max_tweets(default: int = 30) -> int:
    """x_accounts.json の default_max_tweets を UI 用レンジに正規化して返す"""
    config = _load_x_accounts_config()
    raw = config.get("default_max_tweets", default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(10, min(100, value))


def _load_x_accounts() -> list:
    """x_accounts.json から監視アカウントリストを正規化して返す"""
    data = _load_x_accounts_config()
    raw_accounts = data.get('accounts', [])
    if not isinstance(raw_accounts, list):
        return []

    normalized = []
    seen = set()
    for item in raw_accounts:
        if not isinstance(item, dict):
            continue
        username = str(item.get('username', '')).strip().lstrip('@')
        if not username or username in seen:
            continue
        seen.add(username)
        label = str(item.get('label', username)).strip() or username
        normalized.append({"username": username, "label": label})
    return normalized


def _build_x_race_terms(race_name: str) -> list[str]:
    """X検索に使うレース名の表記ゆれ候補を返す。"""
    base = _to_text(race_name).replace('"', '').strip()
    if not base:
        return []

    candidates = [base]
    no_year = re.sub(r'\s*[0-9０-９]{4}$', '', base).strip()
    if no_year:
        candidates.append(no_year)
    no_space = base.replace(" ", "").replace("\u3000", "")
    if no_space:
        candidates.append(no_space)

    for term in list(candidates):
        if "ステークス" in term:
            candidates.append(term.replace("ステークス", "S"))
            candidates.append(term.replace("ステークス", ""))
        if "Ｓ" in term:
            candidates.append(term.replace("Ｓ", "S"))

    terms = []
    seen = set()
    for t in candidates:
        t = _to_text(t).strip()
        if not t or t in seen:
            continue
        seen.add(t)
        terms.append(t)
    return terms[:8]


def _build_x_recent_search_queries(race_name: str, accounts: list, *, include_lang_ja: bool, max_query_len: int = 512) -> list[str]:
    """アカウントを分割して Recent Search 用クエリを複数組み立てる。"""
    race_terms = _build_x_race_terms(race_name)
    topic_expr = "(予想 OR 本命 OR 印 OR 調教 OR 追い切り OR 追切)"
    race_expr = " OR ".join(f"\"{t}\"" for t in race_terms)

    clauses = []
    if race_terms:
        clauses.append(f"\"{race_terms[0]}\"")
        if race_expr and race_expr != f"\"{race_terms[0]}\"":
            clauses.append(f"({race_expr})")
            clauses.append(f"({race_expr}) {topic_expr}")
    if not clauses:
        clauses.append(topic_expr)

    base_suffix = f" {topic_expr} -is:retweet"
    if include_lang_ja:
        base_suffix += " lang:ja"

    chunks = []
    current = []
    for acc in accounts:
        candidate = current + [acc]
        from_expr = " OR ".join(f"from:{a['username']}" for a in candidate)
        query = f"({from_expr}){base_suffix}"
        if len(query) <= max_query_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = [acc]
        else:
            # 単体でも超過する異常ケース（username/race_nameが極端に長い）
            current = []

    if current:
        chunks.append(current)

    queries = []
    for chunk in chunks:
        from_expr = " OR ".join(f"from:{a['username']}" for a in chunk)
        for clause in clauses:
            query = f"({from_expr}) {clause} -is:retweet"
            if include_lang_ja:
                query += " lang:ja"
            if len(query) <= max_query_len:
                queries.append(query)

    # 重複クエリを除去（順序維持）
    uniq_queries = []
    seen_q = set()
    for q in queries:
        if q in seen_q:
            continue
        seen_q.add(q)
        uniq_queries.append(q)
    queries = uniq_queries
    return queries


def _search_x_general_tweets(race_name: str, max_tweets: int) -> tuple:
    """アカウント指定なしでレース名の一般検索を行う（アカウント検索0件時のフォールバック用）。
    Returns (tweets_list, newest_id)。エラー時は ([], None)。
    """
    if not X_BEARER_TOKEN:
        return [], None

    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    all_tweets = []
    seen_ids: set = set()
    newest_id = None

    race_terms = _build_x_race_terms(race_name)
    topic_expr = "(競馬 OR 予想 OR 本命 OR 印 OR 調教 OR 追い切り OR 追切)"
    horse_terms = [h for h in get_all_horse_names()[:6] if h]
    horse_quoted = []
    for h in horse_terms:
        hs = _to_text(h).replace('"', '').strip()
        if hs:
            horse_quoted.append(f'"{hs}"')
    horse_expr = " OR ".join(horse_quoted)

    clauses = []
    if race_terms:
        clauses.append(f"\"{race_terms[0]}\" {topic_expr}")
        race_expr = " OR ".join(f"\"{t}\"" for t in race_terms)
        clauses.append(f"({race_expr}) {topic_expr}")
    if horse_expr:
        clauses.append(f"({horse_expr}) {topic_expr}")
    if not clauses:
        clauses.append(topic_expr)

    # 重複を除去（順序維持）
    uniq_clauses = []
    seen_clause = set()
    for c in clauses:
        if c in seen_clause:
            continue
        seen_clause.add(c)
        uniq_clauses.append(c)
    clauses = uniq_clauses

    for include_lang in (True, False):
        for clause in clauses:
            query = f"{clause} -is:retweet"
            if include_lang:
                query += ' lang:ja'
            if len(query) > 512:
                continue

            params = {
                "query": query,
                "max_results": min(100, max_tweets - len(all_tweets)),
                "tweet.fields": "created_at,public_metrics,author_id",
                "expansions": "author_id",
                "user.fields": "username",
            }
            try:
                resp = requests.get(
                    "https://api.x.com/2/tweets/search/recent",
                    headers=headers, params=params, timeout=15,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                users = {u['id']: u['username'] for u in data.get('includes', {}).get('users', [])}
                for tw in data.get('data', []):
                    if len(all_tweets) >= max_tweets:
                        break
                    tweet_id = tw.get('id')
                    if not tweet_id or tweet_id in seen_ids:
                        continue
                    seen_ids.add(tweet_id)
                    username = users.get(tw.get('author_id', ''), '')
                    all_tweets.append({
                        "tweet_id": tweet_id,
                        "text": tw.get('text', ''),
                        "author_username": username,
                        "author_label": username,
                        "created_at": tw.get('created_at', ''),
                        "url": f"https://x.com/{username}/status/{tweet_id}" if username else "",
                        "public_metrics": tw.get('public_metrics', {}),
                    })
                    if _is_newer_tweet_id(tweet_id, newest_id):
                        newest_id = tweet_id
                if len(all_tweets) >= max_tweets:
                    break
            except Exception:
                continue
        if all_tweets:
            break

    return all_tweets, newest_id


def _is_newer_tweet_id(candidate_id, current_id) -> bool:
    """tweet_id の新旧を安全に判定する（基本は整数比較、失敗時は文字列比較）"""
    if current_id in (None, ""):
        return True
    try:
        return int(str(candidate_id)) > int(str(current_id))
    except (TypeError, ValueError):
        cand = str(candidate_id)
        curr = str(current_id)
        if len(cand) != len(curr):
            return len(cand) > len(curr)
        return cand > curr


def _normalize_x_text_for_match(text: str) -> tuple[str, str]:
    """X投稿の一致判定向けに文字列を正規化する。"""
    raw = unicodedata.normalize("NFKC", _to_text(text)).lower()
    spaced = re.sub(r"\s+", " ", raw).strip()
    compact = re.sub(r"\s+", "", spaced)
    return spaced, compact


def _tweet_matches_race_name(tweet_text: str, race_name: str) -> bool:
    """投稿本文が対象レースに言及しているかを判定する。"""
    terms = _build_x_race_terms(race_name)
    if not terms:
        return True

    spaced_text, compact_text = _normalize_x_text_for_match(tweet_text)
    for term in terms:
        t_spaced, t_compact = _normalize_x_text_for_match(term)
        if not t_spaced:
            continue
        # 通常言及 / ハッシュタグ言及 / 空白ゆれを許容
        if t_spaced in spaced_text:
            return True
        if t_compact and t_compact in compact_text:
            return True
        if f"#{t_compact}" in compact_text:
            return True
    return False


def _filter_x_tweets_by_race_name(tweets: list, race_name: str) -> tuple[list, int]:
    """対象レース言及のないツイートを除外する。"""
    filtered = []
    dropped = 0
    for tw in tweets or []:
        if not isinstance(tw, dict):
            continue
        text = _to_text(tw.get("text", ""))
        if _tweet_matches_race_name(text, race_name):
            filtered.append(tw)
        else:
            dropped += 1
    return filtered, dropped


def search_x_tweets(race_name, accounts, max_tweets=30, since_id=None):
    """
    X API v2 Recent Search でレース関連ツイートを取得する。

    戻り値:
        tuple: (tweets_list, newest_id)
            tweets_list: ツイート情報の辞書リスト
            newest_id: 取得結果の最新tweet_id（差分取得用）
    """
    if not X_BEARER_TOKEN or not accounts:
        return [], None

    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}"}
    api_endpoints = [
        "https://api.x.com/2/tweets/search/recent",
        "https://api.twitter.com/2/tweets/search/recent",
    ]
    active_api_url = api_endpoints[0]
    fallback_notified = False

    # アカウント名→ラベルのマッピング
    label_map = {a['username']: a.get('label', a['username']) for a in accounts}

    all_tweets = []
    seen_tweet_ids = set()
    newest_id = None

    def _request_with_fallback(params: dict):
        nonlocal active_api_url, fallback_notified
        try:
            return requests.get(active_api_url, headers=headers, params=params, timeout=15), None
        except requests.RequestException as first_error:
            if active_api_url != api_endpoints[0]:
                return None, first_error
            # 接続系エラー時のみ旧ドメインへフォールバック
            try:
                resp = requests.get(api_endpoints[1], headers=headers, params=params, timeout=15)
                active_api_url = api_endpoints[1]
                if not fallback_notified:
                    st.info("ℹ️ api.x.com へ接続できなかったため、api.twitter.com にフォールバックしました。")
                    fallback_notified = True
                return resp, None
            except requests.RequestException as fallback_error:
                return None, fallback_error

    # lang:ja 優先戦略: まず日本語フィルタ付き、0件ならフィルタなしで再検索
    for include_lang_ja in (True, False):
        queries = _build_x_recent_search_queries(
            race_name,
            accounts,
            include_lang_ja=include_lang_ja,
            max_query_len=512,
        )
        if not queries:
            if include_lang_ja:
                # lang:ja 付きで超過した場合は、フィルタなし構成で再試行する
                continue
            st.warning("⚠️ X検索クエリを組み立てられませんでした。アカウント数やレース名を確認してください。")
            return [], None

        for query in queries:
            next_token = None
            while len(all_tweets) < max_tweets:
                params = {
                    "query": query,
                    "max_results": min(100, max_tweets - len(all_tweets)),  # API上限は100
                    "tweet.fields": "created_at,public_metrics,author_id",
                    "expansions": "author_id",
                    "user.fields": "username",
                }
                if since_id:
                    params["since_id"] = str(since_id)
                if next_token:
                    params["next_token"] = next_token

                resp, req_error = _request_with_fallback(params)
                if req_error is not None:
                    st.warning(f"⚠️ X API接続エラー: {req_error}")
                    return all_tweets, newest_id

                if resp.status_code == 401 or resp.status_code == 403:
                    st.error("❌ X API認証エラー: Bearer Tokenを確認してください")
                    return [], None
                if resp.status_code == 429:
                    st.warning("⚠️ X APIレート制限に達しました。15分後に再試行してください。")
                    return all_tweets, newest_id
                if resp.status_code != 200:
                    st.warning(f"⚠️ X APIエラー: {resp.status_code} {resp.text[:200]}")
                    return all_tweets, newest_id

                data = resp.json()

                # author_id → username マッピング構築
                users = {u['id']: u['username'] for u in data.get('includes', {}).get('users', [])}

                tweets = data.get('data', [])
                if not tweets:
                    break

                for tw in tweets:
                    if len(all_tweets) >= max_tweets:
                        break
                    tweet_id = tw.get('id')
                    if not tweet_id:
                        continue
                    if tweet_id in seen_tweet_ids:
                        continue
                    seen_tweet_ids.add(tweet_id)

                    author_id = tw.get('author_id', '')
                    username = users.get(author_id, '')
                    tweet_url = f"https://x.com/{username}/status/{tweet_id}" if username else ""

                    all_tweets.append({
                        "tweet_id": tweet_id,
                        "text": tw.get('text', ''),
                        "author_username": username,
                        "author_label": label_map.get(username, username),
                        "created_at": tw.get('created_at', ''),
                        "url": tweet_url,
                        "public_metrics": tw.get('public_metrics', {}),
                    })

                    # newest_id を更新（安全な新旧比較）
                    if _is_newer_tweet_id(tweet_id, newest_id):
                        newest_id = tweet_id

                # ページング
                meta = data.get('meta', {})
                next_token = meta.get('next_token')
                if not next_token or len(all_tweets) >= max_tweets:
                    break

            if len(all_tweets) >= max_tweets:
                break

        # lang:ja で結果があれば終了
        if all_tweets:
            break

    return all_tweets, newest_id


def analyze_x_tweets_with_gemini(tweets, horse_names):
    """
    複数ツイートをバッチでGemini解析し、馬別のプラス/マイナス情報を返す。

    戻り値:
        list: 馬別の解析結果辞書リスト
    """
    if not GEMINI_API_KEY or not tweets:
        return []

    horse_list_str = "\n".join([f"- {name}" for name in horse_names])

    # ツイート一覧テキスト構築
    tweet_lines = []
    for i, tw in enumerate(tweets, 1):
        author = tw.get('author_username', '不明')
        date_str = (tw.get('created_at') or '')[:10]
        text = tw.get('text', '')
        tweet_lines.append(f"[{i}] @{author} ({date_str}): {text}")
    tweets_text = "\n\n".join(tweet_lines)

    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""あなたは競馬予想の専門家です。以下のX (Twitter) 投稿群を読み、各馬の評価情報を抽出してください。

# 投稿一覧
{tweets_text}

# 注目すべき出走馬（これら以外の馬名が登場しても抽出してください）
{horse_list_str}

# 抽出してほしい情報（各馬について）
プラス情報として以下を重点的に探してください：
- 前走・近走の成績（例：「前走G2優勝」「3連勝中」「重賞実績あり」）
- 調教・追切の様子（例：「最終追切で好時計」「動き抜群」「好調仕上がり」）
- 追切・調教タイム（例：「坂路4F52.3」「CW6F82.1」「終い11.4」）がある場合は数値を必ず残す
- 体調・調子（例：「状態上昇中」「気配良好」「充実期」）
- コース・距離適性（例：「東京ダート1600m得意」「左回り巧者」）
- 騎手・厩舎の強み（例：「ルメール騎手で信頼度高い」「名手とのコンビ」）
- その他の好材料

マイナス情報として以下を重点的に探してください：
- 前走・近走での敗因（例：「前走惨敗」「近走凡走続き」）
- 調教不安（例：「追切動き平凡」「仕上がり遅れ気味」）
- コース・距離の不安（例：「距離短縮が課題」「東京コースは初」）
- 枠順・展開の不安（例：「外枠で先行困難」）
- その他の懸念点

# 出力形式
以下のJSON形式で**必ず**出力してください（説明文は一切不要）：

```json
[
  {{
    "馬名": "馬の名前",
    "プラス情報": "具体的な好材料を2～3文で詳しく記載（追切タイムがあれば数値を含める）",
    "マイナス情報": "具体的な懸念点・不安材料を記載（なければ「特になし」）",
    "source_index": [1, 3]
  }}
]
```

source_index は情報元の投稿番号リスト（複数可）。

# 注意事項
- 投稿に情報がない馬は出力しない
- 同じ馬について複数投稿で言及されている場合は情報を統合して1件にまとめる
- 馬名が全く見当たらない場合のみ「全体的な予想」として1件だけ出力
- JSONのみ出力し、前後に説明文を付けないこと
"""
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )

        response_text = response.text
        if not response_text:
            return []

        analysis_results = _parse_gemini_json_response(response_text, expected="list")

        # source_index → 実際のツイートURLとタイトルに変換
        for result in analysis_results:
            indices = result.pop('source_index', [])
            if indices and isinstance(indices, list):
                # 最初の参照投稿のURLをsource_urlに使用
                first_idx = indices[0] - 1  # 1-indexed → 0-indexed
                if 0 <= first_idx < len(tweets):
                    tw = tweets[first_idx]
                    result['source_url'] = tw.get('url', '')
                    result['source_title'] = f"𝕏 @{tw.get('author_username', '不明')}"
                else:
                    result['source_url'] = ''
                    result['source_title'] = '𝕏投稿'
            else:
                result['source_url'] = ''
                result['source_title'] = '𝕏投稿'
            result['source_type'] = 'x_twitter'

        return analysis_results

    except (json.JSONDecodeError, ValueError):
        return []
    except Exception as e:
        error_msg = str(e)
        if _is_transient_gemini_error(error_msg):
            raise
        st.warning(f"⚠️ X投稿の解析をスキップしました: {type(e).__name__} ({error_msg[:120]})")
        return []


def fetch_and_analyze_x_tweets(race_name, max_tweets=30):
    """
    X投稿の検索・解析オーケストレーター。

    戻り値:
        tuple: (tweets_metadata, raw_analysis_results)
    """
    accounts = _load_x_accounts()
    if not accounts:
        st.warning("⚠️ x_accounts.json が見つからないか、アカウントが未登録です。")
        return [], []

    since_id = st.session_state.get('x_newest_id')

    progress_bar = st.progress(0)
    status_text = st.empty()

    # Phase 1: ツイート検索
    status_text.info("𝕏 X投稿を検索中...")
    progress_bar.progress(0.2)

    tweets = []
    newest_id = None
    for attempt in range(3):
        try:
            tweets, newest_id = search_x_tweets(race_name, accounts, max_tweets, since_id)
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                st.warning(f"⚠️ X検索に失敗しました: {e}")
                progress_bar.empty()
                status_text.empty()
                return [], []

    # フォールバック1: since_id で絞りすぎて0件の場合、since_id なしで再検索
    if not tweets and since_id:
        status_text.info("𝕏 差分検索が0件のため全件再検索中...")
        try:
            tweets, newest_id = search_x_tweets(race_name, accounts, max_tweets, since_id=None)
        except Exception:
            pass

    # フォールバック2: アカウント限定検索が0件の場合、一般キーワード検索
    if not tweets:
        status_text.info("𝕏 監視アカウントから0件のため一般検索を試行中...")
        try:
            tweets, newest_id = _search_x_general_tweets(race_name, max_tweets)
            if tweets:
                st.caption(f"ℹ️ 監視アカウントからは投稿が見つからなかったため、一般検索から{len(tweets)}件取得しました。")
        except Exception:
            pass

    # 最終フィルタ: 対象レース名に言及していない投稿を除外
    if tweets:
        tweets, dropped_count = _filter_x_tweets_by_race_name(tweets, race_name)
        if dropped_count > 0:
            st.caption(f"ℹ️ 対象レース外の投稿を {dropped_count} 件除外しました。")

    progress_bar.progress(0.5)

    if not tweets:
        progress_bar.empty()
        status_text.empty()
        st.info("ℹ️ 該当するツイートが見つかりませんでした。監視アカウント名・レース名（表記ゆれ）・X APIトークンを確認してください。")
        return [], []

    status_text.info(f"𝕏 {len(tweets)}件のツイートを解析中...")

    # Phase 2: Gemini解析（バッチ）
    horse_names = get_all_horse_names()
    raw_results = []
    for attempt in range(3):
        try:
            raw_results = analyze_x_tweets_with_gemini(tweets, horse_names)
            break
        except Exception as e:
            if attempt < 2 and _is_transient_gemini_error(str(e)):
                time.sleep(2)
            else:
                st.warning(f"⚠️ X投稿のGemini解析に失敗しました: {e}")
                break

    progress_bar.progress(1.0)
    progress_bar.empty()
    status_text.empty()

    # newest_id をセッションに保存（差分取得用）
    if newest_id:
        st.session_state['x_newest_id'] = newest_id

    return tweets, raw_results


def aggregate_horse_analysis(youtube_results, web_results, doc_results=None, x_results=None):
    """
    YouTube・Web記事・ドキュメント・X投稿の分析結果を馬名ごとに集約するDataFrameを作成する

    引数:
        youtube_results (list): YouTube分析の生データリスト
        web_results (list): Web記事分析の生データリスト
        doc_results (list): ドキュメント分析の生データリスト（省略可）
        x_results (list): X投稿分析の生データリスト（省略可）

    戻り値:
        DataFrame: 馬名ごとに集約されたメリット・デメリット情報
    """
    if doc_results is None:
        doc_results = []
    if x_results is None:
        x_results = []
    horse_data = defaultdict(lambda: {
        "メリット_items": [],
        "メリット_sources": [],
        "デメリット_items": [],
        "デメリット_sources": [],
    })

    def normalize_horse_name(name):
        """馬名をそのまま返す（将来的にエイリアス対応可）"""
        return name

    def as_text(value):
        """Geminiの出力揺れ（str/list/None）を安全に文字列化する。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts = [str(v).strip() for v in value if str(v).strip()]
            return " / ".join(parts).strip()
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False).strip()
        return str(value).strip()

    # YouTube結果を処理
    for item in youtube_results:
        if not isinstance(item, dict):
            continue
        horse = normalize_horse_name(as_text(item.get("馬名", "不明")) or "不明")
        plus = as_text(item.get("プラス情報", ""))
        minus = as_text(item.get("マイナス情報", ""))
        url = as_text(item.get("video_url", ""))
        title = as_text(item.get("video_title", "YouTube動画")) or "YouTube動画"

        if plus and plus not in ("特になし", ""):
            horse_data[horse]["メリット_items"].append(plus)
            horse_data[horse]["メリット_sources"].append((title[:40], url))
        if minus and minus not in ("特になし", ""):
            horse_data[horse]["デメリット_items"].append(minus)
            horse_data[horse]["デメリット_sources"].append((title[:40], url))

    # Web記事結果を処理
    for item in web_results:
        if not isinstance(item, dict):
            continue
        horse = normalize_horse_name(as_text(item.get("馬名", "不明")) or "不明")
        plus = as_text(item.get("プラス情報", ""))
        minus = as_text(item.get("マイナス情報", ""))
        url = as_text(item.get("source_url", ""))
        title = as_text(item.get("source_title", "Web記事")) or "Web記事"

        if plus and plus not in ("特になし", ""):
            horse_data[horse]["メリット_items"].append(plus)
            horse_data[horse]["メリット_sources"].append((title[:40], url))
        if minus and minus not in ("特になし", ""):
            horse_data[horse]["デメリット_items"].append(minus)
            horse_data[horse]["デメリット_sources"].append((title[:40], url))

    # ドキュメント結果を処理
    for item in doc_results:
        if not isinstance(item, dict):
            continue
        horse = normalize_horse_name(as_text(item.get("馬名", "不明")) or "不明")
        plus = as_text(item.get("プラス情報", ""))
        minus = as_text(item.get("マイナス情報", ""))
        title = as_text(item.get("source_title", "アップロードドキュメント")) or "アップロードドキュメント"

        if plus and plus not in ("特になし", ""):
            horse_data[horse]["メリット_items"].append(plus)
            horse_data[horse]["メリット_sources"].append((f"📄{title[:38]}", ""))
        if minus and minus not in ("特になし", ""):
            horse_data[horse]["デメリット_items"].append(minus)
            horse_data[horse]["デメリット_sources"].append((f"📄{title[:38]}", ""))

    # X (Twitter) 結果を処理
    for item in x_results:
        if not isinstance(item, dict):
            continue
        horse = normalize_horse_name(as_text(item.get("馬名", "不明")) or "不明")
        plus = as_text(item.get("プラス情報", ""))
        minus = as_text(item.get("マイナス情報", ""))
        url = as_text(item.get("source_url", ""))
        title = as_text(item.get("source_title", "𝕏投稿")) or "𝕏投稿"

        if plus and plus not in ("特になし", ""):
            horse_data[horse]["メリット_items"].append(plus)
            horse_data[horse]["メリット_sources"].append((f"𝕏{title[:38]}", url))
        if minus and minus not in ("特になし", ""):
            horse_data[horse]["デメリット_items"].append(minus)
            horse_data[horse]["デメリット_sources"].append((f"𝕏{title[:38]}", url))

    rows = []
    for horse_name, data in horse_data.items():
        merit_text = "\n\n".join([
            f"[{i+1}] {text}" for i, text in enumerate(data["メリット_items"])
        ])
        demerit_text = "\n\n".join([
            f"[{i+1}] {text}" for i, text in enumerate(data["デメリット_items"])
        ])

        merit_sources_parts = []
        for i, (t, u) in enumerate(data["メリット_sources"]):
            if u:
                merit_sources_parts.append(f"[{i+1}] [{t}]({u})")
            else:
                merit_sources_parts.append(f"[{i+1}] {t}")
        merit_sources = "\n".join(merit_sources_parts) if merit_sources_parts else "（なし）"

        demerit_sources_parts = []
        for i, (t, u) in enumerate(data["デメリット_sources"]):
            if u:
                demerit_sources_parts.append(f"[{i+1}] [{t}]({u})")
            else:
                demerit_sources_parts.append(f"[{i+1}] {t}")
        demerit_sources = "\n".join(demerit_sources_parts) if demerit_sources_parts else "（なし）"

        all_urls = set(
            [u for _, u in data["メリット_sources"] if u] +
            [u for _, u in data["デメリット_sources"] if u]
        )
        source_count = len(all_urls)

        rows.append({
            "馬名": horse_name,
            "メリット": merit_text or "（情報なし）",
            "メリット出典": merit_sources,
            "デメリット": demerit_text or "（情報なし）",
            "デメリット出典": demerit_sources,
            "情報源数": source_count,
        })

    if not rows:
        return pd.DataFrame(columns=["馬名", "メリット", "メリット出典", "デメリット", "デメリット出典", "情報源数"])

    df = pd.DataFrame(rows)

    # 情報源数の多い馬を上位にソート
    df = df.sort_values("情報源数", ascending=False).reset_index(drop=True)

    return df


def _normalize_training_text(text: str) -> str:
    """追切タイム抽出用に全角数字・記号を半角へ正規化する。"""
    if not text:
        return ""
    trans_table = str.maketrans(
        "０１２３４５６７８９．：－，ＦＣＷＳＢＧ",
        "0123456789.:-,FCWSBG"
    )
    return _to_text(text).translate(trans_table)


def _is_training_segment(text: str) -> bool:
    """文が追切コメントとして妥当かを判定する。"""
    normalized = _normalize_training_text(text)
    if not normalized:
        return False

    has_strong = bool(_TRAINING_STRONG_CONTEXT_PAT.search(normalized))
    has_keyword = bool(_TRAINING_KEYWORDS.search(normalized))
    has_weak = bool(_TRAINING_WEAK_CONTEXT_PAT.search(normalized))
    has_time = bool(_TRAINING_TIME_PAT.search(normalized))
    has_intensity = bool(_TRAINING_INTENSITY_PAT.search(normalized))
    has_lap_hint = bool(_TRAINING_LAP_HINT_PAT.search(normalized))
    has_phase = bool(
        _TRAINING_PHASE_WEEK_PAT.search(normalized)
        or _TRAINING_PHASE_LATEST_PAT.search(normalized)
        or _TRAINING_PHASE_PREV_PAT.search(normalized)
    )
    has_place = bool(re.search(r'栗東|美浦|坂路|CW|ウッド|南W|北W|ポリ', normalized, flags=re.IGNORECASE))
    has_race_context = bool(_NON_TRAINING_RACE_CONTEXT_PAT.search(normalized))

    if has_strong:
        return True

    # 「馬なり」「一杯」など強度表現 + 時間/時期ヒント
    if (has_place or has_intensity) and (has_time or has_lap_hint or has_phase):
        return True

    # 弱シグナルは補助情報付きの場合のみ採用
    if has_weak and (has_time or has_intensity or has_place or has_phase):
        if has_race_context and not (has_place or has_intensity or has_phase):
            return False
        return True

    # ラップ数字だけ・競走展開コメントだけは除外
    if has_race_context:
        return False

    if has_time and (has_place or has_intensity):
        return True

    return False


def _extract_training_sentences(text: str) -> list[str]:
    """追切に関係する文のみを抽出して返す（非追切コメントを除外）。"""
    normalized = _normalize_training_text(text)
    if not normalized:
        return []

    candidates = re.split(r'[。\n]+', normalized)
    picked = []
    for raw in candidates:
        chunk = raw.strip(" ・-　\t")
        if not chunk:
            continue

        chunk_has_strong_context = bool(_TRAINING_STRONG_CONTEXT_PAT.search(chunk))
        for part in re.split(r'[、，]+', chunk):
            s = part.strip(" ・-　\t")
            if not s:
                continue
            if not _is_training_segment(s):
                if not (chunk_has_strong_context and _TRAINING_INTENSITY_PAT.search(s)):
                    continue

            starts = []
            for pat in (
                _TRAINING_PHASE_WEEK_PAT,
                _TRAINING_PHASE_LATEST_PAT,
                _TRAINING_STRONG_CONTEXT_PAT,
                _TRAINING_KEYWORDS,
                _TRAINING_LAP_HINT_PAT,
                _TRAINING_TIME_PAT,
                _TRAINING_INTENSITY_PAT,
            ):
                m = pat.search(s)
                if m:
                    starts.append(m.start())
            if starts:
                s = s[min(starts):].lstrip("、, ")
            if s:
                picked.append(s)

    # 文分割で何も取れないが全体は追切系の場合は、全文を採用
    if not picked and _is_training_segment(normalized):
        picked = [normalized.strip()]

    uniq = []
    seen = set()
    for s in picked:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def _classify_training_phase(text: str) -> str:
    """追切コメントを 1週前 / 直近 / 前走最終 / 不明 に分類する。"""
    normalized = _normalize_training_text(text)
    if _TRAINING_PHASE_PREV_PAT.search(normalized):
        return "前走最終"
    if _TRAINING_PHASE_WEEK_PAT.search(normalized):
        return "1週前"
    if _TRAINING_PHASE_LATEST_PAT.search(normalized):
        return "直近"
    return "不明"


def _extract_training_intensity(text: str) -> tuple[str, int]:
    """追切強度ラベルを抽出し、比較用スコアを返す。"""
    normalized = _normalize_training_text(text)
    labels = []
    best_score = -1
    for label, score in _TRAINING_INTENSITY_LEVELS:
        if label in normalized:
            labels.append(label)
            if score > best_score:
                best_score = score

    for special in ("併せ先着", "併せ同入", "併せ遅れ"):
        if special in normalized and special not in labels:
            labels.append(special)

    if not labels:
        return "不明", -1
    return " / ".join(labels), best_score


def _extract_training_place(text: str) -> str:
    """追切コメントから調教場所（栗東坂路/CWなど）を抽出する。"""
    normalized = _normalize_training_text(text)
    if not normalized:
        return "—"

    base = ""
    stable_match = re.search(r'(栗東|美浦)', normalized)
    if stable_match:
        base += stable_match.group(1)

    course_patterns = [
        (r'坂路', '坂路'),
        (r'(?:CW|CWコース)', 'CW'),
        (r'(?:W|ウッド|南W|北W)', 'W'),
        (r'ポリ|ポリトラック', 'ポリ'),
        (r'芝', '芝'),
        (r'ダート', 'ダート'),
    ]
    course = ""
    for pat, label in course_patterns:
        if re.search(pat, normalized, flags=re.IGNORECASE):
            course = label
            break

    if course:
        base += course

    cond = ""
    cond_match = re.search(r'[\\(（](良|稍重|重|不良)[\\)）]', normalized)
    if cond_match:
        cond = cond_match.group(1)
    else:
        cond_inline = re.search(r'(良|稍重|重|不良)', normalized)
        if cond_inline:
            cond = cond_inline.group(1)

    if not base and not cond:
        return "—"
    if cond:
        return f"{base}({cond})" if base else f"({cond})"
    return base


def _extract_training_lap_times(text: str) -> dict:
    """追切コメントからハロン別タイムを抽出する。"""
    normalized = _normalize_training_text(text)
    laps = {k: [] for k in ["総合", "6F", "5F", "4F", "3F", "2F", "1F"]}

    def _add(key: str, value: str):
        value = _to_text(value).strip()
        if value and value not in laps[key]:
            laps[key].append(value)

    # 例: 1:08.5
    for total in re.findall(r'\b\d:\d{2}\.\d\b', normalized):
        _add("総合", total)

    # 例: 4F52.3 / 1F11.4
    for f, val in re.findall(r'([1-6])[Ff]\s*([0-9]{2}\.[0-9])', normalized):
        _add(f"{f}F", val)
    # 例: C34.5 / W67.1 など（Fはハロン表記と衝突するため除外）
    for mark, val in re.findall(r'([CWSBG])\s*([0-9]{2}\.[0-9])', normalized, flags=re.IGNORECASE):
        key = "4F"
        _add(key, val)

    # 例: 82.1-66.4-51.9-37.8-11.7 / 52.3-37.8-11.8
    for seq in re.findall(r'([0-9]{2}\.[0-9](?:\s*-\s*[0-9]{2}\.[0-9]){1,5})', normalized):
        values = re.findall(r'[0-9]{2}\.[0-9]', seq)
        if not values:
            continue
        n = len(values)
        if n == 2:
            labels = ["2F", "1F"]
        elif n >= 3:
            start_f = min(6, n + 1)
            labels = [f"{f}F" for f in range(start_f, 2, -1)] + ["1F"]
            labels = labels[:n]
        else:
            labels = ["1F"]

        for label, val in zip(labels, values):
            _add(label, val)

    # 例: 終い11.4 / ラスト1F11.4
    for val in re.findall(r'(?:終い|ラスト)\s*(?:[1１][Ff])?\s*([0-9]{2}\.[0-9])', normalized):
        _add("1F", val)

    # 例: 66秒5
    for sec, frac in re.findall(r'([0-9]{1,2})秒([0-9])', normalized):
        _add("総合", f"{sec}.{frac}")

    return laps


def _format_training_laps(laps: dict) -> str:
    """ハロン辞書を比較表示向けの文字列に整形する。"""
    order = ["総合", "6F", "5F", "4F", "3F", "2F", "1F"]
    parts = []
    for key in order:
        vals = laps.get(key) or []
        if vals:
            parts.append(f"{key}:{' / '.join(vals)}")
    return " | ".join(parts) if parts else "—"


def _normalize_horse_token(text: str) -> str:
    """馬名マッチ用に記号・空白を除いた比較キーへ正規化する。"""
    normalized = unicodedata.normalize("NFKC", _to_text(text))
    if not normalized:
        return ""
    normalized = normalized.replace("　", "").replace(" ", "")
    normalized = re.sub(r"[()\[\]【】「」『』＜＞<>]", "", normalized)
    return normalized.strip().lower()


def _match_horse_name_from_text(text: str, horse_names: list[str]) -> str:
    """文字列中から出走馬名に一致する馬を返す（見つからなければ空文字）。"""
    raw = unicodedata.normalize("NFKC", _to_text(text))
    if not raw:
        return ""

    # 1) 生文字列包含で先に判定（日本語馬名はこれが最も確実）
    for horse in sorted(horse_names or [], key=len, reverse=True):
        normalized_horse = unicodedata.normalize("NFKC", _to_text(horse))
        if normalized_horse and normalized_horse in raw:
            return horse

    # 2) 正規化後で再判定（記号や空白揺れ対応）
    norm_text = _normalize_horse_token(raw)
    if not norm_text:
        return ""
    for horse in sorted(horse_names or [], key=len, reverse=True):
        if not horse:
            continue
        if _normalize_horse_token(horse) in norm_text:
            return horse

    # 3) 類似度でフォールバック（軽微な文字化け・表記揺れ対策）
    head_token = re.split(r'[\s　]+', raw)[0] if raw else ""
    norm_head = _normalize_horse_token(head_token)
    if norm_head and horse_names:
        best_name = ""
        best_score = 0.0
        for horse in horse_names:
            score = SequenceMatcher(None, norm_head, _normalize_horse_token(horse)).ratio()
            if score > best_score:
                best_score = score
                best_name = horse
        if best_name and best_score >= 0.6:
            return best_name
    return ""


def _normalize_training_phase_label(label: str) -> str:
    """時期ラベルを 直近 / 1週前 / 前走最終 / 不明 へ正規化する。"""
    text = _to_text(label)
    if not text:
        return "不明"
    if "前走" in text:
        return "前走最終"
    if "1週前" in text or "一週前" in text:
        return "1週前"
    if "最終" in text or "直近" in text or "直前" in text:
        return "直近"
    return "不明"


def _is_blank_training_value(value) -> bool:
    text = _to_text(value)
    return text in ("", "—", "-", "不明", "なし", "N/A")


def _training_row_lap_count(row: dict) -> int:
    return sum(0 if _is_blank_training_value(row.get(col)) else 1 for col in ("6F", "5F", "4F", "3F", "2F", "1F"))


def _training_row_score(row: dict) -> tuple:
    source_priority = {
        "umasiru": 4,
        "web_fallback": 3,
        "web": 2,
        "x_twitter": 1,
        "youtube": 1,
    }
    stype = _to_text(row.get("source_type") or "")
    priority = source_priority.get(stype, 0)
    laps = _training_row_lap_count(row)
    has_place = 0 if _is_blank_training_value(row.get("場所")) else 1
    has_intensity = 0 if _is_blank_training_value(row.get("脚色")) else 1
    return priority, laps, has_place, has_intensity


def _build_training_time_row(
    horse: str,
    phase: str,
    place: str = "—",
    lap_values: dict | None = None,
    intensity: str = "不明",
    source_type: str = "",
    source_title: str = "",
    source_url: str = "",
) -> dict:
    laps = lap_values or {}
    return {
        "馬名": _to_text(horse) or "不明",
        "時期": _normalize_training_phase_label(phase),
        "場所": _to_text(place) or "—",
        "6F": _to_text(laps.get("6F") or "—") or "—",
        "5F": _to_text(laps.get("5F") or "—") or "—",
        "4F": _to_text(laps.get("4F") or "—") or "—",
        "3F": _to_text(laps.get("3F") or "—") or "—",
        "2F": _to_text(laps.get("2F") or "—") or "—",
        "1F": _to_text(laps.get("1F") or "—") or "—",
        "脚色": _to_text(intensity) or "不明",
        "source_type": _to_text(source_type),
        "source_title": _to_text(source_title),
        "source_url": _to_text(source_url),
    }


def _filter_training_items_by_horses(training_items: list[dict] | None, allowed_horses: set[str]) -> list[dict]:
    """馬名が許可集合に含まれる要素だけを返す。"""
    if not allowed_horses:
        return [x for x in (training_items or []) if isinstance(x, dict)]
    filtered = []
    for item in training_items or []:
        if not isinstance(item, dict):
            continue
        horse = _to_text(item.get("馬名"))
        if horse in allowed_horses:
            filtered.append(item)
    return filtered


def _filter_training_time_rows_by_horses(training_time_rows: list[dict] | None, allowed_horses: set[str]) -> list[dict]:
    """構造化タイム行を出走馬に限定する。"""
    if not allowed_horses:
        return [x for x in (training_time_rows or []) if isinstance(x, dict)]
    filtered = []
    for row in training_time_rows or []:
        if not isinstance(row, dict):
            continue
        horse = _to_text(row.get("馬名"))
        if horse in allowed_horses:
            filtered.append(row)
    return filtered


def merge_training_time_rows(*row_lists: list[dict]) -> list[dict]:
    """馬名+時期単位で重複統合し、より情報量が多い行を優先する。"""
    merged: dict[tuple[str, str], dict] = {}
    for rows in row_lists:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            horse = _to_text(row.get("馬名") or "不明") or "不明"
            phase = _normalize_training_phase_label(row.get("時期") or "不明")
            normalized = _build_training_time_row(
                horse=horse,
                phase=phase,
                place=row.get("場所", "—"),
                lap_values={k: row.get(k, "—") for k in ("6F", "5F", "4F", "3F", "2F", "1F")},
                intensity=row.get("脚色", "不明"),
                source_type=row.get("source_type", ""),
                source_title=row.get("source_title", ""),
                source_url=row.get("source_url", ""),
            )
            key = (horse, phase)
            if key not in merged:
                merged[key] = normalized
                continue

            current = merged[key]
            challenger = normalized
            if _training_row_score(challenger) >= _training_row_score(current):
                primary, secondary = challenger, current
            else:
                primary, secondary = current, challenger

            # 主行を優先しつつ、欠損列だけ副行から補完する
            stitched = dict(primary)
            for col in ("場所", "6F", "5F", "4F", "3F", "2F", "1F", "脚色", "source_title", "source_url"):
                if _is_blank_training_value(stitched.get(col)) and not _is_blank_training_value(secondary.get(col)):
                    stitched[col] = secondary[col]
            merged[key] = stitched

    phase_rank = {name: idx for idx, name in enumerate(TRAINING_PHASE_ORDER)}
    return sorted(
        merged.values(),
        key=lambda r: (_to_text(r.get("馬名")), phase_rank.get(_to_text(r.get("時期")), 99))
    )


def aggregate_training_time_rows_from_items(training_items: list[dict] | None) -> list[dict]:
    """追切コメントからハロン情報を抽出し、構造化タイム行へ変換する。"""
    rows = []
    for item in training_items or []:
        if not isinstance(item, dict):
            continue
        horse = _to_text(item.get("馬名") or "不明") or "不明"
        text = _to_text(item.get("評価内容") or "")
        source_type = _to_text(item.get("source_type") or "")
        source_title = _to_text(item.get("情報源") or "")
        source_url = _to_text(item.get("url") or "")
        for seg in _extract_training_sentences(text):
            laps = _extract_training_lap_times(seg)
            if not any(laps.get(k) for k in ("6F", "5F", "4F", "3F", "2F", "1F")):
                continue
            phase = _classify_training_phase(seg)
            intensity_label, _ = _extract_training_intensity(seg)
            lap_values = {}
            for col in ("6F", "5F", "4F", "3F", "2F", "1F"):
                vals = laps.get(col) or []
                lap_values[col] = vals[0] if vals else "—"
            rows.append(_build_training_time_row(
                horse=horse,
                phase=phase,
                place=_extract_training_place(seg),
                lap_values=lap_values,
                intensity=intensity_label,
                source_type=source_type,
                source_title=source_title,
                source_url=source_url,
            ))
    return merge_training_time_rows(rows)


def _extract_umasiru_training_time_rows(
    html: str,
    source_url: str,
    source_title: str,
    horse_names: list[str],
) -> list[dict]:
    """うましる記事HTMLから時期別の追切タイムテーブルを抽出する。"""
    soup = BeautifulSoup(html or "", "html.parser")
    allowed_horses = {_to_text(x) for x in (horse_names or []) if _to_text(x)}
    rows: list[dict] = []
    for table in soup.find_all("table"):
        tr_list = table.find_all("tr")
        if len(tr_list) < 3:
            continue

        title_text = tr_list[0].get_text(" ", strip=True)
        if not title_text:
            continue
        horse_name = _match_horse_name_from_text(title_text, horse_names)
        # タイトル先頭トークンも試す（例: "エコロヴァルツ 4月1日(水) 評価B"）
        if not horse_name:
            m = re.match(r"^\s*([^\s　]+)", title_text)
            if m:
                token = _to_text(m.group(1))
                matched = _match_horse_name_from_text(token, horse_names)
                if matched:
                    horse_name = matched
                elif not allowed_horses:
                    horse_name = token
        if not horse_name:
            continue
        if allowed_horses and horse_name not in allowed_horses:
            continue

        header_cells = [c.get_text(" ", strip=True) for c in tr_list[1].find_all(["th", "td"])]
        normalized_headers = [_to_text(x) for x in header_cells]
        if not normalized_headers or "時期" not in normalized_headers:
            continue

        for tr in tr_list[2:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not cells:
                continue

            phase = _normalize_training_phase_label(cells[0])
            if phase not in TRAINING_PHASE_ORDER:
                phase = "不明"

            # 想定: 時期/場所/6F/5F/4F/3F/1F/脚色
            place = cells[1] if len(cells) >= 2 else "—"
            lap_values = {
                "6F": cells[2] if len(cells) >= 3 else "—",
                "5F": cells[3] if len(cells) >= 4 else "—",
                "4F": cells[4] if len(cells) >= 5 else "—",
                "3F": cells[5] if len(cells) >= 6 else "—",
                "2F": "—",
                "1F": cells[6] if len(cells) >= 7 else "—",
            }
            intensity = cells[7] if len(cells) >= 8 else "不明"

            rows.append(_build_training_time_row(
                horse=horse_name,
                phase=phase,
                place=place,
                lap_values=lap_values,
                intensity=intensity,
                source_type="umasiru",
                source_title=source_title,
                source_url=source_url,
            ))
    return merge_training_time_rows(rows)


def search_umasiru_training_articles(race_name: str, max_articles: int = 3) -> list[dict]:
    """うましるの追切記事を優先検索する。"""
    query = f"{race_name} 追い切り評価 全頭診断 site:umasiru.com"
    articles = []
    if TAVILY_API_KEY:
        try:
            articles = search_web_articles_with_tavily(
                query,
                max_articles=max(1, max_articles),
                include_domains=["umasiru.com"],
            )
        except Exception:
            articles = []

    if not articles:
        candidates = search_web_articles(query, max_articles=max(3, max_articles * 2))
        for item in candidates:
            domain = urlparse(_to_text(item.get("url"))).netloc.replace("www.", "")
            if domain == "umasiru.com":
                articles.append(item)

    dedup = []
    seen = set()
    for article in articles:
        url = _to_text(article.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        dedup.append(article)
        if len(dedup) >= max_articles:
            break
    return dedup


def fetch_umasiru_training_time_rows(
    race_name: str,
    horse_names: list[str],
    max_articles: int = 3,
) -> tuple[list[dict], list[dict]]:
    """うましる記事を取得し、馬別追切タイム行へ変換する。"""
    articles = search_umasiru_training_articles(race_name, max_articles=max_articles)
    collected_rows = []
    used_articles = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    for article in articles:
        url = _to_text(article.get("url"))
        if not url:
            continue
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            html = resp.text
        except Exception:
            continue

        source_title = _to_text(article.get("title")) or _to_text(BeautifulSoup(html, "html.parser").title)
        rows = _extract_umasiru_training_time_rows(
            html=html,
            source_url=url,
            source_title=source_title or "うましる",
            horse_names=horse_names,
        )
        if rows:
            collected_rows.extend(rows)
            used_articles.append(article)

    return used_articles, merge_training_time_rows(collected_rows)


def _horses_missing_training_time(horse_names: list[str], training_time_rows: list[dict]) -> list[str]:
    """タイム列が未取得の馬を返す。"""
    covered = set()
    for row in training_time_rows or []:
        horse = _to_text(row.get("馬名"))
        if not horse:
            continue
        has_any_lap = any(not _is_blank_training_value(row.get(col)) for col in ("6F", "5F", "4F", "3F", "2F", "1F"))
        if has_any_lap:
            covered.add(horse)
    return [h for h in (horse_names or []) if h and h not in covered]


def _build_training_fallback_queries(race_name: str, missing_horses: list[str]) -> list[str]:
    """不足馬向けの追切補完クエリを返す。"""
    queries = [f"{race_name} 追い切り 調教 時計 1週前 最終追い切り"]
    batch_size = 4
    for idx in range(0, len(missing_horses), batch_size):
        batch = " ".join(missing_horses[idx:idx + batch_size])
        if batch:
            queries.append(f"{race_name} {batch} 追い切り 時計 評価")
    return queries


def refresh_training_state(preserve_existing_time_rows: bool = True) -> tuple[list[dict], list[dict]]:
    """training_items と training_time_rows を再計算してセッションへ反映する。"""
    allowed_horses = {_to_text(x) for x in get_all_horse_names() if _to_text(x)}
    training_items = _filter_training_items_by_horses(aggregate_training_data(), allowed_horses)
    st.session_state['training_items'] = training_items
    parsed_time_rows = _filter_training_time_rows_by_horses(
        aggregate_training_time_rows_from_items(training_items),
        allowed_horses,
    )
    if preserve_existing_time_rows:
        existing_rows = _filter_training_time_rows_by_horses(st.session_state.get('training_time_rows', []), allowed_horses)
        merged_time_rows = merge_training_time_rows(existing_rows, parsed_time_rows)
    else:
        merged_time_rows = merge_training_time_rows(parsed_time_rows)
    st.session_state['training_time_rows'] = merged_time_rows
    return training_items, merged_time_rows


def aggregate_training_data() -> list:
    """web_raw / x_raw / youtube_raw / yt_detail_analysis から追切・調教関連情報を抽出する。
    重複は (馬名, 種別, 評価内容, 情報源, url, source_type) の完全一致で排除し、馬名昇順で返す。
    """
    results = []
    seen = set()

    def _add(horse, text, label, title, url, stype):
        segments = _extract_training_sentences(text)
        if not segments:
            return
        horse = (_to_text(horse) or '不明').strip() or '不明'
        title = _to_text(title) or ''
        url   = _to_text(url)   or ''
        for seg in segments:
            key = (horse, label, seg, title, url, stype)
            if key in seen:
                continue
            seen.add(key)
            results.append({
                '馬名': horse,
                '評価内容': seg,
                '種別': label,
                '情報源': title,
                'url': url,
                'source_type': stype
            })

    # youtube_raw（バッチ分析）
    for item in st.session_state.get('youtube_raw', []):
        if not isinstance(item, dict):
            continue
        h = item.get('馬名', '')
        _add(h, item.get('プラス情報', ''), 'プラス', item.get('video_title', ''), item.get('video_url', ''), 'youtube')
        _add(h, item.get('マイナス情報', ''), 'マイナス', item.get('video_title', ''), item.get('video_url', ''), 'youtube')

    # yt_detail_analysis（YouTube詳細: video_id → list[dict]）
    for video_id, detail_list in (st.session_state.get('yt_detail_analysis') or {}).items():
        for item in (detail_list or []):
            if not isinstance(item, dict):
                continue
            h = item.get('馬名', '')
            title = item.get('video_title', '') or video_id
            url   = item.get('video_url', '') or f"https://www.youtube.com/watch?v={video_id}"
            _add(h, item.get('プラス情報', ''), 'プラス', title, url, 'youtube')
            _add(h, item.get('マイナス情報', ''), 'マイナス', title, url, 'youtube')

    # web_raw
    for item in st.session_state.get('web_raw', []):
        if not isinstance(item, dict):
            continue
        h = item.get('馬名', '')
        _add(h, item.get('プラス情報', ''), 'プラス', item.get('source_title', ''), item.get('source_url', ''), 'web')
        _add(h, item.get('マイナス情報', ''), 'マイナス', item.get('source_title', ''), item.get('source_url', ''), 'web')

    # x_raw
    for item in st.session_state.get('x_raw', []):
        if not isinstance(item, dict):
            continue
        h = item.get('馬名', '')
        _add(h, item.get('プラス情報', ''), 'プラス', item.get('source_title', ''), item.get('source_url', ''), 'x_twitter')
        _add(h, item.get('マイナス情報', ''), 'マイナス', item.get('source_title', ''), item.get('source_url', ''), 'x_twitter')

    results.sort(key=lambda x: x['馬名'])
    return results


def _extract_training_times(text: str) -> str:
    """追切評価テキストからタイム数値を抽出してスラッシュ区切りで返す。"""
    if not text:
        return ''
    normalized = _normalize_training_text(text)
    found = list(dict.fromkeys(_TRAINING_TIME_PAT.findall(normalized)))
    return ' / '.join(found)


def generate_markdown_report(df) -> str:
    """現在のセッションステートと出馬表DataFrameから全タブ内容をMarkdown文字列として生成する。

    Args:
        df: load_race_data() で読み込み済みの出馬表DataFrame
    """
    import datetime as _dt

    lines = []
    race = get_race_config()
    race_name = get_race_display_name()

    def _md_text(value) -> str:
        """Markdown出力向けに最低限のエスケープを行う。"""
        text = _to_text(value).replace("|", "｜").replace("\r", "").strip()
        if text.lower() in {"nan", "none", "nat"}:
            return "-"
        return text

    # 表示本体と同じく「馬番が1頭でも確定している場合は馬番欠損行を除外」
    report_df = df.copy() if isinstance(df, pd.DataFrame) else df
    if isinstance(report_df, pd.DataFrame) and not report_df.empty and '馬番' in report_df.columns:
        umaban_num = pd.to_numeric(report_df['馬番'], errors='coerce')
        if umaban_num.notna().any():
            report_df = report_df[umaban_num.notna()].copy().reset_index(drop=True)
    allowed_horses = set()
    if report_df is not None and not report_df.empty and '馬名' in report_df.columns:
        allowed_horses = {_to_text(x) for x in report_df['馬名'].tolist() if _to_text(x)}

    # ── ヘッダー ──
    lines.append(f"# {race_name} — 予想レポート")
    if race:
        lines.append(
            f"**日程**: {race.date_str}　**会場**: {race.venue}　"
            f"**距離**: {race.surface}{race.distance}　**グレード**: {race.grade}"
        )
    lines.append(f"\n*生成日時: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")

    # ── 出馬表 ──
    lines.append("---\n## 📋 出馬表")
    if report_df is not None and not report_df.empty:
        col_candidates = [
            ("枠番", ["枠番", "枠"]),
            ("馬番", ["馬番"]),
            ("馬名", ["馬名"]),
            ("性齢", ["性齢"]),
            ("斤量", ["斤量"]),
            ("騎手", ["騎手"]),
            ("前走", ["前走"]),
            ("2走前", ["2走前"]),
            ("3走前", ["3走前"]),
            ("オッズ", ["オッズ", "単勝オッズ"]),
        ]
        selected_cols = []
        rename_map = {}
        for target, candidates in col_candidates:
            src = next((c for c in candidates if c in report_df.columns), None)
            if src:
                selected_cols.append(src)
                rename_map[src] = target

        if selected_cols:
            df_entry = report_df[selected_cols].rename(columns=rename_map)
            lines.append('| ' + ' | '.join(str(c) for c in df_entry.columns) + ' |')
            lines.append('|' + '---|' * len(df_entry.columns))
            for _, row in df_entry.iterrows():
                lines.append('| ' + ' | '.join(_md_text(v).replace('\n', ' ') for v in row) + ' |')
        else:
            lines.append("*出馬表の表示対象列が見つかりませんでした*")
    else:
        lines.append("*出馬表データなし*")

    # ── レース特徴・傾向 ──
    lines.append("\n---\n## 🏟️ レース特徴・傾向")
    rc_raw = st.session_state.get('race_characteristics')
    rc = dict(rc_raw) if isinstance(rc_raw, dict) else {}
    # 欠損時は最小限データで「コース特徴」を補完
    if not _to_text(rc.get('コース特徴')):
        fallback_rc = get_minimal_race_characteristics()
        if _to_text(fallback_rc.get('コース特徴')):
            rc['コース特徴'] = fallback_rc.get('コース特徴')

    if rc:
        preferred_keys = [
            'コース特徴', '勝ちやすい馬のタイプ', '苦手な馬のタイプ',
            '枠順有利', '枠順不利', '過去の傾向', '騎手厩舎傾向', '注目ポイント',
            '情報ソース', '情報取得方式', '情報ソースURL',
        ]
        skip_keys = {'データ分析テーブル'}
        output_keys = []
        for key in preferred_keys:
            if key in skip_keys:
                continue
            if key in rc and _to_text(rc.get(key)):
                output_keys.append(key)
        for key in rc.keys():
            if key in skip_keys:
                continue
            if key not in output_keys and _to_text(rc.get(key)):
                output_keys.append(key)

        if output_keys:
            for key in output_keys:
                lines.append(f"\n### {_md_text(key)}\n{_to_text(rc.get(key))}")
        else:
            lines.append("*レース特徴データなし（「レース特徴・傾向」タブで取得してください）*")
    else:
        lines.append("*レース特徴データなし（「レース特徴・傾向」タブで取得してください）*")

    # ── 総合予想（馬別）— 見出し+本文形式（長文・改行を含むためテーブル不使用）──
    lines.append("\n---\n## 🏇 総合予想（馬別）")
    horse_df = st.session_state.get('horse_df')
    if horse_df is not None and not horse_df.empty:
        for _, row in horse_df.iterrows():
            horse_name_raw = _to_text(row.get('馬名'))
            if allowed_horses and horse_name_raw and horse_name_raw not in allowed_horses:
                continue
            lines.append(f"\n### {horse_name_raw or '?'}")
            merit = str(row.get('メリット') or '').strip()
            demerit = str(row.get('デメリット') or '').strip()
            if merit:
                lines.append(f"**✅ プラス情報**\n\n{merit}")
            if demerit:
                lines.append(f"\n**⚠️ マイナス情報**\n\n{demerit}")
    else:
        lines.append("*予想データなし（「情報入力」タブで検索してください）*")

    # ── YouTubeから情報入手 ──
    lines.append("\n---\n## 🎥 YouTubeから情報入手")
    youtube_videos = st.session_state.get('youtube_videos') or []
    yt_detail_map = st.session_state.get('yt_detail_analysis') or {}
    yt_conclusion_map = st.session_state.get('yt_video_conclusions') or {}
    if youtube_videos:
        lines.append("| No. | タイトル | チャンネル | 公開日 | URL |")
        lines.append("|---|---|---|---|---|")
        for i, video in enumerate(youtube_videos, 1):
            title = _md_text(video.get('title') or '（タイトル不明）').replace('\n', ' ')
            channel = _md_text(video.get('channel_title') or '（チャンネル不明）').replace('\n', ' ')
            published = _md_text((video.get('published_at') or '')[:10] or '不明')
            url = _to_text(video.get('video_url'))
            url_cell = f"[リンク]({url})" if url else "（なし）"
            lines.append(f"| {i} | {title} | {channel} | {published} | {url_cell} |")

    if yt_conclusion_map:
        lines.append("\n### 動画結論（本命・対抗）")
        lines.append("| 動画 | 本命 | 対抗 | 単穴 | 連下 | 危険な人気馬 | 買い目方針 |")
        lines.append("|---|---|---|---|---|---|---|")

        id_to_video = {str(v.get('video_id') or ''): v for v in youtube_videos}
        displayed_ids = set()

        for video in youtube_videos:
            video_id = str(video.get('video_id') or '')
            conclusion = yt_conclusion_map.get(video_id) or {}
            if not conclusion:
                continue
            displayed_ids.add(video_id)
            title = _md_text(video.get('title') or video_id or '動画')
            row = [
                title,
                _md_text(_to_text(conclusion.get('本命')) or "不明"),
                _md_text(_to_text(conclusion.get('対抗')) or "不明"),
                _md_text(_to_text(conclusion.get('単穴')) or "不明"),
                _md_text(_to_text(conclusion.get('連下')) or "-"),
                _md_text(_to_text(conclusion.get('危険な人気馬')) or "-"),
                _md_text(_to_text(conclusion.get('買い目方針')) or "-"),
            ]
            lines.append("| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |")

        for video_id, conclusion in yt_conclusion_map.items():
            if str(video_id) in displayed_ids:
                continue
            if not conclusion:
                continue
            row = [
                _md_text(str(video_id)),
                _md_text(_to_text(conclusion.get('本命')) or "不明"),
                _md_text(_to_text(conclusion.get('対抗')) or "不明"),
                _md_text(_to_text(conclusion.get('単穴')) or "不明"),
                _md_text(_to_text(conclusion.get('連下')) or "-"),
                _md_text(_to_text(conclusion.get('危険な人気馬')) or "-"),
                _md_text(_to_text(conclusion.get('買い目方針')) or "-"),
            ]
            lines.append("| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |")

    if yt_detail_map:
        lines.append("\n### 馬別抽出結果（動画ごと）")
        if youtube_videos:
            id_to_video = {str(v.get('video_id') or ''): v for v in youtube_videos}
        else:
            id_to_video = {}
        displayed_ids = set()

        for video in youtube_videos:
            video_id = str(video.get('video_id') or '')
            analysis_results = yt_detail_map.get(video_id, []) or []
            filtered_results = []
            for res in analysis_results:
                if not isinstance(res, dict):
                    continue
                horse_name_raw = _to_text(res.get('馬名'))
                if allowed_horses and horse_name_raw and horse_name_raw not in allowed_horses:
                    continue
                filtered_results.append(res)

            if not filtered_results:
                continue
            displayed_ids.add(video_id)
            title = _md_text(video.get('title') or video_id or '動画')
            lines.append(f"\n#### {title}")
            for res in filtered_results:
                horse_name = _md_text(_to_text(res.get('馬名')) or '不明')
                plus = _to_text(res.get('プラス情報') or '')
                minus = _to_text(res.get('マイナス情報') or '')
                lines.append(f"- **{horse_name}**")
                if plus:
                    lines.append(f"  - ✅ プラス: {plus}")
                if minus:
                    lines.append(f"  - ⚠️ マイナス: {minus}")

        # キャッシュ由来などで youtube_videos に存在しない video_id も出力
        for video_id, analysis_results in yt_detail_map.items():
            if str(video_id) in displayed_ids:
                continue
            filtered_results = []
            for res in analysis_results:
                if not isinstance(res, dict):
                    continue
                horse_name_raw = _to_text(res.get('馬名'))
                if allowed_horses and horse_name_raw and horse_name_raw not in allowed_horses:
                    continue
                filtered_results.append(res)

            if not filtered_results:
                continue
            title = _md_text(id_to_video.get(str(video_id), {}).get('title') or str(video_id) or '動画')
            lines.append(f"\n#### {title}")
            for res in filtered_results:
                horse_name = _md_text(_to_text(res.get('馬名')) or '不明')
                plus = _to_text(res.get('プラス情報') or '')
                minus = _to_text(res.get('マイナス情報') or '')
                lines.append(f"- **{horse_name}**")
                if plus:
                    lines.append(f"  - ✅ プラス: {plus}")
                if minus:
                    lines.append(f"  - ⚠️ マイナス: {minus}")
    elif not youtube_videos:
        lines.append("*YouTubeデータなし*")

    # ── 追切結果・評価 ──
    lines.append("\n---\n## 🏋️ 追切結果・評価")
    training_items = st.session_state.get('training_items') or []
    training_time_rows = st.session_state.get('training_time_rows') or []

    training_items = _filter_training_items_by_horses(training_items, allowed_horses)
    training_time_rows = _filter_training_time_rows_by_horses(training_time_rows, allowed_horses)
    merged_time_rows = merge_training_time_rows(training_time_rows)

    if merged_time_rows:
        lines.append("\n### 追切タイム（馬別・時期別）")
        phase_label = {"直近": "最終追切", "1週前": "1週前", "前走最終": "前走最終", "不明": "時期不明"}
        phase_order = {"直近": 0, "1週前": 1, "前走最終": 2, "不明": 3}

        by_horse: dict[str, list[dict]] = {}
        for row in merged_time_rows:
            horse = _to_text(row.get("馬名")) or "不明"
            by_horse.setdefault(horse, []).append(row)

        for horse in sorted(by_horse.keys()):
            lines.append(f"\n#### {horse}")
            lines.append("| 時期 | 場所 | 6F | 5F | 4F | 3F | 2F | 1F | 脚色 |")
            lines.append("|---|---|---|---|---|---|---|---|---|")

            rows = sorted(
                by_horse[horse],
                key=lambda r: phase_order.get(_normalize_training_phase_label(r.get("時期")), 99)
            )
            for row in rows:
                phase_key = _normalize_training_phase_label(row.get("時期"))
                cells = [
                    phase_label.get(phase_key, "時期不明"),
                    row.get("場所", "—"),
                    row.get("6F", "—"),
                    row.get("5F", "—"),
                    row.get("4F", "—"),
                    row.get("3F", "—"),
                    row.get("2F", "—"),
                    row.get("1F", "—"),
                    row.get("脚色", "不明"),
                ]
                lines.append("| " + " | ".join((_md_text(v).replace('\n', ' ') or "—") for v in cells) + " |")
    else:
        lines.append("*追切タイムデータなし*")

    if training_items:
        lines.append("\n### 追切コメント（プラス/マイナス）")
        comments_by_horse: dict[str, dict[str, list[str]]] = {}

        for item in training_items:
            horse = _to_text(item.get("馬名")) or "不明"
            kind = _to_text(item.get("種別"))
            content = _to_text(item.get("評価内容")).replace("\n", " ").strip()
            if not content:
                continue

            bucket = comments_by_horse.setdefault(horse, {"plus": [], "minus": []})
            for seg in _extract_training_sentences(content):
                if kind == "プラス":
                    if seg not in bucket["plus"]:
                        bucket["plus"].append(seg)
                else:
                    if seg not in bucket["minus"]:
                        bucket["minus"].append(seg)

        for horse in sorted(comments_by_horse.keys()):
            lines.append(f"\n#### {horse}")
            plus_comments = comments_by_horse[horse]["plus"]
            minus_comments = comments_by_horse[horse]["minus"]

            lines.append("**✅ プラス**")
            if plus_comments:
                for c in plus_comments:
                    lines.append(f"- {_md_text(c)}")
            else:
                lines.append("- なし")

            lines.append("**⚠️ マイナス**")
            if minus_comments:
                for c in minus_comments:
                    lines.append(f"- {_md_text(c)}")
            else:
                lines.append("- なし")
    elif not merged_time_rows:
        lines.append("*追切コメントデータなし*")

    return '\n'.join(lines)


def fetch_and_analyze_web_articles(
    queries,
    total_article_limit=20,
    include_domains=None,
    auto_add_horse_queries=True,
):
    """
    複数クエリでWeb記事を検索・解析するオーケストレーター関数
    全出走馬を4頭ずつグループ化した馬別クエリを自動追加し、全頭分の情報を収集する

    引数:
        queries (list): 検索クエリのリスト
        total_article_limit (int): 最終的に取得するWeb記事の上限件数

    戻り値:
        tuple: (articles_metadata, raw_analysis_results)
    """
    queries = list(queries or [])
    race_name = get_race_display_name()
    all_horse_names = get_all_horse_names()

    # 全馬名を4頭ずつグループ化した馬別クエリを自動追加
    if auto_add_horse_queries:
        batch_size = 4
        for i in range(0, len(all_horse_names), batch_size):
            batch = all_horse_names[i:i + batch_size]
            horses_str = " ".join(batch)
            queries = list(queries) + [f"{race_name} {horses_str} 予想 評価 分析"]

    all_articles = []
    all_web_raw = []
    seen_article_keys = set()
    domains_for_tavily = include_domains or WEB_SEARCH_ALLOWLIST

    progress_bar = st.progress(0)
    status_text = st.empty()
    total_queries = len(queries)
    if total_queries == 0:
        progress_bar.empty()
        status_text.empty()
        return [], []
    tavily_warned = False

    for q_idx, query in enumerate(queries):
        if len(all_articles) >= total_article_limit:
            break

        status_text.info(f"🌐 Web検索中... ({q_idx+1}/{len(queries)}): {query[:30]}")
        articles = []
        remaining = max(0, total_article_limit - len(all_articles))
        if remaining == 0:
            break

        # 1) Tavily優先
        tavily_error = None
        if TAVILY_API_KEY:
            for retry in range(3):
                try:
                    status_text.info(f"🌐 Tavily検索中... ({q_idx+1}/{len(queries)}): {query[:30]}")
                    articles = search_web_articles_with_tavily(
                        query,
                        max_articles=min(5, remaining),
                        include_domains=domains_for_tavily
                    )
                    if articles:
                        break
                except Exception as e:
                    tavily_error = e
                    if retry < 2:
                        status_text.info("⏳ Tavily検索リトライ中...")
                        time.sleep(2)
        else:
            if not tavily_warned:
                st.warning("⚠️ TAVILY_API_KEYが未設定のため、Gemini検索へフォールバック中です。")
                tavily_warned = True

        # 2) Tavily失敗/空時はGemini検索へフォールバック
        if not articles:
            if TAVILY_API_KEY:
                msg = "↪ Tavily失敗 → Gemini検索へ切替"
                if tavily_error:
                    msg += f"（{type(tavily_error).__name__}）"
                status_text.info(msg)

            gemini_search_error = None
            for retry in range(3):
                try:
                    articles = search_web_articles(query, max_articles=min(5, remaining))
                    break
                except Exception as e:
                    gemini_search_error = e
                    if retry < 2:
                        status_text.info("⏳ Gemini検索リトライ中...")
                        time.sleep(2)
            if not articles and gemini_search_error:
                msg = str(gemini_search_error)
                st.warning(f"⚠️ Gemini検索に失敗しました: {type(gemini_search_error).__name__} ({msg[:120]})")

        # レース/馬名との関連が高い記事を優先して複数件解析する
        articles = articles[:max(remaining, 5)]
        unique_articles = _select_articles_for_analysis(
            articles,
            race_name=race_name,
            horse_names=all_horse_names,
            query=query,
            max_items=min(MAX_ANALYZE_ARTICLES_PER_QUERY, remaining),
        )

        selected_articles = []
        for article in unique_articles:
            url_key = _to_text(article.get("url", "")).strip().lower()
            title_key = _to_text(article.get("title", "")).strip().lower()
            article_key = url_key or f"title::{title_key}"
            if not article_key:
                continue
            if article_key in seen_article_keys:
                continue
            seen_article_keys.add(article_key)
            selected_articles.append(article)

        # Tavily結果の関連度が低い場合は Gemini検索結果で補完する
        if not selected_articles and articles and TAVILY_API_KEY:
            gemini_backfill_error = None
            try:
                gemini_candidates = search_web_articles(query, max_articles=min(5, remaining))
                backfill_unique = _select_articles_for_analysis(
                    gemini_candidates,
                    race_name=race_name,
                    horse_names=all_horse_names,
                    query=query,
                    max_items=min(MAX_ANALYZE_ARTICLES_PER_QUERY, remaining),
                )
                for article in backfill_unique:
                    url_key = _to_text(article.get("url", "")).strip().lower()
                    title_key = _to_text(article.get("title", "")).strip().lower()
                    article_key = url_key or f"title::{title_key}"
                    if not article_key or article_key in seen_article_keys:
                        continue
                    seen_article_keys.add(article_key)
                    selected_articles.append(article)
                if selected_articles:
                    status_text.info("↪ Tavily関連薄のため Gemini検索結果で補完しました")
            except Exception as e:
                gemini_backfill_error = e
            if not selected_articles and gemini_backfill_error:
                msg = str(gemini_backfill_error)
                st.warning(f"⚠️ Gemini補完検索に失敗しました: {type(gemini_backfill_error).__name__} ({msg[:120]})")

        progress_bar.progress((q_idx + 0.5) / total_queries)

        successful_articles = []
        for a_idx, article in enumerate(selected_articles):
            article_title = _to_text(article.get('title', '')) if isinstance(article, dict) else ""
            status_text.info(f"🤖 Web記事を解析中... {(article_title or '無題')[:30]}...")
            results = []
            analyze_error = None
            for retry in range(3):
                try:
                    results = analyze_web_article_with_gemini(article)
                    break
                except Exception as e:
                    analyze_error = e
                    if retry < 2:
                        time.sleep(2)
            if not results and analyze_error:
                msg = str(analyze_error)
                st.warning(f"⚠️ Web記事解析に失敗しました: {type(analyze_error).__name__} ({msg[:120]})")
            if results:
                all_web_raw.extend(results)
                successful_articles.append(article)

        if successful_articles:
            all_articles.extend(successful_articles)

        progress_bar.progress((q_idx + 1) / total_queries)

    progress_bar.empty()
    status_text.empty()
    return all_articles, all_web_raw


def extract_text_from_uploaded_file(uploaded_file):
    """
    アップロードされたPDF/テキストファイルからテキストを抽出する関数

    引数:
        uploaded_file: Streamlitのアップロードファイルオブジェクト

    戻り値:
        str: 抽出されたテキスト
    """
    if uploaded_file is None:
        return ""

    if uploaded_file.type == "application/pdf":
        if not HAS_PDF_SUPPORT:
            st.error("⚠️ PDF処理には PyPDF2 が必要です。`pip install PyPDF2` を実行してください。")
            return ""
        try:
            reader = PyPDF2.PdfReader(uploaded_file)
            text = ""
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text
        except Exception as e:
            st.error(f"⚠️ PDF読み込みエラー: {e}")
            return ""
    else:
        # テキストファイル
        try:
            return uploaded_file.read().decode('utf-8', errors='ignore')
        except Exception as e:
            st.error(f"⚠️ テキスト読み込みエラー: {e}")
            return ""


def _normalize_race_name_for_match(name: str) -> str:
    """レース名を比較用に正規化する。"""
    text = unicodedata.normalize("NFKC", _to_text(name))
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[()（）［］【】「」『』<>＜＞・.。,、]", "", text)
    text = re.sub(r"20\d{2}", "", text)
    text = re.sub(r"(g|jg)[123ⅠⅡⅢ]", "", text)
    return text


def _race_name_alias_candidates(race_name: str) -> list[str]:
    """マッチ精度を上げるために、レース名の別表記候補を返す。"""
    base = _to_text(race_name)
    if not base:
        return []

    candidates = [base]
    normalized_base = _normalize_race_name_for_match(base)

    simple_variants = {
        base.replace("ステークス", "S"),
        base.replace("ステークス", ""),
        base.replace("カップ", "C"),
        base.replace("カップ", ""),
        base.replace("フィリーズ", "F"),
    }
    for variant in simple_variants:
        variant = _to_text(variant)
        if variant and variant not in candidates:
            candidates.append(variant)

    for canonical, aliases in UMANITY_RACE_NAME_ALIASES.items():
        group = [canonical] + list(aliases or [])
        normalized_group = {_normalize_race_name_for_match(name) for name in group}
        if normalized_base in normalized_group:
            for name in group:
                if name and name not in candidates:
                    candidates.append(name)

    return candidates


@st.cache_data(ttl=43200)
def fetch_umanity_graderace_catalog() -> list[dict]:
    """ウマニティ重賞一覧ページから race_id とレース名の対応表を取得する。"""
    url = f"{UMANITY_BASE_URL}/racedata/graderace/"
    response = requests.get(url, headers=UMANITY_HEADERS, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"Umanity catalog HTTP {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    by_id: dict[str, dict] = {}
    for a_tag in soup.find_all("a", href=True):
        href = urljoin(UMANITY_BASE_URL, _to_text(a_tag.get("href")))
        match = re.search(r"/racedata/graderace/(\d{4})/?$", href)
        if not match:
            continue
        race_id = match.group(1)
        race_name = _to_text(a_tag.get_text(" ", strip=True))
        # 一部リンクは「皐月賞 G1 4月19日...」の長文になっているため、レース名部分だけ抽出
        race_name = re.sub(r"\s*(?:J)?G[123ⅠⅡⅢ]\b.*$", "", race_name).strip()
        race_name = re.split(r"\s+", race_name)[0] if race_name else ""
        if not race_name:
            continue
        current = by_id.get(race_id)
        # 同一race_idに複数リンクがあるため、短く素直な表記を優先して保持
        if (not current) or (len(race_name) < len(_to_text(current.get("race_name")))):
            by_id[race_id] = {
                "race_id": race_id,
                "race_name": race_name,
                "url": f"{UMANITY_BASE_URL}/racedata/graderace/{race_id}/",
            }

    return sorted(by_id.values(), key=lambda x: x.get("race_id", ""))


def resolve_umanity_race_info(race_name: str) -> dict | None:
    """レース名からウマニティの graderace 情報を解決する。"""
    catalog = fetch_umanity_graderace_catalog()
    if not catalog:
        return None

    candidates = _race_name_alias_candidates(race_name)
    if not candidates:
        return None

    normalized_catalog = []
    for item in catalog:
        catalog_name = _to_text(item.get("race_name"))
        norm_name = _normalize_race_name_for_match(catalog_name)
        if norm_name:
            normalized_catalog.append((item, catalog_name, norm_name))

    # 1) 正規化完全一致
    for query in candidates:
        query_norm = _normalize_race_name_for_match(query)
        for item, _, norm_name in normalized_catalog:
            if query_norm == norm_name:
                return item

    # 2) 部分一致（略称・正式名称の差を吸収）
    for query in candidates:
        query_norm = _normalize_race_name_for_match(query)
        partial_matches = []
        for item, _, norm_name in normalized_catalog:
            if query_norm and (query_norm in norm_name or norm_name in query_norm):
                partial_matches.append((len(norm_name), item))
        if partial_matches:
            partial_matches.sort(key=lambda x: x[0], reverse=True)
            return partial_matches[0][1]

    # 3) あいまい一致
    best_item = None
    best_score = 0.0
    for query in candidates:
        query_norm = _normalize_race_name_for_match(query)
        if not query_norm:
            continue
        for item, _, norm_name in normalized_catalog:
            score = SequenceMatcher(None, query_norm, norm_name).ratio()
            if score > best_score:
                best_score = score
                best_item = item
    if best_item and best_score >= 0.6:
        return best_item
    return None


def _normalize_umanity_header_label(text: str) -> str:
    """Umanity表ヘッダを比較しやすい形へ正規化する。"""
    normalized = unicodedata.normalize("NFKC", _to_text(text))
    if not normalized:
        return ""
    return normalized.replace("　", "").replace(" ", "").strip()


def _find_umanity_header_index(headers: list[str], *candidates: str) -> int:
    """ヘッダ文字列から候補語に一致する列indexを返す。"""
    for idx, header in enumerate(headers):
        for candidate in candidates:
            if candidate and candidate in header:
                return idx
    return -1


def _extract_weight_from_jockey_cell(text: str) -> str:
    """騎手・斤量セルから斤量数値を抽出する。"""
    normalized = unicodedata.normalize("NFKC", _to_text(text))
    if not normalized:
        return ""
    tail_match = re.search(r"(\d{2}(?:\.\d)?)\s*$", normalized)
    if tail_match:
        return tail_match.group(1)
    any_match = re.search(r"(\d{2}(?:\.\d)?)", normalized)
    return any_match.group(1) if any_match else ""


@st.cache_data(ttl=21600)
def fetch_umanity_racecard_map(race_name: str) -> dict:
    """Umanity racecard から馬別の近3走情報を取得する。"""
    resolved = resolve_umanity_race_info(race_name)
    if not resolved:
        raise RuntimeError(f"Umanity racecard id unresolved: {race_name}")

    race_id = _to_text(resolved.get("race_id"))
    if not race_id:
        raise RuntimeError(f"Invalid Umanity race id: {resolved}")

    page_url = f"{UMANITY_BASE_URL}/racedata/graderace/{race_id}/racecard.php"
    response = requests.get(page_url, headers=UMANITY_HEADERS, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"Umanity racecard page HTTP {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.select_one("table.grace_table")
    if not table:
        raise RuntimeError("Umanity racecard table not found")

    headers = [_normalize_umanity_header_label(th.get_text(" ", strip=True)) for th in table.select("thead th")]
    if not headers:
        head_cells = table.select("tr th")
        headers = [_normalize_umanity_header_label(cell.get_text(" ", strip=True)) for cell in head_cells]
    if not headers:
        raise RuntimeError("Umanity racecard header not found")

    horse_idx = _find_umanity_header_index(headers, "馬名")
    jockey_idx = _find_umanity_header_index(headers, "騎手負担重量", "騎手")
    prev1_idx = _find_umanity_header_index(headers, "前走")
    prev2_idx = _find_umanity_header_index(headers, "2走前", "２走前")
    prev3_idx = _find_umanity_header_index(headers, "3走前", "３走前")
    if horse_idx < 0:
        raise RuntimeError("Umanity racecard horse column not found")

    rows = table.select("tbody tr")
    if not rows:
        rows = table.find_all("tr")[1:]
    if not rows:
        raise RuntimeError("Umanity racecard rows not found")

    entries: dict[str, dict] = {}
    for row in rows:
        cells = row.find_all("td")
        if not cells or horse_idx >= len(cells):
            continue

        horse_cell = cells[horse_idx]
        horse_name = ""
        horse_link = horse_cell.select_one("a")
        if horse_link:
            horse_name = _to_text(horse_link.get_text(" ", strip=True))
        if not horse_name:
            horse_text = _to_text(horse_cell.get_text(" ", strip=True))
            horse_name = re.split(r"\s+", horse_text)[0] if horse_text else ""
        if not horse_name:
            continue

        jockey_text = ""
        if 0 <= jockey_idx < len(cells):
            jockey_text = _to_text(cells[jockey_idx].get_text(" ", strip=True))

        def _cell_text(idx: int) -> str:
            if idx < 0 or idx >= len(cells):
                return ""
            return re.sub(r"\s+", " ", _to_text(cells[idx].get_text(" ", strip=True))).strip()

        entry = {
            "馬名": horse_name,
            "斤量補完": _extract_weight_from_jockey_cell(jockey_text),
            "前走": _cell_text(prev1_idx),
            "2走前": _cell_text(prev2_idx),
            "3走前": _cell_text(prev3_idx),
        }
        entries[_normalize_horse_token(horse_name)] = entry

    if not entries:
        raise RuntimeError("Umanity racecard entries not found")

    return {
        "race_id": race_id,
        "source_url": page_url,
        "entries": entries,
    }


def enrich_entry_table_with_umanity(df: pd.DataFrame, race_name: str) -> pd.DataFrame:
    """出馬表DataFrameへ Umanity racecard の近3走と斤量補完を反映する。"""
    if not isinstance(df, pd.DataFrame) or df.empty or "馬名" not in df.columns:
        return df

    race_label = _to_text(race_name)
    if not race_label:
        return df.copy()

    try:
        payload = fetch_umanity_racecard_map(race_label)
    except Exception:
        return df.copy()

    entries = payload.get("entries") if isinstance(payload, dict) else {}
    if not isinstance(entries, dict) or not entries:
        return df.copy()

    enriched = df.copy()
    for col in ("前走", "2走前", "3走前"):
        if col not in enriched.columns:
            enriched[col] = ""
    if "斤量" not in enriched.columns:
        enriched["斤量"] = ""

    for idx, row in enriched.iterrows():
        horse_name = _to_text(row.get("馬名"))
        key = _normalize_horse_token(horse_name)
        entry = entries.get(key)
        if not entry:
            continue

        for col in ("前走", "2走前", "3走前"):
            val = _to_text(entry.get(col))
            if val:
                enriched.at[idx, col] = val

        current_weight = _to_text(row.get("斤量"))
        if current_weight.lower() in {"", "-", "nan", "none", "---.-"}:
            fallback_weight = _to_text(entry.get("斤量補完"))
            if fallback_weight:
                enriched.at[idx, "斤量"] = fallback_weight

    return enriched


def _extract_umanity_section_title(table, fallback_index: int) -> str:
    """Umanityデータ表の直前見出し（◆〜）をセクション名として抽出する。"""
    label_tag = table.find_previous(
        lambda tag: tag.name in {"p", "h3", "h4"} and "◆" in _to_text(tag.get_text(" ", strip=True))
    )
    if label_tag:
        text = _to_text(label_tag.get_text(" ", strip=True)).lstrip("◆").strip()
        if text:
            return text
    return f"データ分析 {fallback_index + 1}"


def _parse_umanity_analysis_tables(soup: BeautifulSoup) -> list[dict]:
    """Umanityのデータ分析表（人気/脚質/枠順など）を抽出する。"""
    tables = []
    for idx, table in enumerate(soup.select("table.grace_data_table01")):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        headers = [_to_text(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"])]
        headers = [h for h in headers if h]
        if len(headers) < 2:
            continue

        parsed_rows = []
        for row in rows[1:]:
            cells = [_to_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if not cells:
                continue
            if len(cells) < len(headers):
                cells = cells + [""] * (len(headers) - len(cells))
            row_dict = {headers[i]: cells[i] for i in range(len(headers))}
            parsed_rows.append(row_dict)

        if not parsed_rows:
            continue

        tables.append({
            "section": _extract_umanity_section_title(table, idx),
            "headers": headers,
            "rows": parsed_rows,
        })
    return tables


def _parse_percent_number(value) -> float | None:
    """'55.0%' のような文字列から数値を抽出する。"""
    text = _to_text(value).replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _top_and_bottom_by_rate(table: dict) -> tuple[dict | None, dict | None]:
    """表から複勝率ベースの最上位/最下位行を返す。"""
    headers = table.get("headers") if isinstance(table, dict) else None
    if not isinstance(headers, list) or len(headers) < 2:
        return None, None
    label_col = headers[0]

    ranked = []
    for row in table.get("rows", []) if isinstance(table, dict) else []:
        if not isinstance(row, dict):
            continue
        label = _to_text(row.get(label_col))
        rate = _parse_percent_number(row.get("複勝率"))
        if not label or rate is None:
            continue
        ranked.append((rate, row))
    if not ranked:
        return None, None
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1], ranked[-1][1]


def _table_top_rows(table: dict, limit: int = 3) -> list[dict]:
    """表から複勝率の高い順に上位行を返す。"""
    ranked = []
    for row in table.get("rows", []) if isinstance(table, dict) else []:
        if not isinstance(row, dict):
            continue
        rate = _parse_percent_number(row.get("複勝率"))
        if rate is None:
            continue
        ranked.append((rate, row))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in ranked[:limit]]


def _format_rate_row(row: dict, label_col: str) -> str:
    """成績行を説明文へ整形する。"""
    label = _to_text(row.get(label_col))
    rate = _to_text(row.get("複勝率"))
    record = _to_text(row.get("着別度数"))
    parts = [label]
    if rate:
        parts.append(f"複勝率{rate}")
    if record:
        parts.append(f"着別{record}")
    return "（".join([parts[0], " / ".join(parts[1:])]) + "）" if len(parts) > 1 else parts[0]


def _build_race_characteristics_from_umanity(
    race_name: str,
    grade: str,
    venue: str,
    distance: str,
    surface: str,
    date_str: str,
    source_url: str,
    umanity_race_label: str,
    tables: list[dict],
) -> dict:
    """Umanityデータ分析表から、画面表示用のレース特徴dictを構築する。"""
    table_map = {}
    for table in tables:
        section = _to_text(table.get("section"))
        if "人気別成績" in section:
            table_map["popularity"] = table
        elif "単勝オッズ別成績" in section:
            table_map["odds"] = table
        elif "配当" in section:
            table_map["payout"] = table
        elif "脚質別成績" in section:
            table_map["style"] = table
        elif "枠順別成績" in section:
            table_map["frame"] = table
        elif "種牡馬別成績" in section:
            table_map["sire"] = table

    past_lines = []
    win_lines = []
    lose_lines = []

    popularity = table_map.get("popularity")
    if popularity:
        top_rows = _table_top_rows(popularity, limit=3)
        label_col = popularity.get("headers", ["人気"])[0]
        if top_rows:
            top_text = " / ".join(_format_rate_row(row, label_col) for row in top_rows)
            past_lines.append(f"人気別上位: {top_text}")
        pop_best, pop_worst = _top_and_bottom_by_rate(popularity)
        if pop_best:
            win_lines.append(f"人気傾向: {_format_rate_row(pop_best, label_col)}")
        if pop_worst:
            lose_lines.append(f"人気傾向: {_format_rate_row(pop_worst, label_col)}")

    odds = table_map.get("odds")
    if odds:
        odds_best, odds_worst = _top_and_bottom_by_rate(odds)
        label_col = odds.get("headers", ["単勝オッズ"])[0]
        if odds_best:
            win_lines.append(f"オッズ帯: {_format_rate_row(odds_best, label_col)}")
        if odds_worst:
            lose_lines.append(f"オッズ帯: {_format_rate_row(odds_worst, label_col)}")

    style = table_map.get("style")
    if style:
        style_best, style_worst = _top_and_bottom_by_rate(style)
        label_col = style.get("headers", ["脚質"])[0]
        if style_best:
            win_lines.append(f"脚質傾向: {_format_rate_row(style_best, label_col)}")
        if style_worst:
            lose_lines.append(f"脚質傾向: {_format_rate_row(style_worst, label_col)}")

    frame = table_map.get("frame")
    frame_good = ""
    frame_bad = ""
    if frame:
        frame_best, frame_worst = _top_and_bottom_by_rate(frame)
        label_col = frame.get("headers", ["枠順"])[0]
        if frame_best:
            frame_good = _format_rate_row(frame_best, label_col)
            win_lines.append(f"枠順傾向: {frame_good}")
        if frame_worst:
            frame_bad = _format_rate_row(frame_worst, label_col)
            lose_lines.append(f"枠順傾向: {frame_bad}")

    payout = table_map.get("payout")
    if payout:
        payout_focus = []
        for row in payout.get("rows", []):
            if not isinstance(row, dict):
                continue
            bet_type = _to_text(row.get("馬券種"))
            avg = _to_text(row.get("平均配当"))
            if bet_type in {"単勝", "複勝", "馬連", "三連複", "三連単"} and avg:
                payout_focus.append(f"{bet_type}平均{avg}")
        if payout_focus:
            past_lines.append("配当傾向: " + " / ".join(payout_focus))

    sire = table_map.get("sire")
    if sire:
        top_sires = []
        for row in sire.get("rows", [])[:3]:
            if not isinstance(row, dict):
                continue
            sire_name = _to_text(row.get("種牡馬"))
            rate = _to_text(row.get("複勝率"))
            if sire_name:
                top_sires.append(f"{sire_name}（複勝率{rate}）" if rate else sire_name)
        if top_sires:
            past_lines.append("同コース好調種牡馬: " + " / ".join(top_sires))

    source_label = _to_text(umanity_race_label) or race_name
    course_text = f"{venue}競馬場 {surface}{distance}（{grade}）を対象に、ウマニティ「{source_label}データ分析」を主ソースとして整理。"
    note_lines = [
        f"主ソース: ウマニティ データ分析（{source_url}）",
        f"取得対象: {date_str} {race_name}",
    ]
    if not _to_text(table_map.get("style")):
        note_lines.append("脚質別データが取得できなかったため、追加分析を推奨。")

    return {
        "コース特徴": course_text,
        "過去の傾向": "\n".join(f"・{line}" for line in past_lines) if past_lines else "",
        "勝ちやすい馬のタイプ": "\n".join(f"・{line}" for line in win_lines) if win_lines else "",
        "苦手な馬のタイプ": "\n".join(f"・{line}" for line in lose_lines) if lose_lines else "",
        "枠順有利": frame_good,
        "枠順不利": frame_bad,
        "騎手厩舎傾向": "このページには騎手・厩舎別の集計表は掲載なし（必要時はサブ分析で補完）。",
        "注目ポイント": "\n".join(f"・{line}" for line in note_lines),
        "情報ソース": "ウマニティ（データ分析）",
        "情報ソースURL": source_url,
        "情報取得方式": "Umanityスクレイピング（主）",
        "データ分析テーブル": tables,
    }


@st.cache_data(ttl=14400)
def get_race_characteristics_with_umanity(race_name="", grade="", venue="", distance="", surface="", date_str=""):
    """Umanityのデータ分析ページをスクレイピングしてレース特徴を取得する。"""
    resolved = resolve_umanity_race_info(race_name)
    if not resolved:
        raise RuntimeError(f"Umanity graderace id unresolved: {race_name}")

    race_id = _to_text(resolved.get("race_id"))
    if not race_id:
        raise RuntimeError(f"Invalid Umanity race id: {resolved}")

    page_url = f"{UMANITY_BASE_URL}/racedata/graderace/{race_id}/race_data_analyze.php"
    response = requests.get(page_url, headers=UMANITY_HEADERS, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"Umanity analyze page HTTP {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    tables = _parse_umanity_analysis_tables(soup)
    if not tables:
        raise RuntimeError("Umanity analyze tables not found")

    race_label = ""
    h1_tags = soup.find_all("h1")
    if h1_tags:
        # 先頭h1は長文タイトル、後段h1は「皐月賞 G1」のような短い表記
        race_label = _to_text(h1_tags[-1].get_text(" ", strip=True))
    if not race_label:
        race_label = _to_text(resolved.get("race_name"))

    return _build_race_characteristics_from_umanity(
        race_name=race_name,
        grade=grade,
        venue=venue,
        distance=distance,
        surface=surface,
        date_str=date_str,
        source_url=page_url,
        umanity_race_label=race_label,
        tables=tables,
    )


def get_race_characteristics_primary(race_name="", grade="", venue="", distance="", surface="", date_str="", extra_context=""):
    """
    レース特徴取得の統合入口。
    1) Umanityスクレイピング（主）を優先
    2) 失敗時のみ Gemini Web検索（副）へフォールバック
    """
    primary_error = None
    try:
        info = get_race_characteristics_with_umanity(
            race_name=race_name,
            grade=grade,
            venue=venue,
            distance=distance,
            surface=surface,
            date_str=date_str,
        )
        if _has_meaningful_race_characteristics(info):
            return info
        primary_error = RuntimeError("Umanity result was too sparse")
    except Exception as e:
        primary_error = e

    fallback = get_race_characteristics_with_gemini(
        race_name=race_name,
        grade=grade,
        venue=venue,
        distance=distance,
        surface=surface,
        date_str=date_str,
        extra_context=extra_context,
    )
    fallback["情報ソース"] = _to_text(fallback.get("情報ソース")) or "Gemini Web検索（サブ）"
    fallback["情報取得方式"] = "Geminiフォールバック（副）"

    if primary_error:
        fallback_note = f"Umanity取得失敗のためGeminiにフォールバック: {type(primary_error).__name__}"
        current_note = _to_text(fallback.get("注目ポイント"))
        fallback["注目ポイント"] = f"{current_note}\n{fallback_note}" if current_note else fallback_note
    return fallback


@st.cache_data(ttl=3600)
def get_race_characteristics_with_gemini(race_name="", grade="", venue="", distance="", surface="", date_str="", extra_context=""):
    """
    GeminiのWeb検索グラウンディングでレース特徴・傾向を取得する関数

    引数:
        race_name, grade, venue, distance, surface, date_str: レースメタデータ
        extra_context (str): ユーザー提供のドキュメントテキスト（補足情報）

    戻り値:
        dict: レース特徴の辞書
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    extra_section = f"\n# 参考資料（ユーザー提供ドキュメント）\n{extra_context[:3000]}\n" if extra_context else ""
    race_label = f"{race_name}（{venue}競馬場 {surface}{distance} {grade}）"

    prompt = f"""
{race_label}について、過去のデータと傾向を詳しく調査してください。
以下の観点で分析してください。
{extra_section}
# 分析観点
1. コースの特徴（{venue}{surface}{distance}の特性、スタート位置、直線の長さ等）
2. 過去10年の傾向（勝ち馬のパターン、人気別成績、年齢別成績など）
3. 勝ちやすい馬のタイプ（脚質、血統、前走条件、ローテーション等）
4. 苦手な馬のタイプ（不向きな条件、注意すべき馬のパターン）
5. 枠順の有利・不利（内枠・外枠の傾向、特定枠番の成績）
6. 騎手・厩舎の傾向（このレースで強い騎手・厩舎）
7. 今年の注目ポイント・特記事項

以下のJSON形式のみで出力してください（説明文不要）：

```json
{{
  "コース特徴": "{venue}{surface}{distance}の特性を詳しく（スタートから直線まで）",
  "過去の傾向": "過去の{race_name}のデータ・傾向を具体的に（人気別・年齢別・脚質別など）",
  "勝ちやすい馬のタイプ": "勝ちやすい馬の条件を箇条書きで詳しく",
  "苦手な馬のタイプ": "不向きな馬の条件を箇条書きで詳しく",
  "枠順有利": "有利な枠順とその理由を具体的に",
  "枠順不利": "不利な枠順とその理由を具体的に",
  "騎手厩舎傾向": "このレースで注目すべき騎手・厩舎の傾向",
  "注目ポイント": "{date_str}の{race_name}で特に注意すべきポイント"
}}
```
"""
    last_error = None
    for retry in range(3):
        try:
            client = google_genai.Client(api_key=GEMINI_API_KEY)
            grounding_tool = genai_types.Tool(google_search=genai_types.GoogleSearch())
            config = genai_types.GenerateContentConfig(tools=[grounding_tool])

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config,
            )

            response_text = response.text or ""
            if not _to_text(response_text):
                raise ValueError("Gemini response is empty")

            parsed = _parse_gemini_json_response(response_text, expected="dict")
            normalized = {}
            for key, value in (parsed or {}).items():
                txt = _to_text(value)
                if txt:
                    normalized[key] = value

            if not _has_meaningful_race_characteristics(normalized):
                raise ValueError("Race characteristics response was too sparse")
            return normalized

        except Exception as e:
            last_error = e
            msg = str(e)
            retryable = _is_transient_gemini_error(msg) or isinstance(e, (ValueError, json.JSONDecodeError))
            if retry < 2 and retryable:
                time.sleep(2 * (retry + 1))
                continue
            raise

    raise RuntimeError(f"Failed to get race characteristics: {type(last_error).__name__ if last_error else 'Unknown'}")


def analyze_document_for_race_characteristics(text, source_name):
    """
    ドキュメントテキストからレース特徴・傾向情報を抽出する関数

    引数:
        text (str): ドキュメントのテキスト
        source_name (str): ドキュメント名

    戻り値:
        dict: レース特徴の辞書
    """
    if not GEMINI_API_KEY or not text:
        return {}
    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        r = get_race_config()
        race_label = f"{r.race_name}（{r.venue}{r.surface}{r.distance} {r.grade}）" if r else "対象レース"
        prompt = f"""
あなたは競馬の専門家です。以下のドキュメントを読み、{race_label}の
特徴・傾向に関する情報を抽出・整理してください。

# ドキュメント（{source_name}）
{text[:4000]}

以下のJSON形式のみで出力してください（情報がない項目は「資料に記載なし」と記載）：

```json
{{
  "コース特徴": "コースの特性に関する記載内容",
  "過去の傾向": "過去のデータ・傾向に関する記載内容",
  "勝ちやすい馬のタイプ": "勝ちやすい馬の条件に関する記載内容",
  "苦手な馬のタイプ": "不向きな馬に関する記載内容",
  "枠順有利": "有利枠に関する記載内容",
  "枠順不利": "不利枠に関する記載内容",
  "騎手厩舎傾向": "騎手・厩舎傾向に関する記載内容",
  "注目ポイント": "その他の注目点・特記事項"
}}
```
"""
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        response_text = response.text or ""
        return _parse_gemini_json_response(response_text, expected="dict")

    except (json.JSONDecodeError, ValueError, Exception) as e:
        error_msg = str(e)
        if _is_transient_gemini_error(error_msg):
            raise
        st.warning(f"⚠️ ドキュメントのレース特徴抽出に失敗しました: {type(e).__name__} ({error_msg[:120]})")
        return {}


def analyze_document_for_horses(text, source_name):
    """
    ドキュメントテキストから馬別のメリット・デメリット情報を抽出する関数

    引数:
        text (str): ドキュメントのテキスト
        source_name (str): ドキュメント名（出典として使用）

    戻り値:
        list: 馬名・プラス情報・マイナス情報のリスト
    """
    if not GEMINI_API_KEY or not text:
        return []

    all_horse_names = get_all_horse_names()
    horse_list_str = "\n".join([f"- {name}" for name in all_horse_names])

    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""
あなたは競馬予想の専門家です。以下のドキュメントから各馬の評価情報を抽出してください。

# ドキュメント（{source_name}）
{text[:4000]}

# 注目すべき出走馬（これら以外の馬名が登場しても抽出してください）
{horse_list_str}

# 抽出してほしい情報（各馬について）
プラス情報: 前走成績・調教・体調・コース適性・騎手厩舎の強みなど
マイナス情報: 敗因・調教不安・コース距離不安・枠順展開不安など

# 出力形式
```json
[
  {{
    "馬名": "馬の名前",
    "プラス情報": "具体的な好材料を2～3文で記載",
    "マイナス情報": "具体的な懸念点を記載（なければ「特になし」）"
  }}
]
```

記事に情報がない馬は出力しない。JSONのみ出力すること。
"""
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        response_text = response.text or ""
        analysis_results = _parse_gemini_json_response(response_text, expected="list")

        for result in analysis_results:
            result['source_url'] = ""
            result['source_title'] = source_name
            result['source_type'] = 'document'

        return analysis_results

    except (json.JSONDecodeError, ValueError):
        return []
    except Exception as e:
        error_msg = str(e)
        if _is_transient_gemini_error(error_msg):
            raise
        st.warning(f"⚠️ ドキュメントの馬情報抽出に失敗しました: {type(e).__name__} ({error_msg[:120]})")
        return []


def highlight_horse_table(row):
    """
    馬別テーブルのスタイリング（メリット=緑、デメリット=薄赤）
    """
    styles = [''] * len(row)
    # 馬名(0)はデフォルト
    styles[1] = 'background-color: #d4edda; color: #155724;'  # メリット
    styles[2] = 'background-color: #d4edda; color: #155724;'  # メリット出典
    styles[3] = 'background-color: #f8d7da; color: #721c24;'  # デメリット
    styles[4] = 'background-color: #f8d7da; color: #721c24;'  # デメリット出典
    # 情報源数(5)はデフォルト
    return styles


def check_password():
    """シンプルなパスワード認証。Streamlit Secrets の PASSWORD キーを使用。"""
    if st.session_state.get('authenticated'):
        return True
    st.markdown("## 🏇 重賞予想アプリ")
    pw = st.text_input("パスワードを入力してください", type="password", key="pw_input")
    if st.button("ログイン", type="primary"):
        correct = st.secrets.get("PASSWORD", "7777")
        if pw == correct:
            st.session_state['authenticated'] = True
            st.rerun()
        elif pw:
            st.error("パスワードが違います")
    return False


def style_dataframe(df):
    """
    データフレームにスタイリングを適用する関数

    引数:
        df (DataFrame): スタイリング対象のデータフレーム

    戻り値:
        Styler: スタイリングが適用されたデータフレーム
    """
    def highlight_plus_minus(row):
        """
        プラス情報を緑、マイナス情報を薄い赤でハイライトする関数
        """
        styles = [''] * len(row)

        # プラス情報列（インデックス1）
        if row['プラス情報']:
            styles[1] = 'background-color: #d4edda; color: #155724;'  # 緑色の背景

        # プラス出典列（インデックス2）
        if row['プラス出典']:
            styles[2] = 'background-color: #d4edda; color: #155724;'

        # マイナス情報列（インデックス3）
        if row['マイナス情報']:
            styles[3] = 'background-color: #f8d7da; color: #721c24;'  # 薄い赤色の背景

        # マイナス出典列（インデックス4）
        if row['マイナス出典']:
            styles[4] = 'background-color: #f8d7da; color: #721c24;'

        return styles

    # スタイリングを適用
    styled_df = df.style.apply(highlight_plus_minus, axis=1)

    return styled_df


# ====================
# データ読み込み関数
# ====================

@st.cache_data
def load_race_data(file_path, mtime=None):  # noqa: ARG001
    """
    CSVファイルから競馬データを読み込む関数

    @st.cache_data + mtime引数によりファイルが更新されると自動的に
    キャッシュが無効化され、最新データを再読み込みします。

    引数:
        file_path (str): CSVファイルのパス
        mtime (float): ファイル更新時刻（キャッシュキー用、直接使用しない）

    戻り値:
        DataFrame: 読み込んだデータ（エラー時はNone）
    """
    try:
        # CSVファイルが存在するか確認
        if not os.path.exists(file_path):
            st.error(f"❌ ファイルが見つかりません: {file_path}")
            st.info("💡 先に get_keiba_info.py を実行してCSVファイルを作成してください。")
            return None

        # CSVファイルを読み込み（UTF-8-SIG エンコーディング）
        df = pd.read_csv(file_path, encoding='utf-8-sig')

        return df

    except Exception as e:
        st.error(f"❌ データ読み込みエラー: {e}")
        return None

def fetch_odds_and_gates(max_retries: int = 3, require_odds: bool = True):
    """
    netkeiba.com から最新の枠番・馬番・オッズを取得する。
    netkeiba はJS描画のため Playwright を使用。
    取得失敗時は空辞書とエラーメッセージを返す（呼び出し元でフォールバック）。

    戻り値:
        tuple[dict, str]: ({馬名: {'枠番': str, '馬番': str, 'オッズ': str}}, error_message)
    """
    errors = []

    def _find_td_by_class_prefix(row, prefix: str):
        for td in row.find_all('td'):
            classes = td.get('class') or []
            if any(str(c).startswith(prefix) for c in classes):
                return td
        return None

    def _extract_from_html(content: str, require_odds_in_result: bool):
        soup = BeautifulSoup(content, 'html.parser')
        shutuba_table = soup.find('table', class_='Shutuba_Table')
        if not shutuba_table:
            raise RuntimeError("Shutuba_Table が見つかりませんでした")

        result = {}
        numeric_odds_count = 0
        for row in shutuba_table.find_all('tr'):
            horse_info = row.find('td', class_='HorseInfo')
            if not horse_info:
                continue
            horse_link = horse_info.find('a')
            if not horse_link:
                continue

            horse_name = horse_link.text.strip()

            # class が "Waku1"/"Umaban1" 形式でも "Waku"/"Umaban" 形式でも拾えるようにする
            waku_td = _find_td_by_class_prefix(row, "Waku")
            umaban_td = _find_td_by_class_prefix(row, "Umaban")
            odds_td = row.select_one('td.Txt_R.Popular') or row.select_one('td.Popular')

            waku = waku_td.get_text(strip=True) if waku_td else ''
            umaban = umaban_td.get_text(strip=True) if umaban_td else ''
            odds = odds_td.get_text(strip=True) if odds_td else '---.-'
            if re.match(r'^\d+(\.\d+)?$', odds):
                numeric_odds_count += 1

            result[horse_name] = {
                '枠番': waku,
                '馬番': umaban,
                'オッズ': odds
            }

        if len(result) < 8:
            raise RuntimeError(f"抽出頭数が少なすぎます: {len(result)}頭")
        if require_odds_in_result:
            min_required = max(5, len(result) // 2)
            if numeric_odds_count < min_required:
                raise RuntimeError(
                    f"オッズが十分取得できませんでした: {numeric_odds_count}/{len(result)}頭"
                )
        return result

    def _fetch_with_playwright_subprocess():
        py_code = r'''
import json
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

RACE_URL = "''' + get_race_url() + r'''"

def _find_td_by_class_prefix(row, prefix):
    for td in row.find_all('td'):
        classes = td.get('class') or []
        if any(str(c).startswith(prefix) for c in classes):
            return td
    return None

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(RACE_URL, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_selector('table.Shutuba_Table', timeout=15000)
    page.wait_for_timeout(2500)
    content = page.content()
    browser.close()

soup = BeautifulSoup(content, 'html.parser')
table = soup.find('table', class_='Shutuba_Table')
if not table:
    raise RuntimeError("Shutuba_Table が見つかりませんでした")

result = {}
for row in table.find_all('tr'):
    horse_info = row.find('td', class_='HorseInfo')
    if not horse_info:
        continue
    horse_link = horse_info.find('a')
    if not horse_link:
        continue
    horse_name = horse_link.text.strip()
    waku_td = _find_td_by_class_prefix(row, "Waku")
    umaban_td = _find_td_by_class_prefix(row, "Umaban")
    odds_td = row.select_one('td.Txt_R.Popular') or row.select_one('td.Popular')
    result[horse_name] = {
        "枠番": waku_td.get_text(strip=True) if waku_td else "",
        "馬番": umaban_td.get_text(strip=True) if umaban_td else "",
        "オッズ": odds_td.get_text(strip=True) if odds_td else "---.-"
    }

print(json.dumps(result, ensure_ascii=False))
'''
        proc = subprocess.run(
            [sys.executable, "-c", py_code],
            capture_output=True,
            text=True,
            timeout=70
        )
        if proc.returncode != 0:
            raise RuntimeError(f"subprocess failed: {proc.stderr.strip() or proc.stdout.strip()}")
        payload = (proc.stdout or "").strip()
        if not payload:
            raise RuntimeError("subprocess returned empty output")
        return json.loads(payload)

    for attempt in range(1, max_retries + 1):
        browser = None
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(get_race_url(), wait_until='domcontentloaded', timeout=30000)
                page.wait_for_selector('table.Shutuba_Table', timeout=15000)
                page.wait_for_timeout(2500)  # オッズ描画待ち
                content = page.content()
                browser.close()
                browser = None

            result = _extract_from_html(content, require_odds)
            return result, ""

        except Exception as e:
            errors.append(f"[{attempt}/{max_retries}] Playwright {type(e).__name__}: {e}")
            if attempt < max_retries:
                time.sleep(1.2 * attempt)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    # Streamlitの実行スレッドでPlaywrightが動かない環境向け（別プロセスで実行）
    try:
        result = _fetch_with_playwright_subprocess()
        if require_odds:
            numeric_odds_count = sum(
                1 for v in result.values()
                if re.match(r'^\d+(\.\d+)?$', str(v.get('オッズ', '')).strip())
            )
            min_required = max(5, len(result) // 2)
            if numeric_odds_count < min_required:
                raise RuntimeError(
                    f"subprocess Playwright: オッズが十分取得できませんでした: {numeric_odds_count}/{len(result)}頭"
                )
        return result, ""
    except Exception as e:
        errors.append(f"[subprocess] Playwright {type(e).__name__}: {e}")

    # Playwrightが使えない環境向けフォールバック（Windowsイベントループ差異の回避）
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(get_race_url(), headers=headers, timeout=20)
        resp.encoding = 'EUC-JP'
        result = _extract_from_html(resp.text, require_odds)
        return result, ""
    except Exception as e:
        errors.append(f"[fallback] requests {type(e).__name__}: {e}")
        errors.append(traceback.format_exc(limit=2))

    return {}, "\n".join(errors)


# ====================
# 予算連動買い目プラン関連
# ====================

def _find_td_by_class_prefix(row, prefix: str):
    """class='Umaban1' のような接尾辞付きクラスにも対応して td を取得する。"""
    for td in row.find_all('td'):
        classes = td.get('class') or []
        if any(str(c).startswith(prefix) for c in classes):
            return td
    return None


def _normalize_umaban(value) -> str:
    text = _to_text(value)
    if not text:
        return ""
    m = re.search(r'\d{1,2}', text)
    if not m:
        return ""
    try:
        return str(int(m.group(0)))
    except ValueError:
        return ""


def _safe_odds_float(value) -> float | None:
    text = _to_text(value).replace(",", "")
    if not text:
        return None
    m = re.search(r'\d+(?:\.\d+)?', text)
    if not m:
        return None
    try:
        v = float(m.group(0))
    except ValueError:
        return None
    if v <= 0:
        return None
    return v


def _ticket_key(nums: list[str], ordered: bool = False) -> str:
    clean = [_normalize_umaban(n) for n in nums]
    clean = [n for n in clean if n]
    if not ordered:
        clean = sorted(clean, key=lambda x: int(x))
    return "-".join(clean)


def _split_ticket_key(ticket_key: str) -> list[str]:
    return [_normalize_umaban(x) for x in str(ticket_key).split('-') if _normalize_umaban(x)]


def _format_ticket_label(bet_type: str, ticket_key: str, umaban_to_horse: dict[str, str]) -> str:
    nums = _split_ticket_key(ticket_key)
    if not nums:
        return ticket_key
    parts = []
    for num in nums:
        horse = _to_text(umaban_to_horse.get(num))
        if horse:
            parts.append(f"{num}({horse})")
        else:
            parts.append(num)
    sep = "→" if bet_type == "三連単" else "-"
    return sep.join(parts)


def _build_horse_umaban_maps(df_active: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    horse_to_umaban = {}
    umaban_to_horse = {}
    if df_active is None or df_active.empty or '馬名' not in df_active.columns:
        return horse_to_umaban, umaban_to_horse

    for _, row in df_active.iterrows():
        horse = _to_text(row.get('馬名'))
        umaban = _normalize_umaban(row.get('馬番'))
        if not horse:
            continue
        if umaban:
            horse_to_umaban[horse] = umaban
            umaban_to_horse[umaban] = horse
    return horse_to_umaban, umaban_to_horse


def _fetch_netkeiba_html(url: str, max_retries: int = 2) -> tuple[str, str]:
    """netkeibaページのHTMLを取得する。requests優先、失敗時はPlaywrightサブプロセスを試す。"""
    errors = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}")
            if not resp.encoding:
                resp.encoding = 'EUC-JP'
            html = resp.text or ""
            if len(html) < 500:
                raise RuntimeError("response body too short")
            return html, ""
        except Exception as e:
            errors.append(f"[{attempt}/{max_retries}] requests {type(e).__name__}: {e}")
            if attempt < max_retries:
                time.sleep(0.8 * attempt)

    # requestsで失敗した場合のみPlaywrightサブプロセスを試す
    try:
        py_code = f"""
from playwright.sync_api import sync_playwright
url = {json.dumps(url, ensure_ascii=False)}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(url, wait_until='domcontentloaded', timeout=30000)
    page.wait_for_timeout(2000)
    print(page.content())
    browser.close()
"""
        proc = subprocess.run(
            [sys.executable, "-c", py_code],
            capture_output=True,
            text=True,
            timeout=70,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "playwright subprocess failed")
        html = (proc.stdout or "").strip()
        if len(html) < 500:
            raise RuntimeError("playwright html too short")
        return html, ""
    except Exception as e:
        errors.append(f"[subprocess] Playwright {type(e).__name__}: {e}")

    return "", "\n".join(errors)


def _extract_bet_type_from_link(text: str, href: str) -> str:
    label = _to_text(text)
    href = _to_text(href)
    if "三連単" in label or "3連単" in label:
        return "三連単"
    if "三連複" in label or "3連複" in label:
        return "三連複"
    if "ワイド" in label:
        return "ワイド"
    if "馬連" in label:
        return "馬連"
    if "複勝" in label:
        return "複勝"
    if "単勝" in label:
        return "複勝"  # 単勝は既存フローで取得済み、b1ページは複勝取得目的で使う

    try:
        q = parse_qs(urlparse(href).query)
        t = (q.get("type") or [""])[0]
    except Exception:
        t = ""
    code_map = {
        "b1": "複勝",
        "b4": "馬連",
        "b5": "ワイド",
        "b6": "ワイド",
        "b7": "三連複",
        "b8": "三連単",
        "b9": "三連単",
    }
    return code_map.get(t, "")


def _discover_bet_type_url_candidates(race_url: str, race_id: str) -> tuple[dict[str, list[str]], list[str]]:
    candidates = {bt: [] for bt in BET_TYPES_ALL if bt != "単勝"}
    warnings = []

    html, err = _fetch_netkeiba_html(race_url, max_retries=2)
    if err:
        warnings.append(f"オッズURL探索: raceページ取得失敗（{err.splitlines()[-1]}）")

    if html:
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.select('a[href*="odds/index.html"]'):
            href_raw = _to_text(a.get('href'))
            if not href_raw:
                continue
            full_url = urljoin(race_url, href_raw)
            bet_type = _extract_bet_type_from_link(a.get_text(" ", strip=True), full_url)
            if bet_type and bet_type in candidates:
                candidates[bet_type].append(full_url)

    # fallback: typeコード候補を追加
    for bet_type, codes in BET_ODDS_TYPE_CODE_CANDIDATES.items():
        for code in codes:
            fallback_url = f"https://race.netkeiba.com/odds/index.html?race_id={race_id}&type={code}"
            candidates[bet_type].append(fallback_url)

    # 重複除去（順序維持）
    for bet_type in list(candidates.keys()):
        seen = set()
        deduped = []
        for url in candidates[bet_type]:
            if url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        candidates[bet_type] = deduped

    return candidates, warnings


def _check_jra_odds_api_status(race_id: str) -> tuple[str, str]:
    """
    netkeibaのJRAオッズAPI状態を返す。
    戻り値: (status, reason)
    """
    url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"https://race.netkeiba.com/odds/index.html?race_id={race_id}",
    }
    try:
        resp = requests.get(url, headers=headers, params={"race_id": race_id}, timeout=15)
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        status = _to_text((data or {}).get("status", "")) or ""
        reason = _to_text((data or {}).get("reason", "")) or ""
        return status.lower(), reason.lower()
    except Exception:
        return "", ""


def _extract_tansho_fukusho_maps(html: str) -> tuple[dict[str, float], dict[str, float]]:
    """単勝/複勝同居ページから馬番別オッズを抽出する。"""
    soup = BeautifulSoup(html, 'html.parser')
    tansho = {}
    fukusho = {}

    tables = [t for t in soup.find_all('table') if ("単勝" in t.get_text(" ", strip=True) or "複勝" in t.get_text(" ", strip=True))]
    if not tables:
        tables = soup.find_all('table')

    range_pat = re.compile(r'(\d+(?:\.\d+)?)\s*[-〜~]\s*(\d+(?:\.\d+)?)')

    for table in tables:
        for row in table.find_all('tr'):
            umaban_td = _find_td_by_class_prefix(row, "Umaban")
            if umaban_td:
                umaban = _normalize_umaban(umaban_td.get_text(strip=True))
            else:
                cells = [td.get_text(" ", strip=True) for td in row.find_all('td')]
                digit_cells = [c for c in cells if re.fullmatch(r'\d{1,2}', c)]
                if len(digit_cells) >= 2:
                    umaban = _normalize_umaban(digit_cells[1])
                elif len(digit_cells) == 1:
                    umaban = _normalize_umaban(digit_cells[0])
                else:
                    umaban = ""

            if not umaban:
                continue

            row_text = row.get_text(" ", strip=True)
            decimals = [float(x) for x in re.findall(r'\d+\.\d+', row_text)]
            if decimals:
                tan = decimals[0]
                if tan > 0:
                    tansho[umaban] = tan

            m = range_pat.search(row_text)
            if m:
                low = _safe_odds_float(m.group(1))
                high = _safe_odds_float(m.group(2))
                if low and high:
                    fukusho[umaban] = (low + high) / 2.0

        if tansho or fukusho:
            break

    return tansho, fukusho


def _extract_combination_odds_map(html: str, expected_size: int, ordered: bool) -> dict[str, float]:
    """
    連系オッズページから組み合わせオッズを抽出する。
    旧レイアウト（1-2形式）と現行レイアウト（cart-item属性）に対応。
    """
    soup = BeautifulSoup(html, 'html.parser')
    odds_map = {}

    # 現行レイアウト: td[cart-item] の末尾に組み合わせ番号が入る
    for cell in soup.select('td[cart-item], td[name*="_b"]'):
        attr = _to_text(cell.get('cart-item') or cell.get('name') or "")
        if not attr:
            continue

        m = re.search(r'_c\d+_((?:\d+_?)+)$', attr)
        if not m:
            continue
        nums = [_normalize_umaban(x) for x in m.group(1).split('_')]
        nums = [n for n in nums if n]
        if len(nums) != expected_size:
            continue

        odds_val = _safe_odds_float(cell.get_text(" ", strip=True))
        if not odds_val:
            continue

        key = _ticket_key(nums, ordered=ordered)
        if not key:
            continue
        if key not in odds_map or odds_val < odds_map[key]:
            odds_map[key] = odds_val

    if odds_map:
        return odds_map

    # 旧レイアウト: 行テキストに「1-2」「1-2-3」が出る形式
    if expected_size == 2:
        combo_pat = re.compile(r'(\d{1,2})\s*[-ー－→/]\s*(\d{1,2})')
    else:
        combo_pat = re.compile(r'(\d{1,2})\s*[-ー－→/]\s*(\d{1,2})\s*[-ー－→/]\s*(\d{1,2})')

    for row in soup.find_all('tr'):
        row_text = row.get_text(" ", strip=True)
        if not row_text:
            continue
        combo = combo_pat.search(row_text)
        if not combo:
            continue

        nums = list(combo.groups())
        if any((not _normalize_umaban(n)) for n in nums):
            continue

        odds_val = None
        for raw in re.findall(r'\d+(?:\.\d+)?', row_text):
            odds_val = _safe_odds_float(raw)
            if odds_val:
                break
        if not odds_val:
            continue

        key = _ticket_key(nums, ordered=ordered)
        if not key:
            continue
        if key not in odds_map or odds_val < odds_map[key]:
            odds_map[key] = odds_val

    return odds_map


def _format_bet_type_list(items: list[str]) -> str:
    ordered = []
    seen = set()
    for bt in BET_TYPES_ALL:
        if bt in (items or []) and bt not in seen:
            ordered.append(bt)
            seen.add(bt)
    for bt in (items or []):
        if bt not in seen:
            ordered.append(bt)
            seen.add(bt)
    return " / ".join(ordered)


def _looks_like_unpublished_odds_html(html: str) -> bool:
    if not html:
        return False
    text = re.sub(r'\s+', ' ', BeautifulSoup(html, 'html.parser').get_text(" ", strip=True))
    hints = (
        "馬券発売開始後",
        "順次公開",
        "発売開始日時",
        "オッズは現在",
        "更新待ち",
    )
    return any(h in text for h in hints)


def fetch_multi_bet_type_odds(df_active: pd.DataFrame, selected_bet_types: list[str]) -> tuple[dict[str, dict[str, float]], list[str]]:
    """買い目プラン用に券種別オッズを取得する（部分成功を許容）。"""
    selected = [bt for bt in (selected_bet_types or []) if bt in BET_TYPES_ALL]
    odds_by_type = {bt: {} for bt in selected}
    warnings = []
    r = get_race_config()

    if not r or not r.race_id:
        return odds_by_type, ["レースIDが未解決のためオッズ取得できません。"]

    horse_to_umaban, _ = _build_horse_umaban_maps(df_active)
    if not horse_to_umaban:
        warnings.append("出馬表の馬番が不足しているため、オッズの突合に失敗する可能性があります。")

    # 単勝: 既存の latest_odds を優先利用（足りない場合はnetkeiba再取得）
    latest_odds = st.session_state.get('latest_odds', {}) or {}
    if "単勝" in odds_by_type:
        for horse, odds_text in latest_odds.items():
            umaban = horse_to_umaban.get(_to_text(horse))
            odds_val = _safe_odds_float(odds_text)
            if umaban and odds_val:
                odds_by_type["単勝"][umaban] = odds_val

        if not odds_by_type["単勝"]:
            gate_data, err = fetch_odds_and_gates(require_odds=False)
            if err:
                warnings.append(f"単勝オッズ取得警告: {err.splitlines()[-1]}")
            for horse, row in (gate_data or {}).items():
                umaban = horse_to_umaban.get(_to_text(horse)) or _normalize_umaban((row or {}).get('馬番'))
                odds_val = _safe_odds_float((row or {}).get('オッズ'))
                if umaban and odds_val:
                    odds_by_type["単勝"][umaban] = odds_val

        if not odds_by_type["単勝"]:
            warnings.append("単勝オッズを取得できませんでした。")

    non_single_types = [bt for bt in selected if bt != "単勝"]
    if non_single_types:
        api_status, api_reason = _check_jra_odds_api_status(str(r.race_id))
        odds_unpublished = api_status in {"middle", "ng"} and ("empty" in api_reason or "result odds empty" in api_reason)
        if odds_unpublished:
            warnings.append("単勝以外の券種オッズは現在未公開です（発売前または更新待ち）。")
            for bt in non_single_types:
                odds_by_type[bt] = {}
            return odds_by_type, warnings

        # 単勝以外のオッズURL候補を収集
        candidates, discover_warnings = _discover_bet_type_url_candidates(get_race_url(), str(r.race_id))
        warnings.extend(discover_warnings)
    else:
        candidates = {}

    unpublished_types = []
    failed_types = []
    for bet_type in selected:
        if bet_type == "単勝":
            continue

        urls = candidates.get(bet_type, [])
        parsed = {}
        last_err = ""
        unpublished_hint = False

        for url in urls:
            html, err = _fetch_netkeiba_html(url, max_retries=2)
            if err and not html:
                last_err = err
                continue
            if _looks_like_unpublished_odds_html(html):
                unpublished_hint = True

            if bet_type == "複勝":
                _, fukusho_map = _extract_tansho_fukusho_maps(html)
                parsed = fukusho_map
            elif bet_type in ("ワイド", "馬連"):
                parsed = _extract_combination_odds_map(html, expected_size=2, ordered=False)
            elif bet_type == "三連複":
                parsed = _extract_combination_odds_map(html, expected_size=3, ordered=False)
            elif bet_type == "三連単":
                parsed = _extract_combination_odds_map(html, expected_size=3, ordered=True)

            if parsed:
                break

        odds_by_type[bet_type] = parsed
        if not parsed:
            if unpublished_hint:
                unpublished_types.append(bet_type)
            else:
                detail = last_err.splitlines()[-1] if last_err else ""
                failed_types.append((bet_type, detail))

    if unpublished_types:
        warnings.append(
            f"以下券種のオッズは現在未公開です（発売前または更新待ち）: {_format_bet_type_list(unpublished_types)}"
        )
    if failed_types:
        failed_labels = _format_bet_type_list([bt for bt, _ in failed_types])
        detail = next((d for _, d in failed_types if d), "")
        msg = f"以下券種のオッズ取得に失敗しました: {failed_labels}"
        if detail:
            msg += f"（{detail}）"
        warnings.append(msg)

    return odds_by_type, warnings


def _count_info_items(text: str) -> int:
    s = _to_text(text)
    if not s or s in {"（情報なし）", "情報なし"}:
        return 0
    marks = re.findall(r'\[\d+\]', s)
    if marks:
        return len(marks)
    parts = [p for p in re.split(r'\n\n+', s) if _to_text(p)]
    return len(parts) if parts else 1


def _extract_horse_scores_for_bet_plan(df_active: pd.DataFrame) -> list[dict]:
    horse_to_umaban, _ = _build_horse_umaban_maps(df_active)
    horse_names = sorted(horse_to_umaban.keys())
    if not horse_names:
        return []

    stats = {
        h: {
            "horse": h,
            "umaban": horse_to_umaban.get(h, ""),
            "plus_count": 0,
            "minus_count": 0,
            "source_count": 0,
            "training_plus": 0,
            "training_minus": 0,
            "yt_bonus": 0.0,
            "odds": None,
            "score": 0.0,
            "prob": 0.0,
        }
        for h in horse_names
    }

    horse_df = st.session_state.get('horse_df')
    if horse_df is not None and not horse_df.empty and '馬名' in horse_df.columns:
        for _, row in horse_df.iterrows():
            horse = _to_text(row.get('馬名'))
            if horse not in stats:
                continue
            stats[horse]["plus_count"] = _count_info_items(row.get('メリット'))
            stats[horse]["minus_count"] = _count_info_items(row.get('デメリット'))
            try:
                stats[horse]["source_count"] = int(float(row.get('情報源数', 0) or 0))
            except (ValueError, TypeError):
                stats[horse]["source_count"] = 0

    for item in st.session_state.get('training_items', []) or []:
        if not isinstance(item, dict):
            continue
        horse = _to_text(item.get('馬名'))
        if horse not in stats:
            continue
        kind = _to_text(item.get('種別'))
        if kind == "プラス":
            stats[horse]["training_plus"] += 1
        elif kind == "マイナス":
            stats[horse]["training_minus"] += 1

    yt_weight = {"本命": 1.2, "対抗": 0.8, "単穴": 0.5, "連下": 0.3, "危険な人気馬": -1.0}
    yt_map = st.session_state.get('yt_video_conclusions') or {}
    for conclusion in yt_map.values():
        if not isinstance(conclusion, dict):
            continue
        for key, weight in yt_weight.items():
            text = _to_text(conclusion.get(key))
            if not text:
                continue
            for horse in horse_names:
                if horse in text:
                    stats[horse]["yt_bonus"] += weight

    latest_odds = st.session_state.get('latest_odds', {}) or {}
    for horse in horse_names:
        odds = _safe_odds_float(latest_odds.get(horse))
        stats[horse]["odds"] = odds
        implied_prob = (1.0 / odds) if odds and odds > 0 else 0.0
        odds_boost = 0.4 * math.sqrt(implied_prob) if implied_prob > 0 else 0.0

        base = (
            1.0
            + 0.8 * stats[horse]["plus_count"]
            - 0.7 * stats[horse]["minus_count"]
            + 0.35 * math.log1p(max(0, stats[horse]["source_count"]))
            + 0.35 * stats[horse]["training_plus"]
            - 0.30 * stats[horse]["training_minus"]
            + stats[horse]["yt_bonus"]
            + odds_boost
        )
        stats[horse]["score"] = max(0.05, base)

    total = sum(max(0.05, x["score"]) for x in stats.values())
    if total <= 0:
        total = float(len(stats))
    for horse in horse_names:
        stats[horse]["prob"] = max(0.05, stats[horse]["score"]) / total

    return sorted(stats.values(), key=lambda x: x["prob"], reverse=True)


def _build_ticket_candidates(
    bet_type: str,
    horse_scores: list[dict],
    odds_map: dict[str, float],
    anchor_umaban: str = "",
) -> list[dict]:
    entries = [x for x in horse_scores if _normalize_umaban(x.get("umaban"))]
    entries = entries[:6]  # 上位馬を中心に候補生成
    if not entries:
        return []

    if anchor_umaban:
        # 軸馬が上位6頭にいない場合は強制的に含める
        if all(_normalize_umaban(x.get("umaban")) != anchor_umaban for x in entries):
            anchor_entry = next((x for x in horse_scores if _normalize_umaban(x.get("umaban")) == anchor_umaban), None)
            if anchor_entry:
                entries = [anchor_entry] + [x for x in entries if _normalize_umaban(x.get("umaban")) != anchor_umaban]
                entries = entries[:6]

    candidates = []
    is_combo_type = bet_type in {"ワイド", "馬連", "三連複", "三連単"}

    def add_candidate(nums: list[str], probs: list[float], ordered: bool = False):
        key = _ticket_key(nums, ordered=ordered)
        if not key:
            return
        odds = _safe_odds_float((odds_map or {}).get(key))
        if not odds:
            return
        if bet_type in {"単勝", "複勝"}:
            hit = probs[0]
        elif bet_type in {"ワイド", "馬連"}:
            hit = math.sqrt(max(1e-9, probs[0] * probs[1]))
        elif bet_type == "三連複":
            hit = max(1e-9, probs[0] * probs[1] * probs[2]) ** (1.0 / 3.0)
        else:  # 三連単
            hit = (max(1e-9, probs[0] * probs[1] * probs[2]) ** (1.0 / 3.0)) * 0.9
        candidates.append({
            "券種": bet_type,
            "買い目キー": key,
            "オッズ": float(odds),
            "hit_score": float(hit),
            "raw_roi": float(hit * odds),
        })

    if bet_type in {"単勝", "複勝"}:
        for e in entries:
            num = _normalize_umaban(e.get("umaban"))
            if num:
                add_candidate([num], [float(e["prob"])], ordered=False)

    elif bet_type in {"ワイド", "馬連"}:
        for a, b in itertools.combinations(entries, 2):
            nums = [_normalize_umaban(a.get("umaban")), _normalize_umaban(b.get("umaban"))]
            if anchor_umaban and anchor_umaban not in nums:
                continue
            add_candidate(nums, [float(a["prob"]), float(b["prob"])], ordered=False)

    elif bet_type == "三連複":
        for a, b, c in itertools.combinations(entries, 3):
            nums = [_normalize_umaban(a.get("umaban")), _normalize_umaban(b.get("umaban")), _normalize_umaban(c.get("umaban"))]
            if anchor_umaban and anchor_umaban not in nums:
                continue
            add_candidate(nums, [float(a["prob"]), float(b["prob"]), float(c["prob"])], ordered=False)

    elif bet_type == "三連単":
        entries_for_order = entries[:5]  # 点数爆発を抑える
        for a, b, c in itertools.permutations(entries_for_order, 3):
            nums = [_normalize_umaban(a.get("umaban")), _normalize_umaban(b.get("umaban")), _normalize_umaban(c.get("umaban"))]
            if anchor_umaban and anchor_umaban not in nums:
                continue
            add_candidate(nums, [float(a["prob"]), float(b["prob"]), float(c["prob"])], ordered=True)

    # 同一キー重複を除去して高評価を残す
    dedup = {}
    for c in candidates:
        key = c["買い目キー"]
        old = dedup.get(key)
        if (not old) or (c["raw_roi"] > old["raw_roi"]):
            dedup[key] = c
    return list(dedup.values())


def _allocate_point_targets(
    selected_bet_types: list[str],
    score_weight: float,
    candidates_by_type: dict[str, list[dict]],
    max_points: int = BET_MAX_POINTS,
) -> dict[str, int]:
    selected = [bt for bt in BET_TYPES_ALL if bt in (selected_bet_types or [])]
    if not selected:
        return {}

    raw = {}
    for bt in selected:
        raw_hit = BET_POINT_PROFILE_HIT.get(bt, 0)
        raw_roi = BET_POINT_PROFILE_ROI.get(bt, 0)
        raw[bt] = (1.0 - score_weight) * raw_hit + score_weight * raw_roi

    total_raw = sum(raw.values())
    if total_raw <= 0:
        raw = {bt: 1.0 for bt in selected}
        total_raw = float(len(selected))

    scaled = {bt: (raw[bt] / total_raw) * max_points for bt in selected}
    base = {bt: int(math.floor(v)) for bt, v in scaled.items()}
    rem = max_points - sum(base.values())

    if rem > 0:
        frac_sorted = sorted(selected, key=lambda bt: (scaled[bt] - base[bt]), reverse=True)
        for i in range(rem):
            base[frac_sorted[i % len(frac_sorted)]] += 1

    # 候補数上限に合わせて調整
    adjusted = {bt: min(base.get(bt, 0), len(candidates_by_type.get(bt, []))) for bt in selected}
    remain = max_points - sum(adjusted.values())
    while remain > 0:
        expandable = [bt for bt in selected if len(candidates_by_type.get(bt, [])) > adjusted.get(bt, 0)]
        if not expandable:
            break
        expandable = sorted(
            expandable,
            key=lambda bt: candidates_by_type[bt][adjusted[bt]]["final_score"] if adjusted[bt] < len(candidates_by_type[bt]) else -1,
            reverse=True,
        )
        adjusted[expandable[0]] += 1
        remain -= 1
    return adjusted


def _allocate_stakes_to_tickets(tickets: list[dict], budget_yen: int, score_weight: float, stake_unit: int = BET_STAKE_UNIT_YEN) -> list[dict]:
    if not tickets:
        return []
    total_units = int(budget_yen // stake_unit)
    if total_units <= 0:
        return []

    sorted_tickets = sorted(tickets, key=lambda x: x.get("final_score", 0.0), reverse=True)
    if len(sorted_tickets) > total_units:
        sorted_tickets = sorted_tickets[:total_units]

    n = len(sorted_tickets)
    for t in sorted_tickets:
        t["units"] = 1
    remain_units = total_units - n

    if remain_units > 0:
        exp = 1.0 + 1.2 * score_weight
        weights = [max(1e-9, float(t.get("final_score", 0.0))) ** exp for t in sorted_tickets]
        wsum = sum(weights)
        if wsum <= 0:
            weights = [1.0] * n
            wsum = float(n)

        raw_add = [remain_units * (w / wsum) for w in weights]
        add_floor = [int(math.floor(v)) for v in raw_add]
        for i, v in enumerate(add_floor):
            sorted_tickets[i]["units"] += v
        rem = remain_units - sum(add_floor)
        if rem > 0:
            order = sorted(range(n), key=lambda i: raw_add[i] - add_floor[i], reverse=True)
            for i in range(rem):
                sorted_tickets[order[i % n]]["units"] += 1

    for t in sorted_tickets:
        t["配分額"] = int(t["units"] * stake_unit)

    return sorted_tickets


def build_budget_bet_plan(
    df_active: pd.DataFrame,
    budget_yen: int,
    slider_value: int,
    bet_types: list[str],
    anchor_horse: str,
    max_points: int = BET_MAX_POINTS,
    stake_unit: int = BET_STAKE_UNIT_YEN,
    bet_type_odds: dict[str, dict[str, float]] | None = None,
) -> dict:
    warnings = []
    selected_bet_types = [bt for bt in BET_TYPES_ALL if bt in (bet_types or [])]
    if not selected_bet_types:
        return {"summary": {}, "tickets": [], "horse_scores": [], "warnings": ["券種が未選択です。"], "generated_at": datetime.now().isoformat(timespec="seconds")}

    budget_rounded = int(max(stake_unit, (budget_yen // stake_unit) * stake_unit))
    w = max(0.0, min(1.0, float(slider_value) / 100.0))

    horse_scores = _extract_horse_scores_for_bet_plan(df_active)
    if not horse_scores:
        return {"summary": {}, "tickets": [], "horse_scores": [], "warnings": ["馬スコアを算出できませんでした。出馬表を確認してください。"], "generated_at": datetime.now().isoformat(timespec="seconds")}

    horse_to_umaban, umaban_to_horse = _build_horse_umaban_maps(df_active)
    anchor_umaban = ""
    if anchor_horse and anchor_horse != "自動":
        anchor_umaban = _normalize_umaban(horse_to_umaban.get(anchor_horse))
        if not anchor_umaban:
            warnings.append("手動軸馬の馬番が不明のため、自動軸にフォールバックしました。")

    odds_by_type = bet_type_odds or {}
    candidates_by_type = {}
    missing_odds_types = []
    candidate_short_types = []
    for bt in selected_bet_types:
        odds_map = odds_by_type.get(bt, {}) if isinstance(odds_by_type, dict) else {}
        cands = _build_ticket_candidates(bt, horse_scores, odds_map, anchor_umaban=anchor_umaban)
        if not cands:
            if odds_map:
                candidate_short_types.append(bt)
            else:
                missing_odds_types.append(bt)
        candidates_by_type[bt] = cands

    if missing_odds_types:
        warnings.append(f"オッズ未取得のため買い目を生成できない券種: {_format_bet_type_list(missing_odds_types)}")
    if candidate_short_types:
        warnings.append(f"候補不足のため買い目を生成できない券種: {_format_bet_type_list(candidate_short_types)}")

    all_candidates = [c for bt in selected_bet_types for c in candidates_by_type.get(bt, [])]
    if not all_candidates:
        if missing_odds_types and len(missing_odds_types) == len(selected_bet_types):
            terminal = "券種別オッズが未取得のため買い目を生成できませんでした。オッズ公開後に再実行してください。"
        else:
            terminal = "有効な買い目候補がありません。"
        return {"summary": {}, "tickets": [], "horse_scores": horse_scores, "warnings": warnings + [terminal], "generated_at": datetime.now().isoformat(timespec="seconds")}

    roi_vals = [c["raw_roi"] for c in all_candidates]
    min_roi = min(roi_vals)
    max_roi = max(roi_vals)
    for c in all_candidates:
        if max_roi > min_roi:
            c["roi_score"] = (c["raw_roi"] - min_roi) / (max_roi - min_roi)
        else:
            c["roi_score"] = 0.5
        c["final_score"] = (1.0 - w) * c["hit_score"] + w * c["roi_score"]

    for bt in selected_bet_types:
        candidates_by_type[bt] = sorted(candidates_by_type.get(bt, []), key=lambda x: x["final_score"], reverse=True)

    point_targets = _allocate_point_targets(selected_bet_types, w, candidates_by_type, max_points=max_points)
    selected_tickets = []
    for bt in selected_bet_types:
        cnt = point_targets.get(bt, 0)
        if cnt <= 0:
            continue
        selected_tickets.extend(candidates_by_type.get(bt, [])[:cnt])

    selected_tickets = sorted(selected_tickets, key=lambda x: x["final_score"], reverse=True)[:max_points]
    selected_tickets = _allocate_stakes_to_tickets(selected_tickets, budget_rounded, w, stake_unit=stake_unit)
    if not selected_tickets:
        return {"summary": {}, "tickets": [], "horse_scores": horse_scores, "warnings": warnings + ["予算に対して有効な買い目を割り当てられませんでした。"], "generated_at": datetime.now().isoformat(timespec="seconds")}

    total_stake = sum(int(t.get("配分額", 0)) for t in selected_tickets)
    est_return = sum(float(t.get("配分額", 0)) * float(t.get("オッズ", 0)) * float(t.get("hit_score", 0)) for t in selected_tickets)
    hit_index = 0.0
    if total_stake > 0:
        hit_index = sum(float(t.get("配分額", 0)) * float(t.get("hit_score", 0)) for t in selected_tickets) / total_stake
    roi_index = (est_return / total_stake) if total_stake > 0 else 0.0

    type_count = defaultdict(int)
    type_amount = defaultdict(int)
    for t in selected_tickets:
        bt = t.get("券種", "")
        type_count[bt] += 1
        type_amount[bt] += int(t.get("配分額", 0))

    for t in selected_tickets:
        t["買い目"] = _format_ticket_label(t.get("券種", ""), t.get("買い目キー", ""), umaban_to_horse)
        t["推定払戻期待"] = float(t.get("配分額", 0)) * float(t.get("オッズ", 0)) * float(t.get("hit_score", 0))

    summary = {
        "総点数": len(selected_tickets),
        "総投資額": int(total_stake),
        "推定回収指数": float(roi_index),
        "推定的中指数": float(hit_index),
        "方針スライダー": int(slider_value),
        "軸馬": anchor_horse if (anchor_horse and anchor_horse != "自動") else "自動",
        "券種別点数": dict(type_count),
        "券種別投資額": dict(type_amount),
    }

    return {
        "summary": summary,
        "tickets": selected_tickets,
        "horse_scores": horse_scores,
        "warnings": warnings,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ====================
# サイドバー表示関数
# ====================

def display_sidebar():
    """
    サイドバーにレース選択・レース情報・注目馬情報を表示する関数
    """
    r = get_race_config()
    race_name = get_race_display_name() if r else "レース未選択"

    # サイドバーのタイトル
    st.sidebar.title(f"🏇 {race_name}")

    # レース情報
    if r:
        st.sidebar.markdown("---")
        st.sidebar.subheader("📅 レース情報")
        st.sidebar.write(f"**開催日**: {r.date_str}")
        st.sidebar.write(f"**開催場**: {r.venue}競馬場")
        st.sidebar.write(f"**距離**: {r.surface}{r.distance}")
        st.sidebar.write(f"**グレード**: {r.grade}")

        # 応援メッセージ
        st.sidebar.markdown("---")
        st.sidebar.subheader("💪 応援メッセージ")
        st.sidebar.success(
            f"""
            {r.grade}レース、{r.race_name}！

            {r.venue}競馬場で繰り広げられる、
            {r.surface}{r.distance}の激戦。

            どの馬も優勝のチャンスあり！
            熱い戦いに期待しましょう！
            """
        )

    # 注目馬セクション（horse_df がある場合は情報源数上位3馬を表示）
    horse_df = st.session_state.get('horse_df')
    if horse_df is not None and not horse_df.empty and '馬名' in horse_df.columns:
        st.sidebar.markdown("---")
        st.sidebar.subheader("⭐ 注目馬（情報源数上位）")
        top_horses = horse_df.nlargest(3, '情報源数') if '情報源数' in horse_df.columns else horse_df.head(3)
        icons = ["⭐", "🌟", "⚡"]
        for i, (_, row) in enumerate(top_horses.iterrows()):
            icon = icons[i] if i < len(icons) else "🏇"
            with st.sidebar.expander(f"{icon} {row['馬名']}"):
                merit = str(row.get('メリット', ''))[:100]
                st.write(merit if merit and merit != '（情報なし）' else "詳細は「総合予想」タブを確認")

    # フッター
    st.sidebar.markdown("---")
    st.sidebar.caption("🎯 予想は参考程度に。馬券は自己責任で！")

# ====================
# メインコンテンツ表示関数
# ====================

def render_horse_table_html(df: pd.DataFrame) -> str:
    """出馬表をリッチなHTMLテーブルとして生成する。"""
    WAKU_COLORS = {
        '1': 'waku-1', '2': 'waku-2', '3': 'waku-3', '4': 'waku-4',
        '5': 'waku-5', '6': 'waku-6', '7': 'waku-7', '8': 'waku-8',
    }

    def odds_class(odds_str: str) -> str:
        try:
            v = float(str(odds_str).replace(',', ''))
            if v < 5:     return 'odds-hot'
            if v < 15:    return 'odds-warm'
            if v < 50:    return 'odds-normal'
            return 'odds-long'
        except Exception:
            return 'odds-long'

    def safe(val, as_int: bool = False) -> str:
        s = str(val).strip()
        if s in ('', 'None', 'nan', 'NaN', '---.-'):
            return '-'
        if as_int:
            try:
                return str(int(float(s)))
            except (ValueError, OverflowError):
                pass
        return s

    def pick(row: pd.Series, aliases: list[str]) -> str:
        for key in aliases:
            if key in row.index:
                value = row.get(key, "")
                if _to_text(value):
                    return str(value)
        return str(row.get(aliases[0], ""))

    def _past_rank_class(rank: int) -> str:
        if rank == 1:
            return "rank-1"
        if rank == 2:
            return "rank-2"
        if rank == 3:
            return "rank-3"
        return "rank-other"

    def render_past_race_cell(raw_val: str) -> str:
        raw = _to_text(raw_val)
        if not raw or raw in {"-", "nan", "None"}:
            return '<span class="past-race-empty">-</span>'

        text = re.sub(r"\s+", " ", raw).strip()
        escaped_text = html.escape(text)
        match = re.match(r"^(?P<date>\d{2}/\d{2}/\d{2})\s+(?P<rank>\d+)\s+(?P<rest>.+)$", text)
        if not match:
            return f'<div class="past-race-plain">{escaped_text}</div>'

        date = html.escape(match.group("date"))
        rank_num = int(match.group("rank"))
        rest = match.group("rest").strip()
        race_name = rest
        course_info = ""
        course_match = re.search(r"(.+?)\s+([^\s]*／[^\s]+)$", rest)
        if course_match:
            race_name = course_match.group(1).strip()
            course_info = course_match.group(2).strip()

        rank_class = _past_rank_class(rank_num)
        race_name_escaped = html.escape(race_name)
        course_escaped = html.escape(course_info)
        course_html = f'<div class="past-race-course">{course_escaped}</div>' if course_info else ""
        return (
            '<div class="past-race-box">'
            f'<div class="past-race-date">{date}</div>'
            f'<div class="past-race-main"><span class="past-race-rank {rank_class}">{rank_num}着</span>'
            f'<span class="past-race-name">{race_name_escaped}</span></div>'
            f'{course_html}'
            '</div>'
        )

    rows_html = []
    for _, row in df.iterrows():
        waku  = safe(row.get('枠番', ''), as_int=True)
        umaban = safe(row.get('馬番', ''), as_int=True)
        name  = safe(row.get('馬名', ''))
        seage = safe(row.get('性齢', ''))
        kin   = safe(pick(row, ['斤量', '負担重量']))
        jockey = safe(pick(row, ['騎手', '騎手名']))
        prev1 = safe(row.get('前走', ''))
        prev2 = safe(row.get('2走前', ''))
        prev3 = safe(row.get('3走前', ''))
        odds  = safe(pick(row, ['オッズ', '単勝オッズ']))

        waku_cls = WAKU_COLORS.get(waku, 'waku-x')
        waku_cell = f'<span class="waku-badge {waku_cls}">{waku if waku != "-" else "?"}</span>'
        odds_cell = f'<span class="odds-badge {odds_class(odds)}">{odds if odds != "-" else "---"}</span>'

        rows_html.append(f"""
<tr>
  <td>{waku_cell}</td>
  <td class="umaban-cell">{umaban}</td>
  <td class="horse-name-cell">{name}</td>
  <td>{seage}</td>
  <td class="kinryo-cell">{kin}</td>
  <td>{jockey}</td>
  <td class="past-race-cell">{render_past_race_cell(prev1)}</td>
  <td class="past-race-cell">{render_past_race_cell(prev2)}</td>
  <td class="past-race-cell">{render_past_race_cell(prev3)}</td>
  <td>{odds_cell}</td>
</tr>""")

    table = f"""
<div class="horse-table-wrap">
<table class="horse-table">
<thead>
<tr>
  <th>枠</th><th>番</th><th>馬名</th><th>性齢</th>
  <th>斤量</th><th>騎手</th><th class="past-col">前走</th><th class="past-col">2走前</th><th class="past-col">3走前</th><th>単勝オッズ</th>
</tr>
</thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>
</div>"""
    return table


def display_main_content(df):
    """
    メインエリアに出馬表と分析結果を表示する関数

    引数:
        df (DataFrame): 競馬データ
    """
    # カスタムCSS（グローバルテーマ）
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700;900&display=swap');

/* ============ 全体テーマ ============ */
html, body, [class*="css"] { font-family: 'Noto Sans JP', sans-serif; }

/* ============ ヒーローバナー ============ */
.race-hero {
    background: linear-gradient(135deg, #0d1b2a 0%, #1b263b 40%, #1a3a5c 100%);
    padding: 28px 36px 22px;
    border-radius: 16px;
    margin-bottom: 24px;
    text-align: center;
    box-shadow: 0 8px 32px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.06);
    border: 1px solid rgba(255,255,255,.08);
    position: relative;
    overflow: hidden;
}
.race-hero::before {
    content: '';
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at 50% 0%, rgba(212,160,23,.18) 0%, transparent 70%);
}
.race-hero-label {
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.25em;
    color: #d4a017;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.race-hero-title {
    font-size: 2rem;
    font-weight: 900;
    color: #f5e6a3;
    line-height: 1.2;
    margin-bottom: 10px;
    text-shadow: 0 2px 8px rgba(0,0,0,.5);
}
.race-hero-badge {
    display: inline-block;
    background: linear-gradient(135deg, #c0392b, #e74c3c);
    color: #fff;
    font-size: 0.85rem;
    font-weight: 900;
    letter-spacing: 0.15em;
    padding: 3px 14px;
    border-radius: 20px;
    margin-bottom: 10px;
    box-shadow: 0 2px 8px rgba(231,76,60,.4);
}
.race-hero-info {
    font-size: 0.98rem;
    color: rgba(220,220,220,.9);
    letter-spacing: 0.04em;
}
.race-hero-info span { margin: 0 8px; opacity: .6; }

/* ============ 出馬表テーブル ============ */
.horse-table-wrap { overflow-x: auto; border-radius: 12px; }
.horse-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0 5px;
    font-size: 0.9rem;
}
.horse-table thead th {
    background: #1b263b;
    color: rgba(255,255,255,.75);
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 10px 12px;
    text-align: center;
    white-space: nowrap;
}
.horse-table thead th:first-child { border-radius: 8px 0 0 8px; }
.horse-table thead th:last-child  { border-radius: 0 8px 8px 0; }
.horse-table tbody tr {
    background: #ffffff;
    box-shadow: 0 2px 6px rgba(0,0,0,.07);
    transition: box-shadow .15s, transform .15s;
}
.horse-table tbody tr:hover {
    box-shadow: 0 4px 16px rgba(0,0,0,.14);
    transform: translateY(-1px);
}
.horse-table tbody td {
    padding: 10px 12px;
    text-align: center;
    vertical-align: middle;
    border-top: 1px solid #f0f0f0;
    border-bottom: 1px solid #f0f0f0;
}
.horse-table tbody td:first-child { border-left: 1px solid #f0f0f0; border-radius: 8px 0 0 8px; }
.horse-table tbody td:last-child  { border-right: 1px solid #f0f0f0; border-radius: 0 8px 8px 0; }
.horse-name-cell { text-align: left !important; font-weight: 700; font-size: 0.95rem; color: #1a1a2e; }
.umaban-cell { font-weight: 700; color: #333; font-size: 1rem; }
.kinryo-cell { font-weight: 700; color: #0f3554; }
.horse-table thead th.past-col { min-width: 210px; }
.past-race-cell {
    text-align: left !important;
    min-width: 210px;
    line-height: 1.3;
    white-space: normal;
    font-size: 0.78rem;
    color: #1f2937;
}
.past-race-box {
    display: grid;
    gap: 3px;
}
.past-race-date {
    font-size: 0.68rem;
    color: #64748b;
    letter-spacing: 0.01em;
}
.past-race-main {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
}
.past-race-rank {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 34px;
    padding: 1px 6px;
    border-radius: 999px;
    font-size: 0.68rem;
    font-weight: 900;
    border: 1px solid transparent;
}
.past-race-rank.rank-1 { background: #fff2cf; color: #7c4d00; border-color: #f4c95d; }
.past-race-rank.rank-2 { background: #e9edf3; color: #334155; border-color: #b8c2d1; }
.past-race-rank.rank-3 { background: #f5e5d7; color: #7a4a2b; border-color: #d8b49a; }
.past-race-rank.rank-other { background: #f3f4f6; color: #4b5563; border-color: #d1d5db; }
.past-race-name {
    font-weight: 700;
    color: #0f172a;
    overflow-wrap: anywhere;
}
.past-race-course {
    font-size: 0.7rem;
    color: #475569;
}
.past-race-plain {
    font-size: 0.72rem;
    color: #334155;
}
.past-race-empty {
    color: #94a3b8;
    font-size: 0.72rem;
}

/* 枠番バッジ（日本競馬の伝統的な枠色） */
.waku-badge {
    display: inline-flex; align-items: center; justify-content: center;
    width: 30px; height: 30px; border-radius: 50%;
    font-weight: 900; font-size: 0.85rem;
    box-shadow: 0 2px 4px rgba(0,0,0,.2);
}
.waku-1 { background:#ffffff; color:#333; border:2px solid #bbb; }
.waku-2 { background:#2c2c2c; color:#fff; border:2px solid #000; }
.waku-3 { background:#e74c3c; color:#fff; }
.waku-4 { background:#2980b9; color:#fff; }
.waku-5 { background:#f1c40f; color:#333; }
.waku-6 { background:#27ae60; color:#fff; }
.waku-7 { background:#e67e22; color:#fff; }
.waku-8 { background:#e91e8c; color:#fff; }
.waku-x { background:#95a5a6; color:#fff; }

/* オッズバッジ */
.odds-badge {
    display: inline-block; padding: 3px 10px;
    border-radius: 14px; font-weight: 700; font-size: 0.85rem;
}
.odds-hot   { background:#fff0f0; color:#c0392b; border:1px solid #f5c6cb; }
.odds-warm  { background:#fff8e1; color:#d68910; border:1px solid #fde3a7; }
.odds-normal{ background:#f0f7ff; color:#2471a3; border:1px solid #bdd7f5; }
.odds-long  { background:#f5f5f5; color:#7f8c8d; border:1px solid #ddd; }

/* ============ 馬別予想カード ============ */
.merit-card {
    background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
    border-left: 5px solid #28a745;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 6px 0;
    color: #155724;
    font-size: 0.93rem;
    line-height: 1.6;
}
.demerit-card {
    background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
    border-left: 5px solid #dc3545;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 6px 0;
    color: #721c24;
    font-size: 0.93rem;
    line-height: 1.6;
}
.verdict-buy {
    background: linear-gradient(90deg, #28a745, #34ce57);
    border-radius: 10px;
    padding: 10px 20px;
    color: white;
    font-weight: bold;
    font-size: 1.15rem;
    text-align: center;
    margin-bottom: 10px;
    letter-spacing: 0.05em;
}
.verdict-pass {
    background: linear-gradient(90deg, #dc3545, #e85d6a);
    border-radius: 10px;
    padding: 10px 20px;
    color: white;
    font-weight: bold;
    font-size: 1.15rem;
    text-align: center;
    margin-bottom: 10px;
    letter-spacing: 0.05em;
}
.verdict-watch {
    background: linear-gradient(90deg, #e6a817, #f0c040);
    border-radius: 10px;
    padding: 10px 20px;
    color: #333;
    font-weight: bold;
    font-size: 1.15rem;
    text-align: center;
    margin-bottom: 10px;
    letter-spacing: 0.05em;
}
.section-header-merit {
    font-size: 1.05rem;
    font-weight: bold;
    color: #155724;
    border-bottom: 2px solid #28a745;
    padding-bottom: 4px;
    margin-bottom: 8px;
}
.section-header-demerit {
    font-size: 1.05rem;
    font-weight: bold;
    color: #721c24;
    border-bottom: 2px solid #dc3545;
    padding-bottom: 4px;
    margin-bottom: 8px;
}

/* ============ メトリクスカード ============ */
div[data-testid="metric-container"] {
    background: linear-gradient(135deg, #f8f9fe 0%, #eef1fb 100%);
    border: 1px solid #dde2f5;
    border-radius: 12px;
    padding: 14px 18px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,.05);
}
</style>
""", unsafe_allow_html=True)

    # ヒーローバナー
    r = get_race_config()
    if r:
        hero_label = f"🏇 JRA {r.grade} {r.surface}競走"
        hero_title = f"🏆 {r.race_name}"
        hero_badge = r.grade
        hero_info = f"{r.date_str}<span>｜</span>{r.venue}競馬場<span>｜</span>{r.surface}{r.distance}"
    else:
        hero_label = "🏇 JRA 重賞競走"
        hero_title = "🏆 レース未選択"
        hero_badge = ""
        hero_info = "サイドバーからレースを選択してください"
    st.markdown(f"""
<div class="race-hero">
  <div class="race-hero-label">{hero_label}</div>
  <div class="race-hero-title">{hero_title}</div>
  <div style="margin-bottom:10px;"><span class="race-hero-badge">{hero_badge}</span></div>
  <div class="race-hero-info">
    {hero_info}
  </div>
</div>
""", unsafe_allow_html=True)

    def get_active_race_df(source_df: pd.DataFrame) -> pd.DataFrame:
        """
        出走取消馬を除外したDataFrameを返す。
        馬番が1頭でも確定している場合のみ、馬番欠損行を除外する。
        """
        if source_df is None or source_df.empty:
            return source_df
        if '馬番' not in source_df.columns:
            return source_df.copy()

        umaban_num = pd.to_numeric(source_df['馬番'], errors='coerce')
        # 出走確定前（全行欠損）では除外しない
        if not umaban_num.notna().any():
            return source_df.copy()

        return source_df[umaban_num.notna()].copy().reset_index(drop=True)

    df_active = get_active_race_df(df)
    df_active_enriched = enrich_entry_table_with_umanity(
        df_active,
        race_name=(r.race_name if r else ""),
    )
    active_horse_names = set(df_active_enriched['馬名'].astype(str).tolist()) if (
        df_active_enriched is not None and not df_active_enriched.empty and '馬名' in df_active_enriched.columns
    ) else set()
    race_widget_scope = r.race_key if r else "default"

    # タブを作成
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📋 出馬表",
        "📥 情報入力",
        "🏇 総合予想（馬別）",
        "🏟️ レース特徴・傾向",
        "YOUTUBEから情報入手",
        "🏋️ 追切結果・評価",
        "💰 予算別買い目プラン",
    ])

    # ===== タブ1: 出馬表 =====
    with tab1:
        st.markdown("### 📊 出走予定馬一覧")

        # データが空でないか確認
        if df_active_enriched is not None and not df_active_enriched.empty:
            df_display = df_active_enriched.copy()
            if 'オッズ' in df_display.columns:
                # 文字列オッズを安全に上書きできるよう object 型へ寄せる
                df_display['オッズ'] = df_display['オッズ'].astype('object')

            # セッション内のオッズを反映（ボタン取得後）
            if 'latest_odds' in st.session_state and 'オッズ' in df_display.columns:
                for idx, row in df_display.iterrows():
                    horse = str(row.get('馬名', ''))
                    if horse in st.session_state['latest_odds']:
                        df_display.at[idx, 'オッズ'] = st.session_state['latest_odds'][horse]

            sort_option = st.radio(
                "並び順",
                options=["馬番順", "オッズ昇順（人気順）", "オッズ降順（高配当順）"],
                horizontal=True,
                key=f"entry_sort::{race_widget_scope}",
            )

            if '馬番' in df_display.columns:
                df_display['_馬番_num'] = pd.to_numeric(df_display['馬番'], errors='coerce')
            else:
                df_display['_馬番_num'] = pd.Series([float('nan')] * len(df_display), index=df_display.index)

            if 'オッズ' in df_display.columns:
                odds_text = (
                    df_display['オッズ']
                    .astype(str)
                    .str.replace(',', '', regex=False)
                    .str.replace('---.-', '', regex=False)
                    .str.strip()
                )
                df_display['_オッズ_num'] = pd.to_numeric(odds_text, errors='coerce')

            has_numeric_odds = ('_オッズ_num' in df_display.columns) and df_display['_オッズ_num'].notna().any()
            if sort_option == "オッズ昇順（人気順）" and has_numeric_odds:
                df_display = df_display.sort_values(
                    by=['_オッズ_num', '_馬番_num'],
                    ascending=[True, True],
                    na_position='last',
                )
            elif sort_option == "オッズ降順（高配当順）" and has_numeric_odds:
                df_display = df_display.sort_values(
                    by=['_オッズ_num', '_馬番_num'],
                    ascending=[False, True],
                    na_position='last',
                )
            else:
                df_display = df_display.sort_values('_馬番_num', na_position='last')
                if sort_option != "馬番順" and not has_numeric_odds:
                    st.caption("オッズが未公開のため、馬番順で表示しています。")

            drop_cols = [c for c in ['_馬番_num', '_オッズ_num'] if c in df_display.columns]
            if drop_cols:
                df_display = df_display.drop(columns=drop_cols)
            df_display = df_display.reset_index(drop=True)

            # 出馬表を HTML カードテーブルで表示
            st.markdown(render_horse_table_html(df_display), unsafe_allow_html=True)
            if {"前走", "2走前", "3走前"}.issubset(set(df_display.columns)):
                st.caption("近3走データは Umanity racecard を優先して表示しています。")

            # オッズ取得ボタン
            st.markdown("---")
            col_btn, col_info = st.columns([1, 4])
            with col_btn:
                if st.button("🔄 最新オッズを取得", key="fetch_odds_btn"):
                    with st.spinner("netkeiba からオッズを取得中..."):
                        odds_data, odds_error = fetch_odds_and_gates()
                    if odds_data:
                        latest_odds = {
                            h: str(v.get('オッズ', '')).strip()
                            for h, v in odds_data.items()
                            if re.match(r'^\d+(\.\d+)?$', str(v.get('オッズ', '')).strip())
                        }
                        if latest_odds:
                            st.session_state['latest_odds'] = latest_odds
                            st.session_state.pop('latest_odds_error', None)
                            # 表示高速化のためCSVにも反映
                            try:
                                csv_path_local = get_csv_path()
                                if csv_path_local and os.path.exists(csv_path_local):
                                    csv_df = pd.read_csv(csv_path_local, encoding='utf-8-sig')
                                    if '馬名' in csv_df.columns and 'オッズ' in csv_df.columns:
                                        csv_df['オッズ'] = csv_df['オッズ'].astype('object')
                                        updated = False
                                        for idx, row in csv_df.iterrows():
                                            horse = str(row.get('馬名', '')).strip()
                                            if horse in latest_odds and str(row.get('オッズ', '')).strip() != latest_odds[horse]:
                                                csv_df.at[idx, 'オッズ'] = latest_odds[horse]
                                                updated = True
                                        if updated:
                                            csv_df.to_csv(csv_path_local, index=False, encoding='utf-8-sig')
                                            load_race_data.clear()
                            except Exception:
                                pass
                            save_race_cache(get_race_config().race_key)
                            st.rerun()
                        else:
                            st.error("❌ 数値オッズを取得できませんでした（未公開の可能性があります）")
                            st.session_state['latest_odds_error'] = odds_error or "数値オッズなし"
                    else:
                        st.error("❌ オッズの取得に失敗しました")
                        st.session_state['latest_odds_error'] = odds_error
            with col_info:
                if 'latest_odds' in st.session_state:
                    st.caption(f"✅ オッズ取得済み（{len(st.session_state['latest_odds'])}頭）")
                elif st.session_state.get('latest_odds_error'):
                    with st.expander("⚠️ 取得失敗の詳細"):
                        st.code(st.session_state['latest_odds_error'])

            # 統計情報
            st.markdown("---")
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("出走頭数", f"{len(df_active)}頭")

            with col2:
                # オッズが数値の場合の最低オッズ（存在する場合）
                if 'オッズ' in df_active.columns:
                    st.metric("データ取得日", datetime.now().strftime("%Y年%m月%d日"))

            with col3:
                if '騎手' in df_active.columns:
                    unique_jockeys = df_active['騎手'].nunique()
                    st.metric("参加騎手数", f"{unique_jockeys}名")

        else:
            st.warning("⚠️ 表示するデータがありません")

    # ===== タブ2: 情報入力 =====
    with tab2:
        st.markdown("### 📥 情報入力")
        st.info("💡 Web・ドキュメントから情報を収集します。収集後、「総合予想（馬別）」「レース特徴・傾向」タブで結果を確認できます。")

        # ===== Section 1: Web 一括検索 =====
        st.markdown("#### 🔍 Web 一括検索")

        col_s1, col_s3 = st.columns([3, 1])
        with col_s1:
            combined_keyword = st.text_input(
                "検索キーワード",
                value=f"{get_race_display_name()} 予想",
                help="Web検索に使用するキーワード",
                key=f"combined_keyword::{race_widget_scope}"
            )
        with col_s3:
            combined_max_web = st.number_input(
                "Web記事上限数",
                min_value=1,
                max_value=100,
                value=20,
                help="最終的に取得するWeb記事件数の上限",
                key="combined_max_web"
            )

        # 前回の保存情報を表示
        if r:
            _cache_path = _get_cache_path(r.race_key)
            if os.path.exists(_cache_path):
                try:
                    with open(_cache_path, 'r', encoding='utf-8') as _f:
                        _meta = json.load(_f).get('meta', {})
                    _last_updated = _meta.get('last_updated', '')[:16].replace('T', ' ')
                    _art_count = _meta.get('web_article_count', 0)
                    _yt_count = _meta.get('youtube_video_count', 0)
                    st.info(
                        f"💾 前回の保存: {_last_updated} ｜ Web記事 {_art_count}件 ／ YouTube {_yt_count}件\n\n"
                        "🔄 「Web 一括検索」を実行すると新しい情報が追加されます（既存の情報は保持）"
                    )
                except Exception:
                    pass

        if st.button("🔍 Web 一括検索", type="primary", key="combined_search"):
            st.info("⏳ Web の解析には30秒〜1分程度かかります。しばらくお待ちください。")

            # Phase 1: Web検索・解析
            st.markdown("#### Web記事を検索・解析中...")
            rl = get_race_display_name()
            web_queries = [
                combined_keyword,
                f"{rl} 各馬評価 分析",
                f"{rl} 本命 穴馬 予想",
                f"{rl} 調教 追切 状態",
                f"{rl} 過去データ 傾向 コース適性",
                f"{rl} 騎手 厩舎 評価",
                f"{rl} 前走 近走 成績",
                f"{rl} 馬券 買い方 狙い目",
                f"{rl} 出走予定馬 戦力分析",
            ]
            # CSVから上位馬名を動的に追加
            _top_horses = get_all_horse_names()[:5]
            if _top_horses:
                web_queries.append(f"{rl} {' '.join(_top_horses)} 予想")
            new_articles, new_web_raw = fetch_and_analyze_web_articles(
                web_queries, total_article_limit=int(combined_max_web)
            )

            # 差分マージ（既存結果を保持しつつ新しい記事を追加）
            existing_web_raw = st.session_state.get('web_raw', [])
            existing_fp = {_raw_fingerprint(r2) for r2 in existing_web_raw if _raw_fingerprint(r2)}
            added_raw = [
                r2 for r2 in new_web_raw
                if not _raw_fingerprint(r2) or _raw_fingerprint(r2) not in existing_fp
            ]
            existing_article_urls = {a.get('url') for a in st.session_state.get('web_articles', []) if a.get('url')}
            added_articles = [a for a in new_articles if not a.get('url') or a.get('url') not in existing_article_urls]

            merged_web_raw = existing_web_raw + added_raw
            merged_articles = st.session_state.get('web_articles', []) + added_articles

            st.metric("Web記事", f"{len(new_articles)}件取得（うち新規: {len(added_articles)}件）")

            # Phase 2: 馬別集計（YouTube / 既存Web / 新規Web / ドキュメント を全統合）
            merged_horse_df = aggregate_horse_analysis(
                st.session_state.get('youtube_raw', []),
                merged_web_raw,
                st.session_state.get('doc_horse_raw', []),
                st.session_state.get('x_raw', []),
            )
            if active_horse_names and not merged_horse_df.empty and '馬名' in merged_horse_df.columns:
                merged_horse_df = merged_horse_df[
                    merged_horse_df['馬名'].astype(str).isin(active_horse_names)
                ].reset_index(drop=True)

            # セッションステートに保存
            st.session_state['horse_df'] = merged_horse_df
            st.session_state['web_raw'] = merged_web_raw
            st.session_state['web_articles'] = merged_articles
            st.session_state.setdefault('youtube_videos', [])
            st.session_state.setdefault('youtube_raw', [])
            st.session_state.setdefault('youtube_summary_df', pd.DataFrame())
            st.session_state.setdefault('yt_detail_analysis', {})
            st.session_state.setdefault('yt_video_conclusions', {})

            # キャッシュ保存
            if r:
                refresh_training_state(preserve_existing_time_rows=True)
                save_race_cache(r.race_key)

            st.success("✅ 検索・解析が完了しました！「総合予想（馬別）」タブで結果を確認してください。")

        st.markdown("---")

        # ===== Section 2: X (Twitter) 予想投稿 =====
        st.markdown("#### 𝕏 X (Twitter) 予想投稿")

        x_accounts = _load_x_accounts()
        x_disabled = False
        if not X_BEARER_TOKEN:
            st.warning("⚠️ X_BEARER_TOKENが未設定です。.envファイルを確認してください。")
            x_disabled = True
        elif not x_accounts:
            st.warning("⚠️ x_accounts.json が見つからないか、アカウントが未登録です。")
            x_disabled = True
        else:
            st.caption(f"登録アカウント: {', '.join('@' + a['username'] for a in x_accounts)}")

        x_default_max = _get_x_default_max_tweets(30)
        x_max = st.number_input(
            "取得上限ツイート数",
            min_value=10,
            max_value=100,
            value=x_default_max,
            key="x_max_tweets",
        )

        # キャッシュ情報表示
        x_tweets_cached = st.session_state.get('x_tweets', [])
        if x_tweets_cached:
            st.info(f"💾 取得済みX投稿: {len(x_tweets_cached)}件")

        if st.button("𝕏 X投稿を検索", key="x_search", disabled=x_disabled):
            with st.spinner("𝕏 X投稿を検索・解析中..."):
                new_tweets, new_x_raw = fetch_and_analyze_x_tweets(
                    r.race_name, max_tweets=x_max
                )

            if new_tweets:
                # 差分マージ: x_raw は _raw_fingerprint で重複排除
                existing_x_raw = st.session_state.get('x_raw', [])
                existing_fp = {_raw_fingerprint(r2) for r2 in existing_x_raw if _raw_fingerprint(r2)}
                added_raw = [r2 for r2 in new_x_raw
                             if not _raw_fingerprint(r2) or _raw_fingerprint(r2) not in existing_fp]

                # x_tweets は tweet_id で重複排除
                existing_tweet_ids = {t.get('tweet_id') or t.get('url') for t in st.session_state.get('x_tweets', [])
                                      if t.get('tweet_id') or t.get('url')}
                added_tweets = [t for t in new_tweets
                                if (t.get('tweet_id') or t.get('url') or '') not in existing_tweet_ids]

                merged_x_raw = existing_x_raw + added_raw
                merged_x_tweets = st.session_state.get('x_tweets', []) + added_tweets

                st.session_state['x_raw'] = merged_x_raw
                st.session_state['x_tweets'] = merged_x_tweets

                st.metric("X投稿", f"{len(new_tweets)}件取得（うち新規: {len(added_tweets)}件）")

                # 馬別集計の再計算
                updated_horse_df = aggregate_horse_analysis(
                    st.session_state.get('youtube_raw', []),
                    st.session_state.get('web_raw', []),
                    st.session_state.get('doc_horse_raw', []),
                    merged_x_raw,
                )
                if active_horse_names and not updated_horse_df.empty and '馬名' in updated_horse_df.columns:
                    updated_horse_df = updated_horse_df[
                        updated_horse_df['馬名'].astype(str).isin(active_horse_names)
                    ].reset_index(drop=True)
                st.session_state['horse_df'] = updated_horse_df

                if r:
                    refresh_training_state(preserve_existing_time_rows=True)
                    save_race_cache(r.race_key)

                st.success("✅ X投稿の検索・解析が完了しました！「総合予想（馬別）」タブで確認してください。")

        # 取得済みツイート表示
        x_tweets_display = st.session_state.get('x_tweets', [])
        x_tweets_display, dropped_existing = _filter_x_tweets_by_race_name(x_tweets_display, r.race_name)
        if dropped_existing > 0:
            st.session_state['x_tweets'] = x_tweets_display
        if x_tweets_display:
            with st.expander(f"𝕏 取得済みツイート ({len(x_tweets_display)}件)", expanded=False):
                for tw in x_tweets_display:
                    author = tw.get('author_username', '不明')
                    label = tw.get('author_label', author)
                    date_str = (tw.get('created_at') or '')[:10]
                    text = tw.get('text', '')
                    metrics = tw.get('public_metrics', {})
                    likes = metrics.get('like_count', 0)
                    rts = metrics.get('retweet_count', 0)
                    url = tw.get('url', '')

                    st.markdown(f"**@{author}** ({label}) — {date_str}")
                    st.text(text[:300] + ("..." if len(text) > 300 else ""))
                    cols = st.columns([1, 1, 2])
                    cols[0].caption(f"♥ {likes}")
                    cols[1].caption(f"🔁 {rts}")
                    if url:
                        cols[2].caption(f"[元の投稿]({url})")
                    st.markdown("---")

                if st.button("🗑️ X情報をリセット", key="x_reset"):
                    st.session_state.pop('x_raw', None)
                    st.session_state.pop('x_tweets', None)
                    st.session_state.pop('x_newest_id', None)
                    # horse_df を再集計（X情報なしで）
                    updated_horse_df = aggregate_horse_analysis(
                        st.session_state.get('youtube_raw', []),
                        st.session_state.get('web_raw', []),
                        st.session_state.get('doc_horse_raw', []),
                    )
                    if active_horse_names and not updated_horse_df.empty and '馬名' in updated_horse_df.columns:
                        updated_horse_df = updated_horse_df[
                            updated_horse_df['馬名'].astype(str).isin(active_horse_names)
                        ].reset_index(drop=True)
                    st.session_state['horse_df'] = updated_horse_df
                    if r:
                        refresh_training_state(preserve_existing_time_rows=True)
                        save_race_cache(r.race_key)
                    st.rerun()

        st.markdown("---")

        # ===== Section 3: ドキュメントアップロード =====
        st.markdown("#### 📄 ドキュメントをアップロード（PDF / テキスト）")
        st.caption("レース傾向や各馬の情報が含まれたPDF・テキストファイルをアップロードすると、分析に活用されます。")

        uploaded_file = st.file_uploader(
            "ファイルを選択",
            type=["pdf", "txt"],
            help="PDF または テキストファイル（.txt）をアップロードしてください",
            key="doc_uploader"
        )

        col_doc1, col_doc2 = st.columns(2)
        with col_doc1:
            analyze_doc_race = st.button(
                "📊 ドキュメントからレース特徴を抽出",
                disabled=(uploaded_file is None),
                key="btn_doc_race"
            )
        with col_doc2:
            analyze_doc_horses = st.button(
                "🐴 ドキュメントから馬別情報を抽出（総合予想に統合）",
                disabled=(uploaded_file is None),
                key="btn_doc_horses"
            )

        if uploaded_file is not None and (analyze_doc_race or analyze_doc_horses):
            with st.spinner("ドキュメントを読み込み中..."):
                doc_text = extract_text_from_uploaded_file(uploaded_file)

            if doc_text:
                if analyze_doc_race:
                    with st.spinner("レース特徴を抽出中..."):
                        doc_race_info = analyze_document_for_race_characteristics(doc_text, uploaded_file.name)
                    if doc_race_info:
                        existing = st.session_state.get('race_characteristics', {})
                        if not isinstance(existing, dict):
                            existing = {}
                        for k, v in doc_race_info.items():
                            value_text = _to_text(v)
                            if value_text and value_text != "資料に記載なし":
                                prev_text = _to_text(existing.get(k, ""))
                                if prev_text:
                                    existing[k] = f"{prev_text}\n\n【{uploaded_file.name}より】\n{value_text}"
                                else:
                                    existing[k] = f"【{uploaded_file.name}より】\n{value_text}"
                        st.session_state['race_characteristics'] = existing
                        if r:
                            save_race_cache(r.race_key)  # ドキュメントのレース特徴をキャッシュに保存
                        st.success(f"✅ {uploaded_file.name} からレース特徴を抽出しました。「レース特徴・傾向」タブで確認できます。")

                if analyze_doc_horses:
                    with st.spinner("馬別情報を抽出中..."):
                        new_doc_raw = analyze_document_for_horses(doc_text, uploaded_file.name)
                    st.session_state['doc_horse_raw'] = st.session_state.get('doc_horse_raw', []) + new_doc_raw
                    # ドキュメント馬別情報をhorse_dfに即時反映（YouTube/Web結果と再集計）
                    updated_horse_df = aggregate_horse_analysis(
                        st.session_state.get('youtube_raw', []),
                        st.session_state.get('web_raw', []),
                        st.session_state.get('doc_horse_raw', []),
                        st.session_state.get('x_raw', []),
                    )
                    if active_horse_names and not updated_horse_df.empty and '馬名' in updated_horse_df.columns:
                        updated_horse_df = updated_horse_df[
                            updated_horse_df['馬名'].astype(str).isin(active_horse_names)
                        ].reset_index(drop=True)
                    st.session_state['horse_df'] = updated_horse_df
                    if r:
                        save_race_cache(r.race_key)  # ドキュメント解析結果をキャッシュに保存
                    st.success(f"✅ {uploaded_file.name} から {len(new_doc_raw)}件の馬別情報を抽出しました。「総合予想（馬別）」タブで確認できます。")
            else:
                st.error("❌ ファイルからテキストを抽出できませんでした")

        # アップロード済みドキュメント馬別情報の確認
        if st.session_state.get('doc_horse_raw'):
            st.markdown("---")
            with st.expander(f"📄 ドキュメントから抽出した馬別情報（{len(st.session_state['doc_horse_raw'])}件）"):
                for item in st.session_state['doc_horse_raw']:
                    st.markdown(f"**{item.get('馬名', '不明')}** — 📄 {item.get('source_title', '')}")
                    st.write(f"✅ {item.get('プラス情報', '')}")
                    st.write(f"⚠️ {item.get('マイナス情報', '')}")
                    st.markdown("---")
                if st.button("🗑️ ドキュメント馬別情報をリセット", key="btn_doc_horse_reset"):
                    st.session_state.pop('doc_horse_raw', None)
                    st.session_state.pop('horse_df', None)
                    if r:
                        save_race_cache(r.race_key)  # クリア後の状態をキャッシュに反映
                    st.rerun()

        st.markdown("---")

        # ===== Section 3: レース特徴リセット =====
        st.markdown("#### 🏟️ レース特徴・傾向")
        st.info("💡 レース特徴はアプリ起動時に「Umanityスクレイピング優先」で自動取得されます。")
        if st.button("🔄 レース特徴を再取得（Umanity優先）", key="btn_race_refresh"):
            st.session_state.pop('race_characteristics', None)
            st.session_state.pop('race_characteristics_enriched', None)
            st.session_state.pop('race_characteristics_last_attempt', None)
            st.session_state.pop('race_characteristics_last_error', None)
            if r:
                save_race_cache(r.race_key)  # キャッシュからもrace_characteristicsを削除→次回ロード時にAPI再実行
            st.rerun()

    # ===== タブ3: 総合予想（馬別） =====
    with tab3:
        st.markdown("### 🏇 馬名別 総合予想情報")
        st.info("💡 「情報入力」タブで Web 一括検索またはドキュメント分析を実行すると、ここに馬別の分析結果が表示されます。")

        if 'horse_df' in st.session_state and not st.session_state['horse_df'].empty:
            horse_df = st.session_state['horse_df']
            if active_horse_names and '馬名' in horse_df.columns:
                horse_df = horse_df[horse_df['馬名'].astype(str).isin(active_horse_names)].reset_index(drop=True)
            st.success(f"✅ 集計完了: {len(horse_df)}頭分の情報")

            # CSVダウンロード
            csv_horse = horse_df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 CSVでダウンロード",
                data=csv_horse,
                file_name="horse_summary.csv",
                mime="text/csv"
            )

            st.markdown("---")
            st.markdown("#### 🐴 馬を選んで詳細を確認")

            horse_names = horse_df['馬名'].tolist()
            if not horse_names:
                st.info("⚠️ 出走取消馬を除外したため、表示対象の馬がありません。")
            else:
                horse_tabs = st.tabs(horse_names)

                for i, htab in enumerate(horse_tabs):
                    row = horse_df.iloc[i]
                    with htab:
                        merit_text = row.get('メリット', '（情報なし）')
                        demerit_text = row.get('デメリット', '（情報なし）')
                        source_count = row.get('情報源数', 0)

                        # メリット・デメリットの件数を数えてバナー判定
                        merit_items = [x.strip() for x in re.split(r'\n\n(?=\[\d+\])', merit_text.strip()) if x.strip() and x.strip() != '（情報なし）']
                        demerit_items = [x.strip() for x in re.split(r'\n\n(?=\[\d+\])', demerit_text.strip()) if x.strip() and x.strip() != '（情報なし）']
                        m_cnt = len(merit_items)
                        d_cnt = len(demerit_items)

                        # 買い/様子見/消し 判定バナー
                        col_v, col_src = st.columns([3, 1])
                        with col_v:
                            if m_cnt >= 3 and d_cnt <= 1:
                                st.markdown('<div class="verdict-buy">🟢 買い材料多数 — 有力候補</div>', unsafe_allow_html=True)
                            elif d_cnt >= 3 and m_cnt <= 1:
                                st.markdown('<div class="verdict-pass">🔴 消し材料多数 — 評価注意</div>', unsafe_allow_html=True)
                            else:
                                st.markdown('<div class="verdict-watch">🟡 様子見 — 情報を確認して判断</div>', unsafe_allow_html=True)
                        with col_src:
                            st.metric("情報源数", f"{source_count}件", label_visibility="visible")

                        st.markdown("---")
                        col_merit, col_demerit = st.columns(2)

                        with col_merit:
                            st.markdown('<div class="section-header-merit">✅ 買い材料（好材料）</div>', unsafe_allow_html=True)
                            if merit_items:
                                for idx_m, item in enumerate(merit_items, 1):
                                    clean = re.sub(r'^\[\d+\]\s*', '', item)
                                    st.markdown(f'<div class="merit-card"><b>#{idx_m}</b>　{clean}</div>', unsafe_allow_html=True)
                            else:
                                st.info("情報がありませんでした")

                            merit_src = row.get('メリット出典', '（なし）')
                            if merit_src and merit_src != '（なし）':
                                with st.expander("📎 出典を見る"):
                                    st.markdown(merit_src)

                        with col_demerit:
                            st.markdown('<div class="section-header-demerit">⚠️ 消し材料（懸念点）</div>', unsafe_allow_html=True)
                            if demerit_items:
                                for idx_d, item in enumerate(demerit_items, 1):
                                    clean = re.sub(r'^\[\d+\]\s*', '', item)
                                    st.markdown(f'<div class="demerit-card"><b>#{idx_d}</b>　{clean}</div>', unsafe_allow_html=True)
                            else:
                                st.info("懸念点の情報がありませんでした")

                            demerit_src = row.get('デメリット出典', '（なし）')
                            if demerit_src and demerit_src != '（なし）':
                                with st.expander("📎 出典を見る"):
                                    st.markdown(demerit_src)

            st.markdown("---")
            if 'web_articles' in st.session_state and st.session_state['web_articles']:
                with st.expander("🌐 参照したWeb記事一覧"):
                    for art in st.session_state['web_articles']:
                        title = _to_text(art.get('title', '')) if isinstance(art, dict) else ""
                        url = _to_text(art.get('url', '')) if isinstance(art, dict) else ""
                        source_name = _to_text(art.get('source_name', '')) if isinstance(art, dict) else ""
                        title = title or "無題"
                        source_name = source_name or "unknown"
                        if url:
                            st.markdown(f"- [{title}]({url}) — {source_name}")
                        else:
                            st.markdown(f"- {title} — {source_name}")

        else:
            st.info("👆 「情報入力」タブで「🔍 Web 一括検索」を実行してください")

    # ===== タブ4: レース特徴・傾向 =====
    with tab4:
        st.markdown(f"### 🏟️ {get_race_display_name()} レース特徴・傾向")

        if 'race_characteristics' in st.session_state and st.session_state['race_characteristics']:
            race_info = st.session_state['race_characteristics']

            def _as_lines(value):
                """race_info値の揺れ（str/list/dict）を行リストへ正規化する。"""
                if value is None:
                    return []
                if isinstance(value, list):
                    lines = []
                    for item in value:
                        text = str(item).strip()
                        if text:
                            lines.extend([ln.strip() for ln in text.split('\n') if ln.strip()])
                    return lines
                if isinstance(value, dict):
                    value = json.dumps(value, ensure_ascii=False)
                text = str(value).strip()
                return [ln.strip() for ln in text.split('\n') if ln.strip()]
            source_name = _to_text(race_info.get('情報ソース'))
            source_url = _to_text(race_info.get('情報ソースURL'))
            source_method = _to_text(race_info.get('情報取得方式'))

            if source_url:
                st.link_button("🔗 参照元を開く（ウマニティ）", source_url, use_container_width=True)
            if source_name or source_method:
                st.caption(" / ".join([x for x in (source_name, source_method) if x]))

            summary_tab, data_tab = st.tabs(["🧭 傾向サマリー", "📊 Umanityデータ分析"])

            with summary_tab:
                if race_info.get('コース特徴'):
                    st.markdown("#### 🏁 コース特徴")
                    st.info(race_info['コース特徴'])

                col_win, col_lose = st.columns(2)
                with col_win:
                    if race_info.get('勝ちやすい馬のタイプ'):
                        st.markdown("#### ✅ 勝ちやすい馬のタイプ")
                        for line in _as_lines(race_info.get('勝ちやすい馬のタイプ')):
                            st.success(line)
                with col_lose:
                    if race_info.get('苦手な馬のタイプ'):
                        st.markdown("#### ❌ 苦手な馬のタイプ")
                        for line in _as_lines(race_info.get('苦手な馬のタイプ')):
                            st.error(line)

                col_inner, col_outer = st.columns(2)
                with col_inner:
                    if race_info.get('枠順有利'):
                        st.markdown("#### 📍 枠順：有利")
                        st.success(race_info['枠順有利'])
                with col_outer:
                    if race_info.get('枠順不利'):
                        st.markdown("#### ⚠️ 枠順：不利")
                        st.error(race_info['枠順不利'])

                if race_info.get('過去の傾向'):
                    st.markdown("#### 📊 過去の傾向・データ")
                    for line in _as_lines(race_info.get('過去の傾向')):
                        st.write(line)

                if race_info.get('騎手厩舎傾向'):
                    with st.expander("👤 騎手・厩舎の傾向", expanded=False):
                        for line in _as_lines(race_info.get('騎手厩舎傾向')):
                            st.write(line)

                if race_info.get('注目ポイント'):
                    st.markdown("#### 💡 注目ポイント")
                    for line in _as_lines(race_info.get('注目ポイント')):
                        st.warning(line)

            with data_tab:
                data_tables = race_info.get('データ分析テーブル')
                if isinstance(data_tables, list) and data_tables:
                    st.caption("ウマニティ「データ分析」ページの主要テーブルをそのまま表示しています。")
                    for idx, table_info in enumerate(data_tables):
                        section_title = _to_text(table_info.get("section")) or f"データ分析 {idx + 1}"
                        rows = table_info.get("rows")
                        headers = table_info.get("headers")
                        if not isinstance(rows, list) or not rows:
                            continue
                        df_table = pd.DataFrame(rows)
                        if isinstance(headers, list) and headers:
                            ordered_cols = [c for c in headers if c in df_table.columns]
                            remain_cols = [c for c in df_table.columns if c not in ordered_cols]
                            df_table = df_table[ordered_cols + remain_cols]
                        with st.expander(f"◆ {section_title}", expanded=(idx < 2)):
                            st.dataframe(df_table, use_container_width=True, hide_index=True)
                else:
                    st.info("Umanityデータ分析テーブルが未取得のため、サマリー情報のみ表示しています。")

        else:
            st.info("👆 起動時の自動取得（Umanity優先）を待つか、「情報入力」タブの再取得ボタンを実行してください")

    # ===== タブ5: YouTube詳細 =====
    with tab5:
        st.markdown("### 🎥 YouTube予想動画から情報収集")
        st.info("💡 YouTubeの予想動画から、プラス材料・マイナス材料を自動抽出します")

        # 検索キーワード入力
        col_search1, col_search2 = st.columns([3, 1])

        with col_search1:
            search_keyword = st.text_input(
                "検索キーワード",
                value=f"{get_race_display_name()} 予想",
                help="YouTubeで検索したいキーワードを入力",
                key=f"yt_detail_keyword::{race_widget_scope}"
            )

        with col_search2:
            max_videos = st.number_input(
                "取得件数",
                min_value=1,
                max_value=10,
                value=5,
                help="取得する動画の件数",
                key="yt_detail_max"
            )

        # 検索ボタン（検索のみ）
        if st.button("🔍 YouTube検索", type="primary", key="yt_detail_search"):
            with st.spinner("YouTube動画を検索中..."):
                videos = search_youtube_videos(search_keyword, max_videos)
                before_filter = len(videos)
                videos = filter_relevant_videos(videos)
            if videos:
                st.session_state['youtube_videos'] = videos
                st.session_state['yt_detail_analysis'] = {}
                st.session_state['yt_video_conclusions'] = {}
                filtered_out = before_filter - len(videos)
                msg = f"✅ {len(videos)}件の動画を取得しました"
                if filtered_out > 0:
                    msg += f"（{filtered_out}件は無関係として除外）"
                st.success(msg)
            else:
                st.error("❌ 動画を取得できませんでした")

        # 動画リスト（session_stateから読み込み）
        videos = st.session_state.get('youtube_videos', [])

        if videos:
            # 要約表
            if 'youtube_summary_df' in st.session_state and not st.session_state['youtube_summary_df'].empty:
                summary_df = st.session_state['youtube_summary_df']
                st.markdown("### 📊 動画別 プラス・マイナス材料一覧")

                def highlight_cells(val, column_name):
                    if column_name in ['プラス情報', 'プラス出典']:
                        if val and val != '':
                            return 'background-color: #d4edda; color: #155724;'
                    elif column_name in ['マイナス情報', 'マイナス出典']:
                        if val and val != '':
                            return 'background-color: #f8d7da; color: #721c24;'
                    return ''

                styled_df = summary_df.style.apply(
                    lambda row: [
                        '',
                        highlight_cells(row['プラス情報'], 'プラス情報'),
                        highlight_cells(row['プラス出典'], 'プラス出典'),
                        highlight_cells(row['マイナス情報'], 'マイナス情報'),
                        highlight_cells(row['マイナス出典'], 'マイナス出典')
                    ],
                    axis=1
                )
                st.dataframe(
                    styled_df,
                    use_container_width=True,
                    hide_index=True,
                    height=400,
                    column_config={
                        '馬名': st.column_config.TextColumn('馬名', width='medium'),
                        'プラス情報': st.column_config.TextColumn('プラス情報', width='large'),
                        'プラス出典': st.column_config.LinkColumn('プラス出典', width='medium'),
                        'マイナス情報': st.column_config.TextColumn('マイナス情報', width='large'),
                        'マイナス出典': st.column_config.LinkColumn('マイナス出典', width='medium'),
                    }
                )
                csv = summary_df.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📥 CSVでダウンロード",
                    data=csv,
                    file_name="youtube_summary.csv",
                    mime="text/csv"
                )

            # 動画詳細
            st.markdown("---")
            st.markdown("### 📺 取得した動画の詳細情報")
            for idx, video in enumerate(videos, 1):
                st.markdown("---")
                st.markdown(f"### 📺 動画 {idx}: {video['title']}")

                col_video1, col_video2 = st.columns([1, 2])
                with col_video1:
                    st.image(video['thumbnail_url'], use_container_width=True)
                    if st.button("読み込み+概要取得", key=f"yt_load_{video['video_id']}", use_container_width=True):
                        with st.spinner("動画を解析中..."):
                            try:
                                analysis_results, video_conclusion = analyze_video_with_gemini(video)
                            except Exception as e:
                                st.error(f"❌ 解析に失敗しました: {type(e).__name__} ({str(e)[:120]})")
                                analysis_results, video_conclusion = [], {}
                        yt_map = st.session_state.get('yt_detail_analysis', {})
                        yt_map[video['video_id']] = analysis_results
                        st.session_state['yt_detail_analysis'] = yt_map
                        conclusion_map = st.session_state.get('yt_video_conclusions', {})
                        if video_conclusion:
                            conclusion_map[video['video_id']] = video_conclusion
                        else:
                            conclusion_map.pop(video['video_id'], None)
                        st.session_state['yt_video_conclusions'] = conclusion_map
                        refresh_training_state(preserve_existing_time_rows=True)
                        if r:
                            save_race_cache(r.race_key)
                        if analysis_results or video_conclusion:
                            st.success(
                                f"✅ 馬別 {len(analysis_results)}件 / 結論 {('あり' if video_conclusion else 'なし')} で抽出しました"
                            )
                        else:
                            st.warning("⚠️ 抽出結果がありませんでした")
                    st.link_button("▶️ YouTubeで視聴", video['video_url'], use_container_width=True)

                with col_video2:
                    st.caption(f"📢 {video['channel_title']}")
                    published_date = video['published_at'][:10]
                    st.caption(f"📅 公開日: {published_date}")
                    with st.expander("📝 概要欄を表示"):
                        st.write(video['description'] if video['description'] else "（概要なし）")

                st.markdown("#### 🔍 Gemini 馬別分析（字幕・概要欄・動画本編から抽出）")
                yt_map = st.session_state.get('yt_detail_analysis', {})
                analysis_results = yt_map.get(video['video_id'], [])
                conclusion_map = st.session_state.get('yt_video_conclusions', {})
                video_conclusion = conclusion_map.get(video['video_id'], {})

                if video_conclusion:
                    st.markdown("#### 🏁 動画の結論（本命・対抗）")
                    honmei = _to_text(video_conclusion.get('本命'))
                    taiko = _to_text(video_conclusion.get('対抗'))
                    tanan = _to_text(video_conclusion.get('単穴'))
                    has_pick = _has_meaningful_video_conclusion(video_conclusion)

                    if has_pick:
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if honmei:
                                st.success(f"◎ 本命: {honmei}")
                            else:
                                st.caption("◎ 本命: 抽出なし")
                        with c2:
                            if taiko:
                                st.info(f"○ 対抗: {taiko}")
                            else:
                                st.caption("○ 対抗: 抽出なし")
                        with c3:
                            if tanan:
                                st.caption(f"▲ 単穴: {tanan}")
                            else:
                                st.caption("▲ 単穴: 抽出なし")
                    else:
                        st.caption("※ 本命/対抗などの印は抽出できませんでした。")

                    extra_lines = []
                    renshita = _to_text(video_conclusion.get('連下'))
                    danger = _to_text(video_conclusion.get('危険な人気馬'))
                    plan = _to_text(video_conclusion.get('買い目方針'))
                    if renshita:
                        extra_lines.append(f"△ 連下: {renshita}")
                    if danger:
                        extra_lines.append(f"⚠️ 危険な人気馬: {danger}")
                    if plan:
                        extra_lines.append(f"🧾 買い目方針: {plan}")
                    if extra_lines:
                        st.markdown("\n\n".join(extra_lines))

                if analysis_results:
                    for res in analysis_results:
                        horse_name = res.get('馬名', '')
                        plus_info = res.get('プラス情報', '特になし')
                        minus_info = res.get('マイナス情報', '特になし')
                        if horse_name and horse_name != '全体的な予想':
                            st.markdown(f"**🐴 {horse_name}**")
                        col_plus, col_minus = st.columns(2)
                        with col_plus:
                            st.markdown("**✅ プラス材料**")
                            if plus_info and plus_info != '特になし':
                                st.success(plus_info)
                            else:
                                st.caption("（抽出なし）")
                        with col_minus:
                            st.markdown("**⚠️ マイナス材料**")
                            if minus_info and minus_info != '特になし':
                                st.warning(minus_info)
                            else:
                                st.caption("（抽出なし）")
                elif video_conclusion:
                    st.caption("（動画の結論は抽出できましたが、馬別の詳細コメントは抽出されませんでした）")
                else:
                    st.caption("（サムネイル下の「読み込み+概要取得」を押すと分析結果が表示されます）")

        else:
            st.info("👆 上の「🔍 YouTube検索」ボタンをクリックして動画を取得してください（または「総合予想（馬別）」タブで一括検索すると動画も取得されます）")

            col_guide1, col_guide2 = st.columns(2)
            with col_guide1:
                with st.expander("❓ YouTube APIキーの取得方法"):
                    st.markdown(
                        """
                        ### YouTube Data API v3 のAPIキー取得手順

                        1. **Google Cloud Consoleにアクセス**
                           - https://console.cloud.google.com/

                        2. **新しいプロジェクトを作成**
                           - プロジェクト名: 例）Keiba-App

                        3. **YouTube Data API v3を有効化**
                           - 「APIとサービス」→「ライブラリ」
                           - 「YouTube Data API v3」を検索
                           - 「有効にする」をクリック

                        4. **認証情報を作成**
                           - 「APIとサービス」→「認証情報」
                           - 「認証情報を作成」→「APIキー」を選択

                        5. **APIキーをコピー**
                           - 表示されたAPIキー（例: AIza...）をコピー
                           - `app.py` の `YOUTUBE_API_KEY` に貼り付け

                        6. **アプリを再起動**
                           - Streamlitを再起動すると設定が反映されます
                        """
                    )
            with col_guide2:
                with st.expander("🤖 Gemini APIキーの取得方法（重要！）"):
                    st.markdown(
                        """
                        ### Gemini API (Google AI Studio) のAPIキー取得手順

                        1. **Google AI Studioにアクセス**
                           - https://aistudio.google.com/app/apikey

                        2. **Googleアカウントでログイン**
                           - Gmailアカウントでログイン

                        3. **APIキーを作成**
                           - 「Create API Key」ボタンをクリック
                           - 既存のGoogle Cloud プロジェクトを選択または新規作成

                        4. **APIキーをコピー**
                           - 表示されたAPIキー（例: AIza...）をコピー

                        5. **app.pyに貼り付け**
                           - `GEMINI_API_KEY` に貼り付け

                        6. **料金について**
                           - Gemini 2.0 Flash は高速・低コスト

                        7. **アプリを再起動**
                           - Streamlitを再起動すると設定が反映されます
                        """
                    )

    # ===== タブ6: 追切結果・評価 =====
    with tab6:
        st.markdown("### 🏋️ 追切結果・評価")
        st.caption("馬ごとに「最終追切 / 1週前 / 前走最終」を並べ、ハロン別タイム・脚色・追切コメントを比較します。")

        col_fetch_l, col_fetch_r = st.columns([1, 3])
        with col_fetch_l:
            training_article_limit = st.number_input(
                "追切記事上限",
                min_value=5,
                max_value=40,
                value=15,
                step=5,
                key=f"training_article_limit::{race_widget_scope}",
            )
        with col_fetch_r:
            st.caption("うましるを最優先で取得し、不足馬のみ他サイトで補完します。")
            if st.button("🏋️ 追切専用情報を追加取得", key=f"training_fetch_btn::{race_widget_scope}", use_container_width=True):
                if not r:
                    st.warning("⚠️ レース未選択のため取得できません。")
                else:
                    with st.spinner("追切情報を追加取得中..."):
                        horse_names_for_training = sorted(active_horse_names) if active_horse_names else get_all_horse_names()
                        allowed_training_horses = {_to_text(x) for x in horse_names_for_training if _to_text(x)}
                        umasiru_articles, umasiru_rows = fetch_umasiru_training_time_rows(
                            race_name=r.race_name,
                            horse_names=horse_names_for_training,
                            max_articles=3,
                        )
                        umasiru_rows = _filter_training_time_rows_by_horses(umasiru_rows, allowed_training_horses)
                        st.session_state['training_time_rows'] = merge_training_time_rows(
                            _filter_training_time_rows_by_horses(st.session_state.get('training_time_rows', []), allowed_training_horses),
                            umasiru_rows,
                        )

                        missing_before_fallback = _horses_missing_training_time(
                            horse_names_for_training,
                            st.session_state.get('training_time_rows', []),
                        )

                        added_articles = []
                        if missing_before_fallback:
                            fallback_queries = _build_training_fallback_queries(r.race_name, missing_before_fallback)
                            new_articles, new_web_raw = fetch_and_analyze_web_articles(
                                fallback_queries,
                                total_article_limit=int(training_article_limit),
                                include_domains=TRAINING_FALLBACK_ALLOWLIST,
                                auto_add_horse_queries=False,
                            )

                            existing_web_raw = st.session_state.get('web_raw', [])
                            existing_fp = {_raw_fingerprint(x) for x in existing_web_raw if _raw_fingerprint(x)}
                            added_raw = [x for x in new_web_raw if not _raw_fingerprint(x) or _raw_fingerprint(x) not in existing_fp]
                            merged_web_raw = existing_web_raw + added_raw

                            existing_urls = {a.get('url') for a in st.session_state.get('web_articles', []) if a.get('url')}
                            added_articles = [a for a in new_articles if not a.get('url') or a.get('url') not in existing_urls]
                            merged_articles = st.session_state.get('web_articles', []) + added_articles

                            updated_horse_df = aggregate_horse_analysis(
                                st.session_state.get('youtube_raw', []),
                                merged_web_raw,
                                st.session_state.get('doc_horse_raw', []),
                                st.session_state.get('x_raw', []),
                            )
                            if active_horse_names and not updated_horse_df.empty and '馬名' in updated_horse_df.columns:
                                updated_horse_df = updated_horse_df[
                                    updated_horse_df['馬名'].astype(str).isin(active_horse_names)
                                ].reset_index(drop=True)

                            st.session_state['web_raw'] = merged_web_raw
                            st.session_state['web_articles'] = merged_articles
                            st.session_state['horse_df'] = updated_horse_df

                        # コメント抽出由来のタイムも加えて最終統合
                        refresh_training_state(preserve_existing_time_rows=True)
                        if r:
                            save_race_cache(r.race_key)

                    umasiru_horses = {
                        _to_text(row.get("馬名"))
                        for row in umasiru_rows
                        if any(not _is_blank_training_value(row.get(col)) for col in ("6F", "5F", "4F", "3F", "2F", "1F"))
                    }
                    missing_after = _horses_missing_training_time(
                        horse_names_for_training,
                        st.session_state.get('training_time_rows', []),
                    )
                    pre_missing_set = set(missing_before_fallback)
                    post_missing_set = set(missing_after)
                    fallback_resolved = len(pre_missing_set - post_missing_set)
                    st.success(
                        "✅ 追切情報を更新しました "
                        f"(うましる: {len(umasiru_horses)}頭 / 補完: {fallback_resolved}頭 / 未取得: {len(missing_after)}頭 / 補完記事新規: {len(added_articles)}件)"
                    )
                    st.rerun()

        training_items = st.session_state.get('training_items', [])
        training_time_rows = st.session_state.get('training_time_rows', [])
        allowed_display_horses = set(active_horse_names) if active_horse_names else {_to_text(x) for x in get_all_horse_names() if _to_text(x)}
        training_items = _filter_training_items_by_horses(training_items, allowed_display_horses)
        training_time_rows = _filter_training_time_rows_by_horses(training_time_rows, allowed_display_horses)

        if not training_items and not training_time_rows:
            st.info("👆 「情報入力」タブで「🔍 Web 一括検索」または「𝕏 X投稿を検索」を実行してください")
        else:
            from collections import defaultdict

            def _new_bucket():
                return {
                    "laps": {k: [] for k in ["総合", "6F", "5F", "4F", "3F", "2F", "1F"]},
                    "places": [],
                    "plus": [],
                    "minus": [],
                    "intensity_labels": [],
                    "intensity_score": -1,
                }

            horse_data = defaultdict(
                lambda: {
                    "1週前": _new_bucket(),
                    "直近": _new_bucket(),
                    "前走最終": _new_bucket(),
                    "不明": _new_bucket(),
                }
            )

            def _bucket_has_data(bucket: dict) -> bool:
                return (
                    any(bucket["laps"][k] for k in bucket["laps"])
                    or bool(bucket["places"])
                    or bool(bucket["plus"] or bucket["minus"] or bucket["intensity_labels"])
                )

            def _merge_laps(dst: dict, src: dict):
                for key, vals in src.items():
                    for v in vals:
                        if v not in dst[key]:
                            dst[key].append(v)

            def _join_comments(items: list[str]) -> str:
                if not items:
                    return "—"
                return "\n".join(f"・{x}" for x in items)

            def _format_intensity(bucket: dict) -> str:
                return " / ".join(bucket["intensity_labels"]) if bucket["intensity_labels"] else "不明"

            def _first_lap(bucket: dict, key: str) -> str:
                vals = bucket["laps"].get(key, [])
                return vals[0] if vals else "—"

            # 1) 構造化タイム（うましる優先）を先に投入
            for row in training_time_rows:
                if not isinstance(row, dict):
                    continue
                horse = _to_text(row.get("馬名") or "不明") or "不明"
                phase = _normalize_training_phase_label(row.get("時期") or "不明")
                if phase not in TRAINING_PHASE_ORDER:
                    phase = "不明"
                bucket = horse_data[horse][phase]

                place = _to_text(row.get("場所") or "")
                if place and not _is_blank_training_value(place) and place not in bucket["places"]:
                    bucket["places"].append(place)

                for lap_col in ("6F", "5F", "4F", "3F", "2F", "1F"):
                    lap_val = _to_text(row.get(lap_col) or "")
                    if lap_val and not _is_blank_training_value(lap_val) and lap_val not in bucket["laps"][lap_col]:
                        bucket["laps"][lap_col].append(lap_val)

                intensity = _to_text(row.get("脚色") or "")
                if intensity and not _is_blank_training_value(intensity) and intensity not in bucket["intensity_labels"]:
                    bucket["intensity_labels"].append(intensity)

                _, intensity_score = _extract_training_intensity(intensity)
                if intensity_score > bucket["intensity_score"]:
                    bucket["intensity_score"] = intensity_score

            # 2) コメント由来の追切情報（web / YouTube / X）を加算
            for item in training_items:
                horse = _to_text(item.get('馬名') or '不明') or '不明'
                kind = _to_text(item.get('種別') or '')
                comment = _to_text(item.get('評価内容') or '').strip()
                if not comment:
                    continue

                # 念のためここでも追切関連文のみへ絞り込む
                segments = _extract_training_sentences(comment)
                if not segments:
                    continue

                for seg in segments:
                    phase = _classify_training_phase(seg)
                    bucket = horse_data[horse][phase]

                    place = _extract_training_place(seg)
                    if place != "—" and place not in bucket["places"]:
                        bucket["places"].append(place)

                    lap_times = _extract_training_lap_times(seg)
                    _merge_laps(bucket["laps"], lap_times)

                    intensity_label, intensity_score = _extract_training_intensity(seg)
                    if intensity_label != "不明" and intensity_label not in bucket["intensity_labels"]:
                        bucket["intensity_labels"].append(intensity_label)
                    if intensity_score > bucket["intensity_score"]:
                        bucket["intensity_score"] = intensity_score

                    if kind == "プラス" and seg not in bucket["plus"]:
                        bucket["plus"].append(seg)
                    if kind == "マイナス" and seg not in bucket["minus"]:
                        bucket["minus"].append(seg)

            overview_rows = []
            for horse, data in sorted(horse_data.items()):
                week = data["1週前"]
                latest = data["直近"]
                prev = data["前走最終"]
                unknown = data["不明"]

                week_intensity = _format_intensity(week)
                latest_intensity = _format_intensity(latest)
                latest_score = latest["intensity_score"]
                if latest_intensity == "不明" and _bucket_has_data(unknown):
                    unknown_intensity = _format_intensity(unknown)
                    if unknown_intensity != "不明":
                        latest_intensity = f"{unknown_intensity}（時期判定なし）"
                        latest_score = unknown["intensity_score"]

                if week["intensity_score"] >= 0 and latest_score >= 0:
                    if latest_score > week["intensity_score"]:
                        trend = "強化"
                    elif latest_score < week["intensity_score"]:
                        trend = "軽化"
                    else:
                        trend = "同等"
                else:
                    trend = "判定保留"
                intensity_compare = f"1週前: {week_intensity} → 直近: {latest_intensity}（{trend}）"

                coverage = [p for p in ["直近", "1週前", "前走最終"] if _bucket_has_data(data[p])]
                if _bucket_has_data(unknown):
                    coverage.append("時期不明")

                overview_rows.append({
                    "馬名": horse,
                    "データ時期": " / ".join(coverage) if coverage else "—",
                    "1週前 1F": _first_lap(week, "1F"),
                    "直近 1F": _first_lap(latest, "1F") if _first_lap(latest, "1F") != "—" else _first_lap(unknown, "1F"),
                    "強度比較": intensity_compare,
                })

            overview_df = pd.DataFrame(overview_rows)
            st.dataframe(
                overview_df,
                use_container_width=True,
                column_config={
                    "馬名": st.column_config.TextColumn("馬名", width="small"),
                    "データ時期": st.column_config.TextColumn("データ時期", width="medium"),
                    "1週前 1F": st.column_config.TextColumn("⏱ 1週前 1F", width="small"),
                    "直近 1F": st.column_config.TextColumn("⏱ 直近 1F", width="small"),
                    "強度比較": st.column_config.TextColumn("💪 強度比較", width="medium"),
                },
                hide_index=True,
            )

            if active_horse_names:
                active_list = sorted(active_horse_names)
                missing_horses = set(_horses_missing_training_time(active_list, training_time_rows))
                covered_umasiru = set()
                covered_fallback = set()
                for row in training_time_rows:
                    horse = _to_text(row.get("馬名"))
                    if horse not in active_horse_names:
                        continue
                    has_lap = any(not _is_blank_training_value(row.get(col)) for col in ("6F", "5F", "4F", "3F", "2F", "1F"))
                    if not has_lap:
                        continue
                    if _to_text(row.get("source_type")) == "umasiru":
                        covered_umasiru.add(horse)
                    else:
                        covered_fallback.add(horse)
                covered_fallback = covered_fallback - covered_umasiru
                st.caption(
                    f"取得サマリー: うましる {len(covered_umasiru)}頭 / 補完 {len(covered_fallback)}頭 / 未取得 {len(missing_horses)}頭"
                )

            if sum(1 for _, d in horse_data.items() if _bucket_has_data(d["直近"]) or _bucket_has_data(d["1週前"])) < 5:
                st.warning("ℹ️ 追切データがまだ少なめです。上の「追切専用情報を追加取得」を押すと改善しやすいです。")

            st.markdown("---")
            st.markdown("#### 🐴 馬別詳細（最終追切 / 1週前 / 前走最終）")
            phase_label = {"直近": "最終追切", "1週前": "1週前", "前走最終": "前走最終", "不明": "時期不明"}
            phase_order = ["直近", "1週前", "前走最終", "不明"]

            for horse, data in sorted(horse_data.items()):
                with st.expander(f"🐎 {horse}", expanded=False):
                    phase_rows = []
                    for phase in phase_order:
                        bucket = data[phase]
                        if not _bucket_has_data(bucket):
                            continue

                        phase_rows.append({
                            "時期": phase_label[phase],
                            "場所": " / ".join(bucket["places"]) if bucket["places"] else "—",
                            "6F": _first_lap(bucket, "6F"),
                            "5F": _first_lap(bucket, "5F"),
                            "4F": _first_lap(bucket, "4F"),
                            "3F": _first_lap(bucket, "3F"),
                            "2F": _first_lap(bucket, "2F"),
                            "1F": _first_lap(bucket, "1F"),
                            "脚色": _format_intensity(bucket),
                        })

                    if phase_rows:
                        st.dataframe(
                            pd.DataFrame(phase_rows),
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "時期": st.column_config.TextColumn("時期", width="small"),
                                "場所": st.column_config.TextColumn("場所", width="medium"),
                                "6F": st.column_config.TextColumn("6F", width="small"),
                                "5F": st.column_config.TextColumn("5F", width="small"),
                                "4F": st.column_config.TextColumn("4F", width="small"),
                                "3F": st.column_config.TextColumn("3F", width="small"),
                                "2F": st.column_config.TextColumn("2F", width="small"),
                                "1F": st.column_config.TextColumn("1F", width="small"),
                                "脚色": st.column_config.TextColumn("脚色", width="medium"),
                            },
                        )
                    else:
                        st.caption("追切の時期別データがありません。")

                    plus_comments = data["直近"]["plus"] + data["1週前"]["plus"] + data["前走最終"]["plus"] + data["不明"]["plus"]
                    minus_comments = data["直近"]["minus"] + data["1週前"]["minus"] + data["前走最終"]["minus"] + data["不明"]["minus"]
                    col_c1, col_c2 = st.columns(2)
                    with col_c1:
                        st.markdown("**✅ 追切コメント（プラス）**")
                        st.write(_join_comments(plus_comments))
                    with col_c2:
                        st.markdown("**⚠️ 追切コメント（マイナス）**")
                        st.write(_join_comments(minus_comments))

    # ===== タブ7: 予算別買い目プラン =====
    with tab7:
        st.markdown("### 💰 予算別買い目プラン")
        st.caption("既存の馬別評価・追切・YouTube結論・オッズを統合し、予算と方針スライダーに合わせて買い目を提案します。")

        if df_active is None or df_active.empty or '馬名' not in df_active.columns:
            st.info("出馬表データが不足しているため、買い目プランを生成できません。")
        else:
            saved_settings = st.session_state.get('bet_plan_settings') or {}
            default_budget = int(saved_settings.get('budget') or 5000)
            if default_budget < BET_STAKE_UNIT_YEN:
                default_budget = BET_STAKE_UNIT_YEN
            default_budget = int((default_budget // BET_STAKE_UNIT_YEN) * BET_STAKE_UNIT_YEN)
            if default_budget <= 0:
                default_budget = BET_STAKE_UNIT_YEN

            default_slider = int(saved_settings.get('slider') or 50)
            if default_slider < 0:
                default_slider = 0
            if default_slider > 100:
                default_slider = 100

            saved_types = saved_settings.get('bet_types') or BET_TYPES_ALL
            default_types = [bt for bt in BET_TYPES_ALL if bt in saved_types] or BET_TYPES_ALL

            candidate_horses = sorted(active_horse_names) if active_horse_names else sorted(
                {_to_text(x) for x in df_active['馬名'].tolist() if _to_text(x)}
            )
            anchor_options = ["自動"] + candidate_horses
            saved_anchor = _to_text(saved_settings.get('anchor_horse') or "自動")
            if saved_anchor not in anchor_options:
                saved_anchor = "自動"
            anchor_index = anchor_options.index(saved_anchor)

            col_set1, col_set2 = st.columns([1, 1])
            with col_set1:
                budget_yen = st.number_input(
                    "予算（円）",
                    min_value=BET_STAKE_UNIT_YEN,
                    max_value=500000,
                    value=default_budget,
                    step=BET_STAKE_UNIT_YEN,
                    key=f"bet_budget::{race_widget_scope}",
                )
                score_slider = st.slider(
                    "方針スライダー（0=的中率 / 100=回収率）",
                    min_value=0,
                    max_value=100,
                    value=default_slider,
                    key=f"bet_slider::{race_widget_scope}",
                )
            with col_set2:
                selected_bet_types = st.multiselect(
                    "券種",
                    options=BET_TYPES_ALL,
                    default=default_types,
                    key=f"bet_types::{race_widget_scope}",
                )
                anchor_horse = st.selectbox(
                    "軸馬",
                    options=anchor_options,
                    index=anchor_index,
                    key=f"bet_anchor::{race_widget_scope}",
                )

            st.caption("配分単位は 500円固定、提案点数は最大10点です。")

            btn_col1, btn_col2 = st.columns([1, 1])
            with btn_col1:
                refresh_odds_clicked = st.button("🔄 券種別オッズを再取得", key=f"bet_refresh_odds::{race_widget_scope}")
            with btn_col2:
                generate_clicked = st.button("✅ 買い目プランを生成", type="primary", key=f"bet_generate::{race_widget_scope}")

            if refresh_odds_clicked:
                if not selected_bet_types:
                    st.warning("券種を1つ以上選択してください。")
                else:
                    with st.spinner("netkeiba から券種別オッズを取得中..."):
                        fetched_odds, odds_warnings = fetch_multi_bet_type_odds(df_active, selected_bet_types)
                    existing_odds = st.session_state.get('bet_type_odds') or {}
                    for bt, v in fetched_odds.items():
                        existing_odds[bt] = v
                    st.session_state['bet_type_odds'] = existing_odds
                    if odds_warnings:
                        for wmsg in odds_warnings:
                            st.warning(wmsg)
                    else:
                        st.success("券種別オッズを更新しました。")
                    if r:
                        save_race_cache(r.race_key)

            if generate_clicked:
                if not selected_bet_types:
                    st.warning("券種を1つ以上選択してください。")
                else:
                    with st.spinner("買い目プランを生成中..."):
                        fetched_odds, odds_warnings = fetch_multi_bet_type_odds(df_active, selected_bet_types)
                        merged_odds = st.session_state.get('bet_type_odds') or {}
                        for bt, v in fetched_odds.items():
                            merged_odds[bt] = v
                        st.session_state['bet_type_odds'] = merged_odds

                        plan_result = build_budget_bet_plan(
                            df_active=df_active,
                            budget_yen=int(budget_yen),
                            slider_value=int(score_slider),
                            bet_types=selected_bet_types,
                            anchor_horse=anchor_horse,
                            max_points=BET_MAX_POINTS,
                            stake_unit=BET_STAKE_UNIT_YEN,
                            bet_type_odds=merged_odds,
                        )
                        if odds_warnings:
                            existing_warn = plan_result.get("warnings") or []
                            plan_result["warnings"] = list(dict.fromkeys(existing_warn + odds_warnings))

                        st.session_state['bet_plan_settings'] = {
                            "budget": int(budget_yen),
                            "stake_unit": BET_STAKE_UNIT_YEN,
                            "slider": int(score_slider),
                            "bet_types": list(selected_bet_types),
                            "anchor_mode": "manual" if anchor_horse != "自動" else "auto",
                            "anchor_horse": anchor_horse,
                            "max_points": BET_MAX_POINTS,
                        }
                        st.session_state['bet_plan_result'] = plan_result
                        if r:
                            save_race_cache(r.race_key)
                    st.success("買い目プランを更新しました。")

            plan_result = st.session_state.get('bet_plan_result') or {}
            summary = plan_result.get('summary') or {}
            tickets = plan_result.get('tickets') or []
            warnings = plan_result.get('warnings') or []
            horse_scores = plan_result.get('horse_scores') or []

            if warnings:
                with st.expander("⚠️ 生成時の警告", expanded=False):
                    for msg in warnings:
                        st.warning(msg)

            if summary:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("総点数", f"{int(summary.get('総点数', 0))}点")
                m2.metric("総投資額", f"{int(summary.get('総投資額', 0)):,}円")
                m3.metric("推定回収指数", f"{float(summary.get('推定回収指数', 0)):.3f}")
                m4.metric("推定的中指数", f"{float(summary.get('推定的中指数', 0)):.3f}")

                st.caption(f"軸馬: {summary.get('軸馬', '自動')} / 方針スライダー: {summary.get('方針スライダー', 50)}")

                type_rows = []
                count_map = summary.get("券種別点数") or {}
                amount_map = summary.get("券種別投資額") or {}
                for bt in BET_TYPES_ALL:
                    if bt in count_map or bt in amount_map:
                        type_rows.append({
                            "券種": bt,
                            "点数": int(count_map.get(bt, 0)),
                            "投資額": int(amount_map.get(bt, 0)),
                        })
                if type_rows:
                    st.dataframe(pd.DataFrame(type_rows), use_container_width=True, hide_index=True)

            if tickets:
                ticket_df = pd.DataFrame(tickets)
                display_cols = ["券種", "買い目", "オッズ", "配分額", "hit_score", "roi_score", "final_score", "推定払戻期待"]
                display_cols = [c for c in display_cols if c in ticket_df.columns]
                st.markdown("#### 🎫 推奨買い目")
                st.dataframe(
                    ticket_df[display_cols],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "券種": st.column_config.TextColumn("券種", width="small"),
                        "買い目": st.column_config.TextColumn("買い目", width="large"),
                        "オッズ": st.column_config.NumberColumn("オッズ", format="%.2f"),
                        "配分額": st.column_config.NumberColumn("配分額", format="%d"),
                        "hit_score": st.column_config.NumberColumn("hit_score", format="%.4f"),
                        "roi_score": st.column_config.NumberColumn("roi_score", format="%.4f"),
                        "final_score": st.column_config.NumberColumn("final_score", format="%.4f"),
                        "推定払戻期待": st.column_config.NumberColumn("推定払戻期待", format="%.1f"),
                    },
                )
            else:
                st.info("「買い目プランを生成」を押すと、ここに提案が表示されます。")

            if horse_scores:
                with st.expander("🐴 馬スコア内訳", expanded=False):
                    hs_df = pd.DataFrame(horse_scores)
                    hs_cols = [
                        "horse", "umaban", "prob", "score", "plus_count", "minus_count",
                        "source_count", "training_plus", "training_minus", "yt_bonus", "odds",
                    ]
                    hs_cols = [c for c in hs_cols if c in hs_df.columns]
                    st.dataframe(hs_df[hs_cols], use_container_width=True, hide_index=True)

    # ── サイドバー: Markdownレポートダウンロードボタン ──
    # display_main_content(df) 内に置くことで df ロード後に確実に実行される
    with st.sidebar:
        st.markdown("---")
        _report_md = generate_markdown_report(df_active_enriched)
        _safe_name = get_race_display_name().replace(' ', '_').replace('/', '-')
        st.download_button(
            label="📄 Markdownレポート出力",
            data=_report_md,
            file_name=f"{_safe_name}_予想レポート.md",
            mime="text/markdown",
            use_container_width=True,
        )

# ====================
# メイン処理
# ====================

def _on_race_change():
    """レース切替時にセッションステートをクリアする"""
    for key in RACE_SESSION_KEYS:
        st.session_state.pop(key, None)
    # Race-scoped widget keys (e.g. combined_keyword::<race_key>) も掃除する
    for prefix in (
        "combined_keyword::",
        "yt_detail_keyword::",
        "bet_budget::",
        "bet_slider::",
        "bet_types::",
        "bet_anchor::",
        "bet_refresh_odds::",
        "bet_generate::",
    ):
        for key in list(st.session_state.keys()):
            if str(key).startswith(prefix):
                st.session_state.pop(key, None)
    get_all_horse_names.clear()
    load_race_data.clear()


def _display_race_selector():
    """サイドバーにレースセレクターを表示し、選択されたレースをセッションに保存する"""
    st.sidebar.subheader("🏇 レース選択")
    # 起動時に前回レースキーを1回だけ復元
    if '_last_loaded_race_key' not in st.session_state:
        st.session_state['_last_loaded_race_key'] = _load_last_selected_race_key()

    if st.sidebar.button("🔄 重賞一覧を再取得", key="refresh_upcoming_races"):
        clear_fetch_graded_races_cache()
        st.rerun()

    with st.sidebar.expander("📅 重賞一覧の取得期間", expanded=False):
        days_back = int(
            st.number_input(
                "過去日数",
                min_value=0,
                max_value=30,
                value=7,
                step=1,
                key="upcoming_days_back",
                help="今日から何日前までの重賞を候補に含めるか",
            )
        )
        days_ahead = int(
            st.number_input(
                "先日数",
                min_value=1,
                max_value=180,
                value=14,
                step=1,
                key="upcoming_days_ahead",
                help="今日から何日先までの重賞を候補に含めるか",
            )
        )

    # 重賞一覧を取得
    with st.spinner("重賞一覧を取得中..."):
        start_date = date.today() - timedelta(days=days_back)
        races = get_upcoming_races(
            months_ahead=2,
            from_date=start_date,
            days_ahead=days_back + days_ahead,
        )

    if not races:
        st.sidebar.warning("重賞一覧を取得できませんでした")
        # 手動入力フォールバック
        manual_id = st.sidebar.text_input("レースIDを手動入力", placeholder="例: 202605010811")
        manual_name = st.sidebar.text_input("レース名", placeholder="例: フェブラリーステークス")
        if manual_id and manual_name and st.sidebar.button("このレースを使用"):
            from datetime import date as _date
            today = _date.today()
            ensure_data_dir()
            race = RaceInfo(
                race_name=manual_name,
                grade="G1",
                date_str=format_date_with_weekday(today),
                date=today,
                venue="",
                distance="",
                surface="",
                race_id=manual_id,
                race_key=f"manual_{manual_id}",
                csv_file=f"data/race_{manual_id}.csv",
            )
            _on_race_change()
            st.session_state['selected_race'] = race
            st.session_state['_pending_race_key'] = race.race_key
            st.session_state['_prev_race_key'] = race.race_key
            _save_last_selected_race_key(race.race_key)
            st.rerun()
        return

    # セレクトボックスで表示（選択だけでは読み込まない）
    labels = [r.display_label for r in races]
    loaded_race = get_race_config()
    pending_key = st.session_state.get('_pending_race_key')
    last_key = st.session_state.get('_last_loaded_race_key')
    target_key = pending_key or (loaded_race.race_key if loaded_race else None) or (last_key or None)
    default_idx = 0
    if target_key:
        for i, r in enumerate(races):
            if r.race_key == target_key:
                default_idx = i
                break

    selected_idx = st.sidebar.selectbox(
        "直近の重賞レース",
        range(len(labels)),
        format_func=lambda i: labels[i],
        index=default_idx,
        key="race_selector",
    )

    pending_race = races[selected_idx]
    st.session_state['_pending_race_key'] = pending_race.race_key

    if loaded_race and loaded_race.race_key == pending_race.race_key:
        st.sidebar.caption(f"現在読み込み中: {pending_race.display_name}")
    else:
        st.sidebar.caption(f"選択中: {pending_race.display_name}")

    # 起動直後のみ、前回読み込んだレースを自動ロード
    if (
        not loaded_race
        and last_key
        and pending_race.race_key == last_key
        and not st.session_state.get('_initial_race_autoloaded', False)
    ):
        st.session_state['_initial_race_autoloaded'] = True
        # 前回レースが race_id 未解決だった場合、起動時に1回だけ解決を試みる。
        if not pending_race.race_id:
            resolved_id = resolve_race_id(pending_race)
            if resolved_id:
                pending_race.race_id = resolved_id
                pending_race.csv_file = f"data/race_{resolved_id}.csv"
        st.session_state['selected_race'] = pending_race
        st.session_state['_prev_race_key'] = pending_race.race_key
        st.session_state['_pending_race_key'] = pending_race.race_key
        _save_last_selected_race_key(pending_race.race_key)
        st.rerun()

    if st.sidebar.button("✅ このレースを読み込む", key="load_selected_race"):
        prev_loaded = get_race_config()
        if not prev_loaded or prev_loaded.race_key != pending_race.race_key:
            _on_race_change()

        # race_id は読み込みボタン押下時にのみ解決する
        if not pending_race.race_id:
            with st.spinner(f"🔍 {pending_race.race_name} のレースIDを取得中..."):
                resolved_id = resolve_race_id(pending_race)
            if resolved_id:
                pending_race.race_id = resolved_id
                pending_race.csv_file = f"data/race_{resolved_id}.csv"

        st.session_state['selected_race'] = pending_race
        st.session_state['_prev_race_key'] = pending_race.race_key
        st.session_state['_last_loaded_race_key'] = pending_race.race_key
        _save_last_selected_race_key(pending_race.race_key)
        st.rerun()

    # 手動入力フォールバック（重賞一覧に無いレース用）
    with st.sidebar.expander("📝 レースIDを手動入力"):
        manual_id = st.text_input("レースID", placeholder="例: 202605010811", key="manual_race_id")
        manual_name = st.text_input("レース名", placeholder="例: 高松宮記念", key="manual_race_name")
        if manual_id and manual_name and st.button("このレースを使用", key="use_manual_race"):
            from datetime import date as _date
            today = _date.today()
            ensure_data_dir()
            race = RaceInfo(
                race_name=manual_name,
                grade="G1",
                date_str=format_date_with_weekday(today),
                date=today,
                venue="",
                distance="",
                surface="",
                race_id=manual_id,
                race_key=f"manual_{manual_id}",
                csv_file=f"data/race_{manual_id}.csv",
            )
            _on_race_change()
            st.session_state['selected_race'] = race
            st.session_state['_pending_race_key'] = race.race_key
            st.session_state['_prev_race_key'] = race.race_key
            st.session_state['_last_loaded_race_key'] = race.race_key
            _save_last_selected_race_key(race.race_key)
            st.rerun()


def main():
    """
    アプリケーションのメイン処理
    """
    # パスワード認証（未認証の場合はログイン画面を表示して停止）
    if not check_password():
        st.stop()
        return

    # レースセレクターを表示
    _display_race_selector()

    r = get_race_config()

    # レース未選択の場合
    if not r:
        st.info("👈 サイドバーでレースを選択し「✅ このレースを読み込む」を押してください")
        st.stop()
        return

    # race_id 未解決の場合（出馬表未発表）
    if not r.race_id:
        display_sidebar()
        st.warning(f"📋 {r.race_name} の出馬表はまだ公開されていません。レース日が近づいたら再度お試しください。")
        if st.button("🔄 レースIDを再取得", key="retry_resolve_race_id_btn"):
            with st.spinner(f"🔍 {r.race_name} のレースIDを再取得中..."):
                # 直前失敗がキャッシュされている場合も再試行できるようクリア
                clear_resolve_race_id_cache()
                resolved_id = resolve_race_id(r)

            if resolved_id:
                r.race_id = resolved_id
                r.csv_file = f"data/race_{resolved_id}.csv"
                st.session_state['selected_race'] = r
                st.success("✅ レースIDを取得しました。画面を更新します。")
                st.rerun()
            else:
                st.error("❌ まだレースIDを取得できませんでした。時間をおいて再試行してください。")
        st.stop()
        return

    # CSV自動取得（初回のみ）
    csv_path = get_csv_path()
    ensure_data_dir()
    if csv_path and not os.path.exists(csv_path):
        try:
            with st.spinner(f"📥 {r.race_name} の出馬表を取得中..."):
                fetch_race_csv(r.race_id, csv_path)
        except RuntimeError as e:
            st.error(f"❌ 出馬表の取得に失敗しました: {e}")
            st.stop()
            return

    # キャッシュから前回の検索結果を復元（初回ロード時のみ・web_rawをセンチネルとして使用）
    if 'web_raw' not in st.session_state:
        load_race_cache(r.race_key)

    # レース特徴を自動初期化（初回のみ）
    if 'race_characteristics' not in st.session_state:
        st.session_state['race_characteristics'] = get_minimal_race_characteristics()
    if 'race_characteristics_enriched' not in st.session_state:
        st.session_state['race_characteristics_enriched'] = _has_meaningful_race_characteristics(
            st.session_state.get('race_characteristics')
        )

    # 既存キャッシュがGemini由来でも、Umanityで解決可能な重賞は主ソースへ置き換える
    current_rc = st.session_state.get('race_characteristics') or {}
    current_source = _to_text(current_rc.get('情報ソース'))
    if st.session_state.get('race_characteristics_enriched') and "ウマニティ" not in current_source:
        try:
            if resolve_umanity_race_info(r.race_name):
                st.session_state['race_characteristics_enriched'] = False
        except Exception:
            pass

    # 取得失敗時も一定間隔で自動再試行（初回失敗で固着させない）
    if not st.session_state.get('race_characteristics_enriched'):
        now_ts = time.time()
        last_attempt = float(st.session_state.get('race_characteristics_last_attempt') or 0.0)
        if now_ts - last_attempt >= 20.0:
            st.session_state['race_characteristics_last_attempt'] = now_ts
            try:
                with st.spinner("📡 レース特徴を取得中（Umanity優先 / Geminiフォールバック）..."):
                    web_info = get_race_characteristics_primary(
                        race_name=r.race_name, grade=r.grade, venue=r.venue,
                        distance=r.distance, surface=r.surface, date_str=r.date_str,
                    )
                if web_info:
                    merged_rc = dict(st.session_state.get('race_characteristics') or {})
                    for k, v in (web_info or {}).items():
                        if _to_text(v):
                            merged_rc[k] = v
                    st.session_state['race_characteristics'] = merged_rc
                    st.session_state['race_characteristics_enriched'] = _has_meaningful_race_characteristics(merged_rc)
                    st.session_state.pop('race_characteristics_last_error', None)
                    if st.session_state['race_characteristics_enriched']:
                        save_race_cache(r.race_key)
            except Exception as e:
                st.session_state['race_characteristics_last_error'] = f"{type(e).__name__}: {str(e)[:160]}"

    # 枠番・馬番・オッズを初回表示時に自動取得（レースごとに1回）
    if 'gates_saved' not in st.session_state:
        def _is_missing_gate_value(v) -> bool:
            text = str(v).strip() if v is not None else ""
            return (text == "") or (text.lower() in {"nan", "none"}) or (text == "不明")

        def _extract_numeric_odds_map(df_: pd.DataFrame) -> dict[str, str]:
            odds_map = {}
            if 'オッズ' not in df_.columns or '馬名' not in df_.columns:
                return odds_map
            for _, row in df_.iterrows():
                horse = str(row.get('馬名', '')).strip()
                odds = str(row.get('オッズ', '')).strip()
                if horse and re.match(r'^\d+(\.\d+)?$', odds):
                    odds_map[horse] = odds
            return odds_map

        try:
            csv_df = pd.read_csv(csv_path, encoding='utf-8-sig')
            cached_latest_odds = st.session_state.get('latest_odds', {}) or {}
            csv_numeric_odds = _extract_numeric_odds_map(csv_df)

            with st.spinner("🏇 枠順・オッズを自動取得中...（初回のみ）"):
                gate_data, gate_error = fetch_odds_and_gates(require_odds=False)

            csv_updated = False
            latest_numeric_odds: dict[str, str] = {}

            if gate_data:
                for idx, row in csv_df.iterrows():
                    horse = str(row.get('馬名', '')).strip()
                    if not horse or horse not in gate_data:
                        continue
                    fetched = gate_data[horse]

                    waku = str(fetched.get('枠番', '')).strip()
                    umaban = str(fetched.get('馬番', '')).strip()
                    odds = str(fetched.get('オッズ', '')).strip()

                    if '枠番' in csv_df.columns and _is_missing_gate_value(row.get('枠番')) and waku:
                        csv_df.at[idx, '枠番'] = waku
                        csv_updated = True
                    if '馬番' in csv_df.columns and _is_missing_gate_value(row.get('馬番')) and umaban:
                        csv_df.at[idx, '馬番'] = umaban
                        csv_updated = True
                    if 'オッズ' in csv_df.columns and re.match(r'^\d+(\.\d+)?$', odds):
                        latest_numeric_odds[horse] = odds
                        if str(row.get('オッズ', '')).strip() != odds:
                            csv_df.at[idx, 'オッズ'] = odds
                            csv_updated = True

                if csv_updated:
                    csv_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
                    load_race_data.clear()

            # オッズは「最新取得 > キャッシュ > CSV既存」の優先順で復元
            if latest_numeric_odds:
                st.session_state['latest_odds'] = latest_numeric_odds
                st.session_state.pop('latest_odds_error', None)
            elif cached_latest_odds:
                st.session_state['latest_odds'] = cached_latest_odds
                if gate_error:
                    st.session_state['latest_odds_error'] = gate_error
            elif csv_numeric_odds:
                st.session_state['latest_odds'] = csv_numeric_odds
                st.session_state.pop('latest_odds_error', None)
            elif gate_error:
                st.session_state['latest_odds_error'] = gate_error

            if gate_data and csv_updated:
                st.toast(f"✅ {len(gate_data)}頭の枠順/馬番/オッズを更新しました", icon="🏇")

            # 自動取得結果（特に latest_odds）を次回用に永続化
            if gate_data or st.session_state.get('latest_odds'):
                save_race_cache(r.race_key)

        except Exception:
            pass
        st.session_state['gates_saved'] = True

    # サイドバーを表示
    display_sidebar()

    # データを読み込み（ファイル更新時刻をキャッシュキーに含めて常に最新CSVを反映）
    _csv_mtime = os.path.getmtime(csv_path) if os.path.exists(csv_path) else 0
    df = load_race_data(csv_path, mtime=_csv_mtime)

    # メインコンテンツを表示
    if df is not None:
        display_main_content(df)
    else:
        st.error("### ⚠️ データを読み込めませんでした")
        st.info(
            f"""
            **次の手順を試してください:**

            1. レース選択が正しいか確認
            2. ページをリロード（F5キー）で出馬表を再取得
            """
        )

        # サンプルデータ表示ボタン
        if st.button("📝 サンプルデータで試す"):
            sample_data = {
                '枠番': ['1', '2', '3', '4', '5'],
                '馬番': ['1', '2', '3', '4', '5'],
                '馬名': ['サンプル馬A', 'サンプル馬B', 'サンプル馬C', 'サンプル馬D', 'サンプル馬E'],
                '性齢': ['牡5', '牡4', '牡5', '牡6', '牝5'],
                '斤量': ['57.0', '57.0', '57.0', '57.0', '55.0'],
                '騎手': ['騎手A', '騎手B', '騎手C', '騎手D', '騎手E'],
                '調教師': ['調教師A', '調教師B', '調教師C', '調教師D', '調教師E'],
                'オッズ': ['3.5', '4.2', '5.8', '12.0', '15.5']
            }
            sample_df = pd.DataFrame(sample_data)
            st.success("✅ サンプルデータを読み込みました")
            display_main_content(sample_df)

# ====================
# アプリケーション起動
# ====================

if __name__ == "__main__":
    # このファイルが直接実行された場合のみ、main関数を実行
    main()

