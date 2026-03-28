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
from datetime import datetime, date
import re
import json
import time  # 待機時間のために追加
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
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

# APIキーを環境変数から取得（.env ファイル または システム環境変数）
# キーは .env ファイルに記載。絶対にコードに直書きしないこと。
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
try:
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "") or st.secrets.get("TAVILY_API_KEY", "")
except Exception:
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

WEB_SEARCH_ALLOWLIST = [
    "netkeiba.com",
    "keibalab.jp",
    "umanity.jp",
    "spaia-keiba.com",
    "sports.yahoo.co.jp",
]
MAX_ANALYZE_ARTICLES_PER_QUERY = 3

# レース切替時にクリアするセッションステートキー
RACE_SESSION_KEYS = [
    'horse_df', 'youtube_videos', 'youtube_raw', 'youtube_summary_df',
    'web_articles', 'web_raw', 'race_characteristics', 'gates_saved',
    'yt_detail_analysis', 'doc_horse_raw', 'win_rates', 'latest_odds_error',
    'latest_odds', 'combined_keyword', 'yt_detail_keyword',
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


def get_minimal_race_characteristics() -> dict:
    """Gemini失敗時のフォールバック: RaceInfoから最小限のレース特徴を組み立て"""
    r = get_race_config()
    if not r:
        return {}
    return {
        "コース特徴": f"{r.venue}競馬場 {r.surface}{r.distance}",
        "注目ポイント": f"{r.grade}レース",
    }


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


def filter_relevant_videos(videos):
    """
    予想に関係する動画を優先し、公式映像・レース中継系を除外する。
    スコア順で並べ替えた結果を返し、0件の場合のみ緩い条件でフォールバックする。
    """
    if not videos:
        return []

    include_keywords = [
        "予想", "本命", "対抗", "穴", "買い目", "印", "展開", "見解", "考察", "馬券"
    ]
    # レースメタデータから動的にキーワード生成
    r = get_race_config()
    if r:
        race_keywords = [
            r.race_name, r.race_name[:4] if len(r.race_name) > 4 else r.race_name,
            f"{r.venue}{r.distance}", f"{r.surface}{r.distance}",
        ]
    else:
        race_keywords = ["競馬", "予想"]
    exclude_keywords = [
        "jra公式", "公式", "ライブ", "生中継", "レース映像", "レース動画",
        "ハイライト", "cm", "pv", "出走馬紹介", "パドック", "払戻", "結果速報"
    ]
    exclude_channel_tokens = [
        "jra", "日本中央競馬会", "netkeiba", "グリーンチャンネル", "tbs", "フジ"
    ]

    scored = []
    for v in videos:
        title = (v.get('title') or '').lower()
        desc = (v.get('description') or '')[:300].lower()
        channel = (v.get('channel_title') or '').lower()
        text = f"{title} {desc}"

        # レース名すらない動画は除外
        if not any(k in text for k in [rk.lower() for rk in race_keywords]):
            continue

        # 公式/メディア系チャンネルは除外
        if any(token in channel for token in [t.lower() for t in exclude_channel_tokens]):
            continue

        score = 0
        for k in include_keywords:
            if k.lower() in text:
                score += 2
        for k in race_keywords:
            if k.lower() in text:
                score += 1
        for k in exclude_keywords:
            if k.lower() in text:
                score -= 3

        if score >= 2:
            scored.append((score, v))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return [v for _, v in scored]

    # フォールバック: 条件を緩めてレース関連だけ返す
    relaxed = [
        v for v in videos
        if any(k in ((v.get('title', '') + ' ' + (v.get('description', '') or '')[:300]).lower())
               for k in [rk.lower() for rk in race_keywords])
    ]
    return relaxed if relaxed else videos


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


def analyze_video_with_gemini(video):
    """
    Gemini APIを使って動画のタイトルと概要欄を解析し、馬名とプラス/マイナス情報を抽出する関数

    引数:
        video (dict): 動画情報（title, description, video_urlを含む）

    戻り値:
        list: 抽出された情報のリスト（各要素は馬名、プラス情報、マイナス情報を含む辞書）
    """
    # APIキーが設定されていない場合
    if GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE" or not GEMINI_API_KEY:
        return []

    try:
        # 字幕を取得して使用（概要欄よりも豊富な情報が含まれる）
        transcript = fetch_video_transcript(video['video_id'])
        if transcript:
            content_label = "字幕（音声内容）"
            content = transcript
        else:
            content_label = "概要欄"
            content = video.get('description', '') or ''

        # 新しいSDK（google-genai）でクライアントを作成
        # 古いSDK（google-generativeai）とは書き方が異なります
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        # Gemini に送るプロンプトを作成（前走成績・調教・調子を具体的に抽出）
        prompt = f"""
あなたは競馬予想の専門家です。以下のYouTube動画のタイトルと{content_label}を読み、各馬の詳細な評価情報を抽出してください。

# 動画タイトル
{video['title']}

# {content_label}
{content}

# 注目すべき出走馬（これら以外の馬名が登場しても抽出してください）
{chr(10).join(['- ' + name for name in get_all_horse_names()[:10]])}

# 抽出してほしい情報（各馬について）
プラス情報として以下を重点的に探してください：
- 前走・近走の成績（例：「前走G2優勝」「3連勝中」「重賞実績あり」）
- 調教・追切の様子（例：「最終追切で好時計」「動き抜群」「好調仕上がり」）
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
    "プラス情報": "前走成績・調教・調子・適性など具体的な好材料を2～3文で詳しく記載",
    "マイナス情報": "具体的な懸念点・不安材料を記載（なければ「特になし」）"
  }}
]
```

# 注意事項
- 概要欄に情報がなくても、タイトルから推測して記載してよい
- 馬名が全く見当たらない場合のみ「全体的な予想」として1件だけ出力
- プラス情報は「特になし」にせず、必ず何か記載すること
- JSONのみ出力し、前後に説明文を付けないこと
"""

        # Gemini 2.0 Flash を使用（従量課金・最新モデル）
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )

        # レスポンスからテキストを取得
        response_text = response.text

        # レスポンスが空の場合のチェック
        if not response_text:
            return []

        # JSONを頑健にパース
        analysis_results = _parse_gemini_json_response(response_text, expected="list")

        # 動画URLを各結果に追加
        for result in analysis_results:
            result['video_url'] = video['video_url']
            result['video_title'] = video['title']

        return analysis_results

    except (json.JSONDecodeError, ValueError):
        # JSON解析失敗は静かに無視（概要欄が短すぎる動画など）
        return []
    except Exception as e:
        error_msg = str(e)
        # 429 レート制限は呼び出し元でリトライするため、ここでは例外をそのまま投げる
        if _is_transient_gemini_error(error_msg):
            raise  # create_summary_dataframe 側でキャッチしてリトライ
        # それ以外の予期しないエラーのみ表示
        st.warning(f"⚠️ 動画の解析をスキップしました: {type(e).__name__}")
        return []


def _analyze_one_video_worker(video, prompt_template):
    """
    1動画を解析するワーカー関数。ThreadPoolExecutorから呼ばれる。
    Streamlit APIは呼ばない（スレッドアンセーフのため）。
    """
    client = google_genai.Client(api_key=GEMINI_API_KEY)
    for retry in range(3):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
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
                    time.sleep(60 * (retry + 1))  # 60秒、120秒と待機
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
プラス情報: 前走・近走の成績、調教・追切の様子、体調・調子、コース・距離適性、騎手・厩舎の強み
マイナス情報: 前走・近走での敗因、調教不安、コース・距離の不安、枠順・展開の不安

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
        "unavailable",
        "high demand",
        "deadline exceeded",
        "timed out",
        "internal",
    )
    return any(token in msg for token in transient_tokens)


def _select_articles_for_analysis(
    articles,
    race_name: str,
    horse_names: list[str],
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

    scored = []
    for article in articles:
        title = str(article.get("title", "") or "")
        snippet = str(article.get("snippet", "") or "")
        url = str(article.get("url", "") or "")
        text = f"{title} {snippet}"
        parsed = urlparse(url) if url else None
        path = (parsed.path or "/") if parsed else "/"

        score = 0
        score += sum(1 for token in race_tokens if token in text) * 3
        score += sum(1 for horse in horse_tokens if horse in text) * 2
        if "/db/race/" in url or "/race/" in url:
            score += 2
        if path in ("", "/"):
            score -= 4
        if "日本最大の競馬情報サービス" in title:
            score -= 3
        if len(snippet) < 120:
            score -= 1

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
        return []

    title = _to_text(article_info.get('title', '')) if isinstance(article_info, dict) else ""
    snippet = _to_text(article_info.get('snippet', '')) if isinstance(article_info, dict) else ""
    source_url = _to_text(article_info.get('url', '')) if isinstance(article_info, dict) else ""
    source_title = title or "Web記事"
    if not title and not snippet:
        return []

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
    "プラス情報": "具体的な好材料を2～3文で詳しく記載",
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
            return []

        analysis_results = _parse_gemini_json_response(response_text, expected="list")

        for result in analysis_results:
            result['source_url'] = source_url
            result['source_title'] = source_title
            result['source_type'] = 'web'

        return analysis_results

    except (json.JSONDecodeError, ValueError):
        return []
    except Exception as e:
        error_msg = str(e)
        if _is_transient_gemini_error(error_msg):
            raise
        st.warning(f"⚠️ Web記事の解析をスキップしました: {type(e).__name__} ({error_msg[:120]})")
        return []


def aggregate_horse_analysis(youtube_results, web_results, doc_results=None):
    """
    YouTube・Web記事・ドキュメントの分析結果を馬名ごとに集約するDataFrameを作成する

    引数:
        youtube_results (list): YouTube分析の生データリスト
        web_results (list): Web記事分析の生データリスト
        doc_results (list): ドキュメント分析の生データリスト（省略可）

    戻り値:
        DataFrame: 馬名ごとに集約されたメリット・デメリット情報
    """
    if doc_results is None:
        doc_results = []
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


def fetch_and_analyze_web_articles(queries, total_article_limit=20):
    """
    複数クエリでWeb記事を検索・解析するオーケストレーター関数
    全出走馬を4頭ずつグループ化した馬別クエリを自動追加し、全頭分の情報を収集する

    引数:
        queries (list): 検索クエリのリスト
        total_article_limit (int): 最終的に取得するWeb記事の上限件数

    戻り値:
        tuple: (articles_metadata, raw_analysis_results)
    """
    # 全馬名を4頭ずつグループ化した馬別クエリを自動追加
    race_name = get_race_display_name()
    all_horse_names = get_all_horse_names()
    batch_size = 4
    for i in range(0, len(all_horse_names), batch_size):
        batch = all_horse_names[i:i + batch_size]
        horses_str = " ".join(batch)
        queries = list(queries) + [f"{race_name} {horses_str} 予想 評価 分析"]

    all_articles = []
    all_web_raw = []

    progress_bar = st.progress(0)
    status_text = st.empty()
    total_queries = len(queries)
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
                        include_domains=WEB_SEARCH_ALLOWLIST
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
        articles = articles[:remaining]
        unique_articles = _select_articles_for_analysis(
            articles,
            race_name=race_name,
            horse_names=all_horse_names,
            max_items=min(MAX_ANALYZE_ARTICLES_PER_QUERY, remaining),
        )
        all_articles.extend(articles)
        progress_bar.progress((q_idx + 0.5) / total_queries)

        for a_idx, article in enumerate(unique_articles):
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
            all_web_raw.extend(results)

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
        return {}
    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)
        grounding_tool = genai_types.Tool(google_search=genai_types.GoogleSearch())
        config = genai_types.GenerateContentConfig(tools=[grounding_tool])

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
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=config,
        )

        response_text = response.text or ""
        return _parse_gemini_json_response(response_text, expected="dict")

    except (json.JSONDecodeError, ValueError, Exception) as e:
        error_msg = str(e)
        if _is_transient_gemini_error(error_msg):
            raise
        st.warning(f"⚠️ レース特徴の取得に失敗しました: {type(e).__name__} ({error_msg[:120]})")
        return {}


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

    rows_html = []
    for _, row in df.iterrows():
        waku  = safe(row.get('枠番', ''), as_int=True)
        umaban = safe(row.get('馬番', ''), as_int=True)
        name  = safe(row.get('馬名', ''))
        seage = safe(row.get('性齢', ''))
        kin   = safe(row.get('斤量', ''))
        jockey = safe(row.get('騎手', ''))
        trainer = safe(row.get('調教師', ''))
        odds  = safe(row.get('オッズ', ''))

        waku_cls = WAKU_COLORS.get(waku, 'waku-x')
        waku_cell = f'<span class="waku-badge {waku_cls}">{waku if waku != "-" else "?"}</span>'
        odds_cell = f'<span class="odds-badge {odds_class(odds)}">{odds if odds != "-" else "---"}</span>'

        rows_html.append(f"""
<tr>
  <td>{waku_cell}</td>
  <td class="umaban-cell">{umaban}</td>
  <td class="horse-name-cell">{name}</td>
  <td>{seage}</td>
  <td>{kin}</td>
  <td>{jockey}</td>
  <td>{trainer}</td>
  <td>{odds_cell}</td>
</tr>""")

    table = f"""
<div class="horse-table-wrap">
<table class="horse-table">
<thead>
<tr>
  <th>枠</th><th>番</th><th>馬名</th><th>性齢</th>
  <th>斤量</th><th>騎手</th><th>調教師</th><th>単勝オッズ</th>
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
    active_horse_names = set(df_active['馬名'].astype(str).tolist()) if (
        df_active is not None and not df_active.empty and '馬名' in df_active.columns
    ) else set()
    race_widget_scope = r.race_key if r else "default"

    # タブを作成
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 出馬表",
        "📥 情報入力",
        "🏇 総合予想（馬別）",
        "🏟️ レース特徴・傾向",
        "YOUTUBEから情報入手"
    ])

    # ===== タブ1: 出馬表 =====
    with tab1:
        st.markdown("### 📊 出走予定馬一覧")

        # データが空でないか確認
        if df_active is not None and not df_active.empty:
            # 馬番（CSV保存済み）でソート → 枠順と一致
            df_display = df_active.copy()
            if '馬番' in df_display.columns:
                df_display['_馬番_num'] = pd.to_numeric(df_display['馬番'], errors='coerce')
                df_display = df_display.sort_values('_馬番_num', na_position='last')
                df_display = df_display.drop(columns=['_馬番_num']).reset_index(drop=True)

            # セッション内のオッズを反映（ボタン取得後）
            if 'latest_odds' in st.session_state and 'オッズ' in df_display.columns:
                for idx, row in df_display.iterrows():
                    horse = str(row.get('馬名', ''))
                    if horse in st.session_state['latest_odds']:
                        df_display.at[idx, 'オッズ'] = st.session_state['latest_odds'][horse]

            # 出馬表を HTML カードテーブルで表示
            st.markdown(render_horse_table_html(df_display), unsafe_allow_html=True)

            # オッズ取得ボタン
            st.markdown("---")
            col_btn, col_info = st.columns([1, 4])
            with col_btn:
                if st.button("🔄 最新オッズを取得", key="fetch_odds_btn"):
                    with st.spinner("netkeiba からオッズを取得中..."):
                        odds_data, odds_error = fetch_odds_and_gates()
                    if odds_data:
                        st.session_state['latest_odds'] = {
                            h: v['オッズ'] for h, v in odds_data.items()
                        }
                        st.session_state.pop('latest_odds_error', None)
                        st.rerun()
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
            web_articles, web_raw = fetch_and_analyze_web_articles(
                web_queries, total_article_limit=int(combined_max_web)
            )
            st.metric("Web記事", f"{len(web_articles)}件取得")

            # Phase 2: 馬別集計（ドキュメントから抽出した馬別情報も統合）
            doc_horse_raw = st.session_state.get('doc_horse_raw', [])
            youtube_raw = []
            horse_df = aggregate_horse_analysis(youtube_raw, web_raw, doc_horse_raw)
            if active_horse_names and not horse_df.empty and '馬名' in horse_df.columns:
                horse_df = horse_df[horse_df['馬名'].astype(str).isin(active_horse_names)].reset_index(drop=True)

            # セッションステートに保存
            st.session_state['horse_df'] = horse_df
            st.session_state['youtube_videos'] = []
            st.session_state['youtube_raw'] = youtube_raw
            st.session_state['web_raw'] = web_raw
            st.session_state['youtube_summary_df'] = pd.DataFrame()
            st.session_state.pop('yt_detail_analysis', None)
            st.session_state['web_articles'] = web_articles
            st.success("✅ 検索・解析が完了しました！「総合予想（馬別）」タブで結果を確認してください。")

        st.markdown("---")

        # ===== Section 2: ドキュメントアップロード =====
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
                        st.success(f"✅ {uploaded_file.name} からレース特徴を抽出しました。「レース特徴・傾向」タブで確認できます。")

                if analyze_doc_horses:
                    with st.spinner("馬別情報を抽出中..."):
                        new_doc_raw = analyze_document_for_horses(doc_text, uploaded_file.name)
                    st.session_state['doc_horse_raw'] = st.session_state.get('doc_horse_raw', []) + new_doc_raw
                    # ドキュメント馬別情報をhorse_dfに即時反映（YouTube/Web結果と再集計）
                    updated_horse_df = aggregate_horse_analysis(
                        st.session_state.get('youtube_raw', []),
                        st.session_state.get('web_raw', []),
                        st.session_state.get('doc_horse_raw', [])
                    )
                    if active_horse_names and not updated_horse_df.empty and '馬名' in updated_horse_df.columns:
                        updated_horse_df = updated_horse_df[
                            updated_horse_df['馬名'].astype(str).isin(active_horse_names)
                        ].reset_index(drop=True)
                    st.session_state['horse_df'] = updated_horse_df
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
                    st.rerun()

        st.markdown("---")

        # ===== Section 3: レース特徴リセット =====
        st.markdown("#### 🏟️ レース特徴・傾向")
        st.info("💡 レース特徴はアプリ起動時に自動表示されます。「レース特徴・傾向」タブで確認してください。")
        if st.button("🔄 レース特徴をWeb再取得", key="btn_race_refresh"):
            st.session_state.pop('race_characteristics', None)
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
                st.write(race_info['過去の傾向'])

            if race_info.get('騎手厩舎傾向'):
                with st.expander("👤 騎手・厩舎の傾向"):
                    st.write(race_info['騎手厩舎傾向'])

            if race_info.get('注目ポイント'):
                st.markdown("#### 💡 今年の注目ポイント")
                st.warning(race_info['注目ポイント'])

        else:
            st.info("👆 「情報入力」タブで「🔍 Geminiでレース特徴を分析」を実行するか、ドキュメントをアップロードしてください")

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
                                analysis_results = analyze_video_with_gemini(video)
                            except Exception as e:
                                st.error(f"❌ 解析に失敗しました: {type(e).__name__}")
                                analysis_results = []
                        yt_map = st.session_state.get('yt_detail_analysis', {})
                        yt_map[video['video_id']] = analysis_results
                        st.session_state['yt_detail_analysis'] = yt_map
                        if analysis_results:
                            st.success(f"✅ {len(analysis_results)}件の馬情報を抽出しました")
                        else:
                            st.warning("⚠️ 抽出結果がありませんでした")
                    st.link_button("▶️ YouTubeで視聴", video['video_url'], use_container_width=True)

                with col_video2:
                    st.caption(f"📢 {video['channel_title']}")
                    published_date = video['published_at'][:10]
                    st.caption(f"📅 公開日: {published_date}")
                    with st.expander("📝 概要欄を表示"):
                        st.write(video['description'] if video['description'] else "（概要なし）")

                st.markdown("#### 🔍 Gemini 馬別分析（字幕・概要欄から抽出）")
                yt_map = st.session_state.get('yt_detail_analysis', {})
                analysis_results = yt_map.get(video['video_id'], [])
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

# ====================
# メイン処理
# ====================

def _on_race_change():
    """レース切替時にセッションステートをクリアする"""
    for key in RACE_SESSION_KEYS:
        st.session_state.pop(key, None)
    # Race-scoped widget keys (e.g. combined_keyword::<race_key>) も掃除する
    for prefix in ("combined_keyword::", "yt_detail_keyword::"):
        for key in list(st.session_state.keys()):
            if str(key).startswith(prefix):
                st.session_state.pop(key, None)
    get_all_horse_names.clear()
    load_race_data.clear()


def _display_race_selector():
    """サイドバーにレースセレクターを表示し、選択されたレースをセッションに保存する"""
    st.sidebar.subheader("🏇 レース選択")
    if st.sidebar.button("🔄 重賞一覧を再取得", key="refresh_upcoming_races"):
        clear_fetch_graded_races_cache()
        st.rerun()

    # 重賞一覧を取得
    with st.spinner("重賞一覧を取得中..."):
        races = get_upcoming_races(months_ahead=2, days_ahead=14)

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
            st.rerun()
        return

    # セレクトボックスで表示（選択だけでは読み込まない）
    labels = [r.display_label for r in races]
    loaded_race = get_race_config()
    pending_key = st.session_state.get('_pending_race_key')
    target_key = pending_key or (loaded_race.race_key if loaded_race else None)
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

    # レース特徴を自動初期化（初回のみ）
    if 'race_characteristics' not in st.session_state:
        # Gemini で動的取得、失敗時は最小限フォールバック
        st.session_state['race_characteristics'] = get_minimal_race_characteristics()
        try:
            with st.spinner("📡 レース特徴をWeb検索で取得中...（初回のみ）"):
                web_info = get_race_characteristics_with_gemini(
                    race_name=r.race_name, grade=r.grade, venue=r.venue,
                    distance=r.distance, surface=r.surface, date_str=r.date_str,
                )
            if web_info:
                st.session_state['race_characteristics'].update(web_info)
        except Exception:
            pass  # フォールバックデータは表示される

    # 枠番・馬番が未取得の場合は自動取得してCSVに保存（初回のみ）
    if 'gates_saved' not in st.session_state:
        try:
            csv_df = pd.read_csv(csv_path, encoding='utf-8-sig')
            needs_update = csv_df['枠番'].isna().all() or (csv_df['枠番'].astype(str).str.strip() == '').all()
            if needs_update:
                with st.spinner("🏇 枠番・馬番を取得してCSVに保存中...（初回のみ）"):
                    gate_data, gate_error = fetch_odds_and_gates(require_odds=False)
                if gate_data:
                    for idx, row in csv_df.iterrows():
                        horse = str(row.get('馬名', ''))
                        if horse in gate_data:
                            csv_df.at[idx, '枠番'] = gate_data[horse]['枠番']
                            csv_df.at[idx, '馬番'] = gate_data[horse]['馬番']
                    csv_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
                    load_race_data.clear()
                    st.toast(f"✅ {len(gate_data)}頭の枠番・馬番をCSVに保存しました", icon="🏇")
                elif gate_error:
                    st.session_state['latest_odds_error'] = gate_error
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
