# 重賞レース予想アプリ

## プロジェクト概要

直近の重賞レースをサイドバーから選択し、出馬情報・予想情報を
YouTubeとWeb検索から自動収集し、馬名ごとに整理して表示するStreamlit Webアプリ。
netkeiba.comのスケジュールページから重賞一覧を取得し、任意のレースに対応。

## ファイル構成

```
c:\WORK\keiba\
├── app.py                  # Streamlitアプリ本体（メインファイル）
├── race_catalog.py         # netkeiba.comから重賞一覧を取得するモジュール
├── get_keiba_info.py       # netkeiba.comから出走表をスクレイピングしてCSVを生成
├── data/                   # レースごとのCSVファイル（自動生成）
├── february_s_info.csv     # 旧フェブラリーS用CSV（後方互換）
├── .env                    # APIキー（Gitにコミット禁止）
├── .gitignore              # .envなどを除外
└── CLAUDE.md               # このファイル
```

## 起動方法

```bash
# 1. 依存パッケージをインストール
pip install streamlit pandas requests beautifulsoup4 google-api-python-client google-genai python-dotenv

# 2. アプリを起動（出馬表はサイドバーでレース選択時に自動取得）
streamlit run app.py
```

### get_keiba_info.py の単独実行（任意）
```bash
# デフォルト（フェブラリーS）
python get_keiba_info.py

# 任意のレース
python get_keiba_info.py --race-id 202607030811 --output data/race_202607030811.csv
```

## APIキー管理

APIキーは `.env` ファイルで管理する。コードへの直書き禁止。

```
# .env ファイルの内容
YOUTUBE_API_KEY=AIza...
GEMINI_API_KEY=AIza...
TAVILY_API_KEY=tvly-...
```

- **YouTube Data API v3**: Google Cloud Console > APIとサービス > 認証情報
- **Gemini API**: https://aistudio.google.com/app/apikey

## レース選択の仕組み

1. `race_catalog.py` が netkeiba.com のスケジュールページから重賞一覧を取得
2. サイドバーの `st.selectbox` でレースを選択
3. 選択時に `race_id` を遅延解決（特別レースページから出馬表URLを取得）
4. 出馬表未公開の場合は `race_id = None` となり「出馬表未発表」メッセージを表示
5. レース切替時は全セッションステートをクリア

### RaceInfo データクラス（race_catalog.py）
```python
@dataclass
class RaceInfo:
    race_name: str        # "高松宮記念"
    grade: str            # "G1" / "G2" / "G3"
    date_str: str         # "3月29日"
    date: datetime.date
    venue: str            # "中京"
    distance: str         # "1200m"
    surface: str          # "芝" / "ダート"
    race_id: str | None   # 出馬表ページから解決。未解決時はNone
    race_key: str         # キャッシュキー用一意識別子
    csv_file: str         # "data/race_202607030811.csv"
```

## タブ構成（app.py の display_main_content）

| タブ | 内容 |
|---|---|
| 📋 出馬表 | CSVから読み込んだ出走馬一覧 |
| 📥 情報入力 | Web一括検索、ドキュメント分析の実行 |
| 🏇 総合予想（馬別） | Web検索結果を馬ごとにメリット・デメリットで表示 |
| 🏟️ レース特徴・傾向 | コース特徴・枠順傾向・注目ポイントの表示 |
| 🎥 YouTube詳細 | YouTube動画のサムネイル・概要欄の詳細 |

## 主要関数（app.py）

| 関数 | 役割 |
|---|---|
| `get_race_config()` | 選択中のRaceInfoを返す |
| `get_race_display_name()` | "レース名 年" 形式の表示名 |
| `get_csv_path()` | 選択中レースのCSVパス |
| `get_race_url()` | 選択中レースのnetkeiba出馬表URL |
| `search_youtube_videos(keyword, max_results)` | YouTube Data API v3 で動画検索（1時間キャッシュ） |
| `analyze_video_with_gemini(video)` | 動画タイトル・概要欄をGeminiで解析、馬別JSON返却 |
| `create_summary_dataframe(videos)` | 全動画を解析して `(df, raw_results)` タプルを返す |
| `search_web_articles_with_tavily(query, max_articles, include_domains)` | Tavily APIでWeb検索（競馬系ドメイン優先） |
| `search_web_articles(query, max_articles)` | Gemini Google SearchグラウンディングでWeb検索（1時間キャッシュ） |
| `analyze_web_article_with_gemini(article_info)` | Web記事スニペットをGeminiで解析、馬別JSON返却 |
| `fetch_and_analyze_web_articles(queries, total_article_limit)` | Tavily優先・GeminiフォールバックでWeb検索/解析、`(articles, raw)` 返却 |
| `aggregate_horse_analysis(youtube_raw, web_raw)` | YouTube + Web の生データを馬名ごとに集約、DataFrame返却 |
| `get_race_characteristics_with_gemini(...)` | レースメタデータを引数にレース特徴をGeminiで取得 |

## 主要関数（race_catalog.py）

| 関数 | 役割 |
|---|---|
| `fetch_graded_races(year, month)` | netkeiba.comスケジュールから重賞一覧を取得 |
| `resolve_race_id(race)` | 特別レースページからrace_idを解決 |
| `get_upcoming_races(months_ahead)` | 当月+N月分の重賞を日付順で返す |

## 主要関数（get_keiba_info.py）

| 関数 | 役割 |
|---|---|
| `fetch_race_csv(race_id, output_file)` | 出馬表を取得しCSV保存。失敗時はRuntimeError |

## データフロー

```
[サイドバー: レース選択]
├── race_catalog.get_upcoming_races() → 重賞一覧
├── resolve_race_id() → race_id 解決
└── get_keiba_info.fetch_race_csv() → CSV自動取得

[🔍 一括検索ボタン]
├── fetch_and_analyze_web_articles(queries, total_article_limit) → (web_articles, web_raw)
│   ├── search_web_articles_with_tavily()  ← Tavily API（優先）
│   ├── search_web_articles()  ← Gemini Google Search grounding（フォールバック）
│   └── analyze_web_article_with_gemini()
└── aggregate_horse_analysis(youtube_raw, web_raw) → horse_df
        └── 馬名タブ形式で表示（✅ メリット | ⚠️ デメリット）
```

## Web検索クエリ（動的生成）

`get_race_display_name()` でレース名を動的に生成。例:
1. ユーザー入力キーワード
2. {レース名} {年} 各馬評価 分析
3. {レース名} {年} 本命 穴馬 予想
4. ...（計9クエリ + 馬名バッチクエリ）

## セッションステートのキー一覧

| キー | 内容 |
|---|---|
| `selected_race` | 選択中のRaceInfoオブジェクト |
| `_prev_race_key` | 前回選択したレースのrace_key（変更検出用） |
| `horse_df` | 馬別集計DataFrame |
| `youtube_videos` | YouTube動画リスト |
| `youtube_raw` | YouTube分析の生データリスト |
| `youtube_summary_df` | YouTube動画別集計DataFrame |
| `web_articles` | Web記事メタデータリスト |
| `race_characteristics` | レース特徴辞書 |

## Gemini API 使用モデル

- デフォルト: `gemini-2.5-flash`（`GEMINI_MODEL` 環境変数で上書き可）
- SDK: `google-genai`（`from google import genai as google_genai`）
- グラウンディング: `from google.genai import types as genai_types` を使用

## 共有・デプロイ方法

### ngrok（ローカルPC、一時的な共有）
```bash
pip install pyngrok
ngrok http 8501
# 発行されたURLを相手に送る（PCが動いている間だけ有効）
# .env のAPIキーは外部に露出しない（トンネル経由のHTTPのみ転送）
```

### Streamlit Community Cloud（無料・恒久的）
1. GitHubリポジトリにコード（`.env` は除く）をプッシュ
2. https://share.streamlit.io でデプロイ
3. Streamlit Cloud の Secrets に APIキーを設定（`.streamlit/secrets.toml` 形式）
