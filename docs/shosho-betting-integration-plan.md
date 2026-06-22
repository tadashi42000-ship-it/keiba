# 丞相メソッド 買い推奨統合プラン（CODEX実装用）

## Context / 目的

[docs/shosho-baken-method.md](shosho-baken-method.md) でまとめた丞相（プロ馬券師）の馬券術を、
**現地モードの「買い目」タブ／買い推奨**に取り込む。現状の買い目エンジンは
「人気馬ほど高スコア（odds_score = 1/odds）」で、丞相の「過剰人気を避け期待値（単勝4〜9.9倍）を取る」
という思想と真逆。そこで既存スコアは壊さず、**2軸（軸信頼／妥味＝期待値）**＋**馬別フラグ**＋
**券種・買い目レコメンド**を追加する。

### 確定した方針（ユーザー回答）
- **2軸並列表示**: 既存の能力ベース指数（=軸信頼）は温存。丞相流の「妥味（期待値）」を別軸で追加。
- **スコープ**: ①馬別フラグ（危険人気⚠／穴候補🎯／軸減点） ②券種・買い目レコメンド。
  - 期待値オッズカーブ（4〜9.9倍スイートスポット）は「妥味軸」の算出基盤として内包する。
  - 外部AI（ChatGPT/Gemini）研究ノートのプロンプト改修は**今回対象外**。

### 思想の出典マッピング（丞相メソッドまとめの該当章）
- 危険人気: §7 / 穴候補: §6 / 軸減点リスト: §8 / 期待値・オッズ帯: §3・§5-1 / 券種使い分け: §5 / トラックバイアス: §9（**既存実装あり**）。

---

## 現状アーキテクチャ（実装済み・再利用する土台）

買い目エンジンは加点式の `(bonus, reason)` モジュールを合算する設計で、丞相フラグはこの様式に素直に乗る。

- スコアリング中核: [backend/app/services/same_day_service.py](../backend/app/services/same_day_service.py)
  - `_rank_horses(horses, course_stats, track_bias)` … `score` を `odds_score + style_bonus + recent_bonus + time_bonus + body_bonus + sire_bonus + broodmare_bonus + bias_bonus` で算出し `reason` を生成（L2067付近）。
  - 既存ボーナス関数（**同じ様式で新規追加する**）: `_time_level_bonus` / `_body_weight_bonus` / `_sire_aptitude_bonus` / `_broodmare_sire_aptitude_bonus` / `_track_bias_bonus` / `_recent_finish_bonus`。
  - `_build_bet_plan_from_entry(...)` … `ranking`（全頭）＋ `tickets`（上位3頭の単勝）を生成（L844付近）。**ここに券種レコメンドを足す**。
  - 馬別データ源 `recent_run_details`（`_build_recent_run_details` / `_fetch_horse_run_details_cached`）に各走の
    `date, venue, finish, race_name, distance_m, surface, going, carried_weight, corner, body_weight, time_index, race_eval` が入っている → **丞相フラグの大半はここから導出可能**。
  - キャッシュ整合: `_same_day_sheet_has_recent_run_details()` が必須キーの有無でキャッシュ再生成を判定（L512付近）。`TRACK_BIAS_SCHEMA_VERSION`（L45）。
- 既存の関連サービス: `track_bias.py`（`compute_track_bias`：丞相§9の「6番人気以下の穴がどこを通ったか」に相当する馬場偏り算出が**既に存在**）、`sire_aptitude.py`、`race_time_rating.py`。
- API: [backend/app/api/v1/races.py](../backend/app/api/v1/races.py)、スナップショットに `bet_plan` / `track_bias` を載せて返す。
- フロント型: [frontend/src/lib/api/types.ts](../frontend/src/lib/api/types.ts) … `BetRankingItem`(L162) / `BetTicket`(L174) / `BetPlanResponse`(L182) / `TrackBias`(L254)。
- フロント表示:
  - 詳細「買い目」タブ: [frontend/src/app/races/[raceKey]/page.tsx](../frontend/src/app/races/[raceKey]/page.tsx) … `TabKey="bet"`、`BetTab`（L444付近）、共有md生成（L536/L544「買い目」）。
  - 現地シート各Rカード: [frontend/src/components/mobile/same-day-sheet-client.tsx](../frontend/src/components/mobile/same-day-sheet-client.tsx) … `RankingRow`（`score`/`bias_bonus` 表示、L418付近）。

---

## データ実現性マップ（丞相ルール → 算出可否）

`recent_run_details` と「現レース文脈（surface/distance_m/venue/going/race_date/race_name/field_size）」から導出する。

| 丞相ルール | 種別 | 可否 | 算出元 |
|---|---|---|---|
| 前走逃げて好走（§7,§8） | 危険人気/−5 | ✅ | `details[0]` の `corner`→`classify_corner_style`＝逃げ かつ `finish<=3` |
| 半年以上の休み明け（§7,§8） | 危険人気/−3 | ✅ | race_date − `details[0].date` ≥ 約180日 |
| 特殊馬場好走→良馬場（§7,§8） | 危険人気/−4 | ✅ | `details[0].going∈{重,不良}` かつ `finish<=3` かつ現 `going=良` |
| 距離短縮ローテ（§6,§8） | 穴候補 | ✅ | `details[0].distance_m − 現distance ≥ 200`（マイル/中距離→短距離で加点強） |
| 距離延長ローテ（§8） | −5 | ✅ | 現distance − `details[0].distance_m ≥ 200` |
| 芝→ダート替わり（§6） | 穴候補 | ✅(部分) | `details[0].surface=芝` かつ現`surface=ダ`（馬体重460↑等で重み増） |
| 初ダート/初芝（§8） | −5 | ✅ | 直近3走に現surfaceの出走が無い |
| 前走4〜6着（§5-1,§6） | 穴候補(単勝妙味) | ✅ | `details[0].finish∈4..6` |
| ピンパー（§5-1） | 穴候補 | ✅(近似) | 近3走の `finish` 分布が「1着 or 着外」に二極化 |
| 得意コース回帰（§6） | 穴候補 | ✅(部分) | 直近走 `venue==現venue` かつ `finish<=3` |
| 季節適性 冬牝/夏牡（§8,§10-3） | −1 | ✅(部分) | 現レース月 ＋ `sex_age` の性別 |
| 前走ローカル競馬場（§8,§10-1） | −4 | ✅ | `details[0].venue ∈ ローカル6場` かつ現がメイン場 |
| ハンデで斤量重い（§8） | −3 | ✅(部分) | 現 `weight` がレース内上位 ＋ レースがハンデ戦 |
| 坂コース実績なし（§8,§10-1） | −2 | ✅ | 現venueが急坂場 かつ 過去に急坂場で `finish<=3` 無し |
| 馬体重±15kg以上（§8） | −2 | ✅ | `body_delta` 絶対値 ≥ 15 |
| 右/左回り初・偏り（§8,§10-1） | −1 | ✅ | venue→回り対応表 と 過去走venueの回り分布 |
| 牝馬限定→牡馬混合(ダ)（§7,§8） | 危険人気/−5 | △ | `details[0].race_name` に「牝」かつ現race_nameが非限定 かつ `surface=ダ` |
| 初ブリンカー（§6） | 穴候補 | ❌ | 出馬表のブリンカー印が未取得（**将来拡張**） |
| 昇級初戦（§8） | −4 | ❌ | クラス情報が現データに無い（**将来拡張**） |
| 芝外枠替わり/ダ内枠替わり（§7） | 危険人気 | ❌ | 前走の枠が `recent_run_details` に無い（**将来拡張**） |

> ❌/△ は実装時に「データ不足のため未対応」と明記し、推測で埋めない。venue系の対応表（回り・急坂・ローカル/メイン・関西/関東）は §10 を典拠に定数化する。

---

## Phase 1 — backend: 丞相シグナル算出モジュール（新規）

新規 `backend/app/services/shosho_signals.py`。純粋関数の集合で副作用なし、既存 `(bonus, reason)` 様式に合わせる。

```python
# 公開エントリ
def evaluate_shosho_signals(horse: dict, ctx: ShoshoRaceContext) -> dict:
    """returns {
      'danger_flags': [{'code','label','weight'}],   # 危険人気（§7）
      'value_flags':  [{'code','label','weight'}],    # 穴候補（§6,§5-1）
      'axis_demerits':[{'code','label','points'}],    # 軸減点（§8, -5..-1）
      'axis_demerit_total': int,
    }"""
```

- `ShoshoRaceContext`: `surface, distance_m, venue, going, race_date(date), is_handicap, is_filly_only, field_size, race_month`。
  `same_day_service` 側で race メタ＋entry から組み立て（race_name から `is_handicap`=「ハンデ」, `is_filly_only`=「牝」「牝馬限定」を判定）。
- venue 定数（§10典拠）: `HANDEDNESS`(右/左), `STEEP_SLOPE_VENUES`(中山/阪神/中京…), `LOCAL_VENUES`, `MAIN_VENUES`, `KANSAI/KANTO`。
- 検出器は1ルール=1関数（テスト容易化）。例: `_detect_layoff`, `_detect_front_runner_overbet`, `_detect_distance_shorten`, `_detect_prev_finish_4_6`, `_detect_pin_par`, `_detect_body_weight_swing`, `_detect_handedness_mismatch` …。
- `weight`/`points` は丞相まとめ §8 の −5〜−1 をそのまま採用。danger/value の weight は控えめな既定値（例 danger 0.04〜0.08、value 0.02〜0.06）から開始し定数で集中管理。
- 実装不可ルール（初ブリンカー/昇級初戦/枠替わり）は関数を作らず、モジュール冒頭コメントに「未対応・要データ拡張」と明記。

---

## Phase 2 — backend: 2軸スコア（軸信頼／妥味）

`same_day_service._rank_horses` を拡張。**既存 `score` フィールドは変更しない**（後方互換・既存テスト維持）。各 ranking item に新フィールドを追加する。

- `axis_score`（軸信頼, §8）: 能力系ボーナス合算（`style+recent+time+body+sire+broodmare+bias`、**odds_score を含めない**）から `axis_demerit_total` を減算した値。「堅い軸はどれか」を表す。
- `value_score`（妥味/期待値, §3,§5-1,§6）: `ev_curve(odds)` ＋ `value_flags` 加点 − `danger_flags` 減点。
  - `ev_curve(odds)`: 単勝4〜9.9倍をピーク、3.9倍以下と10倍超を逓減、1倍台は強く減点する区分関数（丞相§5-1）。オッズ未公開時は 0（中立）。
- 追加フィールド: `axis_score, value_score, danger_flags, value_flags, axis_demerits, axis_demerit_total`。`reason` には主要フラグを連結（既存 `_rank_reason` を拡張）。
- ソート: `ranking` の既定ソートは現状維持。フロントで「候補指数/軸信頼/妥味」を切替表示できるよう、3値とも item に持たせるだけにする（バックエンドで多重ソートはしない）。
- `_build_bet_plan_from_entry`: ranking に上記を載せる。`provisional_only`（馬番未確定）時も flags/2軸は算出可。

---

## Phase 3 — backend: 券種・買い目レコメンダ（新規）

`shosho_signals.py`（または `same_day_service` 内）に `recommend_bets(ranked, ctx, budget_yen) -> dict` を追加し、`bet_plan["recommendations"]` として返す。丞相§5・§6の買い方ルールをコード化する。

1. **レース性質判定**（`race_shape`）:
   - `has_dangerous_favorite`: 最低オッズ（=人気筆頭）馬に danger_flags あり（§5-1,§7）。
   - `is_rough`: danger多数 / ハンデ / 牝馬限定重賞 / 2歳 / 穴候補(value_flags)が複数頭（§6-3連複の高配当条件）。
   - `is_solid`: 単勝1倍台が存在し danger 無し（§5-1「素直に強い1倍台＝見送り」）。
2. **券種選択と買い目生成**（点数上限を厳守, §5）:
   - 単勝（§5-1）: `value_score` 上位かつオッズ4〜9.9倍の馬を1点。`has_dangerous_favorite` 時に妙味大として推奨度↑。
   - ワイド（§5-2）: 軸=`axis_score`上位かつ減点少の1頭 → 相手=`value_score`上位2〜3頭。人気×人気1点はオッズ5倍以上が条件。
   - 馬連（§5-3）: 相手2点に厳選、合計**6点以内**。単勝1倍台軸は除外。
   - 3連複（§5-6, §6）: `is_rough` のときのみ。軸=人気（axis上位1〜2）、相手=穴（value上位）、**20点以内**。
   - 見送り（§2,§5-1）: `is_solid` かつ妙味馬なし → 「見送り推奨」を返す。
   - 各 ticket に `strategy`（券種ルール名）、`reason`（丞相典拠の短文）、`max_points`/`point_note` を付与。
3. 予算: 既存 `budget_yen` を尊重し、券種ごとの配分は均等回避（本命ライン厚め, §5-3）。

> 数値しきい値（オッズ帯, 休み明け日数, 距離差, 点数上限, weight 既定値）は `shosho_signals.py` 冒頭の定数ブロックに集約し、チューニングを1箇所で行えるようにする。

---

## Phase 4 — frontend: 買い目／買い推奨タブ表示

型を拡張し、既存表示を壊さず追記する。

- [frontend/src/lib/api/types.ts](../frontend/src/lib/api/types.ts):
  - `BetRankingItem` に `axis_score?`, `value_score?`, `danger_flags?`, `value_flags?`, `axis_demerits?`, `axis_demerit_total?`。
  - `BetTicket` に `strategy?`, `point_note?`。`BetPlanResponse` に `recommendations?`（`{race_shape, tickets, note}`）。
- 詳細「買い目」タブ `BetTab`（[page.tsx](../frontend/src/app/races/[raceKey]/page.tsx) L444付近）:
  - 各馬行に **軸信頼／妙味の2値**と、危険人気⚠・穴候補🎯チップ（label表示）を追加。減点合計をバッジ表示。
  - 上部に「買い推奨」ブロック: `race_shape` ラベル（荒れ/堅い/危険人気あり）＋ 推奨券種・買い目・点数上限ノート・丞相理由。
  - ソート切替（候補指数／軸信頼／妙味）。共有md生成（L536/L544）にも2軸・フラグ・推奨を追記。
- 現地シート `RankingRow`（[same-day-sheet-client.tsx](../frontend/src/components/mobile/same-day-sheet-client.tsx) L418付近）:
  - 省スペースで ⚠／🎯 アイコンと妙味値を追加。カード下部に推奨券種の1行サマリ。
- 既存の `formatCandidateIndex`（×100表示）を流用して2軸も同一スケールで表示。

---

## Phase 5 — スキーマ/キャッシュ整合・テスト

- キャッシュ再生成: `_same_day_sheet_has_recent_run_details()` の ranking 必須キー検査に `value_score`・`danger_flags`（少なくとも1キー）を追加し、旧キャッシュを自動失効させる。併せて新しい版数定数 `SHOSHO_SCHEMA_VERSION` を導入し snapshot に保存（または `TRACK_BIAS_SCHEMA_VERSION` を bump）。
- テスト（[backend/tests/test_same_day_api.py](../backend/tests/test_same_day_api.py) の既存パターンに倣う）:
  - `shosho_signals`: 各検出器の正/負ケース（前走逃げ好走・休み明け・距離短縮・前走4-6着・馬体重±15・坂実績なし・回り偏り など）。
  - 2軸: `axis_score` が odds を含まないこと／`value_score` の ev_curve（1.x倍は低, 4-9.9倍ピーク, 10倍超逓減）。
  - `recommend_bets`: 危険人気ありで単勝妙味推奨、荒れ条件で3連複（≤20点）、堅いレースで見送り、点数上限の遵守。
  - `_build_bet_plan_from_entry` が新フィールド／`recommendations` を返すこと。
- フロント: `npm run build`（型チェック）。

---

## 変更/新規ファイル一覧

- 新規: `backend/app/services/shosho_signals.py`（フラグ検出 ＋ 2軸補助 ＋ 券種レコメンダ ＋ venue定数 ＋ しきい値定数）
- 変更: `backend/app/services/same_day_service.py`（`_rank_horses` 2軸化・`_build_bet_plan_from_entry` に recommendations・context組立・キャッシュ版数）
- 変更: `backend/tests/test_same_day_api.py`（テスト追加）
- 変更: `frontend/src/lib/api/types.ts`（型拡張）
- 変更: `frontend/src/app/races/[raceKey]/page.tsx`（BetTab 2軸・フラグ・買い推奨・md）
- 変更: `frontend/src/components/mobile/same-day-sheet-client.tsx`（RankingRow にフラグ・推奨サマリ）
- 典拠: `docs/shosho-baken-method.md`（しきい値・ルールの出典。コード定数のコメントから参照）

---

## 検証手順（CODEX完了時）

1. バックエンド単体: `cd backend && python -m pytest tests/test_same_day_api.py -q` が緑。
2. スナップショット生成: 過去開催日でサービスを実行し、`bet_plan.ranking[].{axis_score,value_score,danger_flags,value_flags}` と `bet_plan.recommendations` が入ること、旧キャッシュが版数更新で再生成されることを確認。
3. 既知ケースで妥当性目視: 1倍台の堅い人気馬は `value_score` が低く「見送り/危険」、前走4〜6着で4〜9.9倍の差し馬は妙味上位、休み明け人気は danger フラグ、を確認（丞相§3・§5-1・§7）。
4. フロント: `cd frontend && npm run build`、現地シート→買い目タブで2軸・⚠/🎯・買い推奨ブロックが表示され、ソート切替が動作。
5. 共有md: 「買い目」タブのコピーに2軸・フラグ・推奨が含まれること。

---

## 留意点

- これは**意思決定支援であり的中保証ではない**。丞相メソッド自体「ハズレ前提・長期回収」が前提（§2）。UIに自己責任の注記を残す。
- 実装不可ルール（初ブリンカー/昇級初戦/枠替わり）は無理に近似せず「未対応」を明示。将来、出馬表のブリンカー印・クラス・前走枠を取り込めば拡張可能（拡張ポイントとしてコメントを残す）。
- 既存 `score`/`bias_bonus`/`tickets` は互換維持。新機能はすべて追加フィールドで提供し、未対応クライアントでも壊れないこと。
