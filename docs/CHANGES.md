# 重賞レース選択機能の実装計画

## Context

現在のアプリはフェブラリーステークス2026専用にハードコードされている。これを任意の直近重賞レースを選択できるように汎用化する。ユーザーがサイドバーでレースを選ぶと、そのレースの出馬表取得・検索・分析が全て動的に切り替わる。

---

## 1. 新規ファイル: `race_catalog.py`

netkeiba.comのレーススケジュールページから直近の重賞一覧を取得するモジュール。

### データ構造
```python
@dataclass
class RaceInfo:
    race_name: str        # "高松宮記念"
    grade: str            # "G1" / "G2" / "G3"
    date_str: str         # "2026/03/29(日)"
    date: datetime.date
    venue: str            # "中京"
    distance: str         # "1200m"
    surface: str          # "芝" / "ダート"
    race_id: str | None   # "202607030811" - 出馬表ページから解決。未解決時はNone
    race_key: str         # "{date}_{venue}_{race_name}" — キャッシュキー用の一意識別子
    csv_file: str         # "data/race_202607030811.csv"
```

- `race_key` は `resolve_race_id` のキャッシュキーとして使用（dataclass全体ではなく文字列）
- `race_id` が `None` の場合、UI側で「出馬表未発表」を表示

### 主要関数
- `fetch_graded_races(year: int, month: int) -> list[RaceInfo]`: netkeiba.comスケジュールページをスクレイピング（`https://race.netkeiba.com/top/schedule.html?year={year}&month={month}`）
- `resolve_race_id(race: RaceInfo) -> str | None`: 特別レースページから`race_id`を解決（レース選択時のみ遅延実行）。解決不可時は `None` を返す
- `get_upcoming_races(months_ahead: int = 2) -> list[RaceInfo]`: 当月+翌月分の重賞を日付順で返す

### キャッシュ
- `fetch_graded_races`: `functools.lru_cache`（内部: `_fetch_graded_races_cached`）
- `resolve_race_id`: `functools.lru_cache`（内部: `_resolve_race_id_cached`、キーは `race_key + special_url`）

### エラーハンドリング
- スクレイピング失敗 → 空リスト返却 + 警告表示
- race_id解決失敗 → `None` 返却（UIで「出馬表未発表」表示）
- フォールバック: レースID手動入力用のテキストフィールドをサイドバーに設置

---

## 2. `data/` ディレクトリ作成

- レースごとのCSVを `data/race_{race_id}.csv` に保存
- `.gitignore` に `data/` を追加
- 既存の `february_s_info.csv` はそのまま残す（後方互換のため）

---

## 3. `get_keiba_info.py` の修正

### 変更内容
- `fetch_race_csv(race_id: str, output_file: str) -> str` 関数を新規追加（既存main()のロジックを抽出）
  - 失敗時は例外を送出（`RuntimeError` 等）— app.py側でユーザー向けメッセージを表示
  - 成功時は出力ファイルパスを返す
- `main()` は `argparse` で `--race-id`, `--output` を受け付けるように変更（デフォルトは現在の値で後方互換）

### 変更箇所
- L21: `RACE_ID` → 関数パラメータ化（デフォルト値として残す）
- L27: `OUTPUT_FILE` → 関数パラメータ化（デフォルト値として残す）
- L191-238: `main()` リファクタ

---

## 4. `app.py` の修正（セクション別）

### 4A. 定数セクション (L42-161)

**削除するもの:**
- `CSV_FILE` (L62) — `st.session_state['selected_race'].csv_file` に置換
- `RACE_ID` (L64), `RACE_URL` (L65) — 動的計算
- `FEATURED_HORSES` (L76-92) — 完全削除
- `HORSE_NAME_ALIASES` (L94-98) — 完全削除
- `RACE_INFO_FROM_DOC` (L100-161) — 完全削除

**追加するもの:**
```python
def get_race_config() -> RaceInfo | None:
    return st.session_state.get('selected_race')

def get_race_display_name() -> str:
    r = get_race_config()
    return f"{r.race_name} {r.date.year}" if r else "レース未選択"

def get_csv_path() -> str:
    r = get_race_config()
    return r.csv_file if r else ""

def get_race_url() -> str:
    r = get_race_config()
    return f"https://race.netkeiba.com/race/shutuba.html?race_id={r.race_id}" if r and r.race_id else ""

def get_minimal_race_characteristics() -> dict:
    """Gemini失敗時のフォールバック: RaceInfoから最小限のレース特徴を組み立て"""
    r = get_race_config()
    if not r:
        return {}
    return {
        "コース特徴": f"{r.venue}競馬場 {r.surface}{r.distance}",
        "注目ポイント": f"{r.grade}レース",
    }
```

### 4B. ページ設定 (L42-47)
- `page_title` → `"重賞予想アプリ"`

### 4C. `get_all_horse_names()` (L167-177)
- 引数に `csv_path` を追加、ハードコード `CSV_FILE` を除去
- **全呼び出し元**で `get_csv_path()` を渡すように統一

### 4D. `filter_relevant_videos()` (L246-268)
- `race_keywords` をレース名・会場・距離から動的生成

### 4E. `extract_horse_names_from_text()` (L364)
- `FEATURED_HORSES` への依存を撤去（CSVの馬名リストのみ使用）

### 4F. Geminiプロンプト関数（約6箇所）
すべての「フェブラリーステークス2026」を `get_race_display_name()` + レースメタデータに置換:
- `analyze_video_with_gemini` (L575)
- `search_web_articles` (L698)
- `analyze_web_article_with_gemini` (L822付近)
- `get_race_characteristics_with_gemini` (L1229) — **引数に `race_name, grade, venue, distance, surface, date` を追加し、レースごとに別キャッシュ化**
- `analyze_document_for_race_characteristics` (L1293)
- `analyze_document_for_horses` (L1332) — ハートボンド固有のエイリアス指示を削除
- `fetch_and_analyze_web_articles` (L1086) — 馬バッチクエリのレース名

### 4G. `aggregate_horse_analysis()` (L923)
- `HORSE_NAME_ALIASES` への依存を撤去（エイリアスなしで動作するように）
- `FEATURED_HORSES` ベースのソートを削除（情報源数ソートのみ）

### 4H. `check_password()` (L1427)
- `"🏇 フェブラリーステークス 2026 予想アプリ"` → `"🏇 重賞予想アプリ"`

### 4I. `fetch_odds_and_gates()` (L1514)
- `RACE_URL` の参照を `get_race_url()` に置換

### 4J. `display_sidebar()` (L1705-1746)
**大幅な再構成:**
1. **レースセレクター追加**（サイドバー最上部）: `st.sidebar.selectbox` で重賞一覧から選択
2. レース情報をレースメタデータから動的表示
3. 応援メッセージを汎用化（レース名を動的に挿入）
4. 注目馬セクション: `horse_df` がある場合は情報源数上位3馬を表示、なければ非表示（`FEATURED_HORSES` 依存を完全撤去）

### 4K. `display_main_content()` ヒーローバナー (L2043-2053)
- レース名・日付・会場・距離・グレードを全て `get_race_config()` から動的に

### 4L. Web検索クエリ (L2183-2194)
- 9つのハードコードクエリを `get_race_display_name()` で動的生成
- 注目馬固有のクエリ（ダブルハートボンド等）を削除し、CSVから馬名を動的追加

### 4M. デフォルト検索キーワード (L2164, L2462)
- `"フェブラリーステークス 2026 予想"` → `f"{get_race_display_name()} 予想"`

### 4N. `main()` 関数 (L2670+)

**フロー変更:**
1. パスワード認証（既存）
2. **レース選択チェック**: `selected_race` がなければレース一覧取得＆選択UI表示
3. **レース変更検出**: `prev_race_id` と比較し、変更時はセッションステートクリア
4. **race_id未解決チェック**: `race_id is None` なら「出馬表未発表」メッセージ表示して停止
5. **CSV自動取得**: 未取得なら `fetch_race_csv()` をspinner付きで実行。失敗時はエラーメッセージ表示
6. レース特徴初期化: `get_race_characteristics_with_gemini()` で動的取得。**失敗時は `get_minimal_race_characteristics()` をフォールバックとして保持**
7. 既存の枠番取得・データ読み込み・表示（CSV_FILEを `get_csv_path()` に）
8. サンプルデータのハードコード馬名を汎用的なものに変更

### 4O. セッションステートクリア（レース切替時）

```python
RACE_SESSION_KEYS = [
    'horse_df', 'youtube_videos', 'youtube_raw', 'youtube_summary_df',
    'web_articles', 'web_raw', 'race_characteristics', 'gates_saved',
    'yt_detail_analysis', 'doc_horse_raw', 'win_rates', 'latest_odds_error',
    'latest_odds', 'combined_keyword', 'yt_detail_keyword',
]

def on_race_change():
    for key in RACE_SESSION_KEYS:
        st.session_state.pop(key, None)
    get_all_horse_names.clear()
    load_race_data.clear()
```

---

## 5. ドキュメント更新

### `CLAUDE.md`
- プロジェクト概要を「任意の重賞予想アプリ」に変更
- ファイル構成に `race_catalog.py`, `data/` を追加
- `FEATURED_HORSES`, `RACE_INFO_FROM_DOC` の記述を削除
- データフローにレース選択ステップを追加
- 新しいPublic APIs（`fetch_graded_races`, `resolve_race_id`, `fetch_race_csv`）を記載

### `APP_FUNCTIONS_MANUAL.md`
- 「任意重賞」前提に更新

---

## 修正対象ファイル一覧

| ファイル | 変更種別 |
|---|---|
| `race_catalog.py` | **新規作成** |
| `data/` | **新規ディレクトリ** |
| `.gitignore` | `data/` 追加 |
| `get_keiba_info.py` | 修正（`fetch_race_csv()` 追加、argparse対応） |
| `app.py` | 大幅修正（~30箇所のハードコード置換 + レース選択UI + 状態分離） |
| `CLAUDE.md` | 更新 |
| `APP_FUNCTIONS_MANUAL.md` | 更新 |

---

## 前提条件

- netkeiba のDOMは月次スケジュール/特別レースページで取得可能である（外部接続制限のため未実測）
- CSV列スキーマ（`枠番, 馬番, 馬名, 性齢, 斤量, 騎手, 調教師, オッズ`）は維持する
- 出馬表未公開レースは `race_id` 未解決（`None`）として扱う
- 既存の `february_s_info.csv` を直接使う従来運用が壊れない（後方互換）

---

## 検証方法

### 正常系
1. `streamlit run app.py` で起動
2. サイドバーにレース一覧が表示されることを確認
3. 直近の重賞を選択 → 出馬表が自動取得・表示されることを確認
4. タイトル/サイドバー/検索文言が選択レースに一致することを確認
5. 情報入力タブでWeb検索 → 選択したレースの情報が取得されることを確認
6. 別のレースに切り替え → `horse_df/web_articles/latest_odds` が混在しないことを確認

### 失敗系
7. `race_id` 未解決でクラッシュせず「出馬表未発表」を表示
8. Gemini APIキー未設定・429時もレース特徴タブが最低限表示される（`get_minimal_race_characteristics` フォールバック）
9. `fetch_race_csv` 失敗時にユーザー向けエラーメッセージが表示される

### 回帰
10. `february_s_info.csv` を直接使う従来運用が壊れない
11. `fetch_odds_and_gates` が選択中 `race_id` の URL を参照する

---

## 実装確定仕様（追補）

- キャッシュ方式は `functools.lru_cache` で統一。
  - `fetch_graded_races` は内部で `_fetch_graded_races_cached` を使用。
  - `resolve_race_id` は内部で `_resolve_race_id_cached` を使用。
- `resolve_race_id` の公開シグネチャは互換性優先で維持。
  - `resolve_race_id(race: RaceInfo) -> str | None`
- `race_id` 再試行導線を `app.py` に追加。
  - `race_id` 未解決画面で「レースIDを再取得」ボタンを表示。
  - 再試行時は `clear_resolve_race_id_cache()` でキャッシュをクリアしてから再取得。
- `date_str` は `YYYY/MM/DD(曜)` 形式へ統一。
  - スケジュール取得時に同形式で生成。
  - 手動入力レースでも同形式を設定。


---


---

## Additional Fixes (2026-03-26)

### Background
Additional issues were found during Playwright regression checks.

- Invalid `special_url` values could trigger `LocationParseError` during `race_id` resolution.
- On Windows (`cp932`), `get_keiba_info.py` logging with check/cross symbols could raise `UnicodeEncodeError`.
- On race switch, `combined_keyword` could retain the previous race value.

### Implemented Changes

#### `race_catalog.py`
- Added `_normalize_special_url()` to normalize/validate `special_url`.
- Applied normalization both when parsing schedule links and right before `resolve_race_id` fetch.
- Invalid URLs now safely fall back to `None`.
- Added handling for `ValueError`-class URL parse failures (LocationParseError-equivalent path).

#### `get_keiba_info.py`
- Replaced check/cross log symbols with `[OK]/[NG]`.
- Removed cp932-incompatible output characters to avoid Windows console crashes.

#### `app.py`
- Made race-scoped widget keys for keyword inputs:
  - `combined_keyword` -> `combined_keyword::{race_key}`
  - `yt_detail_keyword` -> `yt_detail_keyword::{race_key}`
- Extended `_on_race_change()` to clear race-scoped widget keys by prefix:
  - `combined_keyword::`
  - `yt_detail_keyword::`

### Playwright Verification
- No recurrence of `LocationParseError` after login.
- Verified race switch clears previous race keyword state.
- Measured result:
  - before: `SESSION_CLEAR_MARKER_WEB_ONLY_12345`
  - after: `Tulip Sho 2026 prediction`
  - verdict: `WEB_CLEARED = True`

### Files Updated (Additional)
- `race_catalog.py`
- `get_keiba_info.py`
- `app.py`
- `CHANGES.md`

---

## Additional Fixes (2026-03-30)

### Background
Search results had been effectively session-scoped, so re-login and cross-device checks could appear incomplete.  
To reduce update time and API calls, we added persistence and incremental merge behavior for race search results.

### Implemented Changes

#### `app.py`
- Added cache IO helpers:
  - `_get_cache_path(race_key)`
  - `_raw_fingerprint(item)`
  - `save_race_cache(race_key)`
  - `load_race_cache(race_key)`
- Changed "Web batch search" from replace-all to merge-by-diff:
  - Keep existing results.
  - Add only new items after dedupe.
  - Rebuild `horse_df` from merged raw sources.
- Added automatic restore on app load/re-login:
  - Use `web_raw` presence as sentinel.
  - Load cache for the selected race key when session is fresh.
- Wired cache save calls into related flows:
  - After Web batch search.
  - After document race-characteristics extraction.
  - After document horse extraction.
  - After document-horse reset.
  - After race-characteristics refresh action.
  - After successful race-characteristics web fetch in `main()`.

#### `.gitignore`
- Updated data policy to keep `data/search_cache/` under Git while still ignoring generated CSV/log artifacts.

### Known Limitations / Notes
- YouTube detail state (for example `yt_detail_analysis`) is not persisted yet, so cross-device depth can still differ.
- Dedupe currently prioritizes `url`/`source_url` with title fallback; false positives/negatives are still possible.
- For device-to-device checks, use the server host IP (not `localhost`) from other devices.
- Current implementation includes auto `git add`/`git commit` during cache save; this is an operational caveat.

### Verification
- Confirmed section append keeps Markdown hierarchy and existing content intact.
- Confirmed notes are aligned with current code paths in `app.py` and `.gitignore`.
- Confirmed this update is documentation-only and does not alter runtime behavior.

### Files Updated (Additional)
- `CHANGES.md`

---

## Markdownレポート出力機能追加 (2026-04-03)

### Background
6タブ分の情報（出馬表・レース特徴・総合予想・追切評価）をサイドバーのボタン1つでMarkdownファイルとしてダウンロードできる機能を追加した。

### Changes (`app.py`)
- `generate_markdown_report(df)` 関数を追加（`aggregate_training_data()` 直後）
  - 引数 `df`: `load_race_data()` 済みの出馬表DataFrame（再読み込みなし）
  - 出馬表: 枠/馬番/馬名/性齢/斤量/騎手/調教師をMarkdownテーブルで出力
  - レース特徴: `race_characteristics` の全キーを見出し+本文形式で出力
  - 総合予想: `horse_df` を馬名見出し+プラス/マイナス本文形式で出力（テーブル不使用、改行・記号の崩れ回避）
  - 追切評価: `training_items` をMarkdownテーブルで出力（`|` → `｜`、改行除去でテーブル崩れ回避）
- `display_main_content(df)` 末尾に `with st.sidebar:` ブロックを追加
  - `display_sidebar()` は `load_race_data()` より前に呼ばれるため、df 取得後の `display_main_content` 内でサイドバーにボタンを描画
  - `st.download_button("📄 Markdownレポート出力", ...)` をサイドバー末尾に配置
  - ファイル名: `{レース名}_{年}_予想レポート.md`（空白→`_`、`/`→`-`）

---

## 追切結果・評価タブ追加 + X監視アカウント更新 (2026-04-03)

### Background
Web/X/YouTubeの馬別分析結果に追切・調教情報が混在しているため、専用タブに集約して一覧確認できるようにした。
あわせてX監視アカウントを実運用向けに更新し、大阪杯（2026-04-05）の検索キャッシュを追加。

### Implemented Changes

#### `app.py`
- `_TRAINING_KEYWORDS` 定数を追加（追切/調教/坂路/ウッド等の正規表現）
- `aggregate_training_data()` 関数を追加:
  - `web_raw`, `x_raw`, `youtube_raw`, `yt_detail_analysis` から追切キーワード含む行を抽出
  - `_to_text()` で文字列化、完全一致重複排除（6キーのtuple）、馬名昇順ソート
- `RACE_SESSION_KEYS` に `training_items` を追加（レース切替時クリア対象）
- `save_race_cache()` に `training_items` / `yt_detail_analysis` の保存を追加
- `load_race_cache()` に `yt_detail_analysis` 復元と `aggregate_training_data()` 再生成を追加
- 更新トリガーを5箇所に追加（Web検索後・X検索後・Xリセット後・YouTube詳細分析後・キャッシュ読込後）
- `st.tabs` を6タブに拡張し「🏋️ 追切結果・評価」タブを追加
- 追切タブ表示: DataFrame一覧（馬名/種別/評価内容/情報源）+ 出典リンクexpander

#### `x_accounts.json`
- 監視アカウントをプレースホルダーから実運用アカウントに更新:
  - ちかさん@競馬展開予想 (`chika_tenkai`)
  - ユキムラ【6連続G1本命馬券内】 (`yukimura_g1`)
  - けんしろう (`kenshiro_ytb`)
  - アキラ｜トラックバイアス (`akira_trackbias`)
  - 超越者リットマン (`rittman_keiba`)
  - かっち@競馬 (`kacchi_keiba`)

#### `data/search_cache/`
- `2026-04-05_阪神_大阪杯.json` を追加（大阪杯の検索結果キャッシュ）

### Files Updated (Additional)
- `app.py`
- `x_accounts.json`
- `data/search_cache/2026-04-05_阪神_大阪杯.json`
- `CHANGES.md`

---

## 総合動作検証 + 仕様整理（2026-04-03）

### Verification
今回の差分（Xフィルタ強化、追切タブ、前回レース自動復元を含む）について、以下を実施。

| 検証項目 | 結果 | 補足 |
|---|---|---|
| `python -m py_compile app.py race_catalog.py get_keiba_info.py` | ✅ 成功 | 構文エラーなし |
| Streamlit起動スモーク（`streamlit run app.py --server.headless true --server.port 8510`） | ✅ 成功 | `http://127.0.0.1:8510` が HTTP 200 を返すことを確認 |
| 重賞一覧取得（`get_upcoming_races`） | ✅ 成功 | 直近重賞が取得できることを確認 |
| Xレース名フィルタ（ユニット） | ✅ 成功 | 対象レース投稿のみ残り、他レース投稿が除外されることを確認 |
| うましる追切テーブル抽出（ユニット） | ✅ 成功 | `時期/場所/6F/5F/4F/3F/1F/脚色` の構造化行を抽出できることを確認 |
| 前回レースキー保存/読込（ユニット） | ✅ 成功 | `data/last_selected_race.json` 経由で復元可能であることを確認 |

### 仕様整理（今回の主要挙動）
- X投稿は取得後・表示前・キャッシュ読込時の3段階で「対象レース名に言及する投稿のみ」を残す。
- 追切タブは「うましる優先 + 不足馬のWeb補完」でタイム行を構築する。
- 追切コメントのプラス/マイナスは従来どおり `web / YouTube / X (+ YouTube詳細)` 由来で追切関連文のみを表示。
- アプリ起動時、`data/last_selected_race.json` に保存された前回レースを優先して自動選択・自動ロードする。

### APIキー使用量目安（1操作あたり）
実装コードベースの呼び出し回数目安。実際の課金は契約プラン・リトライ・キャッシュヒット率で増減する。

| 操作 | 使用キー | 1回あたりの呼び出し目安 | 備考 |
|---|---|---|---|
| アプリ初回起動時のレース特徴自動取得 | `GEMINI_API_KEY` | 0〜1回 | セッション未初期化かつキャッシュ未命中時のみ |
| `🔍 Web 一括検索` | `TAVILY_API_KEY` | 検索クエリ数分（概ね 10〜20回） | `9固定 + 馬名バッチ` のクエリを順次検索 |
| `🔍 Web 一括検索`（Tavily失敗時フォールバック） | `GEMINI_API_KEY` | 検索クエリ数分（最大同程度） | Gemini Web Search フォールバック |
| `🔍 Web 一括検索`（記事解析） | `GEMINI_API_KEY` | 1〜`total_article_limit` 回（既定20） | 解析対象記事ごとに1回 |
| `𝕏 X投稿を検索`（投稿取得） | `X_BEARER_TOKEN` | 1〜数回（通常）〜十数回（多ページ） | クエリ分割・ページング・再試行で変動 |
| `𝕏 X投稿を検索`（投稿解析） | `GEMINI_API_KEY` | 1回 | 取得投稿をバッチ解析 |
| `🏋️ 追切専用情報を追加取得`（うましる検索） | `TAVILY_API_KEY` | 0〜1回 | 失敗時はGemini検索へフォールバック |
| `🏋️ 追切専用情報を追加取得`（不足馬補完検索） | `TAVILY_API_KEY` | 1〜`1 + ceil(不足馬/4)` 回 | 不足馬のみクエリ生成 |
| `🏋️ 追切専用情報を追加取得`（補完記事解析） | `GEMINI_API_KEY` | 0〜`training_article_limit` 回（既定15） | 記事ごとの馬別抽出 |
| `🔍 YouTube検索` | `YOUTUBE_API_KEY` | 1回 | `search().list()` 1回 |
| YouTube動画ごとの `読み込み+概要取得` | `GEMINI_API_KEY` | 1回/クリック | 動画1本ごとに1回 |
| `📊 ドキュメントからレース特徴を抽出` | `GEMINI_API_KEY` | 1回 | ドキュメント1件あたり |
| `🐴 ドキュメントから馬別情報を抽出` | `GEMINI_API_KEY` | 1回 | ドキュメント1件あたり |
| `🔄 レース特徴をWeb再取得`（次回起動時） | `GEMINI_API_KEY` | 1回 | `race_characteristics` を消した後の再取得 |
| `🔄 最新オッズを取得` / 出馬表CSV取得 | APIキー不要 | 0回 | `netkeiba` へのHTTP/Playwrightアクセス |

### Cost Notes
- X APIの課金単位は契約プラン依存（ツイート単価課金プランでは取得件数に比例）。
- Gemini / YouTube / Tavily もプラン・モデル・入力/出力トークン量で変動。
- このアプリは `st.cache_data` とレースキャッシュで再実行を抑制する設計。

---

## 追加修正（2026-04-07）

### Background
直近の運用で、YouTube要約品質、出馬表の枠順/オッズ反映、Markdownレポート出力内容の不足が確認されたため、
既存機能を壊さずに品質改善と永続化挙動の補強を行った。

### Implemented Changes

#### `app.py`
- YouTube要約専用モデルを切り出し:
  - `GEMINI_MODEL_YOUTUBE`（環境変数）を追加し、既定値を `gemini-3.1-flash` に設定。
  - `_youtube_model_candidates()` / `_generate_content_with_youtube_model()` を追加し、YouTube処理のみ専用モデル経由に変更。
- レースキャッシュのオッズ情報を保存/復元対象に追加:
  - `latest_odds`, `latest_odds_error` を `save_race_cache()` / `load_race_cache()` に連携。
- レース読込時の自動反映を強化:
  - 枠順・オッズの自動取得後、取得済みオッズを表示データとCSVへ反映し、次回起動用キャッシュへ保存。
- Markdownレポート出力を拡張:
  - 出馬表にオッズ列を含めて出力。
  - 追切タイム（馬別・時期別）と追切コメント（プラス/マイナス）を出力。
  - `nan` 相当値は `-` に正規化して可読性を改善。

#### `get_keiba_info.py`
- netkeibaのクラス名揺れ対策を追加:
  - `class='Waku1'`, `class='Umaban1'` など接尾辞付きクラスを拾える `_find_td_by_class_prefix()` を追加。
  - これにより枠順/馬番が `不明` になりやすいケースを改善。

#### `x_accounts.json`
- 監視アカウント設定を運用中の構成に更新（6アカウント、`default_max_tweets=30`）。

### Verification
- `rg` で以下の実装点を確認:
  - YouTube専用モデル切替 (`GEMINI_MODEL_YOUTUBE`, `_generate_content_with_youtube_model`)
  - オッズ永続化キー (`latest_odds`, `latest_odds_error`) の保存/復元
  - 枠順抽出補強 (`_find_td_by_class_prefix`)
  - レポート出力 (`generate_markdown_report`) の追切・オッズ関連反映

### Files Updated (Additional)
- `app.py`
- `get_keiba_info.py`
- `x_accounts.json`
- `CHANGES.md`
