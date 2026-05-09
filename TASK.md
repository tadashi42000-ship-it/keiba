# TASK Progress Tracker

## Project Snapshot
- Date (JST): 2026-05-05
- Branch: `same-day-mode`
- Current phase: 当日モード実用化完了直後 / 重賞モードは legacy Streamlit で継続利用
- Recent updates:
  - 5/3東京現地利用向けのNext.js/PWA当日モードを整備済み。全Rシート、詳細キャッシュ、単勝オッズ同期、AI共有Markdown、近3走の走破タイム/指数/レースレベル/開催場所を確認済み
  - PCで重賞モードを使う場合は `legacy/streamlit_app` のStreamlit版を起動する。Next.js/PWA版は現時点では当日モード中心
  - 次回作業前に未コミット変更を確認し、必要なら `git add . && git commit -m "backup same-day mobile updates"` で退避する
  - 品質向上フェーズ完了: T-LS-06〜T-LS-10（Gemini 404/YouTube自動解析/買い目スコア統合/Web多様化/E2E）すべて Done
  - Session-QUALITY-004 で 皐月賞 E2E (`errors=[]`, `404=0`, `parse_fail=0`, `bet_generate_success=true`) 達成
  - 新プラン採択: 当日レースモード（任意の開催日・会場を指定し 1R〜12R 単位で予想）
  - Session-SAMEDAY-004 で T-SD-01〜T-SD-08 を完了（race_key衝突解消、same-day selector、近3走連携、E2E回帰）
  - 当日モード情報源は netkeiba 主体（Umanity 平レースは URL 未確定のため空実装フォールバック）
  - YouTube検索を同名平レース向けに強化（開催日・会場・R番号をクエリ補完、非対象会場/日付の動画を除外）
  - Session-SAMEDAY-006 で T-SD-09〜T-SD-12 を完了（馬データ/追切/コース統計/脚質判定）。4/26 東京5R・6Rの Playwright 実測で `馬別情報 26件/27件` を確認
  - Session-SAMEDAY-007 で当日現地向け出馬表を補強（初回オッズ軽量化、rerun後成功表示、発走/馬場メタ、斤量修正、馬体重列、上がり3F、脚質分布）。4/26 東京5R・6Rで Playwright 確認済み
  - Session-SAMEDAY-008 で当日モードのレース読込時に脚質/前走/オッズを自動補完。4/26 東京4Rで Playwright 確認済み。Web一括検索のYouTube同時取得は当日モードでは無効化
  - Session-SAMEDAY-009 で「レース30分前に買う馬を決める」視点の検証を実施。馬番未確定時の買い目タブを暫定候補馬ランキングへフォールバックし、コース特徴の脚質表現矛盾を修正
  - Session-SAMEDAY-010 で脚質判定を4角順位+頭数比率へ修正。4/26東京4Rを基本情報取得で再生成し、脚質分布 `先行1 / 差し6 / 追込1 / 自在2` と枠別Markdown割合表をPlaywright確認
  - Session-MOBILE-SD-001 で legacy 当日モードの中核機能を FastAPI + Next.js PWA へ移植。4/26東京4Rをスマホ幅 Playwright で検証し、出馬表/脚質分布/近3走/上がり3F/特徴/枠別割合/候補ランキング/YouTube非自動実行を確認
  - Session-MOBILE-SD-002 で移植計画の実装検証を実施。4/26東京4R/5R/6RのAPI実測でレース一覧・entry・course-stats・bet-planは動作、単勝オッズ/馬体重は引き続き未公開扱いで警告表示
  - Session-MOBILE-SD-003 で 4/26 01:02 JST 時点の再チェックを実施。東京4R/5R/6Rは馬番/脚質/近3走/買い目候補まで正常、単勝オッズ/馬体重は引き続き未公開
  - Session-MOBILE-SD-004 で東京全12Rの現地用記録シート生成を実装・実行。`data/same_day_sheets/2026-04-26_tokyo_same_day_sheet.md/json` を作成
  - Session-MOBILE-SD-005 でPWA内に全Rシートページを追加。キャッシュ優先APIで5秒以内に東京12R一覧をスマホ幅表示確認
  - Session-REPO-001 で検証副産物のGit管理混入を整理。`tmp/` とPlaywright/スクショ生成物を追跡対象外へ移行し、backend/frontend検証を再実行
  - Session-MOBILE-SD-014 で 5/3 東京現地運用向けに全Rシート/詳細キャッシュを調整。候補指数表示、localStorage詳細キャッシュ、オッズのみ軽量更新を確認
  - Session-MOBILE-SD-016 で5R以降の全Rシートキャッシュを確認し、詳細ページ初回もサーバー側シートキャッシュから即表示するよう変更
  - Session-MOBILE-SD-017 で当日モード詳細に近3走の走破タイム/タイム指数/レースレベル/着差を追加。5/3東京シートキャッシュを新形式へ更新
  - Session-MOBILE-SD-018 でR詳細ページ上部にAI共有用Markdownコピー機能を追加。5/3東京5RでMarkdown生成とコピー成功をPlaywright確認

## Quick Handoff
| Item | Current state / command |
|---|---|
| Active branch | `same-day-mode` |
| Must-read sections next time | `Project Snapshot`, `Quick Handoff`, latest `Session Log` |
| Current main product | `frontend` + `backend` のNext.js/PWA当日モード |
| Legacy product | `legacy/streamlit_app/app.py` のStreamlit重賞モード |
| Run Streamlit graded mode | `cd C:\WORK\keiba\legacy\streamlit_app; python -m streamlit run app.py` |
| Streamlit URL/password | `http://localhost:8501` / `7777` |
| Run mobile PWA local/tunnel | `powershell -ExecutionPolicy Bypass -File scripts\start_mobile_pwa.ps1 -Date 2026-05-03 -Venue 東京 -SkipBuild` |
| Stop mobile PWA/tunnel | `powershell -ExecutionPolicy Bypass -File scripts\stop_mobile_pwa.ps1` |
| Backend validation | `cd backend; python -m pytest tests -q` |
| Frontend validation | `cd frontend; npm run lint; npm run build` |
| Known caveat | Cloudflare quick tunnel URL is temporary and changes after restart |
| Known caveat | PowerShellに日本語引数を直書きすると文字化けする場合あり。URLエンコードまたはUnicode escapeを使う |
| Known caveat | 2・3走前のタイム指数はnetkeiba側が空欄なら `指数なし` |
| Backup rule | 作業終了時は `git status --short --branch` を確認し、必要ならコミット/プッシュして退避 |

### Current Uncommitted Work To Preserve
- `TASK.md`
- `backend/app/schemas/races.py`
- `backend/app/services/same_day_service.py`
- `frontend/src/app/races/[raceKey]/page.tsx`
- `frontend/src/app/same-day-sheet/page.tsx`
- `frontend/src/components/mobile/external-workbench-card.tsx`
- `frontend/src/lib/api/types.ts`
- `frontend/src/components/mobile/same-day-sheet-client.tsx`（new file）

### Next Recommended First Action
1. `git status --short --branch` で未コミット変更を確認する。
2. 変更を残す場合は `git add .; git commit -m "backup same-day mobile updates"; git push` で退避する。
3. 重賞モード利用なら Streamlit、当日モード利用なら `scripts/start_mobile_pwa.ps1` を起動する。

## Milestones
| ID | Milestone | Target state | Progress % | Status | Due | Notes |
|---|---|---|---:|---|---|---|
| M1 | Foundation | FastAPI v1 + Next.js/PWA baseline | 100 | Done | 2026-04-20 | Completed |
| M2 | Race UI expansion | List/detail + CSV/odds operation UI | 100 | Done | 2026-04-27 | Completed |
| M3 | Streamlit logic migration | characteristics/cache normalization as APIs | 100 | Done | 2026-05-11 | same-day mode + race-mode branching + cache/recent-runs integration completed |
| M4 | External API migration | Tavily/Gemini/YouTube/X moved to backend services | 85 | InProgress | 2026-05-25 | YouTube relevance and fallback hardening completed in legacy flow |
| M5 | Deployment operations | Vercel/Render operational verification | 78 | InProgress | 2026-04-30 | full local stack checks passed; staging URL run pending |
| M6 | Legacy Streamlit stabilization | Satsuki Sho tabs (YouTube/report/bet plan) stable for practical use | 100 | Done | 2026-04-22 | Playwright E2E + cache verification completed (Web/YouTube/report/bet-plan/training sanity) |
| M7 | Mobile same-day mode | On-site 30-min-before flow in Next.js PWA | 99 | InProgress | 2026-04-26 | 5/3 Tokyo 5R+ cached with odds, course stats, candidate ranking, and recent-run time/index details |

## Task Board
| TaskID | Area | Task | Status | Progress % | Priority | Depends on | Next action | Owner |
|---|---|---|---|---:|---|---|---|---|
| T-M1-01 | Frontend | Next.js + PWA scaffold | Done | 100 | P0 | - | Verified (`lint/build`) | Codex |
| T-M1-02 | Backend | `/health`, `/api/v1/*`, `/races/*` baseline APIs | Done | 100 | P0 | - | Verified (`pytest`) | Codex |
| T-M1-03 | Docs | README + migration docs baseline | Done | 100 | P1 | T-M1-01,T-M1-02 | Continuous updates only | Codex |
| T-M2-01 | Frontend | Race list workbench UI | Done | 100 | P0 | T-M1-01,T-M1-02 | Verified | Codex |
| T-M2-02 | Frontend | Odds/table operation UX | Done | 100 | P1 | T-M2-01 | Verified | Codex |
| T-M2-03 | Frontend | Race detail route | Done | 100 | P1 | T-M2-01,T-M2-02 | Verified | Codex |
| T-M2-04 | Frontend | Detail-page behavior refinements | Done | 100 | P1 | T-M2-03 | Verified | Codex |
| T-M2-05 | Frontend | Mojibake cleanup in race UI strings | Done | 100 | P0 | T-M2-04 | Replaced corrupted strings + verified (`lint/build`, Playwright snapshot) | Codex |
| T-M2-06 | Frontend/Backend | Upcoming races support past 7 days (`days_back`) | Done | 100 | P0 | T-M2-03 | Added API/UI support + tests (`pytest`, `lint`, `build`) | Codex |
| T-M3-01 | Backend | `race_characteristics` API | Done | 100 | P0 | T-M1-02 | Verified | Codex |
| T-M3-02 | Backend | Cache read/write wrapper API | Done | 100 | P1 | T-M3-01 | Verified | Codex |
| T-M3-03 | Frontend | Cache API wiring in detail page | Done | 100 | P1 | T-M3-02 | Verified (`lint/build`) | Codex |
| T-M3-04 | Backend | Cache payload validation hardening | Done | 100 | P1 | T-M3-02 | Verified (`pytest`) | Codex |
| T-M3-06 | Backend | Cache filename sanitization hardening | Done | 100 | P0 | T-M3-02 | Invalid-char race_key handled + test added (`pytest`) | Codex |
| T-M4-01 | Backend | Tavily/Gemini abstraction | Done | 100 | P0 | T-M3-02 | Verified | Codex |
| T-M4-02 | Backend | YouTube/X summary/search APIs | Done | 100 | P1 | T-M4-01 | Verified (`pytest`) | Codex |
| T-M4-03 | Frontend | External API workbench UI | Done | 100 | P1 | T-M4-02 | Verified (`lint/build`) | Codex |
| T-M4-04 | Backend | YouTube/X horse-analysis APIs | Done | 100 | P0 | T-M4-02 | `/external/*/horse-analysis` verified (`pytest`) | Codex |
| T-M4-05 | Backend | YouTube race relevance filtering refactor | Done | 100 | P0 | T-M4-04 | strict race filter + fallback query candidates + tests (35 passed) | Codex |
| T-M3-05 | Backend | `resolve-id` fallback strategy (out-of-window races) | Done | 100 | P0 | T-M3-01 | Added date-window fallback + tests (`pytest`) | Codex |
| T-M5-01 | Infra | Deployment verification flow (Render/Vercel) | InProgress | 80 | P1 | T-M1-03 | Run `scripts/check-stack.ps1` against real staging URLs | User+Codex |
| T-M5-02 | Docs | `.env` source-of-truth operations | Done | 100 | P2 | T-M1-03 | `docs/migration/env-operations.md` added | Codex |
| T-M5-03 | Infra | CI automation (backend+frontend) | Done | 100 | P1 | T-M1-01,T-M1-02 | `.github/workflows/ci.yml` added | Codex |
| T-M5-04 | Infra | Repository hygiene for generated verification artifacts | Done | 100 | P1 | T-M1-01,T-M1-02 | `.gitignore` hardened + `tmp/` removed from Git index; verified (`pytest`, `lint`, `build`) | Codex |
| T-LS-01 | Legacy Streamlit | Umanity-first race characteristics + fallback flow | Done | 100 | P0 | T-M3-05 | Primary scraping path stabilized, fallback retained | Codex |
| T-LS-02 | Legacy Streamlit | Entry table enrichment from Umanity racecard (前走〜3走前) | Done | 100 | P0 | T-LS-01 | Added racecard mapping + horse-wise merge + weight backfill | Codex |
| T-LS-03 | Legacy Streamlit UI | Improve past-race readability and add odds sort control | Done | 100 | P0 | T-LS-02 | Added rank-focused rendering + `馬番/オッズ昇順/オッズ降順` toggle + Playwright check | Codex |
| T-LS-04 | Legacy Streamlit Report | Exclude budget bet plan section from Markdown report | Done | 100 | P1 | T-LS-03 | Removed `💰 予算別買い目プラン` from `generate_markdown_report` | Codex |
| T-LS-05 | QA | Claude Code validation handoff (Satsuki Sho scenario) | InProgress | 60 | P0 | T-LS-01,T-LS-04 | Run checklist in `Claude Code Verification Checklist` section | User+Claude Code |
| T-LS-06 | Legacy Streamlit | Fix Gemini 404 cascade (GEMINI_MODEL_WEB_FALLBACK + retry loop) | Done | 100 | P0 | T-LS-05 | app.py:93 fallback → `gemini-2.5-flash-lite` + app.py:4261-4270 non-transient 即break; compile OK + test_playwright 8/8 PASS | Claude Code |
| T-LS-07 | Legacy Streamlit | Auto-run YouTube per-horse analysis in Tab2 bulk search | Done | 100 | P0 | T-LS-06 | app.py:7109-7127 で `added_videos` を `analyze_all_videos_with_gemini` に渡し `youtube_raw`/`youtube_summary_df` にマージ + help 文更新; compile OK + test_playwright 8/8 PASS | Claude Code |
| T-LS-08 | Legacy Streamlit | Integrate Umanity race_characteristics into bet-plan score | Done | 100 | P0 | T-LS-07 | app.py:5944-6009 frame/style bonus helpers + stats 統合 + app.py:6045-6060 フロア補正 + app.py:6085-6100 券種別 pool_size(単勝/複勝/ワイド/馬連=8, 三連複=10, 三連単=8); compile OK + test_playwright 8/8 PASS | Claude Code |
| T-LS-09 | Legacy Streamlit | Web article per-horse coverage boost (IS-007) | Done | 100 | P1 | T-LS-06 | `MAX_ANALYZE_ARTICLES_PER_QUERY` を 5へ増加、`_get_uncovered_horse_names` 新設、`_select_articles_for_analysis` に未カバー馬ヒット +2.0 を実装。`python -m py_compile legacy/streamlit_app/app.py` と `python legacy/streamlit_app/test_playwright.py` 8/8 PASS で回帰なし。 | Codex |
| T-LS-10 | QA | E2E 検証: 皐月賞シナリオ再生成 | Done | 100 | P0 | T-LS-06,T-LS-07,T-LS-08,T-LS-09 | Playwright実走で `errors=[] / 404=0 / parse_fail=0 / bet_generate_success=true` を確認。買い目は推定オッズ補完警告を表示しつつ `三連複/三連単/単勝/馬連/ワイド` 各2点で計10点を生成。 | User+Codex |
| T-SD-00 | Research | 当日モード実装前の URL/挙動調査（最優先） | Done | 100 | P0 | - | 実測完了。`race_list_sub.html?kaisai_date=YYYYMMDD` で 1R〜12R の race_id 抽出可（JRA 3会場/36R）。`race_list.html` は JS 依存で静的抽出不向き。`newspaper.html/shutuba_past.html/data_top.html` は 200、`yoso_pro.html` は 404。Umanity は 12桁 race_id 直指定系 URL が 404（`race_8.php` は独自16桁コードのみ応答）。当日モードは netkeiba 主体で実装継続し、Umanity 平レースは空実装フォールバック。 | Codex |
| T-SD-01 | Legacy Streamlit | race_key 衝突修正 + `fetch_races_by_date` / `group_races_by_venue` 追加 | Done | 100 | P0 | T-SD-00 | `race_catalog.py` を更新し `RaceInfo.race_number` + `build_race_key` 導入。`test_same_day.py` で race_key 衝突防止/会場ソート検証を PASS。 | Codex |
| T-SD-02 | Legacy Streamlit | `fetch_recent_runs` 追加（shutuba_past.html 主経路 + horse 個別フォールバック） | Done | 100 | P0 | T-SD-00 | `get_keiba_info.py` に `fetch_recent_runs` 実装。`202606030811` 実測で 18頭分取得を確認（失敗時は空返却で継続）。 | Codex |
| T-SD-03 | Legacy Streamlit | `same_day_sources.py` 新規（netkeiba 中心、Umanity は T-SD-00 次第で条件付き） | Done | 100 | P0 | T-SD-00,T-SD-01 | `same_day_sources.py` 新設。`newspaper/shutuba_past/data_top` 取得 + Umanity は `return None` の安全フォールバックを実装。 | Codex |
| T-SD-04 | Legacy Streamlit UI | サイドバーのモード切替ラジオ + 日付/会場ピッカー + モード切替時の session クリア | Done | 100 | P0 | T-SD-01 | `race_mode` ラジオと same-day date/venue/race selector を追加。モード切替時に `RACE_SESSION_KEYS` + scoped key をクリア。 | Codex |
| T-SD-05 | Legacy Streamlit UI | 既存7タブ描画を `_display_main_content(race, race_widget_scope)` に関数化 + 未スコープ widget key を全面スコープ化 + 親タブ追加 | Done | 100 | P0 | T-SD-04 | `_display_main_content` 化と widget key 全面 `::{race_widget_scope}` 化を完了。親タブは DuplicateWidgetID リスク回避のため会場/レース selectbox 方式（5-d代替）を採用。 | Codex |
| T-SD-06 | Legacy Streamlit UI | 情報取得ボタン分岐 + レース特徴自動取得のモード分岐 | Done | 100 | P0 | T-SD-02,T-SD-03,T-SD-05 | Tab2 に `🏁 基本情報取得` / `📡 ネット情報取得` を追加。`race_mode==graded` ガードで当日モード自動リトライを停止。 | Codex |
| T-SD-07 | Legacy Streamlit UI | 出馬表タブに直近3走 3列を表示 | Done | 100 | P1 | T-SD-02 | `recent_runs::{race_key}` を CSV/UI に反映。same-day 実機で前走/2走前/3走前の表示更新を確認。 | Codex |
| T-SD-08 | QA | 新規静的テスト追加 + 当日モード E2E 手動検証 + 重賞モード回帰 | Done | 100 | P0 | T-SD-05,T-SD-06,T-SD-07 | `test_same_day.py` 4/4 PASS、`test_playwright.py` 8/8 PASS。Playwright手動で休催日空表示・当日モード動線・重賞モード回帰を確認。 | Codex |
| T-SD-09 | Legacy Streamlit | 馬データページ + 調教ページ取得を追加（馬別情報の底上げ） | Done | 100 | P0 | T-SD-08 | `same_day_sources.py` の文字化けを解消し `fetch_horse_profile` / `fetch_oikiri_comments` を安定化。`app.py` で空キャッシュ自動復旧フォールバックを追加。Playwright実測: 4/26 東京5R `馬別情報26件`、東京6R `馬別情報27件`。 | Codex |
| T-SD-10 | Legacy Streamlit | X 広域キーワード検索モード追加（レース名+騎手名 OR） | Done | 100 | P1 | T-SD-08 | `search_x_tweets_broad` / `fetch_and_analyze_x_tweets_broad` を導入し、same-day のXボタンを broad 経路へ分岐。`X_MAX_REQUESTS_PER_UPDATE` でリクエスト上限を制御。静的検証 `test_same_day.py` 6/6 PASS。 | Codex |
| T-SD-11 | Legacy Streamlit | 会場×距離の統計レース特徴（netkeiba コース別成績スクレイピング） | Done | 100 | P0 | T-SD-09,T-SD-12 | `fetch_course_stats` の会場コード・脚質/人気帯集計を復旧。`app.py` の same-day レース特徴へ統合済み。Playwright実測で東京5R/6Rとも `参照元を開く（netkeiba）` と枠順/脚質統計表示を確認。 | Codex |
| T-SD-12 | Legacy Streamlit | 直近3走通過順からのルールベース脚質判定 + 出馬表表示 | Done | 100 | P0 | T-SD-08 | `fetch_recent_runs` の `corners` を使う `classify_running_style` を反映。出馬表に `脚質` 列を表示し CSV互換維持。Playwright実測で東京5R/6Rとも `脚質` + `前走/2走前/3走前` を確認。 | Codex |
| T-SD-13 | QA | Phase 2 E2E 検証（T-SD-09〜12 統合） | InProgress | 70 | P0 | T-SD-09,T-SD-10,T-SD-11,T-SD-12 | 4/26 東京5R/6Rの E2E は完了（脚質列・近3走列・馬別情報>20件・コース統計表示）。残りは X取得件数>=5 と買い目 `frame_bonus/style_bonus` 非ゼロ複数馬の最終確認。 | Codex |
| T-SD-14 | Legacy Streamlit UI | 当日現地向けの出馬表補強（馬体重/上がり3F/発走・馬場/脚質分布） | Done | 100 | P0 | T-SD-12 | `fetch_race_csv` の斤量/馬体重分離、`fetch_recent_runs` の上がり3F追加、初回オッズ自動取得を static-only に軽量化、rerun後の成功表示を実装。`py_compile` / `test_same_day.py` 7/7 / `test_playwright.py` 8/8 / Playwright 4/26東京5R・6Rで確認。 | Codex |
| T-SD-15 | Legacy Streamlit UI | 当日モード読込時の出馬表自動補完 + Web一括検索YouTube除外 | Done | 100 | P0 | T-SD-14 | `_ensure_same_day_initial_entry_fields` を追加し、CSV既存時も race load で近3走/脚質/CSVオッズを補完。Web一括検索のYouTube同時取得UIを same-day では非表示・無効化。`py_compile` / `test_same_day.py` 7/7 / `test_playwright.py` 8/8 / Playwright 4/26東京4Rで確認。 | Codex |
| T-SD-16 | Legacy Streamlit UX | 当日30分前判断向けの買い目/特徴タブ補強 | Done | 100 | P0 | T-SD-15 | 馬番未確定時でも候補馬ランキングを暫定表示し、正式買い目は馬番取得後に促す。コース特徴は複勝率ベース/勝ち切り傾向を分離表示。Playwright 4/26東京4Rで `暫定候補馬ランキング` と新脚質メモを確認。 | Codex |
| T-SD-14 | Legacy Streamlit Phase 3 | 出走頭数抽出を recent_runs に追加（field_sizes） | Done | 100 | P0 | T-SD-12 | `_extract_field_size` を追加し、shutuba_past/horse page 両経路で `field_sizes` を返すよう拡張。古いキャッシュ互換は app 側フォールバックで維持。 | Codex |
| T-SD-15 | Legacy Streamlit Phase 3 | 当日モード脚質判定を4角順位+頭数比率へ修正 | Done | 100 | P0 | T-SD-14 | `_classify_corner_style(corner_text, field_size)` と `classify_running_style` を前走優先・自在控えめ方式へ変更。field_sizes 欠損時は絶対値フォールバック。 | Codex |
| T-SD-16 | Legacy Streamlit Phase 3 | 脚質判定/枠別Markdown表のテスト追加 | Done | 100 | P0 | T-SD-15 | `test_same_day.py` 10/10 PASS、`test_playwright.py` 8/8 PASS。Playwrightで4/26東京4Rの脚質分布改善と枠別Markdown割合表を確認。 | Codex |
| M-SD-01 | Mobile Backend | same-day一覧/entry/course-stats/bet-plan API追加 | Done | 100 | P0 | T-SD-14,T-SD-15,T-SD-16 | `/api/v1/races/same-day`, `/{race_id}/entry`, `/{race_id}/course-stats`, `/{race_id}/bet-plan` を追加。`pytest backend/tests` 39/39 PASS。 | Codex |
| M-SD-02 | Mobile Backend | legacy当日ロジックの純粋関数移植 | Done | 100 | P0 | M-SD-01 | Streamlit `app.py` は import せず、脚質判定/field_sizes fallback/枠別割合/候補ランキングを `backend/app/services/same_day_service.py` に移植。 | Codex |
| M-SD-03 | Mobile Frontend | スマホ向け当日レース選択/詳細タブUI | Done | 100 | P0 | M-SD-01 | ホームに当日レースモードを追加。詳細は `出馬表/特徴/買い目/外部情報` タブ、馬カード表示へ再設計。`npm run lint` / `npm run build` PASS。 | Codex |
| M-SD-04 | Mobile External | 当日モードのYouTube/X/Web自動実行抑止 | Done | 100 | P1 | M-SD-03 | 外部情報タブで手動実行に限定し、検索語に日付/会場/R番号/レース名を含める案内を表示。初回導線でYouTube自動実行なしをPlaywright確認。 | Codex |
| M-SD-05 | Docs/QA | TASK.md更新 + モバイルE2E検証 | Done | 100 | P0 | M-SD-01,M-SD-02,M-SD-03,M-SD-04 | 4/26東京4Rでスマホ幅Playwright確認。スクリーンショット `mobile-same-day-tokyo4-entry.png` 保存。オッズ未公開時は警告と `未公開` 表示。 | Codex |
| M-SD-06 | Mobile QA | 実装計画との差分検証 + 4/26東京4R/5R/6R API実測 | Done | 100 | P0 | M-SD-05 | 計画項目をコード/API/UI/テスト観点で照合。東京4R/5R/6Rで entry/course-stats/bet-plan を直接検証。`pytest` 39/39、`lint/build` PASS。 | Codex |
| M-SD-07 | Mobile Ops | 東京全12Rの現地用記録シート生成 | Done | 100 | P0 | M-SD-06 | `scripts/export_same_day_sheet.py` を追加し、2026-04-26東京12R分をMarkdown/JSONへ出力。Python UTF-8読込で全12R・候補上位・脚質分布を確認。 | Codex |
| M-SD-08 | Mobile Frontend | PWA内の全Rシート閲覧ページ | Done | 100 | P0 | M-SD-07 | `/same-day-sheet` を追加。通常は生成済みJSONキャッシュを即表示し、必要時のみ全R再生成。Playwrightスマホ幅で東京12R表示確認。 | Codex |
| M-SD-09 | Mobile Frontend/Backend | 5/3東京現地運用向けキャッシュ/オッズ更新調整 | Done | 100 | P0 | M-SD-08 | 全Rシートは候補指数表示、refreshは既存キャッシュのオッズのみ軽量更新、詳細はlocalStorageへ静的情報保存。`pytest` 42/42、`lint/build`、Playwright/tunnel確認済み。 | Codex |
| M-SD-10 | Mobile Frontend | 5R以降の詳細ページをシートキャッシュ優先表示 | Done | 100 | P0 | M-SD-09 | localStorage未保存でも `/same-day-sheet` キャッシュから該当Rの entry/course_stats/bet_plan を即表示。5Rでオッズ/特徴をPlaywright確認。 | Codex |
| M-SD-11 | Mobile Backend/Frontend | 近3走の走破タイム・タイム指数・レースレベル追加 | Done | 100 | P0 | M-SD-10 | `recent_run_details` を追加し、詳細ページに小チップ表示。候補指数へ小幅反映。5/3東京5R実測 + 5R〜12Rキャッシュ更新、`pytest/lint/build` PASS。 | Codex |
| M-SD-12 | Mobile Frontend | R詳細ページのAI共有用Markdownコピー | Done | 100 | P1 | M-SD-11 | 出馬表/近3走指数/特徴/候補/買い目/外部情報をMarkdown化。5/3東京5RでPlaywrightコピー確認、`lint/build` PASS。 | Codex |

## Issue / Blocker Log
| IssueID | Date | Issue | Impact | Temporary action | Permanent fix | Status |
|---|---|---|---|---|---|---|
| IS-001 | 2026-04-15 | Next.js 16 + `next-pwa` Turbopack mismatch | Build instability | Force `next build --webpack` | Track Turbopack compatibility | Watching |
| IS-002 | 2026-04-15 | Some races fail `resolve-id` | Odds fetch blocked for edge races | UI warning and fallback flow | Backend fallback strategy implemented + tests | Closed |
| IS-003 | 2026-04-15 | Env operation drift risk | Reproducibility risk | Root `.env.example` as source-of-truth | Enforce via docs/checklist | Open |
| IS-004 | 2026-04-15 | Mixed local dependency conflicts | Local test friction | Use dedicated backend venv | Document isolated env workflow | Open |
| IS-005 | 2026-04-15 | Some future races stay unresolved (`race_id=null`) | Odds/CSV fetch cannot proceed for those races | UI warning and skip unresolved races | Upstream-dependent; retry closer to race date | Watching |
| IS-006 | 2026-04-15 | YouTube summary can include off-race videos despite race_name input | Summary/horse analysis quality drops for specific race verification | Use tighter query terms and max_results=2 during manual checks | Strict race filter + fallback query candidates + 同名平レース時の開催日/会場/R番号コンテキスト補完・非対象会場/日付除外を実装 | Closed |
| IS-007 | 2026-04-18 | Legacy Streamlit Web article acquisition precision regressed vs earlier behavior | Horse-level evaluation quality decreases when low-quality sources dominate | Keep Umanity as primary structured source and cap noisy fetch paths | Historical diff対応 + モデル候補/記事選定調整後に Playwright再検証（Web解析失敗0・404 0・非対象レース混入なし） | Closed |
| IS-008 | 2026-04-18 | Some bet types show missing/unavailable odds (複勝/ワイド/馬連/三連複/三連単) | Budget plan can degrade or output warnings before market publication | Partial-success handling with explicit warnings | 未公開判定強化 + API/HTMLフォールバック + 推定オッズ補完を実装（警告表示は維持） | Watching |
| IS-009 | 2026-04-18 | Entry table readability for past-race performance was weak | Hard to compare finish positions quickly | Added rank-first visual layout with condensed race/course lines | Keep style tuning based on QA feedback | Closed |
| IS-010 | 2026-04-24 | race_key 衝突（同名平レースの欠落・キャッシュ上書き） | 当日モードで 1 会場内の同名レース（「3歳未勝利」等）が片方しか表示されない。キャッシュ衝突で重賞も含めデータ消失リスク | T-SD-01 で race_number を race_key に含める（`{date}_{venue}_{race_name}_{race_number}`）。旧キャッシュは再生成 | `race_catalog.py` の新key設計 + `test_same_day.py` で静的検証済み | Closed |
| IS-011 | 2026-04-24 | 当日 1R-12R を取得する静的 URL が未確定 | 当日モード着手不能 | T-SD-00 で `race_list.html` / `db.netkeiba.com/race/list/YYYYMMDD/` / `race_list_sub.html` を実測調査 | 主経路 `race_list_sub.html?kaisai_date=YYYYMMDD`、補助経路 `db.netkeiba.com/race/list/YYYYMMDD/` で確定 | Closed |
| IS-012 | 2026-04-24 | 未スコープ widget key が複数（DuplicateWidgetID 事故の温床） | 親タブで 12 レース同時描画時にアプリ全体クラッシュ | T-SD-05 で `_display_main_content` 関数化 + `combined_*/x_*/doc_*/yt_detail_*/btn_race_refresh/fetch_odds_btn` 等を `::{race_widget_scope}` 化 | scoped key クリア処理も含めて実装、`test_same_day.py` で検証済み | Closed |
| IS-013 | 2026-04-24 | レース特徴自動取得（app.py:9040-9074）が無条件実行 | 当日モードで Umanity graderace / Gemini に無駄リトライ、20秒ごとに誤情報で上書き | T-SD-06 で `race_mode==graded` ガード、当日モードは空 dict 運用 | `main()` 分岐で same_day 時の自動特徴取得を停止、Playwright回帰で副作用なしを確認 | Closed |
| IS-014 | 2026-04-24 | Umanity 平レース対応 URL が不明（既存は graderace 4桁 ID のみ） | 「ウマニティ+netkeiba」方針の履行に不確実性 | T-SD-00 で Umanity 平レース公開有無を実測。非対応なら netkeiba 単独で運用する旨をユーザー確認 | 12桁 race_id 直接URLは全滅。`race_8.php` は独自16桁コードでのみ応答。実装は netkeiba 主体で継続し、ユーザー再開時に正式合意を取得 | Watching |
| IS-015 | 2026-04-24 | 改訂前プランで `yoso_pro.html` を候補にしていたが実在未確認 | 実装時に 404 連鎖 | T-SD-03 の候補から除外し `newspaper.html` / `shutuba_past.html` / `data_top.html` のみ採用 | `https://race.netkeiba.com/yoso/yoso_pro.html?race_id=...` の 404 を実測確認し候補除外を確定 | Closed |
| IS-016 | 2026-04-24 | same_day 馬プロフィールの空キャッシュが残り、`馬別情報 0件` が継続 | 平場で馬別情報が拾えず、予想根拠が痩せる | `same_day_sources.py` の文字化け修正 + Streamlit再起動 | `app.py` に空キャッシュ自動復旧（cache clear + direct fetch fallback）を追加。Playwrightで東京5R/6Rが `馬別情報26件/27件` まで回復 | Closed |
| IS-017 | 2026-04-25 | 初回表示前の Playwright オッズ自動取得が未公開レースで長時間ブロックしうる | 出馬表タブ表示が遅れ、現地運用で待ちが発生 | 手動更新ボタンで必要時のみ Playwright 取得 | 初回自動取得は `allow_playwright=False` の static-only 軽量確認へ変更し、表示後に実行。手動「最新オッズを取得」は従来の Playwright 経路を維持 | Closed |
| IS-018 | 2026-04-25 | netkeiba 出馬表の `Weight` class を斤量として読んでいた | 斤量が空表示になり、当日馬体重追加時にも混同リスク | 基本情報取得でCSV再生成 | `parse_shutuba_table` で斤量は騎手斤量セル、馬体重/増減は `Weight` セルに分離。東京5R/6Rで `57.0` と馬体重列を確認 | Closed |
| IS-019 | 2026-04-25 | 当日モードで既存CSVを読むと前走/脚質が自動補完されない | ユーザーがレースを読み込んだ直後、出馬表の判断材料が空欄になる | 「基本情報取得」を手動実行 | race load 時に `fetch_recent_runs` をキャッシュ付きで実行し、CSVと `recent_runs::{race_key}` に fill-only 反映。4/26東京4Rで脚質分布/近3走/上りを確認 | Closed |
| IS-020 | 2026-04-25 | 当日モードのWeb一括検索でYouTube同時取得が走りうる | 平場では混入・APIコスト・待ち時間が増えやすい | YouTubeタブで必要時のみ手動実行 | same-day ではWeb一括検索のYouTube同時取得を非表示・強制OFF。注意captionを表示し、YouTubeタブは手動用に維持 | Closed |
| IS-021 | 2026-04-25 | 馬番未確定の前日データでは買い目タブが「馬スコア算出不可」で止まる | レース30分前の確認前に開いた場合、候補馬判断もできず不安になる | 出馬表の単勝オッズ/近走を目視 | 馬番なしでも馬名ベースでスコアを作り、暫定候補馬ランキングを表示。正式買い目は馬番取得後に再生成する導線に変更 | Closed |
| IS-022 | 2026-04-25 | コース特徴で複勝率上位脚質と勝ち馬脚質傾向が矛盾して見える | 現地で軸馬/相手馬の判断を迷わせる | 表の詳細を人間が読み分ける | `schema_version` を付与し旧キャッシュを再生成。注目ポイントは「複勝率ベース」と「勝ち切り傾向」を分離して表示 | Closed |
| IS-023 | 2026-04-25 | 当日モード脚質判定が出走頭数を無視し、4角でなく3角寄りの値を参照していた | 4/26東京4Rなどで脚質が追込に偏り、展開判断・買い目スコアの信頼性が落ちる | 近3走の表示自体は維持し、人手で通過順を確認 | `field_sizes` を取得し、4角順位/頭数比率ベースの前走優先判定に変更。枠別Markdown表も追加して特徴判断を補強 | Closed |
| IS-024 | 2026-04-25 | PWAローカル検証で `127.0.0.1:3000` から `localhost:8000` へのCORSが失敗 | Playwright/スマホ実機検証でAPIがLoadingのまま止まる | `localhost:3000` で開くか手動fetchで確認 | backend CORS default に `http://127.0.0.1:3000` を追加。production `next start` でE2E確認済み | Closed |
| IS-025 | 2026-04-25 | 4/26東京4R/5R/6Rの単勝オッズ/馬体重がAPI実測でも未公開 (`---.-`, 空) | オッズ込みランキング・馬体重増減シグナルの最終評価ができない | 候補ランキングは近走/脚質ベースで表示し、オッズは `未公開` と明示 | entry API warnings とUI表示を追加。2026-04-26 01:02 JST の再実測でも `odds_count=0/body_count=0` のため、公開後に手動更新で再確認する | Watching |
| IS-026 | 2026-04-26 | PowerShell here-string から日本語 venue を直接渡すとCLI検証で文字化けし、東京フィルタが0件になる | 開発者向けAPI直叩き検証で false negative が出る | Python検証では `'\u6771\u4eac'` のようにUnicode escapeを使う | ブラウザ/UI経由はURLエンコードで正常。必要なら検証スクリプト化して日本語リテラルをコード内UTF-8ファイルに固定する | Watching |

## Session Log
### 2026-04-15 / Session-010
- Implemented T-M4-02 (YouTube/X summary APIs).
- Verified backend + frontend checks.
- Next: finish workbench UI and deployment flow.

### 2026-04-15 / Session-011
- Implemented env operation docs (`env-operations.md`).
- Linked docs from README.
- Next: complete T-M4-03.

### 2026-04-15 / Session-012
- Completed T-M4-03 (workbench UI improvements).
- Added link previews and query visibility.
- Next: continue final-stage migration tasks.

### 2026-04-15 / Session-013
- Implemented T-M4-04 (YouTube/X horse-analysis APIs) and frontend integration.
- Added `scripts/check-stack.ps1` for local/staging verification flow.
- Verified: backend `pytest`, frontend `lint/build`.
- Next: run staging verification (`T-M5-01`) with real deployed URLs.

### 2026-04-15 / Session-014
- Validated `scripts/check-stack.ps1` end-to-end by temporarily starting backend and running the script.
- Result: local checks passed for all required backend endpoints.
- Next: execute the same script against deployed Render/Vercel URLs.

### 2026-04-15 / Session-015
- Implemented race fallback resolution in `race_service` for past/out-of-window race keys.
- Hardened odds column detection and added `waku` to odds payload.
- Added backend tests (`test_race_service_fallback.py`) and GitHub Actions CI workflow.
- Verified: backend `pytest` (26 passed), frontend `lint/build`.
- Next: run `scripts/check-stack.ps1` against actual Render/Vercel deployment URLs and capture results.

### 2026-04-15 / Session-016
- Improved `scripts/check-stack.ps1` with per-request timeout control (`-RequestTimeoutSec`) and info logs.
- Updated backend config to load env from both `backend/.env` and root `.env`.
- Ran full local stack check (`backend + frontend + external posts`) successfully.
- Next: execute the same check against Render/Vercel URLs and record outputs.

### 2026-04-15 / Session-017
- Fixed mojibake in frontend race pages/components (`race-workbench`, `race detail`, odds option/table/status panels, odds labels).
- Added odds-unpublished fallback so horse rows remain visible when all odds are null.
- Verification:
  - `npm run lint` (frontend) passed
  - `npm run build` (frontend) passed
  - `pytest backend/tests -q` passed (27 passed)
  - Playwright snapshot partially confirmed readable labels in race workbench
- Next: run end-to-end manual validation in local browser with your target race flow.

### 2026-04-15 / Session-018
- Executed additional local production-like checks with `uvicorn` + `next start` + `check-stack.ps1`.
- Ran batch verification for races API:
  - upcoming sample 20 races: resolved 4 / unresolved 16 (future races not yet published)
  - resolved races odds fetch: horse rows returned, no `nan` string leakage in `umaban/waku`
- Found and fixed cache upsert failure for malformed race_key filename (`?`, `*`, etc.):
  - strengthened `_sanitize_race_key_for_cache`
  - added `test_cache_filename_sanitize.py`
- Verification:
  - `pytest backend/tests -q` passed (28 passed)
  - `npm run lint` and `npm run build` (frontend) passed
  - `check-stack.ps1` local (without external paid POSTs) passed
- Next: user-side manual browser validation on target races, then staging URL verification when available.

### 2026-04-15 / Session-019
- Implemented past-window support for race listing:
  - backend `/api/v1/races/upcoming` now accepts `days_back` (default 7)
  - service window changed to `today - days_back` through `today + days_ahead`
  - frontend race workbench added `過去日数` input and passes `days_back`
- Replaced `race-workbench-card.tsx` with clean UTF-8 text labels (mojibake cleanup in this view).
- Verification:
  - backend: `PYTHONPATH=. pytest tests -q` (30 passed)
  - frontend: `npm run lint` / `npm run build` passed
  - API check: `/api/v1/races/upcoming?days_back=7&days_ahead=14` includes 2026-04-12 桜花賞
- Next: manual UI validation with your local browser flow (桜花賞選択→詳細→キャッシュ復元確認).

### 2026-04-15 / Session-020
- Verified against last week race scenario (桜花賞) on local stack:
  - `GET /api/v1/races/upcoming?days_back=7` includes `2026-04-12_阪神_桜花賞`
  - `GET /api/v1/races/resolve-id` resolves to `race_id=202609020611`
  - `POST /api/v1/races/fetch-csv` succeeded; `GET /odds` returned 18 horses (odds all null)
  - `GET /api/v1/races/cache` found legacy cache for 桜花賞 with web/x/training payload
  - `GET /api/v1/races/characteristics` succeeded when using race_key selected from API list
- External API smoke checks for 桜花賞:
  - web-summary: success
  - youtube-summary / youtube-horse-analysis: success but relevance drift observed
  - x-summary / x-horse-analysis: success with 0 tweets for current monitored accounts
- Note: Playwright MCP browser cannot reach local backend (`Failed to fetch`) in this environment, so UI E2E used API-level validation instead.
- Next: tighten YouTube relevance filter and add fallback flow when X returns 0.

### 2026-04-15 / Session-021
- Root-caused YouTube mixed-race issue:
  - not due race being finished; caused by loose relevance filtering and broad YouTube result set
  - old filter had path that could return non-target videos when strict race match was weak
- Refactored YouTube filtering/search:
  - strict race mode now requires target race signal and rejects explicit non-target race titles
  - added query-candidate fallback (`race_name 競馬 予想` etc.) and merged/deduped search results
  - removed strict-mode fallback-to-all behavior
- Added regression tests:
  - `test_external_youtube_filter.py` extended for strict filtering and fallback candidate behavior
- Verification:
  - `PYTHONPATH=. pytest tests -q` passed (35 passed)
  - API smoke (桜花賞):
    - `/external/youtube/search` now returns race-relevant titles
    - `/races/upcoming` + `/resolve-id` + `/fetch-csv` + `/odds` flow still passes
- Next: optional refinement for X zero-hit fallback strategy (account/query tuning).

### 2026-04-18 / Session-022
- Re-centered validation target on legacy Streamlit (皐月賞 2026) while retaining migration artifacts.
- Strengthened legacy flow:
  - Umanity-first race characteristics path finalized (primary scraping + fallback path coexistence)
  - Umanity racecard (`racecard.php`) parsing added and merged to entry table (前走/2走前/3走前)
  - Weight display robustness improved via racecard jockey-weight fallback when base CSV weight is blank
  - Removed `調教師` from entry table/report columns by request
- Report update:
  - Removed `💰 予算別買い目プラン` block from Markdown report output by request.
- Verification:
  - `python -m py_compile legacy/streamlit_app/app.py` passed
  - Playwright confirmed updated entry columns and racecard-based values on 皐月賞.
- Next: refine entry-table readability + sorting UX and hand off a concrete validation checklist for Claude Code.

### 2026-04-18 / Session-023
- Improved entry-table readability for past races:
  - each past-race cell now renders as `date + rank badge + race name + course`
  - rank emphasis (`1着/2着/3着/others`) added for quick comparison.
- Added sorting control in 出馬表 tab:
  - `馬番順`
  - `オッズ昇順（人気順）`
  - `オッズ降順（高配当順）`
  - automatic fallback to horse number order when numeric odds are unavailable.
- Verification:
  - `python -m py_compile legacy/streamlit_app/app.py` passed
  - Playwright check:
    - `オッズ昇順` top rows start from low odds (`6.0`, `6.7`, `6.9`, ...)
    - `オッズ降順` top rows start from high odds (`72.8`, `48.3`, ...)
    - past-race cells show multi-line rank-focused layout.
- Next: run independent Claude Code verification for Satsuki Sho full flow and feed back any gaps.

## Claude Code Verification Checklist
- Scope:
  - Target race: `2026-04-19 皐月賞 (中山 芝2000m)`
  - Validate legacy Streamlit tabs: `出馬表`, `YOUTUBEから情報入手`, `レース特徴・傾向`, `予算別買い目プラン`, `Markdownレポート出力`.
- Functional checks:
  - 出馬表:
    - columns include `斤量`, `前走`, `2走前`, `3走前`
    - `調教師` is not shown
    - past-race cells are rank-readable (`1着/2着/3着...`)
    - sort options switch ordering correctly (`馬番順/オッズ昇順/オッズ降順`)
  - レース特徴:
    - Umanity data loads as primary source
    - fallback path is only used when primary retrieval fails
  - YouTube:
    - summary/horse extraction does not drift into other races
    - conclusion fields (`本命/対抗/単穴`) do not get filled with irrelevant text
  - 買い目プラン:
    - odds warnings are explicit when market data is unavailable
    - no crash when one or more bet-type odds are missing
  - Markdown report:
    - includes entry/race characteristics/youtube/training sections
    - excludes `予算別買い目プラン` section.
- Suggested local commands:
  - `python -m py_compile legacy/streamlit_app/app.py`
  - `python -m streamlit run legacy/streamlit_app/app.py --server.headless true --server.port 8765`
  - (optional) Playwright/manual browser walkthrough on `http://127.0.0.1:8765`.

### 2026-04-21 / Session-QUALITY-001
- プラン採択: `reflective-sniffing-wilkes.md`（YouTube読取 & 買い目プラン品質向上）。
- 起因: 2026-04-19 皐月賞キャッシュ分析 + Web 記事解析の 404 連鎖・激遅バグ（実測 `gemini-2.0-flash` が新規ユーザーに 404）を確認。
- 作業順: 変更0 (404 fix) → 変更1 (YouTube auto-analyze) → 変更2 (bet-plan score) → 変更3 (Web diversity)。
- 進捗: T-LS-06 / T-LS-07 / T-LS-08 完了。compile OK + `test_playwright.py` 8/8 PASS を毎変更後に確認済み。
- 残作業: T-LS-09（変更3: Web 多様化）+ T-LS-10（E2E 皐月賞再生成）を Codex へ引継。
- Codex 引継要点:
  1) app.py:165 `MAX_ANALYZE_ARTICLES_PER_QUERY` 3→5。
  2) `_select_articles_for_analysis` (app.py:1854 付近) に未カバー馬ヒットボーナス +2.0 を追加。`st.session_state['horse_df']` で plus+minus=0 の馬を「未カバー」とみなす。
  3) E2E: `streamlit run legacy/streamlit_app/app.py --server.port 8765` → 7777 → 皐月賞 → Tab2 Web一括検索 → 404 0件／2〜3分／情報0件≤3／yt_bonus≠0 が 5 頭以上／三連複 10 頭候補。
  4) 各変更後に `cd legacy/streamlit_app && python test_playwright.py` を流し 8/8 PASS を維持。
- 完了済み変更サマリ（参考）:
  - 変更0: app.py:93 `GEMINI_MODEL_WEB_FALLBACK="gemini-2.5-flash-lite"` + app.py:4261-4270 で非一時エラー即 break。
  - 変更1: app.py:7109-7127 で Tab2 Web一括検索時に `analyze_all_videos_with_gemini(added_videos)` を自動実行、`youtube_raw`/`youtube_summary_df` を差分マージ。help 文更新。
  - 変更2: app.py:5944-6009 に `_extract_frame_bonus_map` / `_extract_style_bonus_map` 追加、stats に `frame_bonus`/`style_bonus` 反映、base 式に加算、情報0件馬のフロア補正、`_build_ticket_candidates` を券種別 pool_size (単勝/複勝/ワイド/馬連=8, 三連複=10, 三連単=8) に変更。

### 2026-04-22 / Session-QUALITY-002
- T-LS-09 実装完了:
  - `app.py` で `MAX_ANALYZE_ARTICLES_PER_QUERY = 5` へ変更。
  - `_get_uncovered_horse_names` を追加し、`horse_df` の plus+minus=0 を未カバー判定。
  - `_select_articles_for_analysis` に未カバー馬ヒットボーナス `+2.0` を追加。
- Web取得 404 の再発点を実測で追跡:
  - Playwright (8501, 皐月賞) で Web一括検索中に `404 NOT_FOUND (models/gemini-2.0-flash)` 警告を再確認。
  - 直接モデル疎通検証で `gemini-2.0-flash*` は新規ユーザー 404、`gemini-2.5-flash-lite` は応答可を確認。
  - `app.py` の `_web_model_candidates` から `gemini-2.0-flash` を除外し、404起因候補を解消。
- E2E 進捗 (T-LS-10):
  - Playwrightで 皐月賞 Tab2 Web一括検索（YouTube同時取得 OFF）を再実施し、`Web記事 20件（新規14件）`・`Web記事解析失敗 0件`・`404 0件` を確認。
  - 買い目プラン再生成まで実施し、キャッシュ更新を確認（`2026-04-22T00:21:06`）。
- 残作業:
  - YouTube同時取得 ON の長時間E2Eで `yt_bonus!=0` 件数と三連複候補観点の最終確認。

### 2026-04-22 / Session-QUALITY-003
- YouTubeバッチ解析経路を修正（`legacy/streamlit_app/app.py`）:
  - `analyze_all_videos_with_gemini` を `tuple(summary_df, raw_results, conclusion_map)` 返却へ統一。
  - `_analyze_one_video_worker` を `analyze_video_with_gemini(..., suppress_streamlit_warning=True)` ベースに変更し、動画ごとの `yt_video_conclusions` を確実に生成。
  - `_derive_video_conclusion_from_rows` を追加し、Gemini結論が弱い動画でも馬別抽出から `本命/対抗/単穴` を補完。
  - Tab2 Web一括検索（YouTube同時取得ON）で `new_yt_conclusions` を `st.session_state['yt_video_conclusions']` に差分マージするよう修正。
- 馬名ゆれ・yt_bonus集計を補強:
  - `_match_horse_name_from_text` に先頭一致フォールバック（軽微な誤記許容）を追加。
  - 買い目スコア計算時の `yt_bonus` を厳密一致だけでなく `_find_horses_in_text` + トークン単位マッチで加点。
- 検証結果（Playwright, 8501, 皐月賞）:
  - Tab2 Web一括検索（YouTube ON, 件数5）で `Web一括検索を途中終了（240秒上限）` を確認しつつ完走。
  - 同run後キャッシュ: `last_updated=2026-04-22T08:51:39`, `web_article_count=74`, `youtube_video_count=5`, `yt_video_conclusion_count=6`, `youtube_raw_count=37`。
  - 買い目再生成後: `last_updated=2026-04-22T08:55:57`, `yt_bonus!=0 が 7頭`（ロブチェン/カヴァレリッツォ/アスクエジンバラ/ライヒスアドラー/リアライズシリウス/アドマイヤクワッズ/バステール）。
  - 警告表示は明示的に維持: `オッズ未取得のため買い目を生成できない券種: ワイド / 馬連 / 三連複 / 三連単`。
- 回帰確認:
  - `python -m py_compile legacy/streamlit_app/app.py` OK
  - `python legacy/streamlit_app/test_playwright.py` 8/8 PASS（ブラウザ補助T2は既知のログイン遷移ゆらぎで [NG] 表示）

### 2026-04-23 / Session-QUALITY-004
- 買い目オッズ欠損対策を最終実装（`legacy/streamlit_app/app.py`）:
  - 未公開オッズHTML判定を強化（`---.-` 主体ページを未公開扱い）。
  - API `status=middle/ng` + `result odds empty` を「ヒント」として扱い、HTML側フォールバックを継続。
  - 公式オッズ未取得時の推定オッズ補完（複勝/ワイド/馬連/三連複/三連単）を追加し、警告を明示表示。
- Playwright実機検証（8501, 皐月賞 2026-04-19）:
  - Tab2 Web一括検索（YouTube同時取得ON）完走。
  - 画面上で `Web一括検索を途中終了(240秒上限)` を表示しつつ、最終的に `検索・解析が完了しました` を確認。
  - Web解析失敗ログは `404=0 / parse_fail=0 / ServerError=0`。
  - レース特徴タブは `ウマニティ（データ分析） / Umanityスクレイピング（主）` を表示し、取得失敗表示なし。
  - YouTubeタブは非対象レース名（桜花賞/オークス/日本ダービー等）混入なし。
- 買い目最終結果（キャッシュ実測）:
  - `last_updated=2026-04-24T00:10:01`
  - `bet_plan_result.summary.券種別点数 = {三連複:2, 三連単:2, 単勝:2, 馬連:2, ワイド:2}`（計10点）
  - 警告: `公式オッズ未取得の券種は推定オッズで補完しました...` / `以下券種のオッズは現在未公開です...`
  - つまり「未公開券種でもクラッシュせず、推定補完で提案維持」を達成。
- 追切コメント品質チェック:
  - `training_items=438` を走査し、追切系キーワード非含有のコメント `0件`（非追切文の混入は検出なし）。
- E2Eスクリプト運用性を補強（`tmp/pw_satsuki_e2e.py`）:
  - 認証後の「このレースを読み込む」段階を成功条件に追加し、ログイン待機の取りこぼしを解消。
  - Windows cp932 環境での `print` UnicodeError を回避。
  - 実行結果: `bet_generate_success=true`, `errors=[]`, `web_fail_404_count=0`, `web_parse_fail_count=0`。
  - Next: FastAPI + Next.js 側へ同等の odds fallback / warning UX を移植（T-M3/M4 継続）。

### 2026-04-24 / Session-QUALITY-CLOSE
- 品質向上フェーズ（T-LS-06〜T-LS-10）をすべて Done でクローズ。
  - T-LS-06: Gemini 404 連鎖解消（fallback を gemini-2.5-flash-lite へ、非一時エラー即 break）
  - T-LS-07: Tab2 Web一括検索で YouTube 馬別解析を自動実行（差分マージ）
  - T-LS-08: Umanity race_characteristics を買い目スコアに統合（枠/脚質ボーナス + 情報0件馬フロア補正 + 券種別 pool_size）
  - T-LS-09: Web 記事の馬別カバレッジ向上（未カバー馬ヒットボーナス +2.0, MAX 3→5）
  - T-LS-10: 皐月賞 E2E で `errors=[]/404=0/parse_fail=0/bet_generate_success=true` を達成
- 成果物: 皐月賞 2026 キャッシュ最終版 `last_updated=2026-04-24T00:10:01`、計10点の買い目プラン（三連複/三連単/単勝/馬連/ワイド 各2点）。推定オッズ補完で未公開券種でもクラッシュせず。
- 次フェーズ: 当日レースモード（T-SD-01〜T-SD-08）。プランは `C:\Users\tadas\.claude\plans\reflective-sniffing-wilkes.md`。

### 2026-04-24 / Session-SAMEDAY-001
- 新機能「当日レースモード」の仕様を確定（AskUserQuestion で詰めた）:
  - モード統合: サイドバーに「重賞モード / 当日レースモード」ラジオ（既存重賞UIは非破壊）
  - 会場スコープ: 日付＋会場選択で 1 会場 12 レース分のタブを表示（全会場合算はしない）
  - UI 構成: 親=レース(1R-12R)、子=既存 7 タブ（出馬表/情報入力/総合予想/レース特徴/YouTube/追切/買い目）
  - 情報源: ウマニティ + netkeiba レース詳細ページの 2 源に集約。Tavily/X/YouTube は残すが「平レースは精度低下」の注記。
  - 前走成績: 直近 3 走を CSV/UI に横展開。
- Next: T-SD-00 URL/挙動調査を手動実測で着手。

### 2026-04-24 / Session-SAMEDAY-002
- プラン改訂（ユーザーからの P0/P1 指摘を全件実コードで検証し、計画に反映）:
  - **P0 race_key 衝突**: race_catalog.py:215 実コード確認済。RaceInfo に `race_number` 追加と race_key 再設計を T-SD-01 の主要アクションに昇格（IS-010）。
  - **P0 当日導線 URL 前提**: race_list.html は JS レンダリング、schedule.html は重賞月次のみで平レース列挙に不適と確認。改訂前の「schedule.html フォールバック」記述は削除。T-SD-00 を最優先研究タスクとして新設（IS-011）。
  - **P0 widget key 衝突**: app.py:7371/7378/7387/7408/7556/7666/7751/7983 等に未スコープ key 多数を grep 確認。T-SD-05 で `_display_main_content(race, race_widget_scope)` 関数化と全面スコープ化を必須アクションに明記（IS-012）。
  - **P1 タブ数**: app.py:7201-7209 で tab1〜tab7 を確認（改訂前プラン「5タブ」は誤り）。プランの全記述を 7 タブに訂正。
  - **P1 Umanity 平レース**: race_catalog.py:4550 で Umanity race_id が独自4桁体系（netkeiba 12桁と非互換）と確認。改訂前の `racedata/race/{netkeiba_race_id}` 仮説を削除。T-SD-03 の Umanity 部分は T-SD-00 結果次第で条件付き実装に降格（IS-014）。
  - **P1 yoso_pro.html**: 実在未確認のため候補から除外。`newspaper.html` / `shutuba_past.html` / `data_top.html` に限定（IS-015）。
  - **P1 horse_id 解決手順**: T-SD-02 で `shutuba_past.html` 主経路（1リクエストで全馬分）+ 副経路として shutuba.html → `db.netkeiba.com/horse/{id}` 個別取得を明記。
  - **P1 レース特徴自動取得**: app.py:9040-9074 が無条件実行と確認。T-SD-06 に `race_mode==graded` ガード追加を主要アクションとして明記（IS-013）。
  - **P2 QA 強化**: T-SD-08 に新規 `test_same_day.py`（race_number 衝突/shape/widget key grep 静的検証）を追加、既存 8/8 PASS 維持を前提に。
- 追加タスク: T-SD-00 を新設（URL/挙動調査、User+Claude Code 共同）。他 T-SD-01〜08 の依存・アクション・検証条件を全面書き直し。
- プランファイル: `C:\Users\tadas\.claude\plans\reflective-sniffing-wilkes.md` に改訂版を保存。
- Next: T-SD-00 の URL/挙動調査（手動で `db.netkeiba.com/race/list/YYYYMMDD/` 等を fetch して構造確認）に着手。

### 2026-04-24 / Session-SAMEDAY-003
- T-SD-00 実測を完了:
  - netkeiba: `race_list_sub.html?kaisai_date=YYYYMMDD` で race_id を安定抽出（例: 2026-04-19 は 36 race_id、2026-04-26 は `shutuba.html` 導線で 36 race_id）。`race_list.html` はJS依存で静的抽出に不向き。`db.netkeiba.com/race/list/YYYYMMDD/` は補助導線として race_id 抽出可能。
  - 実在確認: `newspaper.html` / `shutuba_past.html` / `data_top.html` は HTTP 200。`yoso_pro.html` は HTTP 404。
  - Umanity: 平レース向けの 12桁 race_id 直指定 URL は全滅（`/racedata/race/...`, `/racedata/{id}/`, `/racedata/race.php?...`, `/racedata/race_8.php?code=<12桁>` いずれも404）。`race_8.php` は独自16桁コードでのみ応答。
- 分岐判断:
  - ユーザー不在のため、当日モードは netkeiba 主体で実装継続。
  - Umanity平レースは `same_day_sources.py` で空実装（return None）にして機能を阻害しない形で保持。
- 進捗反映:
  - Task Board: `T-SD-00` を Done(100) へ更新。
  - Issue: `IS-011` / `IS-015` を Closed、`IS-014` を Watching へ更新。
- Next: `T-SD-01`（race_key衝突修正 + fetch_races_by_date / group_races_by_venue 実装）に着手。

### 2026-04-24 / Session-SAMEDAY-004
- T-SD-01〜T-SD-08 を実装・検証して完了:
  - `race_catalog.py`: `RaceInfo.race_number` / `build_race_key` / `fetch_races_by_date` / `group_races_by_venue` を追加し、同名平レースの key 衝突を解消。
  - `get_keiba_info.py`: `fetch_recent_runs` を追加（`shutuba_past` 主経路 + `horse/result` 副経路）。
  - `same_day_sources.py` 新規: `fetch_netkeiba_race_column` 実装、`fetch_umanity_flat_racecard` は空実装フォールバック。
  - `app.py`: `race_mode` 分岐、same-day selector、`🏁 基本情報取得` / `📡 ネット情報取得`、`recent_runs` キャッシュ反映、`race_mode==graded` ガードを追加。
  - `_display_main_content` 関数化 + 未スコープ widget key を race scope 化。親タブは DuplicateWidgetID リスク回避で selectbox 方式を採用。
- 実行検証:
  - `python -m py_compile legacy/streamlit_app/race_catalog.py legacy/streamlit_app/get_keiba_info.py legacy/streamlit_app/same_day_sources.py legacy/streamlit_app/app.py` PASS
  - `python legacy/streamlit_app/test_same_day.py` PASS (4/4)
  - `python legacy/streamlit_app/test_playwright.py` PASS (8/8)
  - Playwright 手動E2E (port 8767):
    - 当日モード `2026/04/24` で「休催日/公開前」空表示を確認
    - 当日モード `2026/04/19 福島 1R` で `🏁 基本情報取得` 実行後、出馬表に近3走3列が展開されることを確認
    - `📡 ネット情報取得` 実行で `記事3件 / 馬別情報8件` を確認
    - `💰 予算別買い目プラン` で 10点/5,000円の提案生成を確認
    - 重賞モードへ戻して `中山グランドジャンプ` 読込、YouTubeタブ/レポートボタン/買い目タブ表示の回帰なしを確認
- 懸念/フォロー:
  - Umanity 平レース URL は依然未確定（`IS-014` Watching 継続）。
  - 同一 race で netkeiba ページにより馬別抽出0件になるケースは警告表示で継続（処理自体は完走）。
- Next: ユーザーレビュー（同一手順での実機確認）を受け、必要なら same-day ネット情報の警告文言を調整。

### 2026-04-24 / Session-SAMEDAY-005
- 同名平レース混入対策として YouTube 検索・フィルタを強化:
  - `app.py` に `get_youtube_default_keyword` / `_build_youtube_search_keyword` を追加し、検索語に不足している開催日・会場・R番号・レース名を自動補完。
  - YouTubeタブとWeb一括検索（YouTube同時取得）の初期キーワードをコンテキスト付き（`YYYY/MM/DD 会場 R レース名 予想`）へ変更。
  - `filter_relevant_videos` を拡張し、同名平レースでは `会場+R番号`（または日付付き）一致を必須化。加えて、非対象会場・非対象日付が明示された動画を除外。
- テスト更新:
  - `test_playwright.py` の静的チェックに新規ヘルパー関数存在確認を追加。
- 検証:
  - `python -m py_compile legacy/streamlit_app/app.py legacy/streamlit_app/test_playwright.py` PASS
  - `python legacy/streamlit_app/test_same_day.py` PASS (4/4)
  - `python legacy/streamlit_app/test_playwright.py` PASS (8/8)
- Next: Playwright実機で `3歳未勝利` 系キーワードの混入率を比較検証し、必要なら「日付一致必須」の閾値を調整。

### 2026-04-24 / Session-SAMEDAY-006
- T-SD-09〜T-SD-12 を完了（実装 + 再検証）:
  - `same_day_sources.py` の文字化けを解消し、`fetch_horse_profile` / `fetch_course_stats` の判定キーを復旧。
  - `app.py` に空プロフィールキャッシュ復旧を追加（`_fetch_horse_profile_cached.clear()` + direct fetch fallback）。
  - 戦績0件馬でも最小コメントを残すようにし、馬別情報0件化を回避。
- 4/26 東京競馬場 実機検証（Playwright）:
  - 5R `3歳未勝利(芝1800m)`: `当日ソース解析が完了（記事3件 / 馬別情報26件）`
  - 6R `3歳1勝クラス(芝1600m)`: `当日ソース解析が完了（記事3件 / 馬別情報27件）`
  - 両レースで `脚質` 列 + `前走/2走前/3走前` を確認。
  - 両レースでレース特徴タブに netkeiba コース統計（枠順/脚質系表示）を確認。
  - 追切は未公開警告のみ（仕様どおり）。
- 回帰:
  - `python legacy/streamlit_app/test_same_day.py` PASS (6/6)
  - `python legacy/streamlit_app/test_playwright.py` PASS (8/8)
- Next: T-SD-13 残項目（X件数>=5、買い目 `frame_bonus/style_bonus` 非ゼロ複数馬）を最終確認。

### 2026-04-25 / Session-SAMEDAY-007
- ユーザー指摘リストを実コードで精査:
  - BUG-1 は `race_catalog.fetch_races_by_date` が現行ファイルに存在するため、旧 Streamlit プロセス/モジュールキャッシュ起因の運用問題と判断。作業前に残存 streamlit プロセスを停止。
  - BUG-2 は正: 初回自動オッズ取得が Playwright 経路に入りうるため、表示後の static-only 軽量確認へ変更（手動更新は Playwright 維持）。
  - BUG-3 は正: `基本情報取得` 成功後の `st.rerun()` で成功表示が消えるため、session flag で rerun後に再表示。
  - BUG-4 は仕様内: 4/25時点の 4/26 東京5R/6Rでは oikiri/馬体重/馬場状態は未公開。取得経路だけ整備。
- 実装:
  - `get_keiba_info.py`: `parse_shutuba_table` の斤量/馬体重分離、`fetch_race_metadata`、`fetch_recent_runs` の `last3fs` / `前走上り` 追加。
  - `app.py`: 出馬表に `馬体重` 列、近3走カードに `上り` 表示、発走/馬場メタ caption、脚質分布サマリー、初回オッズ軽量化、基本情報成功表示の永続化を追加。
  - `test_same_day.py`: 上がり3F/馬体重/軽量取得 helper の静的検証を追加。
- 検証:
  - `python -m py_compile legacy/streamlit_app/app.py legacy/streamlit_app/get_keiba_info.py legacy/streamlit_app/test_same_day.py` PASS
  - `python legacy/streamlit_app/test_same_day.py` PASS (7/7)
  - `python legacy/streamlit_app/test_playwright.py` PASS (8/8)
  - Playwright manual (port 8782): 2026/04/26 東京5R・6Rで `基本情報取得` 後、成功表示、発走時刻、斤量、馬体重列、上がり3F、脚質分布を確認。馬体重/馬場は前日未公開のため空表示。
- Deferred:
  - 5分ごとの自動オッズ更新、取消/除外強調、パドックメモ、1日合計投資額は仕様/UX影響が大きいため未実装。必要なら別タスク化。
- Next: レート制限回復後に T-SD-13 残項目（X件数>=5、買い目 `frame_bonus/style_bonus` 非ゼロ複数馬）を再実行。

### 2026-04-25 / Session-SAMEDAY-008
- ユーザー報告（4/26 東京4Rでレース読込直後に脚質・前走・オッズが出ない）を再現・調査:
  - `race_202605020204.csv` には単勝オッズが保存済みだったが、近3走/脚質列が未補完で、UI表示前の自動補完経路がなかった。
  - `fetch_recent_runs('202605020204')` は10頭分を返し、アグアフレスカ/イブキ等の前走・上り・通過順を取得可能と確認。
- 実装:
  - `app.py` に `_ensure_same_day_initial_entry_fields` を追加し、same-day race load 時にCSVの単勝オッズ復元、static-only初回オッズ補完、近3走/脚質のCSV fill-only反映、`recent_runs::{race_key}` キャッシュ保存を実施。
  - Web一括検索では same-day 時に YouTube 同時取得を強制OFFにし、チェックボックスを出さず「必要ならYouTubeタブで個別実行」のcaptionを表示。
  - `test_same_day.py` に helper/caption/YouTube無効化の静的検証を追加。
- 検証:
  - `python -m py_compile legacy/streamlit_app/app.py legacy/streamlit_app/get_keiba_info.py legacy/streamlit_app/test_same_day.py` PASS
  - `python legacy/streamlit_app/test_same_day.py` PASS (7/7)
  - `python legacy/streamlit_app/test_playwright.py` PASS (8/8, Streamlit未起動時は既存仕様でskip)
  - Playwright manual (port 8783): 2026/04/26 東京4Rを読み込み、出馬表に `脚質`、`前走/2走前/3走前`、`前走上り`、`単勝オッズ`、`脚質分布: 差し1 / 追込8 / 自在1` を確認。情報入力タブでYouTube同時取得チェックボックス非表示も確認。
- Next: ユーザー実機でStreamlit再起動後に 4/26 東京4Rを再読込し、表示が即時補完されるか確認。T-SD-13残件（X件数>=5、買い目bonus非ゼロ）はレート制限回復後に継続。

### 2026-04-25 / Session-SAMEDAY-009
- 「当日レース30分前に、買う馬を決める助けになるか」という観点で 4/26 東京4Rを再検証:
  - 出馬表は発走時刻、単勝オッズ、近3走、上がり3F、脚質、脚質分布が即表示され、候補比較の入口として有用。
  - ただし前日状態では馬番/枠番が未確定のため、買い目タブが正式馬券番号を生成できず、当初は `馬スコアを算出できませんでした` で止まっていた。
  - コース特徴タブで「勝ちやすい馬のタイプ: 先行/逃げ」と「注目ポイント: 差し有利」が矛盾して見える表示も確認。
- 実装:
  - race load 時にCSVの馬番が全欠損なら、単勝オッズが既にあっても static-only の枠順/馬番再取得を試すよう変更。
  - 馬番がまだない場合でも、馬名ベースでスコアを算出し、買い目タブに `暫定候補馬ランキング` を表示。正式買い目は馬番取得後に再生成する注意書きを追加。
  - コース特徴に `schema_version=same_day_course_stats_v2` を付与し、旧キャッシュを自動再生成。注目ポイントは「複勝率ベースでは先行・逃げが安定」「勝ち切り傾向は差し有利」と分離表現に変更。
- 検証:
  - `python -m py_compile legacy/streamlit_app/app.py legacy/streamlit_app/test_same_day.py` PASS
  - `python legacy/streamlit_app/test_same_day.py` PASS (7/7)
  - `python legacy/streamlit_app/test_playwright.py` PASS (8/8, Streamlit未起動時は既存仕様でskip)
  - Playwright manual (port 8784): 2026/04/26 東京4Rで `暫定候補馬ランキング` が出ること、`馬スコアを算出できませんでした` が出ないこと、レース特徴の旧 `脚質トレンド:` が消え `勝ち馬脚質傾向:` と新注目ポイントになることを確認。
- 残リスク:
  - 2026/04/25時点では4/26東京4Rの馬番/枠番/馬体重が未公開のため、正式な買い目番号生成の最終確認はレース当日、枠番/馬番取得後に再実行が必要。
  - 当日30分前は「最新オッズを取得」→「買い目プランを生成」の順で確認する運用を推奨。
- Next: 4/26当日に馬番/枠番が取れた状態で正式買い目（単勝/複勝/ワイド等）の生成を最終確認。

### 2026-04-25 / Session-SAMEDAY-010
- ユーザー依頼の Phase 3（脚質判定修正 + 枠別Markdown割合表）を実装:
  - `get_keiba_info.py` に `_extract_field_size` を追加し、`shutuba_past.html` 主経路と horse/result フォールバックの `recent_runs` に `field_sizes` を追加。
  - `shutuba_past.html` の馬名セルが `Horse_Info` class だったため、主経路が空になって horse/result fallback へ落ちていた問題も修正。
  - `_extract_corner_positions` を空白保持 + 境界付き正規表現へ変更し、斤量 `57.0` と通過順 `3-1-1-1` が連結して `03-1-1-1` になる誤抽出を防止。
  - `app.py` の `_classify_corner_style` を4角順位（最後の値）+ 頭数比率に変更。`classify_running_style` は前走優先・自在控えめ方式へ変更し、古い `field_sizes` 欠損キャッシュは絶対値フォールバック。
  - `same_day_sources.py` のコース統計に枠別1着数/1着率/馬券外率を追加し、`app.py` のレース特徴に `枠別割合表` Markdown表を表示。
- 検証:
  - `python -m py_compile legacy/streamlit_app/app.py legacy/streamlit_app/get_keiba_info.py legacy/streamlit_app/same_day_sources.py legacy/streamlit_app/test_same_day.py` PASS
  - `python legacy/streamlit_app/test_same_day.py` PASS (10/10)
  - `python legacy/streamlit_app/test_playwright.py` PASS (8/8)
  - 実データ直接検証: `fetch_recent_runs('202605020204')` で10頭すべて `field_sizes` 取得、脚質分布は `差し6 / 自在2 / 先行1 / 追込1`。
  - Playwright manual (port 8786): 2026/04/26 東京4Rで「基本情報取得」後、出馬表の脚質分布 `先行1 / 差し6 / 追込1 / 自在2` を確認。レース特徴タブで `枠別成績割合` Markdown表（1着/複勝/それ以外/出走数）を確認。
- Next: 4/26当日の馬番/馬体重公開後に、正式買い目番号生成と直前オッズ更新を再確認。

### 2026-04-25 / Session-MOBILE-SD-001
- Implemented Mobile Same-Day Migration for FastAPI + Next.js PWA:
  - Added backend same-day service without importing Streamlit `app.py`.
  - Added `/api/v1/races/same-day`, `/api/v1/races/{race_id}/entry`, `/api/v1/races/{race_id}/course-stats`, `/api/v1/races/{race_id}/bet-plan`.
  - Migrated 4角順位+頭数比率の脚質判定、`field_sizes` fallback、枠別 `1着/複勝/それ以外/出走数`、候補馬ランキング。
  - Reworked mobile home into an 当日レースモード selector and mobile detail into `出馬表/特徴/買い目/外部情報` tabs.
  - Kept YouTube/X/Web manual-only in same-day flow and displayed date/venue/R-number query guidance.
- Verification:
  - Backend: `pytest backend/tests -q` passed (39/39).
  - Frontend: `npm run lint` passed.
  - Frontend: `npm run build` passed.
  - Playwright mobile width: 2026-04-26 東京4R loaded, `脚質分布 = 先行1 / 差し6 / 追込1 / 自在2`, 近3走, 上がり3F, 枠別割合, 候補馬ランキング, and YouTube non-auto note confirmed.
  - Screenshot saved: `mobile-same-day-tokyo4-entry.png`.
- Notes:
  - 2026-04-25時点では 2026-04-26 東京4R の単勝オッズ/馬体重は未公開のため、UIは `未公開` と警告を表示。当日公開後に手動更新で再確認する。
  - Dev server HMR WebSocket was noisy in this environment, so final E2E used production-like `next start`.
- Next: 4/26当日に東京4R/5R/6Rで馬体重・単勝オッズ公開後の手動更新を確認し、正式買い目の実用性を再評価。

### 2026-04-26 / Session-MOBILE-SD-002
- 実装計画の検証を実施:
  - API土台: `same-day` / `entry` / `course-stats` / `bet-plan` の4エンドポイントがコード上存在し、Pydantic schemaで `race_number`, `race_key`, `start_time`, `track_conditions`, `style_distribution`, `warnings` を返す構成を確認。
  - legacyロジック移植: Streamlit `app.py` は import しておらず、脚質判定・field_sizes fallback・枠別割合・候補ランキングは `backend/app/services/same_day_service.py` の純粋関数側に存在。
  - スマホUI: ホームの当日レース選択、詳細の `出馬表/特徴/買い目/外部情報`、馬カード表示、脚質分布サマリー、手動更新ボタンを確認。
  - 外部情報: 当日モード初回導線ではYouTube/X/Webを自動実行せず、外部情報タブの手動実行と検索語ガイドに限定。
- 4/26東京競馬場API実測:
  - 東京4R: 10頭、`先行1 / 差し6 / 追込1 / 自在2`、候補上位 `マーゴットドライ / ボンボンベイビー / イブキ`、course-stats 枠別8行。
  - 東京5R: 18頭、`先行2 / 差し8 / 追込5 / 自在1`、候補上位 `ムーングレイル / ブラッキッシュ / ニシノマルガリート`、course-stats 枠別8行。
  - 東京6R: 8頭、`逃げ2 / 差し2 / 追込1 / 自在3`、候補上位 `フジガイフウ / サレジオ / アルデキングダム`、course-stats 枠別8行。
  - 3レースとも馬番ありのため `provisional_only=false` で正式単勝チケットを生成。
  - 3レースともローカル取得時点では `odds_count=0 / body_count=0`。未公開警告は意図どおり表示対象。
- Verification:
  - Backend: `pytest backend/tests -q` passed (39/39).
  - Frontend: `npm run lint` passed.
  - Frontend: `npm run build` passed.
- Findings:
  - PowerShellで日本語 `東京` を直接 here-string 経由で渡すとCLI検証だけ文字化けする。Unicode escapeで再実行すると正常に12R取得。UI/ブラウザ導線は対象外。
  - 枠別Markdownは正規UTF-8では `| 枠 | 1着 | 複勝 | それ以外 | 出走数 |` を返す。PowerShell表示の文字化けは表示エンコーディング由来。
- Next: オッズ/馬体重が公開されたタイミングでスマホUIから「最新オッズ・基本情報を取得」を押し、`未公開` が数値/馬体重へ置き換わるかをPlaywrightで再確認。

### 2026-04-26 / Session-MOBILE-SD-003
- 4/26当日 01:02 JST 時点で東京4R/5R/6Rの再チェックを実施:
  - 東京4R: 10頭、`先行1 / 差し6 / 追込1 / 自在2`、候補上位 `マーゴットドライ / ボンボンベイビー / イブキ`。
  - 東京5R: 18頭、`先行2 / 差し8 / 追込5 / 自在1`、候補上位 `ムーングレイル / ブラッキッシュ / ニシノマルガリート`。
  - 東京6R: 8頭、`逃げ2 / 差し2 / 追込1 / 自在3`、候補上位 `フジガイフウ / サレジオ / アルデキングダム`。
  - 3レースとも馬番は取得済みで `provisional_only=false`。単勝チケット生成まで進む。
  - 3レースとも `odds_count=0 / body_count=0`。時刻的に単勝オッズ/馬体重は未公開の可能性が高く、UI警告 `未公開` 継続が妥当。
- Verification:
  - Backend same-day API tests: `pytest backend/tests/test_same_day_api.py -q` passed (4/4).
- Next:
  - 4R発走前の実運用チェックでは、馬体重発表後にスマホUIで「最新オッズ・基本情報を取得」を押す。
  - `odds_count>0` または `body_count>0` にならない場合は、netkeibaの公開HTMLを保存して parse selector を再調整する。

### 2026-04-26 / Session-MOBILE-SD-004
- 現地用に東京全12Rの記録シート生成を実装:
  - `scripts/export_same_day_sheet.py` を追加。
  - `--date YYYY-MM-DD --venue 東京` で当日レース一覧、entry、course-stats、bet-plan を全R分まとめて取得。
  - Markdownは印刷/スマホ閲覧向けに、各Rごとに候補馬ランキング、買い目メモ、出馬表メモ、枠別割合を出力。
  - JSONは後続更新・差分確認用のスナップショットとして保存。
- 実行結果:
  - `python scripts\export_same_day_sheet.py --date 2026-04-26 --venue 東京`
  - 出力: `data/same_day_sheets/2026-04-26_東京_same_day_sheet.md`
  - 出力: `data/same_day_sheets/2026-04-26_東京_same_day_sheet.json`
  - PowerShellの日本語パス/表示ゆらぎ対策としてASCII別名も作成:
    - `data/same_day_sheets/2026-04-26_tokyo_same_day_sheet.md`
    - `data/same_day_sheets/2026-04-26_tokyo_same_day_sheet.json`
- 検証:
  - `python -m py_compile scripts/export_same_day_sheet.py` PASS。
  - Python UTF-8読込で全12Rを確認。
  - 主要確認: 1R〜12Rすべて馬リスト、脚質分布、候補馬ランキング、買い目メモを保持。
  - 4/26 01:15 JST 時点では全12Rとも `odds=0件/body=0件` のため、記録シート上は `未公開/未発表` 表示。
- Next:
  - オッズ/馬体重公開後に同じコマンドを再実行し、同名ファイルを更新する。
  - 必要なら差分比較用に `--out-dir data/same_day_sheets/after_weight` のように保存先を分ける。

### 2026-04-26 / Session-MOBILE-SD-005
- PWA内で全Rシートを見られるように追加実装:
  - Backend: `GET /api/v1/races/same-day-sheet?date=YYYY-MM-DD&venue=東京` を追加。
  - Backend: 通常表示は `data/same_day_sheets/*_same_day_sheet.json` のキャッシュを優先し、現地スマホでの待ち時間を短縮。
  - Backend: `refresh=true` 指定時のみ全Rをライブ再取得し、再生成したJSONを保存。
  - Frontend: `/same-day-sheet` ページを追加。全Rカードに発走、頭数、脚質分布、オッズ取得頭数、馬体重取得頭数、候補上位4頭、詳細リンクを表示。
  - Frontend: ホームの当日レースモードに「東京の全Rシートを見る」導線を追加。
- Verification:
  - Backend: `pytest backend/tests -q` passed (40/40)。
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - Playwright mobile width: `/same-day-sheet?date=2026-04-26&venue=東京` を開き、5秒以内に `12R / 生成 2026-04-26T01:15:38`、1R〜12R、4R/11R、候補馬、`未公開` 警告を確認。
  - Screenshot saved: `mobile-same-day-full-sheet.png`。
- Notes:
  - ライブ全R再生成は重いので、現地では通常「シート読込」でキャッシュを見て、オッズ/馬体重公開後だけ「オッズ・馬体重公開後に全Rを再生成」を押す運用。
- Next:
  - 馬体重/オッズ公開後に `refresh=true` 経路で再生成し、オッズ取得頭数・馬体重取得頭数が増えるか確認。

## Operating Rules
- Update this file at session start/end.
- Keep max 2 tasks as InProgress at the same time.
- Any Blocked task must reference an IssueID.
- Done tasks must include one-line verification evidence.
- Always set one concrete next action before ending a session.

### 2026-04-26 / Session-MOBILE-SD-006
- 現地スマホ実機確認に向け、同一Wi-Fi不要の一時公開導線を追加/起動:
  - Frontend: `next.config.ts` に `/api/v1/:path*` と `/health` のrewritesを追加し、スマホブラウザからはPWAとAPIを同一オリジンで利用できるようにした。
  - Runtime: `NEXT_PUBLIC_API_BASE_URL=''` / `BACKEND_INTERNAL_URL=http://127.0.0.1:8000` でNext dev serverを再起動。
  - Tunnel: `tmp/cloudflared.exe` のQuick Tunnelで `http://127.0.0.1:3000` を一時公開。
- Verification:
  - Local: `http://127.0.0.1:3000/health` returned 200。
  - Tunnel: `https://pads-christina-guests-iii.trycloudflare.com/health` returned 200。
  - Tunnel: `/same-day-sheet?date=2026-04-26&venue=東京` returned 200。
  - Tunnel: `/api/v1/races/same-day-sheet?date=2026-04-26&venue=東京` returned 200。
- Operation:
  - 現地では `https://pads-christina-guests-iii.trycloudflare.com/same-day-sheet?date=2026-04-26&venue=%E6%9D%B1%E4%BA%AC` を開く。
  - 帰宅後または利用終了後は `tmp/cloudflared_3000.pid`, `tmp/frontend_3000.pid`, `tmp/backend_8000.pid` のプロセスを停止して公開を閉じる。
- Risk:
  - trycloudflare URLは一時公開URLなので、URLを知る人はアクセス可能。今日の現地利用限定で運用する。

### 2026-04-26 / Session-MOBILE-SD-007
- iPhone実機で「ボタンが押せない」報告を受けて原因切り分け:
  - Playwright iPhone相当で公開URLを確認したところ、HTMLは表示されるがReact click handler後の `/api/v1/...` 通信が発生しない状態を確認。
  - Next dev server + tunnel のHMR WebSocket 502/invalid responseが出ており、現地運用には不安定と判断。
- Fix:
  - `/same-day-sheet` をclient state依存からserver-rendered pageへ変更。
  - 初回表示でBackendから全Rシートを取得し、12R分のカードと詳細リンクをHTMLに直接描画するようにした。
  - 「シート読込」「再生成」はJSボタン依存ではなく通常リンク/GETフォームへ変更。iPhoneでhydrationが不安定でも一覧閲覧が可能。
  - Frontendを `npm run dev` から production build + `npm run start -- -H 0.0.0.0` に切り替え。
- Verification:
  - `npm run lint` passed。
  - `npm run build` passed。
  - Local: `/same-day-sheet?date=2026-04-26&venue=東京` returned 200 and HTML contains `4R` / `このRの詳細を見る`。
  - Tunnel: same URL returned 200 and HTML contains `4R` / `このRの詳細を見る`。
  - Playwright iPhone: tunnel URL shows 12 race cards in initial HTML, no console errors。
- Operation:
  - iPhone側は同じtrycloudflare URLを再読み込みする。古い画面が残る場合はSafariのリロード、またはプライベートタブで開く。

### 2026-04-26 / Session-MOBILE-SD-008
- iPhone実機で詳細リンク後に `Failed to fetch` になる問題を修正:
  - Cause: production build時に `.env.local` の `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` が埋め込まれ、iPhoneからは端末自身のlocalhostへアクセスしていた。
  - Fix: `frontend/src/lib/api/client.ts` で `localhost` / `127.0.0.1` が設定されている場合はAPI baseを空文字にし、同一オリジン `/api/v1/...` + Next rewrite 経由に統一。
  - Rebuild/restart: `npm run build` 後、`npm run start -- -H 0.0.0.0` を再起動。
- Verification:
  - `npm run lint` passed。
  - `npm run build` passed。
  - Playwright iPhone/tunnel: 4R詳細で `Failed to fetch` が消え、`/api/v1/races/202605020204/entry` が200。
  - 4R詳細で脚質分布 `先行1 / 差し6 / 追込1 / 自在2`、出馬表、近3走、上がり3Fを確認。
- Operation:
  - iPhone側で古いJSが残る場合は `&v=3` を付けるか、Safariリロード/プライベートタブで開く。

### 2026-04-26 / Session-MOBILE-SD-009
- Detail page navigation improvement:
  - `/races/[raceKey]` 上部に `全R一覧へ戻る` を追加。
  - 詳細URLの `date` / `venue` または読み込み済みrace metaから `/same-day-sheet?date=...&venue=...` を組み立てるため、トップへ戻って当日レース一覧を再取得する必要を減らした。
  - `トップへ戻る` は残し、通常運用は `全R一覧へ戻る` を優先する形に変更。
- Verification:
  - `npm run lint` passed。
  - `npm run build` passed。
  - Production server restarted with `npm run start -- -H 0.0.0.0`。
  - Playwright iPhone/tunnel: 4R詳細の先頭リンクから `/same-day-sheet?date=2026-04-26&venue=東京` に戻り、12 race cards表示を確認。
- Operation:
  - iPhoneで古い詳細画面が残る場合は詳細URLに `&v=4` を付けるか、Safariリロード/プライベートタブで開く。

### 2026-04-26 / Session-MOBILE-SD-010
- 現地スマホ向け追加修正:
  - オッズ未表示問題: netkeiba `shutuba/odds` が `---.-` / `result odds empty` を返す場合、JRA公式の単勝・複勝オッズ（馬番順）ページへフォールバックして単勝オッズを取得する経路を追加。
  - Backend: `get_entry_snapshot` でCSVオッズ -> netkeiba odds API/page -> JRA公式 odds の順に単勝を補完し、取得できた場合はCSVにも反映。
  - UI: 詳細ページの馬カードに枠色（1白/2黒/3赤/4青/5黄/6緑/7橙/8桃）と左枠線を追加。
  - UI: 前走/2走前/3走前の着順を `2着` のようなバッジ表示へ変更し、上がり3Fも同じ行に視認しやすく表示。
  - UI: 全R一覧の候補馬ランキングにも枠色バッジを追加。
- Verification:
  - Backend: `python -m py_compile backend/app/services/same_day_service.py` passed。
  - Backend: `PYTHONPATH=. pytest tests -q` passed (40/40)。
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - API: tunnel `/api/v1/races/202605020204/entry` returned odds_count=10 and warnings=0。
  - Same-day sheet cache refreshed: Tokyo 1R-12R odds counts = `15,14,16,10,18,8,16,11,16,15,13,16`。
  - Playwright iPhone/tunnel: 4R detail shows JRA odds, colored frame labels, and `2着/11着` style finish badges.
- Notes:
  - netkeiba odds source still returns empty for these races; current odds display relies on JRA official fallback.
  - iPhoneで古いPWA cacheが残る場合はURLに `&v=5` 等を付けて再読込する。

### 2026-04-26 / Session-MOBILE-SD-011
- Race detail client-side cacheを追加:
  - `/races/[raceKey]` で一度取得した `race / entry / courseStats / betPlan` を `sessionStorage` に保存。
  - 同じブラウザタブ内で全R一覧へ戻って再度詳細へ入った場合、API再取得を待たずに保存済みデータを即表示する。
  - 更新したい場合は既存の `最新オッズ・基本情報を取得` ボタンで force refresh し、再取得後にキャッシュも上書きする。
  - 画面上部に `保存済みデータを即表示中 / HH:MM` または `このレース情報を端末に保存済み / HH:MM` を表示。
- Verification:
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - Production server restarted。
  - Playwright iPhone/tunnel: 4R詳細を初回取得後、全R一覧へ戻って再度4R詳細へ入ると `保存済みデータを即表示中` が1秒以内に出ることを確認。
  - sessionStorage key: `keiba:same-day:race-detail:202605020204` を確認。
- Notes:
  - `sessionStorage` のため同じSafariタブ内では残る。タブを閉じる/ブラウザが破棄すると消える。
  - オッズを最新化したい場合は手動更新ボタンを押す運用。

### 2026-04-27 / Session-MOBILE-SD-012
- 来週の現地利用に向け、スマホPWA起動を1コマンド化:
  - Added `scripts/start_mobile_pwa.ps1`。
  - Added `scripts/stop_mobile_pwa.ps1`。
  - `start_mobile_pwa.ps1` は古い backend/frontend/cloudflared を安全に停止し、FastAPI backend、Next.js production frontend、必要に応じて Cloudflare Quick Tunnel を起動する。
  - 起動後に iPhone 用URL `/same-day-sheet?date=...&venue=...` を標準出力へ表示する。
  - `stop_mobile_pwa.ps1` は pid file と port owner の両方から backend/frontend/tunnel を停止し、古いpid/一時URLファイルも削除する。
- Operation:
  - 通常起動: `powershell -ExecutionPolicy Bypass -File scripts\start_mobile_pwa.ps1 -Date 2026-05-03 -Venue 東京`
  - ビルド済みを再利用: `powershell -ExecutionPolicy Bypass -File scripts\start_mobile_pwa.ps1 -Date 2026-05-03 -Venue 東京 -SkipBuild`
  - ローカル検証のみ: `powershell -ExecutionPolicy Bypass -File scripts\start_mobile_pwa.ps1 -Date 2026-05-03 -Venue 東京 -SkipBuild -NoTunnel`
  - 終了: `powershell -ExecutionPolicy Bypass -File scripts\stop_mobile_pwa.ps1`
- Verification:
  - Script syntax check passed for both start/stop scripts via `[scriptblock]::Create(...)`。
  - Local startup path was verified with `-SkipBuild -NoTunnel`: `/health` returned 200 and `/same-day-sheet?date=2026-04-26&venue=東京` returned 200 with 12R visible。
  - Stop script was verified to stop frontend/backend listening owners on ports 3000/8000 and remove stale pid/url files。
  - Cloudflare Quick Tunnel startup was verified: generated public URL returned `/health` 200 and `/same-day-sheet?date=2026-04-26&venue=東京` 200 with 12R visible。
- Notes:
  - Cloudflare Quick Tunnel URL is temporary and public to anyone who knows the URL; stop it after use。
  - `tmp/cloudflared.exe` is reused if present; if missing, the start script downloads it。
  - Public URL changes every time the tunnel starts, so the script output should be treated as the source of truth。



### 2026-04-27 / Session-MOBILE-SD-013
- 今回のスマホPWA現地運用ノウハウを Codex Skill として抽出:
  - Created `C:\Users\tadas\.codex\skills\mobile-field-pwa\SKILL.md`。
  - Created `C:\Users\tadas\.codex\skills\mobile-field-pwa\agents\openai.yaml`。
  - 仙台旅行アプリなど別プロジェクトへ展開できるよう、競馬固有実装ではなく「現地でスマホ片手に使うPWA」の設計/実装/検証手順へ一般化。
- Covered:
  - mobile-first day sheet/detail architecture, same-origin API rewrites, iPhone + tunnel pitfalls, server-rendered critical list, sessionStorage detail cache, manual refresh, fallback/warnings, startup/stop script expectations, Playwright/mobile validation checklist。
- Verification:
  - Skill frontmatter and `agents/openai.yaml` were written and inspected。
  - Key sections found: `Next.js + iPhone + Tunnel Rules`, `Startup Script Expectations`, `Common Failure Modes`。
- Usage:
  - 別プロジェクトで `$mobile-field-pwa` を指定して依頼すると、このノウハウを前提に設計/実装できる。

### 2026-05-02 / Session-REPO-001
- 実施内容:
  - リポジトリ整理のおすすめ順に沿って、まず `.gitignore` を強化。
  - `tmp/`、`.playwright-mcp/`、Playwrightスクリーンショット、pid/log、Next PWA生成物（`sw.js` / `workbox-*` / `fallback-*`）をGit管理対象外へ整理。
  - 既にGit管理されていた `tmp/` 配下の検証副産物を `git rm -r --cached tmp` で追跡解除（ローカルファイルは保持）。
  - 新規実装ソース（backend/frontend/docs/scripts/legacy追加分）と検証副産物が `git status` 上で分離して見える状態にした。
- 結果:
  - `git check-ignore` で `tmp/cloudflared.exe`、`.playwright-mcp/*.yml`、rootスクショ、Next PWA生成物がignore対象であることを確認。
  - `legacy/streamlit_app/data/search_cache/*.json` は従来方針どおり追跡可能なまま維持。
- Verification:
  - Backend: `$env:PYTHONPATH='backend'; python -m pytest backend\tests -q` passed（40/40）。
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
- 発生課題:
  - 最初に `$env:PYTHONPATH='.'` でpytestを実行したため `ModuleNotFoundError: No module named 'app'` が発生。正しい実行方法は `$env:PYTHONPATH='backend'`。
- 次回着手:
  - コミット前に `git status --short` を確認し、ソース追加分と `tmp/` 追跡解除をまとめてコミットする。

### 2026-05-02 / Session-MOBILE-SD-014
- 実施内容:
  - 2026-05-03 東京向け Next.js/PWA 一時URLを再発行。
  - 全Rシートの `0.223` などの生スコア表示を、スマホで意味が分かる `候補指数` 表示へ変更。
  - 詳細ページの保存先を `sessionStorage` から `localStorage` に変更し、同じ端末/ブラウザならタブを閉じても静的情報が残るようにした。
  - 詳細キャッシュ保存時はオッズを保存対象外にし、最新オッズは更新ボタンで再取得する運用へ寄せた。
  - 全Rシートの `refresh=true` を「重い全再生成」ではなく、既存キャッシュに対する単勝オッズのみ軽量更新に変更。
  - netkeibaオッズAPI用の構造化パーサーを追加し、公開後に `horse_list + odds[1]` 形式を馬名へマッピングできるようにした。
  - 低速なJRA総当たりフォールバックを通常経路から外し、オッズ未公開時でも更新が数秒で返るようにした。
- 結果:
  - 現時点のnetkeiba APIは `result odds empty` のため、5/3東京の単勝オッズはまだ0頭。これは公開前/空レスポンスによるもの。
  - 公開後は全Rシートの更新リンク、または各R詳細の `最新オッズ・基本情報を取得` で再取得する。
  - 新しい一時URL: `https://significantly-vatican-website-observed.trycloudflare.com/same-day-sheet?date=2026-05-03&venue=%E6%9D%B1%E4%BA%AC`
- Verification:
  - Backend: `$env:PYTHONPATH='backend'; python -m pytest backend\tests -q` passed（42/42）。
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - Tunnel `/health` returned 200。
  - Tunnel `/same-day-sheet?date=2026-05-03&venue=東京` returned 200、`候補指数` 表示あり、`0.223` 生表示なし。
  - Tunnel `refresh=true` returned 200 in 3.9s。
  - Playwright: 1R詳細を初回表示後、同一URL再読込で `保存済みデータを即表示中` を確認。
- 発生課題:
  - `scripts/export_same_day_sheet.py` による全R再生成はコース統計取得込みで3分超過しタイムアウト。現地運用は既存シートキャッシュ + オッズ軽量更新を優先する。
- 次回着手:
  - 明日の現地ではPCをスリープさせず、オッズ公開後に全Rシートの更新リンクを押して単勝オッズ反映を確認する。

### 2026-05-02 / Session-MOBILE-SD-015
- 実施内容:
  - netkeiba出馬表ではオッズが表示されているのにPWAで取得できない問題を調査。
  - 原因は、出馬表HTML初期表示が `---.-` で返り、その後JavaScriptが `api_get_jra_odds.html` の圧縮レスポンスを展開してオッズを埋める仕様だったこと。
  - backendのnetkeibaオッズAPI呼び出しを `type=1&action=init&sort=odds&compress=1` へ修正。
  - zlib + base64 の圧縮 `data` をPython側で展開し、`odds["1"]` の馬番別単勝オッズを `__umaban__:{馬番}` としてマージする処理を追加。
  - 馬名マップがない場合でも馬番で `entry.horses` とCSVへ反映できるよう `_merge_odds_into_horses` / `_write_odds_to_csv` を拡張。
- 結果:
  - `202605020406`（5/3東京6R）で単勝オッズ16頭分を取得。
  - 例: `チームユートピア 1.6`、`ワンモメンタム 7.3`、`スーパーガール 57.0`。
  - 新しい一時URL: `https://darwin-nav-lying-dakota.trycloudflare.com/same-day-sheet?date=2026-05-03&venue=%E6%9D%B1%E4%BA%AC`
- Verification:
  - Backend direct: `_fetch_win_odds_map("202605020406")` returned 16 odds from `netkeiba odds API`。
  - Backend entry API: `/api/v1/races/202605020406/entry` returned `odds_count=16`, `warnings=[]`。
  - Backend: `$env:PYTHONPATH='backend'; python -m pytest backend\tests -q` passed（44/44）。
  - Frontend: `npm run lint` passed。
  - Tunnel `/health` returned 200。
  - Tunnel `/same-day-sheet?...&refresh=true` returned 200 in 2.6s and contains `チームユートピア` / `1.6`。
  - Playwright local PWA: 6R詳細画面に `チームユートピア` / `1.6` が含まれることを確認。
- 発生課題:
  - Playwright MCPから新Cloudflare URLへの名前解決が一時的に失敗したため、Playwright画面確認は `http://127.0.0.1:3000` で実施。PowerShellではCloudflare URLも200確認済み。
- 次回着手:
  - 明日は最新URLをスマホで開き、全Rシートの更新リンクを押してオッズ反映を確認する。

### 2026-05-02 / Session-MOBILE-SD-016
- 実施内容:
  - 5R以降の東京全Rシートキャッシュを確認し、entry / course_stats / bet_plan / 単勝オッズが揃っていることを検証。
  - 詳細ページ初回表示時に、localStorage未保存でも同日同場の `/same-day-sheet` キャッシュから該当レースを抽出して表示する経路を追加。
  - 詳細ページのlocalStorage保存はオッズも含めて保存する方針に変更（最新化は手動更新ボタンで上書き）。
  - 新しい一時URLを再発行。
- 結果:
  - 5R〜12Rは全て `entry.horses`、単勝オッズ、枠別/脚質等のレース特徴、候補ランキングがキャッシュ済み。
  - 5R〜12Rのオッズ取得頭数: `15,16,15,9,18,16,15,13`。
  - 新しい一時URL: `https://scenes-shoppers-hop-impression.trycloudflare.com/same-day-sheet?date=2026-05-03&venue=%E6%9D%B1%E4%BA%AC`
- Verification:
  - Backend API direct: 5R〜12Rの `/entry` が全て `warnings=0` かつ単勝オッズ取得済み。
  - Backend sheet cache: 5R〜12Rの `course_stats.frame_stats=8`、`bet_plan.ranking` は各頭数分あり。
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - Backend: `$env:PYTHONPATH='backend'; python -m pytest backend\tests -q` passed（44/44）。
  - Tunnel `/same-day-sheet?date=2026-05-03&venue=東京` returned 200 and includes 5R/6R odds data。
  - Playwright: localStorage clear後、5R詳細初回表示で `保存済みデータを即表示中`、単勝オッズ、`コース特徴`、`枠別成績割合` を確認。
- 発生課題:
  - 詳細初回は完全なブラウザ内保存ではなく、まずサーバー側シートキャッシュJSONを1回読む。ただし重いnetkeiba/Gemini等の再取得は走らない。
- 次回着手:
  - 明日は5R以降は全Rシートから詳細へ入り、必要時だけ `最新オッズ・基本情報を取得` を押して上書きする。

### 2026-05-02 / Session-MOBILE-SD-017
- 実施内容:
  - 当日モード詳細の各馬近3走に `走破タイム / タイム指数 / レースレベル / 着差` を追加する安全実装を実施。
  - `fetch_recent_runs()` の戻り値に後方互換の `horse_id` を追加し、backend側で `db.netkeiba.com/horse/result/{horse_id}/` から詳細を補完。
  - APIレスポンスに `recent_run_details` を追加し、既存の `recent_runs / last3fs / corners / field_sizes` は維持。
  - 候補指数へタイム指数補正を小幅反映（最大+0.12 / 最小-0.03）し、強い場合のみ理由へ `指数A` / `近走指数強め` を追加。
  - 詳細ページは旧localStorage/旧シートキャッシュに `recent_run_details` が無い場合は直接API取得へフォールバックするよう変更。
- 結果:
  - 5/3東京5Rの実測で `1:48.3 / 指数73 C / 着差0.6` のような詳細が取得できることを確認。
  - 5/3東京5R〜12Rのシートキャッシュを新形式へ更新。詳細取得頭数は全レース出走頭数分、タイム指数も概ね取得済み。
  - 5R〜12Rの詳細/指数/オッズ取得状況: `5R 15/15/15`, `6R 16/16/16`, `7R 15/14/15`, `8R 9/8/9`, `9R 18/18/18`, `10R 16/15/16`, `11R 15/15/15`, `12R 13/13/13`（details/indexes/odds）。
- Verification:
  - Backend: `python -m py_compile backend\app\services\same_day_service.py backend\app\schemas\races.py legacy\streamlit_app\get_keiba_info.py` passed。
  - Backend: `$env:PYTHONPATH='backend'; python -m pytest backend\tests -q` passed（46/46, pandas FutureWarning 1件は既存のCSVオッズ書き戻し由来）。
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - Direct check: `get_entry_snapshot("202605020405")` returned 15 horses, warnings 0, recent run details and index-based ranking reasons.
  - PWA restart: 変更前の `next start` が古いビルドを掴んでいたため再起動し、新URLで5R詳細に `1:48.3` / `指数73 C` / `着差0.6` / `指数85 A` が表示されることをPlaywrightで確認。
  - User check: ユーザー端末でも近3走チップ表示が確認できた。
- 発生課題:
  - PowerShellに直接 `東京` を埋め込むと文字化けし、誤った `venue` キャッシュ名が作られることを確認。該当の一時ファイルは削除済み。今後スクリプト経由ではUnicode escapeまたは既存のURLエンコードを使う。
  - 画面変更後は起動中の `next start` を再起動しないと旧ビルドが表示され続ける。現地用URLも再起動ごとに変わる。
- 次回着手:
  - 明日は最新URLを開き、必要に応じて `最新オッズ・基本情報を取得` で直前オッズへ上書きする。

### 2026-05-02 / Session-MOBILE-SD-018
- 実施内容:
  - R詳細ページ上部に `AI共有用Markdown` ボタンを追加。
  - ボタン押下で、ChatGPT/Gemini Deep Researchへ貼り付けやすいMarkdown本文を読み取り専用テキストエリアに表示。
  - Markdownにはレース情報、出馬表、近3走・指数、コース特徴、候補馬ランキング、買い目、外部情報（YouTube/X/Web）を出力。
  - `ExternalWorkbenchCard` のYouTube/X取得結果を親ページへ通知し、R詳細のlocalStorageキャッシュにも保存できるようにした。
  - Clipboard APIで `コピーする` ボタンを追加し、失敗時はテキストエリアを選択して手動コピーできる導線を用意。
- 結果:
  - 5/3東京5Rで、出馬表・走破タイム・指数・レースレベル・コース特徴・候補指数・買い目がMarkdownに含まれることを確認。
  - 外部情報が未取得の場合は `未取得` と明示される。
  - 検証時、Next dev serverではHMR WebSocket由来で詳細ページのhydration確認が不安定だったため、production build + `next start` で実画面確認を実施。
- Verification:
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - Playwright: `http://127.0.0.1:3001` のproduction startで5/3東京5R詳細を開き、`AI共有用Markdown` パネル表示、`## 近3走・指数` を含むtextarea、`コピーしました` 表示を確認。
- 発生課題:
  - Web情報は現時点でR詳細ページ側の取得UIが未実装のため、Markdown内では `未取得` と表示する。必要なら次フェーズでWeb取得UI/キャッシュを追加する。
- 次回着手:
  - 現地利用前に本番用 `next start` / Cloudflare tunnel を再起動し、最新ビルドのURLをスマホへ共有する。

### 2026-05-02 / Session-MOBILE-SD-019
- 実施内容:
  - 5/3東京の現地スマホ利用前提で、全R一覧とR詳細の同期・更新導線を改善。
  - 全R一覧をクライアント描画コンポーネントへ分離し、R詳細のlocalStorageキャッシュを一覧へ反映できるようにした。
  - 全R一覧に `全R詳細をこの端末に保存` ボタンを追加し、12R分の詳細キャッシュを端末に事前保存できるようにした。
  - 全R軽量更新で、単勝オッズに加えて馬体重/増減も再取得・マージするbackend処理を追加。
  - APIレスポンスに `odds_updated_at` / `body_updated_at` を追加し、一覧カードへレース別更新時刻を表示できるようにした。
  - AI共有Markdownの馬場表示を修正し、`track_conditions` が空でも `race_data01` から `馬場:良` 等を補完するようにした。
- 結果:
  - 5/3東京5Rで、R詳細の `最新オッズ・基本情報を取得` 後に、全R一覧へ戻ると5R候補ランキングの単勝が更新後の値へ同期されることを確認。
  - 全R一覧の `全R詳細をこの端末に保存` で、localStorageに12R分の `keiba:same-day:race-detail:*` が保存されることを確認。
  - AI共有Markdownで `- 馬場: 良`、走破タイム、指数、コース特徴が出力されることを確認。
- Verification:
  - Backend: `python -m pytest tests -q` from `backend` passed（46/46, pandas FutureWarning 1件は既存のCSVオッズ書き戻し由来）。
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - Playwright: スマホ幅390pxで `/same-day-sheet?date=2026-05-03&venue=東京` が12R表示、横スクロールなし、全R保存ボタン表示を確認。
  - Playwright: 全R保存後に `cacheKeys=12` を確認。
  - Playwright: 5R詳細更新後、一覧5Rカードが `オープンザパンドラ 単勝 3.2` へ同期されることを確認。
  - Playwright: AI共有Markdownの馬場行が `- 馬場: 良` になることを確認。
- 発生課題:
  - ローカル検証中のNext rewriteは既存8000番backendを参照していたため、8010番の新backendで追加した更新時刻フィールドはブラウザ経由では未確認。直接APIでは `odds_updated_at` が返ることを確認済み。公開前はbackend/Next/tunnelをまとめて再起動する。
  - 馬体重は5/2 23時台時点ではnetkeiba上で未公開のため、更新処理は入ったが `馬体重 0頭` のまま。公開後に全R軽量更新で再確認する。
- 次回着手:
  - 最新ビルドでmobile PWA/tunnelを再起動し、スマホ用URLを再発行する。

### 2026-05-03 / Session-MOBILE-SD-020
- 実施内容:
  - 当日モードR詳細の近3走詳細に `venue`（前走〜3走前の開催場所: 東京/中山/京都など）を追加。
  - `db.netkeiba.com/horse/result/{horse_id}/` の結果表から `開催` 列をheader-basedで取得し、開催表記からJRA場名を正規化する処理を追加。
  - `RecentRunDetail` APIスキーマとfrontend型へ `venue` を追加し、既存の近走表示チップに場所を控えめに表示。
  - AI共有用Markdownの近3走詳細にも `場所 中山` のように出力されるようにした。
  - タイム指数列の検出候補を `タイム指数` に加えて `指数` まで広げ、2・3走前も取得元に値がある場合は表示できるようにした。
  - 旧キャッシュ判定を更新し、`venue` 未格納の当日シートは再生成対象にした。
- 結果:
  - 5/3東京の全12Rシートキャッシュを新形式で再生成。
  - 1Rサンプルで `中山 / 中山 / 福島`、`1:56.2 / 指数64 D` などが近3走チップに表示されることを確認。
  - 2・3走前のタイム指数はnetkeiba側が空欄の場合は `指数なし` のまま。取得元に値があれば同じ表示欄に出る。
  - モバイルPWA/tunnelを最新ビルドで再起動し、5/3東京URLを再発行。
- Verification:
  - Backend: `python -m pytest tests -q` from `backend` passed（46/46, pandas FutureWarning 1件は既存のCSVオッズ書き戻し由来）。
  - Frontend: `npm run lint` passed。
  - Frontend: `npm run build` passed。
  - Cache: `data/same_day_sheets/2026-05-03_tokyo_same_day_sheet.json` に `recent_run_details[].venue` が入ることを直接確認。
  - Playwright: `http://127.0.0.1:3000/same-day-sheet?date=2026-05-03&venue=東京` → 1R詳細で `中山`、`福島`、`指数64 D` が表示されることを確認。
- 発生課題:
  - netkeibaの馬別結果表で2・3走前のタイム指数が空欄の馬は補完できないため、表示は `指数なし` とする。
  - PowerShellで日本語引数を直書きすると文字化けする場合があるため、キャッシュ再生成時はUnicode escape/URLエンコードを使う。
- 次回着手:
  - 現地利用中は新URLを開き、直前は全R一覧の `オッズ・馬体重公開後に全Rを軽量更新` で最新化する。

### 2026-05-09 / Session-MOBILE-SD-021
- 実施内容:
  - 5/10東京競馬場の当日モード利用に向けて、東京全12Rの同日シートキャッシュを生成。
  - `2026-05-10 / 東京` の race_id を全12R分確認し、entry / course_stats / bet_plan をキャッシュへ保存。
  - モバイルPWA + FastAPI + Cloudflare quick tunnel を5/10東京用に起動。
  - Playwrightで全R一覧、全R詳細端末保存、11R NHKマイル詳細を確認。
- 結果:
  - 5/10東京は全12R取得成功。各Rで出走馬、単勝オッズ、近走詳細、コース特徴、候補ランキングが取得済み。
  - 取得状況: `1R 16/16/16`, `2R 16/16/16`, `3R 18/18/18`, `4R 14/14/14`, `5R 16/16/16`, `6R 11/11/11`, `7R 16/16/16`, `8R 11/11/11`, `9R 9/9/9`, `10R 12/12/12`, `11R 18/18/18`, `12R 15/15/15`（horses/odds/details）。
  - 11R NHKマイル詳細で単勝、前走〜3走前の開催場所、走破タイム、指数、AI共有用Markdownボタンを確認。
  - 現在の一時URL: `https://stolen-levy-cumulative-voltage.trycloudflare.com/same-day-sheet?date=2026-05-10&venue=%E6%9D%B1%E4%BA%AC`
- Verification:
  - Direct API/service: `get_same_day_races(2026-05-10, 東京)` returned 12 races with race_id.
  - Direct cache generation: `build_same_day_sheet_snapshot(2026-05-10, 東京)` completed with `race_count=12` and `error=''` for all races.
  - Playwright: `/same-day-sheet?date=2026-05-10&venue=東京` shows 12R, NHKマイル, `全R詳細をこの端末に保存`.
  - Playwright: allR保存後、localStorageに5/10東京race_id分の詳細キャッシュが入ることを確認。
  - Playwright: 11R詳細で `NHKマイル`、`単勝`、`指数`、開催場所チップ、`AI共有用Markdown` を確認。
- 発生課題:
  - 馬体重は5/9 22時台時点では未公開のため `0頭`。当日公開後に `オッズ・馬体重公開後に全Rを軽量更新` を押す。
  - Cloudflare quick tunnel URLは一時URL。PC/プロセス停止やトンネル切断でURLが変わるため、当日朝に再発行・再共有するのが安全。
- 次回着手:
  - 5/10当日朝または出発前にPCをスリープしない設定にし、同URLへスマホ2台でアクセス確認。必要なら `scripts/start_mobile_pwa.ps1 -Date 2026-05-10 -Venue 東京 -SkipBuild` で再起動してURLを共有し直す。
  - レース直前は全R一覧の `オッズ・馬体重公開後に全Rを軽量更新` を押し、馬体重/直前オッズを更新する。
