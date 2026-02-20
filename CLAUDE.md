# フェブラリーステークス 2026 予想アプリ

## プロジェクト概要

フェブラリーステークス（2026年2月22日、東京競馬場ダート1600m G1）の出馬情報・予想情報を
YouTubeとWeb検索から自動収集し、馬名ごとに整理して表示するStreamlit Webアプリ。

## ファイル構成

```
c:\WORK\keiba\
├── app.py                  # Streamlitアプリ本体（メインファイル）
├── get_keiba_info.py       # netkeiba.comから出走表をスクレイピングしてCSVを生成
├── february_s_info.csv     # 出走表データ（get_keiba_info.py が生成）
├── .env                    # APIキー（Gitにコミット禁止）
├── .gitignore              # .envなどを除外
└── CLAUDE.md               # このファイル
```

## 起動方法

```bash
# 1. 依存パッケージをインストール
pip install streamlit pandas requests beautifulsoup4 google-api-python-client google-genai python-dotenv

# 2. 出走表データを取得（初回 or レース直前に実行）
python get_keiba_info.py

# 3. アプリを起動
streamlit run app.py
```

## APIキー管理

APIキーは `.env` ファイルで管理する。コードへの直書き禁止。

```
# .env ファイルの内容
YOUTUBE_API_KEY=AIza...
GEMINI_API_KEY=AIza...
```

- **YouTube Data API v3**: Google Cloud Console > APIとサービス > 認証情報
- **Gemini API**: https://aistudio.google.com/app/apikey

## タブ構成（app.py の display_main_content）

| タブ | 内容 |
|---|---|
| 📋 出馬表 | CSVから読み込んだ出走馬一覧 |
| 📥 情報入力 | YouTube + Web一括検索、ドキュメント分析の実行 |
| 🏇 総合予想（馬別） | YouTube + Web を一括検索し、馬ごとにメリット・デメリットを表示 |
| 🏟️ レース特徴・傾向 | コース特徴・枠順傾向・注目ポイントの表示 |
| 🎥 YouTube詳細 | YouTube動画のサムネイル・概要欄の詳細 |

## 主要関数（app.py）

| 関数 | 役割 |
|---|---|
| `search_youtube_videos(keyword, max_results)` | YouTube Data API v3 で動画検索（1時間キャッシュ） |
| `analyze_video_with_gemini(video)` | 動画タイトル・概要欄をGeminiで解析、馬別JSON返却 |
| `create_summary_dataframe(videos)` | 全動画を解析して `(df, raw_results)` タプルを返す |
| `search_web_articles(query, max_articles)` | Gemini Google SearchグラウンディングでWeb検索（1時間キャッシュ） |
| `analyze_web_article_with_gemini(article_info)` | Web記事スニペットをGeminiで解析、馬別JSON返却 |
| `fetch_and_analyze_web_articles(queries)` | 複数クエリのWeb検索・解析オーケストレーター、`(articles, raw)` 返却 |
| `aggregate_horse_analysis(youtube_raw, web_raw)` | YouTube + Web の生データを馬名ごとに集約、DataFrame返却 |

## データフロー（総合予想タブ）

```
[🔍 一括検索ボタン]
├── search_youtube_videos() → 動画リスト
│   └── create_summary_dataframe() → (summary_df, youtube_raw)
├── fetch_and_analyze_web_articles(queries[0:max_web]) → (web_articles, web_raw)
│   ├── search_web_articles()  ← Gemini Google Search grounding
│   └── analyze_web_article_with_gemini()
└── aggregate_horse_analysis(youtube_raw, web_raw) → horse_df
        └── 馬名タブ形式で表示（✅ メリット | ⚠️ デメリット）
```

## 注目馬（FEATURED_HORSES）

- ハートボンド（2025年JBCクラシック優勝）
- コスタノヴァ（連勝街道実力馬）
- ラムジェット（先行力が持ち味）

## Web検索クエリ一覧（fetch_and_analyze_web_articles に渡す）

1. ユーザー入力キーワード
2. フェブラリーステークス 2026 各馬評価 分析
3. フェブラリーステークス 2026 本命 穴馬 予想
4. フェブラリーステークス 2026 調教 追切 状態
5. フェブラリーステークス 2026 過去データ 傾向 コース適性
6. フェブラリーステークス 2026 騎手 厩舎 評価
7. フェブラリーステークス 2026 前走 近走 成績
8. フェブラリーステークス 2026 馬券 買い方 狙い目
9. フェブラリーステークス 2026 ハートボンド コスタノヴァ ラムジェット
10. フェブラリーステークス 2026 出走予定馬 戦力分析

## セッションステートのキー一覧

| キー | 内容 |
|---|---|
| `horse_df` | 馬別集計DataFrame |
| `youtube_videos` | YouTube動画リスト |
| `youtube_raw` | YouTube分析の生データリスト |
| `youtube_summary_df` | YouTube動画別集計DataFrame |
| `web_articles` | Web記事メタデータリスト |

## Gemini API 使用モデル

- `gemini-2.0-flash` （全API呼び出しで共通）
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
