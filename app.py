"""
フェブラリーステークス（2026年2月22日）情報表示Webアプリ

Streamlitを使用して、CSVファイルから競馬情報を読み込み、
インタラクティブに表示するWebアプリケーション
"""

import streamlit as st
import pandas as pd
import os
from datetime import datetime
import re
import json
import time  # 待機時間のために追加
from urllib.parse import urlparse
from collections import defaultdict
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

# .env ファイルからAPIキーを読み込む（app.py と同じフォルダに .env を置くこと）
load_dotenv()

# ====================
# ページ設定
# ====================

# ページの基本設定（タイトル、アイコン、レイアウト）
st.set_page_config(
    page_title="フェブラリーステークス 2026",
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

# CSVファイルのパス
CSV_FILE = "february_s_info.csv"

# 注目馬のリスト
FEATURED_HORSES = [
    {
        "name": "ダブルハートボンド",
        "description": "2025年JBCクラシック優勝。パワフルな末脚が武器。",
        "icon": "⭐"
    },
    {
        "name": "コスタノヴァ",
        "description": "連勝街道を突き進む実力馬。スピードと持続力を兼ね備える。",
        "icon": "🌟"
    },
    {
        "name": "ラムジェット",
        "description": "ダート界のスピードスター。先行力が持ち味。",
        "icon": "⚡"
    }
]

# 馬名の表記揺れ・別名を正規名に統一するマッピング
# （例: AIが略称を抽出した場合に正しい馬名に寄せる）
HORSE_NAME_ALIASES = {
    "ハートボンド": "ダブルハートボンド",  # ハートボンドは本レース未出走。同名言及はダブルハートボンドを指す
}

# フェブラリーステークス 過去データ・傾向（ドキュメントから抽出・固定データ）
# レース特徴タブに起動時から表示するためのベースデータ
RACE_INFO_FROM_DOC = {
    "コース特徴": (
        "東京ダート1600m。向こう正面の芝コース内からスタートし、ダートへ進入する「芝スタート」が特徴。"
        "内枠(1枠)は約97mの芝走行、外枠(8枠)は約127mの芝走行で約30mの差がある。"
        "外枠ほど高い初速を維持してダートに突入でき、先行争いで戦略的優位に立てる。"
        "内枠は加速が不十分になりやすく、砂かぶり（キックバック）リスクも高い。直線が長く瞬発力も必要。"
        "\n\n良馬場平均勝ちタイム約1分35秒4。稍重で1分34秒台と約1秒短縮。"
        "道悪では逃げ・先行馬が止まりにくく、芝に近い瞬発力勝負になりやすい。"
    ),
    "過去の傾向": (
        "【枠順】1枠は過去10年【0-0-0-19】で0勝。消去候補。"
        "7枠は単勝回収率207%、8枠153%と外枠人気薄が激走。"
        "4枠・5枠は複勝率30%と安定した「安全地帯」。\n"
        "【年齢】5歳馬が【4-4-5-28】と最多勝。7歳以上は【0-4-2-53】で勝利なし。\n"
        "【ステップ】根岸S組【5-2-3-38】が最多勝。チャンピオンズC組は複勝率47.1%と最高効率。\n"
        "【血統】過去10年の優勝馬7頭が父ミスタープロスペクター系。\n"
        "【人気薄】外枠(5〜8枠)の4番人気以下は複勝回収率118%と投資妙味大。"
        "内枠(1〜4枠)の人気薄は複勝回収率38%と妙味なし。"
    ),
    "勝ちやすい馬のタイプ": (
        "・父ミスタープロスペクター系（エーピーインディ系、ストームキャット系含む配合）\n"
        "・ゴールドアリュール産駒（コパノリッキー、ゴールドドリームなど実績多数）\n"
        "・過去に3連勝以上の経験がある馬（過去10年優勝馬9頭に共通）\n"
        "・4コーナーで5番手以内に位置できる先行馬\n"
        "・1800m以上からの距離短縮組（全3着以内馬の約7割）\n"
        "・4〜7枠に入った馬（特に中〜外枠）\n"
        "・道悪時：芝スタートを得意とする馬、芝勝利経験あり、母系にSS系を持つ馬"
    ),
    "苦手な馬のタイプ": (
        "・1枠の馬（過去10年0勝、消去候補）\n"
        "・7歳以上の高齢馬（0勝。連対はあるが勝ち切れない）\n"
        "・1200〜1400mからの距離延長組（東京マイルの直線は甘くない）\n"
        "・サンデーサイレンス系単体（勝ち切れない傾向、2着が多く連軸向き）\n"
        "・良馬場時：パワー不足の軽量型"
    ),
    "枠順有利": (
        "4〜7枠が中心。特に7枠・8枠の人気薄は常に警戒が必要（単勝回収率207%・153%）。"
        "外枠は芝スタートで初速優位、馬群に包まれるリスクも低い。"
        "人気薄の馬(4番人気以下)は外枠(5〜8枠)の複勝回収率118%と投資効率も高い。"
        "2014年コパノリッキー(16番人気1着・13番枠)、2020年ケイティブレイブ(16番人気2着・16番枠)など大波乱も外枠から。"
    ),
    "枠順不利": (
        "1枠は過去10年0勝で明確に不利。内枠は芝走行距離が短く加速不十分になりやすい。"
        "外から被せられると砂かぶり（キックバック）で心理的ストレスとスタミナ浪費のリスク。"
        "人気薄の馬が1〜4枠に入ると複勝回収率38%と投資妙味も低下。"
    ),
    "騎手厩舎傾向": (
        "東京ダートは直線が長く、瞬発力を引き出す騎乗が重要。"
        "戸崎圭太騎手はコース攻略法に精通し、脚を溜めた直線勝負を得意とする。"
        "ルメールら外国人騎手も大舞台で安定した成績を残す傾向。"
        "ゴールドアリュール産駒を管理する厩舎（美浦・栗東問わず）はこのレースへの適性を熟知。"
    ),
    "注目ポイント": (
        "【馬場状態で評価をシフト】\n"
        "良馬場→パワー型・実力馬中心（砂が深くスタミナ勝負）。\n"
        "道悪→芝適性・SS系のスピードタイプが浮上（前が止まりにくく波乱多発）。\n\n"
        "当日の雨量・馬場状態を必ず確認すること。\n"
        "また、前走根岸S連対馬か、チャンピオンズC・地方交流G1実績馬の「距離短縮組」を軸とするのが王道。"
    ),
}

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
        search_response = youtube.search().list(
            q=keyword,  # 検索キーワード
            part='id,snippet',  # 取得する情報（IDとスニペット）
            maxResults=max_results,  # 最大取得件数
            type='video',  # 動画のみ検索
            order='date',  # 新しい順に並べる
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

    # 注目馬リストから馬名を検索
    for horse in FEATURED_HORSES:
        if horse['name'] in text:
            found_horses.append(horse['name'])

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
        # 新しいSDK（google-genai）でクライアントを作成
        # 古いSDK（google-generativeai）とは書き方が異なります
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        # Gemini に送るプロンプトを作成（前走成績・調教・調子を具体的に抽出）
        prompt = f"""
あなたは競馬予想の専門家です。以下のYouTube動画のタイトルと概要欄を読み、各馬の詳細な評価情報を抽出してください。

# 動画タイトル
{video['title']}

# 概要欄
{video['description']}

# 注目すべき有力馬（これら以外の馬名が登場しても抽出してください）
- ダブルハートボンド（※「ハートボンド」と表記された場合も同じ馬として扱ってください）
- コスタノヴァ
- ラムジェット

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
            model='gemini-2.0-flash',
            contents=prompt
        )

        # レスポンスからテキストを取得
        response_text = response.text

        # レスポンスが空の場合のチェック
        if not response_text:
            return []

        # JSONブロックを抽出（```json ... ``` の中身を取得）
        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response_text, re.DOTALL)
        if json_match:
            json_text = json_match.group(1)
        else:
            json_text = response_text.strip()

        # JSONをパース
        analysis_results = json.loads(json_text)

        # 動画URLを各結果に追加
        for result in analysis_results:
            result['video_url'] = video['video_url']
            result['video_title'] = video['title']

        return analysis_results

    except json.JSONDecodeError:
        # JSON解析失敗は静かに無視（概要欄が短すぎる動画など）
        return []
    except Exception as e:
        error_msg = str(e)
        # 429 レート制限は呼び出し元でリトライするため、ここでは例外をそのまま投げる
        if "429" in error_msg or "resource_exhausted" in error_msg.lower():
            raise  # create_summary_dataframe 側でキャッチしてリトライ
        # それ以外の予期しないエラーのみ表示
        st.warning(f"⚠️ 動画の解析をスキップしました: {type(e).__name__}")
        return []


def analyze_all_videos_with_gemini(videos):
    """
    全YouTube動画を1回のGemini API呼び出しでまとめて解析する関数
    N回→1回に削減することでレート制限を回避し、大幅に高速化する

    引数:
        videos (list): 動画情報のリスト

    戻り値:
        list: 抽出された情報のリスト（馬名、プラス情報、マイナス情報、video_url、video_titleを含む辞書）
    """
    if not videos or not GEMINI_API_KEY:
        return []

    # 全動画情報をまとめたテキストを構築
    videos_text = ""
    for i, v in enumerate(videos, 1):
        desc = v.get('description', '') or ''
        videos_text += f"\n## 動画{i}\nタイトル: {v['title']}\n概要欄: {desc[:600]}\nURL: {v['video_url']}\n"

    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""
あなたは競馬予想の専門家です。以下の{len(videos)}本のYouTube動画それぞれのタイトルと概要欄を読み、
各馬の詳細な評価情報を抽出してください。

{videos_text}

# 注目すべき有力馬（これら以外の馬名が登場しても抽出してください）
- ダブルハートボンド（※「ハートボンド」と表記された場合も同じ馬として扱ってください）
- コスタノヴァ
- ラムジェット

# 抽出してほしい情報（各馬について）
プラス情報: 前走・近走の成績、調教・追切の様子、体調・調子、コース・距離適性、騎手・厩舎の強み
マイナス情報: 前走・近走での敗因、調教不安、コース・距離の不安、枠順・展開の不安

# 出力形式
以下のJSON形式で**必ず**出力してください（説明文は一切不要）：

```json
[
  {{
    "動画番号": 1,
    "馬名": "馬の名前",
    "プラス情報": "具体的な好材料を2～3文で記載",
    "マイナス情報": "具体的な懸念点を記載（なければ「特になし」）"
  }}
]
```

# 注意事項
- 各動画につき1馬以上抽出すること（情報がなければタイトルから推測）
- 1本の動画に複数の馬が登場する場合は複数エントリーを出力（動画番号は同じでOK）
- 馬名が全く見当たらない動画のみ「全体的な予想」として1件だけ出力
- JSONのみ出力し、前後に説明文を付けないこと
"""

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        response_text = response.text or ""

        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response_text, re.DOTALL)
        json_text = json_match.group(1) if json_match else response_text.strip()
        analysis_results = json.loads(json_text)

        # 動画番号に基づいてURLとタイトルを付与
        video_map = {i + 1: v for i, v in enumerate(videos)}
        for result in analysis_results:
            video_num = result.pop("動画番号", 1)
            video = video_map.get(video_num, videos[0])
            result['video_url'] = video['video_url']
            result['video_title'] = video['title']

        return analysis_results

    except json.JSONDecodeError:
        return []
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "resource_exhausted" in error_msg.lower():
            raise
        st.warning(f"⚠️ 動画の一括解析に失敗しました: {type(e).__name__}")
        return []


def create_summary_dataframe(videos):
    """
    YouTube動画情報から馬名ごとに整理したデータフレームを作成する関数
    全動画を1回のGemini API呼び出しで解析（高速化版）

    引数:
        videos (list): 動画情報のリスト

    戻り値:
        tuple: (DataFrame, list) — 動画別整理済みDF と 生の分析結果リスト
    """
    status_text = st.empty()
    status_text.info(f"🤖 {len(videos)}本の動画をGeminiで一括解析中...（約20〜30秒）")

    # 全動画を1回のAPIコールでまとめて解析
    all_analysis_results = []
    for retry in range(3):
        try:
            all_analysis_results = analyze_all_videos_with_gemini(videos)
            break
        except Exception:
            if retry < 2:
                wait_sec = (retry + 1) * 10
                status_text.info(f"⏳ レート制限のため待機中... ({wait_sec}秒後に再試行)")
                time.sleep(wait_sec)

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

        prompt = f"""
フェブラリーステークス2026の予想・各馬分析記事を検索してください。
クエリ: {query}

各馬について、競馬評論家やメディアはどのような評価をしていますか？
プラス材料（好材料・強み）とマイナス材料（懸念点・不安材料）を中心に、
各馬の評価を日本語で詳しくまとめてください。
特に以下の馬について詳しく：ダブルハートボンド、コスタノヴァ、ラムジェット
"""
        response = client.models.generate_content(
            model='gemini-2.0-flash',
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
        if "429" in error_msg or "resource_exhausted" in error_msg.lower():
            raise
        st.warning(f"⚠️ Web記事の取得に失敗しました: {type(e).__name__}")
        return []


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

    horse_list_str = "\n".join([f"- {h['name']}" for h in FEATURED_HORSES])

    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""
あなたは競馬予想の専門家です。以下のWeb記事の情報を読み、各馬の詳細な評価情報を抽出してください。

# 記事タイトル
{article_info['title']}

# 記事内容（要約）
{article_info['snippet']}

# 注目すべき有力馬（これら以外の馬名が登場しても抽出してください）
{horse_list_str}

# 重要な注意（馬名の表記について）
「ハートボンド」という名前が記事に登場した場合、本レースには「ダブルハートボンド」が出走しており
「ハートボンド」単体は出走していません。「ハートボンド」の言及は「ダブルハートボンド」として扱い、
馬名を必ず「ダブルハートボンド」で出力してください。

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
            model='gemini-2.0-flash',
            contents=prompt
        )

        response_text = response.text
        if not response_text:
            return []

        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response_text, re.DOTALL)
        json_text = json_match.group(1) if json_match else response_text.strip()

        analysis_results = json.loads(json_text)

        for result in analysis_results:
            result['source_url'] = article_info.get('url', '')
            result['source_title'] = article_info['title']
            result['source_type'] = 'web'

        return analysis_results

    except json.JSONDecodeError:
        return []
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "resource_exhausted" in error_msg.lower():
            raise
        st.warning(f"⚠️ Web記事の解析をスキップしました: {type(e).__name__}")
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
        """馬名の表記揺れをHORSE_NAME_ALIASESで正規化する"""
        return HORSE_NAME_ALIASES.get(name, name)

    # YouTube結果を処理
    for item in youtube_results:
        horse = normalize_horse_name(item.get("馬名", "不明"))
        plus = item.get("プラス情報", "").strip()
        minus = item.get("マイナス情報", "").strip()
        url = item.get("video_url", "")
        title = item.get("video_title", "YouTube動画")

        if plus and plus not in ("特になし", ""):
            horse_data[horse]["メリット_items"].append(plus)
            horse_data[horse]["メリット_sources"].append((title[:40], url))
        if minus and minus not in ("特になし", ""):
            horse_data[horse]["デメリット_items"].append(minus)
            horse_data[horse]["デメリット_sources"].append((title[:40], url))

    # Web記事結果を処理
    for item in web_results:
        horse = normalize_horse_name(item.get("馬名", "不明"))
        plus = item.get("プラス情報", "").strip()
        minus = item.get("マイナス情報", "").strip()
        url = item.get("source_url", "")
        title = item.get("source_title", "Web記事")

        if plus and plus not in ("特になし", ""):
            horse_data[horse]["メリット_items"].append(plus)
            horse_data[horse]["メリット_sources"].append((title[:40], url))
        if minus and minus not in ("特になし", ""):
            horse_data[horse]["デメリット_items"].append(minus)
            horse_data[horse]["デメリット_sources"].append((title[:40], url))

    # ドキュメント結果を処理
    for item in doc_results:
        horse = normalize_horse_name(item.get("馬名", "不明"))
        plus = item.get("プラス情報", "").strip()
        minus = item.get("マイナス情報", "").strip()
        title = item.get("source_title", "アップロードドキュメント")

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

    featured_names = [h["name"] for h in FEATURED_HORSES]
    def sort_key(name):
        if name in featured_names:
            return (0, featured_names.index(name))
        return (1, name)

    df["_sort"] = df["馬名"].apply(sort_key)
    df = df.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)

    return df


def fetch_and_analyze_web_articles(queries):
    """
    複数クエリでWeb記事を検索・解析するオーケストレーター関数

    引数:
        queries (list): 検索クエリのリスト

    戻り値:
        tuple: (articles_metadata, raw_analysis_results)
    """
    all_articles = []
    all_web_raw = []

    progress_bar = st.progress(0)
    status_text = st.empty()

    for q_idx, query in enumerate(queries):
        status_text.info(f"🌐 Web検索中... ({q_idx+1}/{len(queries)}): {query[:30]}")
        articles = []
        for retry in range(3):
            try:
                articles = search_web_articles(query)
                break
            except Exception:
                if retry < 2:
                    wait_sec = (retry + 1) * 8
                    status_text.info(f"⏳ Web検索待機中... ({wait_sec}秒)")
                    time.sleep(wait_sec)

        # 同じsnippetを複数回解析しないよう最初の1件だけ解析する
        unique_articles = articles[:1] if articles else []
        all_articles.extend(articles)
        progress_bar.progress((q_idx + 0.5) / len(queries))

        for a_idx, article in enumerate(unique_articles):
            status_text.info(f"🤖 Web記事を解析中... {article['title'][:30]}...")
            results = []
            for retry in range(3):
                try:
                    results = analyze_web_article_with_gemini(article)
                    break
                except Exception:
                    if retry < 2:
                        time.sleep((retry + 1) * 8)
            all_web_raw.extend(results)
            if a_idx < len(unique_articles) - 1:
                time.sleep(2)

        progress_bar.progress((q_idx + 1) / len(queries))
        if q_idx < len(queries) - 1:
            time.sleep(2)

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
def get_race_characteristics_with_gemini(extra_context=""):
    """
    GeminiのWeb検索グラウンディングでフェブラリーステークスの特徴・傾向を取得する関数

    引数:
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

        prompt = f"""
フェブラリーステークス（東京競馬場 ダート1600m G1）について、過去のデータと傾向を詳しく調査してください。
以下の観点で分析してください。
{extra_section}
# 分析観点
1. コースの特徴（東京ダート1600mの特性、スタート位置、直線の長さ等）
2. 過去10年の傾向（勝ち馬のパターン、人気別成績、年齢別成績など）
3. 勝ちやすい馬のタイプ（脚質、血統、前走条件、ローテーション等）
4. 苦手な馬のタイプ（不向きな条件、注意すべき馬のパターン）
5. 枠順の有利・不利（内枠・外枠の傾向、特定枠番の成績）
6. 騎手・厩舎の傾向（このレースで強い騎手・厩舎）
7. 今年の注目ポイント・特記事項

以下のJSON形式のみで出力してください（説明文不要）：

```json
{{
  "コース特徴": "東京ダート1600mの特性を詳しく（スタートから直線まで）",
  "過去の傾向": "過去のフェブラリーSのデータ・傾向を具体的に（人気別・年齢別・脚質別など）",
  "勝ちやすい馬のタイプ": "勝ちやすい馬の条件を箇条書きで詳しく",
  "苦手な馬のタイプ": "不向きな馬の条件を箇条書きで詳しく",
  "枠順有利": "有利な枠順とその理由を具体的に",
  "枠順不利": "不利な枠順とその理由を具体的に",
  "騎手厩舎傾向": "このレースで注目すべき騎手・厩舎の傾向",
  "注目ポイント": "今年2026年のフェブラリーSで特に注意すべきポイント"
}}
```
"""
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=config,
        )

        response_text = response.text or ""
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        return json.loads(response_text.strip())

    except (json.JSONDecodeError, Exception) as e:
        error_msg = str(e)
        if "429" in error_msg or "resource_exhausted" in error_msg.lower():
            raise
        st.warning(f"⚠️ レース特徴の取得に失敗しました: {type(e).__name__}")
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

        prompt = f"""
あなたは競馬の専門家です。以下のドキュメントを読み、フェブラリーステークス（東京ダート1600m G1）の
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
            model='gemini-2.0-flash',
            contents=prompt
        )
        response_text = response.text or ""
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        return json.loads(response_text.strip())

    except (json.JSONDecodeError, Exception) as e:
        error_msg = str(e)
        if "429" in error_msg or "resource_exhausted" in error_msg.lower():
            raise
        st.warning(f"⚠️ ドキュメントのレース特徴抽出に失敗しました: {type(e).__name__}")
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

    horse_list_str = "\n".join([f"- {h['name']}" for h in FEATURED_HORSES])

    try:
        client = google_genai.Client(api_key=GEMINI_API_KEY)

        prompt = f"""
あなたは競馬予想の専門家です。以下のドキュメントから各馬の評価情報を抽出してください。

# ドキュメント（{source_name}）
{text[:4000]}

# 注目すべき有力馬（これら以外の馬名が登場しても抽出してください）
{horse_list_str}

# 重要な注意（馬名の表記について）
「ハートボンド」という名前が記事に登場した場合、本レースには「ダブルハートボンド」が出走しており
「ハートボンド」単体は出走していません。「ハートボンド」の言及は「ダブルハートボンド」として扱い、
馬名を必ず「ダブルハートボンド」で出力してください。

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
            model='gemini-2.0-flash',
            contents=prompt
        )
        response_text = response.text or ""
        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response_text, re.DOTALL)
        json_text = json_match.group(1) if json_match else response_text.strip()
        analysis_results = json.loads(json_text)

        for result in analysis_results:
            result['source_url'] = ""
            result['source_title'] = source_name
            result['source_type'] = 'document'

        return analysis_results

    except json.JSONDecodeError:
        return []
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "resource_exhausted" in error_msg.lower():
            raise
        st.warning(f"⚠️ ドキュメントの馬情報抽出に失敗しました: {type(e).__name__}")
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
    st.markdown("## 🏇 フェブラリーステークス 2026 予想アプリ")
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
def load_race_data(file_path):
    """
    CSVファイルから競馬データを読み込む関数

    @st.cache_data デコレータにより、一度読み込んだデータは
    キャッシュされ、再読み込みが不要になります

    引数:
        file_path (str): CSVファイルのパス

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

# ====================
# サイドバー表示関数
# ====================

def display_sidebar():
    """
    サイドバーに応援メッセージと注目馬情報を表示する関数
    """
    # サイドバーのタイトル
    st.sidebar.title("🏇 フェブラリーステークス 2026")

    # レース情報
    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 レース情報")
    st.sidebar.write("**開催日**: 2026年2月22日（日）")
    st.sidebar.write("**開催場**: 東京競馬場")
    st.sidebar.write("**距離**: ダート1600m")
    st.sidebar.write("**グレード**: G1")

    # 応援メッセージ
    st.sidebar.markdown("---")
    st.sidebar.subheader("💪 応援メッセージ")
    st.sidebar.success(
        """
        ダート最高峰の激戦、フェブラリーステークス！

        冬の東京で繰り広げられる、
        スピードとパワーの頂上決戦。

        どの馬も優勝のチャンスあり！
        熱い戦いに期待しましょう！🔥
        """
    )

    # 注目馬セクション
    st.sidebar.markdown("---")
    st.sidebar.subheader("⭐ 注目馬")

    # 各注目馬の情報を表示
    for horse in FEATURED_HORSES:
        with st.sidebar.expander(f"{horse['icon']} {horse['name']}"):
            st.write(horse['description'])

    # フッター
    st.sidebar.markdown("---")
    st.sidebar.caption("🎯 予想は参考程度に。馬券は自己責任で！")

# ====================
# メインコンテンツ表示関数
# ====================

def display_main_content(df):
    """
    メインエリアに出馬表と予想シミュレーターを表示する関数

    引数:
        df (DataFrame): 競馬データ
    """
    # タイトル
    st.title("🏆 第43回 フェブラリーステークス（G1）")
    st.subheader("2026年2月22日 東京競馬場 ダート1600m")

    # タブを作成
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📋 出馬表",
        "🎲 勝率シミュレーター",
        "📥 情報入力",
        "🏇 総合予想（馬別）",
        "🏟️ レース特徴・傾向",
        "🎥 YouTube詳細"
    ])

    # ===== タブ1: 出馬表 =====
    with tab1:
        st.markdown("### 📊 出走予定馬一覧")

        # データが空でないか確認
        if df is not None and not df.empty:
            # 出馬表を表示（全幅で表示）
            st.dataframe(
                df,
                use_container_width=True,  # コンテナ幅いっぱいに表示
                hide_index=True,  # インデックス列を非表示
                height=400  # 高さを指定
            )

            # 統計情報
            st.markdown("---")
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("出走頭数", f"{len(df)}頭")

            with col2:
                # オッズが数値の場合の最低オッズ（存在する場合）
                if 'オッズ' in df.columns:
                    st.metric("データ取得日", datetime.now().strftime("%Y年%m月%d日"))

            with col3:
                if '騎手' in df.columns:
                    unique_jockeys = df['騎手'].nunique()
                    st.metric("参加騎手数", f"{unique_jockeys}名")

        else:
            st.warning("⚠️ 表示するデータがありません")

    # ===== タブ2: 勝率シミュレーター =====
    with tab2:
        st.markdown("### 🎯 勝率予想シミュレーター")
        st.info("💡 各馬の勝率をスライダーで調整して、自分なりの予想を立ててみましょう！")

        if df is not None and not df.empty and '馬名' in df.columns:
            # セッションステートの初期化（スライダーの値を保持するため）
            if 'win_rates' not in st.session_state:
                # 初期値として、全馬に均等な確率を設定
                initial_rate = 100 / len(df)
                st.session_state.win_rates = {
                    horse: initial_rate for horse in df['馬名'].tolist()
                }

            # リセットボタン
            col_reset1, col_reset2 = st.columns([1, 5])
            with col_reset1:
                if st.button("🔄 リセット", help="全ての勝率を均等に戻します"):
                    initial_rate = 100 / len(df)
                    st.session_state.win_rates = {
                        horse: initial_rate for horse in df['馬名'].tolist()
                    }
                    st.rerun()

            st.markdown("---")

            # 各馬のスライダーを表示（2列レイアウト）
            horses = df['馬名'].tolist()

            # 馬番がある場合は馬番順にソート
            if '馬番' in df.columns:
                df_sorted = df.sort_values('馬番')
                horses = df_sorted['馬名'].tolist()

            # 2列に分けて表示
            cols = st.columns(2)

            for idx, horse in enumerate(horses):
                col_idx = idx % 2

                with cols[col_idx]:
                    # 馬番情報を取得（ある場合）
                    horse_number = ""
                    if '馬番' in df.columns:
                        umaban = df[df['馬名'] == horse]['馬番'].values[0]
                        horse_number = f"({umaban}番) "

                    # スライダーで勝率を設定
                    rate = st.slider(
                        f"🐴 {horse_number}{horse}",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(st.session_state.win_rates[horse]),
                        step=0.5,
                        key=f"slider_{horse}",
                        help=f"{horse}の勝率を調整"
                    )

                    # セッションステートに保存
                    st.session_state.win_rates[horse] = rate

            # 合計勝率を計算
            st.markdown("---")
            total_rate = sum(st.session_state.win_rates.values())

            # 合計が100%からどれだけ離れているかを表示
            col_total1, col_total2, col_total3 = st.columns(3)

            with col_total1:
                st.metric("合計勝率", f"{total_rate:.1f}%")

            with col_total2:
                difference = abs(100 - total_rate)
                st.metric("100%との差", f"{difference:.1f}%")

            with col_total3:
                if total_rate == 100.0:
                    st.success("✅ 完璧！")
                elif 99.0 <= total_rate <= 101.0:
                    st.info("📊 ほぼ100%")
                else:
                    st.warning("⚠️ 要調整")

            # 予想ランキングを表示
            st.markdown("---")
            st.markdown("### 🏆 あなたの予想ランキング")

            # 勝率の高い順にソート
            sorted_predictions = sorted(
                st.session_state.win_rates.items(),
                key=lambda x: x[1],
                reverse=True
            )

            # トップ5を表示
            ranking_df = pd.DataFrame(sorted_predictions, columns=['馬名', '予想勝率(%)'])
            ranking_df['順位'] = range(1, len(ranking_df) + 1)
            ranking_df = ranking_df[['順位', '馬名', '予想勝率(%)']]

            # 勝率でバーチャートを表示
            st.dataframe(
                ranking_df.head(10),
                use_container_width=True,
                hide_index=True
            )

            # 勝率が最も高い馬を本命として表示
            if sorted_predictions:
                top_horse = sorted_predictions[0]
                if top_horse[1] > 0:
                    st.success(f"🎯 **本命**: {top_horse[0]} ({top_horse[1]:.1f}%)")

        else:
            st.warning("⚠️ シミュレーター用のデータがありません")

    # ===== タブ3: 情報入力 =====
    with tab3:
        st.markdown("### 📥 情報入力")
        st.info("💡 YouTube・Web・ドキュメントから情報を収集します。収集後、「総合予想（馬別）」「レース特徴・傾向」タブで結果を確認できます。")

        # ===== Section 1: YouTube + Web 一括検索 =====
        st.markdown("#### 🔍 YouTube + Web 一括検索")

        col_s1, col_s2, col_s3 = st.columns([3, 1, 1])
        with col_s1:
            combined_keyword = st.text_input(
                "検索キーワード",
                value="フェブラリーステークス 2026 予想",
                help="YouTubeおよびWeb検索に使用するキーワード",
                key="combined_keyword"
            )
        with col_s2:
            combined_max_videos = st.number_input(
                "YouTube件数",
                min_value=1,
                max_value=20,
                value=10,
                key="combined_max_videos"
            )
        with col_s3:
            combined_max_web = st.number_input(
                "Web検索数",
                min_value=1,
                max_value=10,
                value=5,
                key="combined_max_web"
            )

        if st.button("🔍 YouTube + Web 一括検索", type="primary", key="combined_search"):
            st.info("⏳ YouTube + Web の解析には1〜2分程度かかります。しばらくお待ちください。")

            # Phase 1: YouTube検索
            with st.spinner("YouTube動画を検索中..."):
                videos = search_youtube_videos(combined_keyword, combined_max_videos)
            st.metric("YouTube動画", f"{len(videos)}件取得")

            # Phase 2: YouTube動画解析
            st.markdown("#### YouTube動画を解析中...")
            summary_df, youtube_raw = create_summary_dataframe(videos)

            # Phase 3: Web検索・解析
            st.markdown("#### Web記事を検索・解析中...")
            web_queries = [
                combined_keyword,
                "フェブラリーステークス 2026 各馬評価 分析",
                "フェブラリーステークス 2026 本命 穴馬 予想",
                "フェブラリーステークス 2026 調教 追切 状態",
                "フェブラリーステークス 2026 過去データ 傾向 コース適性",
                "フェブラリーステークス 2026 騎手 厩舎 評価",
                "フェブラリーステークス 2026 前走 近走 成績",
                "フェブラリーステークス 2026 馬券 買い方 狙い目",
                "フェブラリーステークス 2026 ダブルハートボンド コスタノヴァ ラムジェット",
                "フェブラリーステークス 2026 出走予定馬 戦力分析",
            ][:combined_max_web]
            web_articles, web_raw = fetch_and_analyze_web_articles(web_queries)
            st.metric("Web記事", f"{len(web_articles)}件取得")

            # Phase 4: 馬別集計（ドキュメントから抽出した馬別情報も統合）
            doc_horse_raw = st.session_state.get('doc_horse_raw', [])
            horse_df = aggregate_horse_analysis(youtube_raw, web_raw, doc_horse_raw)

            # セッションステートに保存
            st.session_state['horse_df'] = horse_df
            st.session_state['youtube_videos'] = videos
            st.session_state['youtube_raw'] = youtube_raw
            st.session_state['web_raw'] = web_raw
            st.session_state['youtube_summary_df'] = summary_df
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
                        for k, v in doc_race_info.items():
                            if v and v != "資料に記載なし":
                                existing[k] = existing.get(k, "") + f"\n\n【{uploaded_file.name}より】\n{v}"
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

    # ===== タブ4: 総合予想（馬別） =====
    with tab4:
        st.markdown("### 🏇 馬名別 総合予想情報")
        st.info("💡 「情報入力」タブで YouTube + Web 一括検索またはドキュメント分析を実行すると、ここに馬別の分析結果が表示されます。")

        if 'horse_df' in st.session_state and not st.session_state['horse_df'].empty:
            horse_df = st.session_state['horse_df']
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
            horse_tabs = st.tabs(horse_names)

            for i, htab in enumerate(horse_tabs):
                row = horse_df.iloc[i]
                with htab:
                    source_count = row.get('情報源数', 0)
                    st.caption(f"情報源数: {source_count}件")

                    col_merit, col_demerit = st.columns(2)

                    with col_merit:
                        st.markdown("### ✅ メリット（好材料）")
                        merit_text = row.get('メリット', '（情報なし）')
                        if merit_text and merit_text != '（情報なし）':
                            items = re.split(r'\n\n(?=\[\d+\])', merit_text.strip())
                            for item in items:
                                item = item.strip()
                                if item:
                                    clean = re.sub(r'^\[\d+\]\s*', '', item)
                                    st.success(clean)
                        else:
                            st.info("情報がありませんでした")

                        merit_src = row.get('メリット出典', '（なし）')
                        if merit_src and merit_src != '（なし）':
                            with st.expander("📎 メリットの出典"):
                                st.markdown(merit_src)

                    with col_demerit:
                        st.markdown("### ⚠️ デメリット（懸念点）")
                        demerit_text = row.get('デメリット', '（情報なし）')
                        if demerit_text and demerit_text != '（情報なし）':
                            items = re.split(r'\n\n(?=\[\d+\])', demerit_text.strip())
                            for item in items:
                                item = item.strip()
                                if item:
                                    clean = re.sub(r'^\[\d+\]\s*', '', item)
                                    st.error(clean)
                        else:
                            st.info("懸念点の情報がありませんでした")

                        demerit_src = row.get('デメリット出典', '（なし）')
                        if demerit_src and demerit_src != '（なし）':
                            with st.expander("📎 デメリットの出典"):
                                st.markdown(demerit_src)

            st.markdown("---")
            if 'web_articles' in st.session_state and st.session_state['web_articles']:
                with st.expander("🌐 参照したWeb記事一覧"):
                    for art in st.session_state['web_articles']:
                        if art['url']:
                            st.markdown(f"- [{art['title']}]({art['url']}) — {art['source_name']}")
                        else:
                            st.markdown(f"- {art['title']} — {art['source_name']}")

        else:
            st.info("👆 「情報入力」タブで「🔍 YouTube + Web 一括検索」を実行してください")

    # ===== タブ5: レース特徴・傾向 =====
    with tab5:
        st.markdown("### 🏟️ フェブラリーステークス レース特徴・傾向")
        st.info("💡 「情報入力」タブでGemini分析またはドキュメント分析を実行すると、ここに結果が表示されます。")

        if 'race_characteristics' in st.session_state and st.session_state['race_characteristics']:
            race_info = st.session_state['race_characteristics']

            if race_info.get('コース特徴'):
                st.markdown("#### 🏁 コース特徴")
                st.info(race_info['コース特徴'])

            col_win, col_lose = st.columns(2)
            with col_win:
                if race_info.get('勝ちやすい馬のタイプ'):
                    st.markdown("#### ✅ 勝ちやすい馬のタイプ")
                    for line in race_info['勝ちやすい馬のタイプ'].strip().split('\n'):
                        line = line.strip()
                        if line:
                            st.success(line)
            with col_lose:
                if race_info.get('苦手な馬のタイプ'):
                    st.markdown("#### ❌ 苦手な馬のタイプ")
                    for line in race_info['苦手な馬のタイプ'].strip().split('\n'):
                        line = line.strip()
                        if line:
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

    # ===== タブ6: YouTube詳細 =====
    with tab6:
        st.markdown("### 🎥 YouTube予想動画から情報収集")
        st.info("💡 YouTubeの予想動画から、プラス材料・マイナス材料を自動抽出します")

        # 検索キーワード入力
        col_search1, col_search2 = st.columns([3, 1])

        with col_search1:
            search_keyword = st.text_input(
                "検索キーワード",
                value="フェブラリーステークス 2026 予想",
                help="YouTubeで検索したいキーワードを入力",
                key="yt_detail_keyword"
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

        # 検索ボタン
        if st.button("🔍 YouTube検索", type="primary", key="yt_detail_search"):
            with st.spinner("YouTube動画を検索中..."):
                videos = search_youtube_videos(search_keyword, max_videos)
            if videos:
                st.session_state['youtube_videos'] = videos
                st.success(f"✅ {len(videos)}件の動画を取得しました")
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
                    st.link_button("▶️ YouTubeで視聴", video['video_url'], use_container_width=True)

                with col_video2:
                    st.caption(f"📢 {video['channel_title']}")
                    published_date = video['published_at'][:10]
                    st.caption(f"📅 公開日: {published_date}")
                    with st.expander("📝 概要欄を表示"):
                        st.write(video['description'] if video['description'] else "（概要なし）")

                st.markdown("#### 🔍 重要ポイント抽出")
                combined_text = video['title'] + "\n" + video['description']
                plus_keywords = ['プラス', '好材料', '強い', '期待', '注目', '有利', '良化', '好調', '推奨', '本命', '◎', '○']
                plus_points = extract_key_points(combined_text, plus_keywords)
                minus_keywords = ['マイナス', '懸念', '不安', '課題', '弱点', '不利', '悪化', '不調', '△', '▲']
                minus_points = extract_key_points(combined_text, minus_keywords)

                col_plus, col_minus = st.columns(2)
                with col_plus:
                    st.markdown("**✅ プラス材料**")
                    if plus_points:
                        for point in plus_points[:3]:
                            st.success(f"• {point}")
                    else:
                        st.caption("（抽出なし）")
                with col_minus:
                    st.markdown("**⚠️ マイナス材料**")
                    if minus_points:
                        for point in minus_points[:3]:
                            st.warning(f"• {point}")
                    else:
                        st.caption("（抽出なし）")

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

def main():
    """
    アプリケーションのメイン処理
    """
    # パスワード認証（未認証の場合はログイン画面を表示して停止）
    if not check_password():
        st.stop()
        return

    # レース特徴を自動初期化（初回のみ）
    # まずドキュメントデータで即時表示し、その後Web検索で2026年情報を補完
    if 'race_characteristics' not in st.session_state:
        st.session_state['race_characteristics'] = RACE_INFO_FROM_DOC.copy()
        try:
            with st.spinner("📡 レース特徴をWeb検索で補完中...（初回のみ）"):
                web_info = get_race_characteristics_with_gemini()
            if web_info:
                st.session_state['race_characteristics'].update(web_info)
        except Exception:
            pass  # 失敗してもドキュメントデータは表示される

    # サイドバーを表示
    display_sidebar()

    # データを読み込み
    df = load_race_data(CSV_FILE)

    # メインコンテンツを表示
    if df is not None:
        display_main_content(df)
    else:
        # データがない場合の表示
        st.error("### ⚠️ データを読み込めませんでした")
        st.info(
            """
            **次の手順を試してください:**

            1. `get_keiba_info.py` を実行して `february_s_info.csv` を作成
            2. CSVファイルが `app.py` と同じフォルダにあることを確認
            3. ページをリロード（F5キー）
            """
        )

        # サンプルデータ表示ボタン
        if st.button("📝 サンプルデータで試す"):
            # サンプルデータを作成
            sample_data = {
                '枠番': ['1', '2', '3', '4', '5'],
                '馬番': ['1', '2', '3', '4', '5'],
                '馬名': ['ダブルハートボンド', 'コスタノヴァ', 'ラムジェット', 'サンプル馬A', 'サンプル馬B'],
                '性齢': ['牡5', '牡4', '牡5', '牡6', '牝5'],
                '斤量': ['57.0', '57.0', '57.0', '57.0', '55.0'],
                '騎手': ['C.ルメール', '横山武史', '戸崎圭太', 'M.デムーロ', '川田将雅'],
                '調教師': ['矢作芳人', '藤沢和雄', '国枝栄', '友道康夫', '池江泰寿'],
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
