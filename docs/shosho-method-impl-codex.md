# CODEX 実装指示書 — 丞相メソッド強化（現地モード回収率アップ）

> この文書を CODEX への指示として使う。CODEX はリポジトリ `c:\WORK\keiba`（backend=FastAPI/Python, frontend=Next.js/TS）で作業する。
> 既存の丞相買い推奨基盤は実装済み。本指示は **動画検証済みと整合する付録A/C/F だけ** を反映し、**回収率（収支）重視**で当日成績を上げる増分実装＋**バックテスト**を追加するもの。
> 典拠ナレッジ: [shosho-baken-method.md](shosho-baken-method.md) 本文§＋「付録: 外部資料由来の補足」。方針メモリ: 「丞相実装は動画と矛盾する外部資料を入れない」。

## 0. 厳守する原則（最重要）
1. **回収率・収支重視**。的中率は低くてよい。2軸（軸信頼=能力、妙味=期待値）を**分離したまま**維持し、単一指数に統合しない（丞相「予想と馬券は別」）。
2. **動画と相反する項目は実装しない**: ❌1%定率ベッティング（既存の固定 `budget_yen` を維持）、❌複勝の5〜10番人気狙い撃ち（複勝は現状の最小スタンス維持）、❌マーケ数値（実績/サロン規模等）。
3. **後方互換**: 既存の `score` / 既存 top-level `tickets` / 既存フィールドは壊さない。新規はすべて optional 追加。
4. **データが無い検出器は実装しない**（調教・パドック・フォトパドック・初ブリンカー・昇級初戦・前走枠）。推測で埋めず、コメントに「データ未取得のため未対応」と明記。
5. しきい値・weight は `backend/app/services/shosho_signals.py` 冒頭の定数ブロックに集約（後追いチューニング可能に）。
6. 完了条件: `pytest` 緑／`tmp/verify_shosho_6_14_offline.py` 緑／`scripts/backtest_shosho.py` 実行可／`frontend` ビルド通過（§8 検証）。

## 1. 触るファイルと既存挙動（事実）
- `backend/app/services/shosho_signals.py`
  - 定数: `SHOSHO_SCHEMA_VERSION="v2"`, `AXIS_DEMERIT_COEF=0.03`, `AXIS_DEMERIT_MAX_PENALTY=0.30`, `POPULAR_ODDS_RANK_MAX=4`, `POPULAR_ODDS_THRESHOLD=5.0`, `VALUE_ODDS_MIN=4.0`, `VALUE_ODDS_MAX_EXCLUSIVE=10.0`, `MID_LONG_ODDS_MIN=5.0`, `CLEAR_FAVORITE_ODDS=2.5`, `ROUGH_VALUE_SCORE_MIN=0.60`, `ROUGH_VALUE_CANDIDATES=3`, `LOCAL_VENUES/MAIN_VENUES/STEEP_SLOPE_VENUES/HANDEDNESS`。
  - `@dataclass(frozen=True) ShoshoRaceContext`: `race_name, grade, venue, surface, distance_m, going, race_date, race_month, field_size, is_handicap, is_filly_only, is_two_year_old, odds_available, top_handicap_weight, odds_rank_by_key`。
  - 関数: `evaluate_shosho_signals(horse, ctx)`→`{danger_flags,value_flags,axis_demerits,axis_demerit_total}`、`ev_curve(odds)`、`horse_key(horse)`、`danger_penalty_applies(horse,ctx)`、`value_score(...)`、`axis_score(ability,demerit_total)`、`recommend_bets(ranked,ctx,budget,provisional_only)`、`_race_shape(ranked,ctx)`、`_win_/_wide_/_quinella_/_trio_recommendations(...)`、`_skip_ticket(...)`。
- `backend/app/services/same_day_service.py`
  - `_build_shosho_context(entry,horses,race)`（odds_rank_by_key・top_handicap_weight 等を生成）、`_odds_rank_by_horse(horses)`、`_rank_horses(...,shosho_ctx)`（各 ranking item に `score=odds_score+ability_score`／`axis_score`／`value_score`／`danger_flags`／`value_flags`／`axis_demerits`／`axis_demerit_total`／`danger_penalty_applied` を付与）、`_build_bet_plan_from_entry(entry,budget_yen,course_stats,track_bias,race)`（`recommendations` と `shosho_schema_version` を同梱、4呼び出し箇所すべて `race` 受け渡し済み）、`_same_day_sheet_has_recent_run_details(...)`（`shosho_schema_version` と ranking の `value_score` をキャッシュ整合チェック）、`get_race_result_rows(race_id, race_meta, refresh)`。
  - **結果行のキー**（バックテストで使用）: `race_id, date, venue, surface, distance_m, race_number, finish_pos, waku, umaban, style, popularity, last3f, body_weight`。
- `backend/app/schemas/races.py`: `BetRankingItem`/`BetTicket`/`BetPlanResponse`（2軸・フラグ・`recommendations` 反映済み。`BetPlanResponse(**dict)` でバリデートし `response_model` で返すため、**新フィールドは必ず Pydantic に追加**しないと欠落する）。
- フロント: `frontend/src/app/races/[raceKey]/page.tsx` の `BetTab`（買い推奨ブロック＋候補馬ランキング＋ソート[候補指数/軸信頼/妙味]＋⚠/🎯＋軸減点＋共有md）、`frontend/src/components/mobile/same-day-sheet-client.tsx` の `RankingRow`、`frontend/src/lib/api/types.ts`。

## 2. Phase 1 — A: 3連複「18点フォーメーション」
`shosho_signals._trio_recommendations` を付録Aの固定フォーメーションに置換（`recommend_bets` 内で **is_rough 時のみ** 呼ぶ現行ゲートは維持＝§5-6準拠）。
- 前提: `ctx.odds_available and ctx.odds_rank_by_key` が揃い、各 ranked item に `umaban` があり、頭数が十分（目安: 人気1〜6番＋穴2＋△4 を満たせる）。
- 配置: 1列目(軸A)=2〜4番人気から `value_score`（同値は `axis_score`）上位1頭 / 2列目=3〜6番人気1頭(B)＋5番人気以下の `value_score` 上位穴2頭(C,D) / 3列目=1番人気(E)＋{B,C,D}＋△（残りから `value_score`(または人気薄)上位)4頭=計8頭。
- 生成: 「A必須・2列目から1頭・3列目から A/2列目選択馬を除外して1頭」を全列挙→ユニーク化で**ちょうど18点**になること（テストで `==18` を保証、`max_points=20` 内）。`strategy="3連複18点鉄板"`, `point_note="18点"`, `reason="1番人気は3列目(合成オッズ低下回避)/2列目に穴2頭"`。
- フォールバック: 人気順・オッズ欠落や頭数不足なら現行の汎用キャップ（≤20点）コンボへ。UI は既存 ticket 描画でOK。

## 3. Phase 2 — C: 4レース評価パラメータ＋期待値指数
**新規スクレイピング禁止**。既存シグナルからの導出のみ。`_race_shape` を拡張（または `_race_metrics(ranked,ctx,entry)` を新設し race_shape に内包）。
- `hatsuran_do`（波乱度 0〜1）: 明確人気馬の有無・`value_candidates` 数・筆頭人気の danger から算出。
- `axis_place_prob`（軸馬連対確率 目安, 0〜1）: 筆頭人気の implied prob（1/odds を出走全体で正規化）と最上位 `axis_score` のブレンド。
- `aite_confidence`（A/B/C）: 2番手以降候補の `value_score` 階層でランク。
- `pace_pattern`: `entry.style_distribution`（既存 `_style_distribution`）の逃げ先行数＋`track_bias` から `前残り/前潰れ/能力重視/TB重視` を判定（`compute_track_bias` 再利用）。
- 期待値指数 top5: `value_score` 降順の上位5頭の ranking item に `is_value_top5=true`。
- これらを `recommendations.race_shape`（dict）に追加。`_race_shape` の既存キー（`has_dangerous_favorite/is_rough/is_solid/value_candidate_count/label`）は維持。

## 4. Phase 3 — F: weight 再校正＋データ可能な検出器追加
- 付録F を参考に danger/value/軸減点の weight を定数で再校正（**ev_curve が妙味の主、フラグは補助**の比率を保つ）。2軸分離厳守。
- 追加可能検出器（`recent_run_details` から導出可・`evaluate_shosho_signals` に小加減点で追加）: コース適性（現 `ctx.venue` 好走）／距離適性（適距離一致）／馬場適性（`ctx.going` 一致好走）／騎手乗り替わり（前走 jockey ≠ 現 jockey）。
- 追加しない（コメントで明記）: 調教・パドック・フォトパドック。
- 再校正後、既存ユニットテスト＋6/14オフライン検証で回帰確認。

## 5. Phase 4 — schema/types & 現地モードUI（最小増分）
- `backend/app/schemas/races.py`: `recommendations.race_shape` に `hatsuran_do/axis_place_prob/aite_confidence/pace_pattern` を optional 追加。`BetRankingItem` に `is_value_top5: bool=False`。`BetTicket`（recommendations側）に `strategy/point_note/max_points` が無ければ追加。
- `frontend/src/lib/api/types.ts`: 上記に対応する optional フィールドを追加。
- `BetTab`（page.tsx）: 買い推奨ブロックに **波乱度・軸連対率・展開パターン** の1行、候補ランキングに **★(is_value_top5)** を追加。共有md（`## 候補馬ランキング`／買い推奨ブロック）にも反映。
- `RankingRow`（same-day-sheet-client.tsx）: ★ と展開ラベルを省スペースで追加、カード下部に推奨券種1行。**モバイル390px幅で横スクロール無し**を維持。

## 6. Phase 5 — バックテスト評価ハーネス（新規 `scripts/backtest_shosho.py`）
- 入力: 過去開催キャッシュ `data/same_day_sheets/*_same_day_sheet.json`（近確オッズ入り entry）＋結果行 `same_day_service.get_race_result_rows(race_id, race_meta)`。
- 手順: 各レースで `same_day_service._build_bet_plan_from_entry(entry, race=race, course_stats=..., track_bias=...)` を再計算→`recommendations.tickets` を `finish_pos` で的中判定（単勝=1着／ワイド=選択2〜3頭中2頭が3着内／馬連=1-2着／3連複=1-2-3着）。
- 指標: 券種別**的中率**（finish_pos から厳密）、**単勝・複勝回収率**（キャッシュ単勝オッズ×的中）。複合券（ワイド/馬連/3連複）の回収率は netkeiba結果ページの**公式払戻を取得＆キャッシュ**して算出。取得不可時は的中率＋注記に縮退。
- A/B比較: 旧ロジック（汎用3連複・旧weight）と新（A/C/F）を切替フラグで回し差分出力。
- 対象日: キャッシュ済み（`2026-05-24`/`2026-05-31` 東京、`tmp/same_day_2026-06-14_tokyo*.json`）＋必要なら追加取得。
- 出力に「キャッシュオッズを近似に使用・少数サンプルの方向性確認であり統計的断定でない」を明記。

## 7. テスト追加（`backend/tests/test_same_day_api.py`、既存パターンに倣う）
- 18点formation: is_rough かつ十分頭数で生成点数が**ちょうど18**・1番人気が軸(1列目)に入らない・各点が3頭ユニーク。フォールバック発動条件も1ケース。
- race metrics: `hatsuran_do∈[0,1]`、堅いレースで低・荒れで高、`pace_pattern` が style 分布で変わる、top5 が `value_score` 降順5頭に付与。
- F再校正: ev_curve は不変（境界回帰）、`axis_score` がオッズ非依存、`value_score` が穴で上がり危険人気(人気馬のみ)で下がる、を維持。
- `BetPlanResponse(**plan)` が新フィールドを欠落させない。

## 8. 検証（CODEX 完了時に実行）
1. `cd backend && python -m pytest tests/test_same_day_api.py -q` → 緑。
2. `cd c:\WORK\keiba && set PYTHONIOENCODING=utf-8 && python tmp/verify_shosho_6_14_offline.py` → 既存12項目＋新アサート緑（18点成立／★top5／race_shape 新指標）。
3. `python scripts/backtest_shosho.py` → 券種別 的中率・回収率の表と「新 vs 旧」差分が出力され、回収率が非劣化〜改善方向。
4. `cd frontend && npm run build` → 通過。現地シート→買い目タブで race_shape 指標・★・18点推奨が表示、390px幅で横スクロール無し。
5. 共有md コピーに 2軸・フラグ・買い推奨・新指標が含まれる。

## 9. やってはいけないこと（再掲）
- 1%定率ベッティング／複勝5-10番人気狙い撃ち／マーケ数値の実装。
- 2軸の単一指数化。既存 `score`・top-level `tickets` の破壊的変更。
- データの無い検出器（調教/パドック/枠替わり/昇級/初ブリンカー）の推測実装。
- `recommend_bets` がオッズ未公開/provisional 時に正式買い目を出すこと（現行どおり note 付きで縮退）。
