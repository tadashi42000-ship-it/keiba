# Deep Research 連携自動化 実装計画（案C: ブラウザ自動化）

> 本書は実装をCODEXへ引き継ぐための設計・手順書。実装は未着手。
> 方針: **個人サブスク（ChatGPT/Gemini Deep Research）を、本人のPCで、本人利用前提で操作する**ブラウザ自動化。
> 既存の手動往復（手順2〜5）を消し、家PC常駐updaterから発走前に各Rを自動調査し、結果をサーバーバックアップへ書き戻して**スマホはキャッシュを読むだけ**にする。

### 確定仕様（ユーザー決定済み）
1. **両プロバイダ統合**: Gemini と ChatGPT の Deep Research を**並列実行**し、2レポートを **Gemini API で1本に統合**（一致点・相違点を明示）→ 既存 parse で構造化。
2. **対象レース**: **5R以降**（`race_number >= 5`）。
3. **再実行なし**: 1Rにつき Deep Research は1回のみ。オッズ大変動でも Deep Research は再実行しない。
4. **オッズ大変動の再評価**: Deep Research ではなく **Gemini API** を **スマホの手動ボタン**から叩く。出力は**印・買い目の差分提案＋短評**（現地で軽く・確実に更新）。
5. **ログインプロファイル永続**: `scripts/.dr_profile/`（Git除外）に保管・再利用。

---

## 0. 用語と前提

- 「Deep Research」= ChatGPT/Gemini 消費者UIの多段Web調査モード（数分かかる）。公式APIではなくUIを駆動する。
- 実行環境 = 家の常駐PC（Playwright導入済み、`run_same_day_updater.py` が常駐中）。
- 連携先スマホ = 既存の同日モードPWA。サーバーバックアップ `GET /research/notes` を起動時に復元する仕組みが既にある。

---

## 1. 確認済みの既存契約（実装が依存する不変点）

| 項目 | 実体 | 備考 |
|---|---|---|
| 共有Markdown生成 | `buildRaceResearchMarkdown()` [frontend/src/app/races/[raceKey]/page.tsx:433](../frontend/src/app/races/[raceKey]/page.tsx#L433) | クライアント生成。`## 出馬表 / ## 血統適性 / ## 近3走・指数 / ## コース特徴 / ## 候補馬ランキング / ## 買い目` 等のセクション |
| Markdown表示 | `ResearchMarkdownPanel` [page.tsx:1198](../frontend/src/app/races/[raceKey]/page.tsx#L1198) | **readOnly `<textarea value={markdown}>`** に全文が入る（=DOMから直接読める） |
| 構造化parse | `POST /api/v1/races/{race_id}/research/parse` [backend/app/api/v1/races.py:171](../backend/app/api/v1/races.py#L171) | body `{raw_text, entry_horses:[{umaban,horse_name}]}` → `ResearchParsed` |
| parse実体 | `parse_research_report()` [backend/app/services/research_parser.py:39](../backend/app/services/research_parser.py#L39) | Geminiで構造化。`raw_text` 10文字未満は422 |
| サーバーバックアップ取得 | `GET /api/v1/races/{race_id}/research/notes` [races.py:184](../backend/app/api/v1/races.py#L184) | 復元元 |
| サーバーバックアップ保存 | `PUT /api/v1/races/{race_id}/research/notes` [races.py:189](../backend/app/api/v1/races.py#L189) | body=`ResearchNotesBackup` |
| バックアップ保存実体 | `save_research_notes_backup()` [backend/app/services/research_notes_store.py:31](../backend/app/services/research_notes_store.py#L31) | `data/research_notes/{safe_id}.json` に書き込み。`notes` 空はValueError(422) |
| バックアップスキーマ | `ResearchNotesBackup` [backend/app/schemas/races.py:297](../backend/app/schemas/races.py#L297) | `{savedAt:int(ms), notes:str, source:str?, parsed:ResearchParsed?, parsed_at:int?, parse_error:str?}` |
| 構造化結果スキーマ | `ResearchParsed` [races.py:266](../backend/app/schemas/races.py#L266) | `marks[] / horse_notes[] / pace_label / tickets[] / scratched[] / assumed_odds等` |
| スマホ側復元 | `useRaceResearchNotes` [frontend/src/hooks/use-race-research-notes.ts](../frontend/src/hooks/use-race-research-notes.ts) | localStorage key `keiba:same-day:research-notes:{raceId}`、起動時にサーバーバックアップを復元 |
| ドリフト検知 | `detectResearchDrift()` [page.tsx:660](../frontend/src/app/races/[raceKey]/page.tsx#L660) | `parsed.assumed_*` と当日オッズ/バイアスを比較 |
| 詳細ページのメタ | `metaFromQuery` [page.tsx:161](../frontend/src/app/races/[raceKey]/page.tsx#L161) | `date/venue/distance/surface/race_number/race_name` を**URLクエリ**から取得 |

**結論**: 書き戻しは「frontendと同じ3API（GET entry → POST research/parse → PUT research/notes）」を叩くだけでよい。スマホ側は無改修で復元される。Markdownは詳細ページの readOnly textarea から取得できるため**生成ロジックの再実装は不要**。

---

## 2. 全体アーキテクチャ

### 経路1: 発走前 Deep Research 自動調査（家PC・常駐）
```
run_same_day_updater.py (--loop, --enable-deep-research)
   │ 5R以降 かつ lookahead窓入りのRごとに 1回（subprocess・既定OFF・失敗隔離）
   ▼
deep_research_runner.py  --race-id <id> --race-key <key> --providers gemini,chatgpt --once
   │
   ├─(A) Markdown取得（keibaアプリ詳細を開く / headless可）
   │     /races/{raceKey}?date=..&venue=..&distance=..&surface=..&race_number=..&race_name=..
   │     → ResearchMarkdownPanel の textarea 値を読む（= 正規Markdown、再実装不要）
   │
   ├─(B) Deep Research 並列実行（persistent context・本人ログイン）
   │     Gemini ║ ChatGPT を同時に:
   │       start → submit(markdown) → wait_done → extract  → report_gemini / report_chatgpt
   │     （片方失敗でも、得られた方だけで続行）
   │
   ├─(S) 統合フェーズ（Gemini API・backend経由）
   │     POST /races/{id}/research/synthesize {reports:[{provider,text},..]}
   │       → 一致点/相違点を明示した「統合レポート(Markdown)」を1本生成
   │
   └─(C) 書き戻し（既存API + 統合）
         GET  /races/{id}/entry           → entry_horses
         POST /races/{id}/research/parse  → ResearchParsed
         PUT  /races/{id}/research/notes  → source="auto-deep-research"
                                            notes=統合レポート, raw_reports=元2本も保持
   ▼
[スマホPWA] 既存の起動時復元で AI評価 / 印 / ドリフト警告 が自動反映
```

### 経路2: オッズ大変動の手動再評価（スマホ・現地・Gemini APIのみ）
```
[スマホ] 買い目タブの「オッズ変動を反映して再評価」ボタン（手動）
   ▼
POST /races/{id}/research/reassess
   { parsed: <既存ResearchParsed>, current_odds: [...], drift: <detectResearchDriftの結果> }
   → Gemini API（Deep Researchではない・軽量1回）
   → { mark_diffs:[{umaban, from, to, reason}], ticket_diffs:[{action:買い増し|見送り|入替, ...}], comment }
   ▼
[スマホ] 差分提案カードを表示（印・買い目の変更提案＋短評）。元のparsedは破壊しない。
```

**設計原則**
1. **疎結合**: runnerは独立プロセス。updaterはsubprocessとして起動し、失敗してもupdater本体は継続（try/timeout/非ゼロ終了を握りつぶす）。
2. **冪等**: 1Rにつき1回。既存バックアップ(source=auto)があればスキップ。`--force` で再実行。
3. **無改修連携**: 書き戻しは既存3APIのみ。backend/frontendの本流を変えない（追加は任意のメタ程度）。
4. **壊れにくさ優先**: provider依存のセレクタは1ファイルに集約し、コード変更なしで差し替え可能にする。
5. **既定OFF**: deep-research自動実行はフラグで明示的に有効化（`--enable-deep-research` / updater側 `-EnableDeepResearch`）。

---

## 3. 新規・変更ファイル一覧

### 新規
| パス | 役割 |
|---|---|
| `scripts/deep_research_runner.py` | 経路1オーケストレータ（A→B並列→S→C）。CLI: `--race-id --race-key --providers gemini,chatgpt --base-url --frontend-url --profile-dir --timeout-sec --headed --once --force --mock-provider --smoke` |
| `scripts/deep_research_providers.py` | Provider抽象 + `GeminiProvider` / `ChatgptProvider` / `MockProvider`。セレクタはここに集約 |
| `scripts/deep_research_selectors.json` | provider別セレクタ定義（UI変更時コード変更不要）。input/submit/deep-research-toggle/running/answer/copy |
| `scripts/.dr_profile/` | Playwright persistent context のユーザープロファイル（**Gemini+ChatGPTの両ログインcookie永続**）。**.gitignore必須・tmp外の安定パス** |
| backend `research_synthesizer.py`（services） | 2レポートをGemini APIで1本に統合（一致点/相違点明示）。既存 `GeminiTextClient` 再利用 |
| backend `research_reassessor.py`（services） | 既存parsed+現オッズ+driftから印・買い目の差分提案＋短評をGemini APIで生成 |
| `tmp/verify_deep_research_runner.py` | セルフ検証（MockProviderでE2E、Playwright CLI verify形式 PASS/FAIL/WARN） |
| `tmp/verify_research_reassess.py` | 再評価ボタンE2E（Geminiスタブ + スマホ描画） |
| `backend/tests/test_research_notes_roundtrip.py` | parse→notes PUT/GET ラウンドトリップとsource保持の契約テスト |
| `backend/tests/test_research_synthesize_reassess.py` | synthesize/reassess エンドポイント契約テスト（Geminiクライアントはスタブ） |

### 変更
| パス | 変更 |
|---|---|
| backend `app/api/v1/races.py` | `POST /{race_id}/research/synthesize` と `POST /{race_id}/research/reassess` を追加（既存parse/notes近傍） |
| backend `app/schemas/races.py` | `ResearchSynthesizeRequest/Response`, `ResearchReassessRequest/Response`（mark_diffs/ticket_diffs/comment）を追加。`ResearchNotesBackup` に任意 `raw_reports:[{provider,text}]` と `reassessment:{mark_diffs,ticket_diffs,comment,odds_snapshot,at}` を後方互換追加 |
| frontend `src/lib/api/client.ts` | `synthesizeResearch` / `reassessResearch` クライアント追加 |
| frontend `src/app/races/[raceKey]/page.tsx` | 買い目タブに「オッズ変動を反映して再評価」ボタン + 差分提案カード（経路2）。元 `parsed` は不変、提案は別表示 |
| `scripts/run_same_day_updater.py` | 任意フック: **5R以降** かつ lookahead窓入りRで `deep_research_runner` をsubprocess起動（既定OFF・失敗隔離・dedup） |
| `scripts/start_same_day_updater.ps1` / `register_same_day_updater_task.ps1` | `-EnableDeepResearch`（任意） |
| `.gitignore` | `scripts/.dr_profile/` を追加 |
| `docs/commercialization-hurdles.md` | H1/H3に「Deep Research自動化はToSグレー・個人利用限定」追記（任意） |

---

## 4. コンポーネント詳細

### 4.1 Markdown取得フェーズ（A）
- `frontend-url`（既定 `http://127.0.0.1:3000`）の詳細ページを開く。URLクエリは `metaFromQuery` が要求する `date_iso/venue/distance/surface/race_number/race_name` を**必ず全部**付ける（欠けると血統/特徴が出ない既知挙動）。これらは updater がシート生成時に保持しているので引数で渡す。
- 取得方法（堅牢順）:
  1. `ResearchMarkdownPanel` の textarea 値を `page.evaluate` で読む（クリップボード権限不要）。
  2. フォールバック: 「コピーする」クリック → `navigator.clipboard.readText()`（`context.grant_permissions(["clipboard-read"])`）。
- ガード: 取得Markdownに必須セクション（`## 出馬表` と `## 近3走・指数`）が含まれ、かつ「未取得」だらけでない（出馬表行数>0）ことを確認。満たさなければ**中断**（調査に値しない＝entry未公開等）。
- `entry/courseStats/betPlan` のロード完了待ちは `networkidle` + 必須セクションのpollで担保。

### 4.2 Deep Research 並列実行フェーズ（B）— 最も壊れやすい部分
- **対象プロバイダ**: `--providers gemini,chatgpt` を**並列**実行（`asyncio` か `concurrent.futures` で2セッション同時）。
- **片方失敗は許容**: 一方が timeout/例外でも、成功した方のレポートだけで統合(S)→書き戻し(C)へ進む。両方失敗時のみ中断。
- **persistent context**: `playwright.chromium.launch_persistent_context(user_data_dir=profile_dir, headless=not headed)`。**同一プロファイルにGemini/ChatGPT両方をログイン**させておく。初回のみ `--headed` で人手ログイン（cookie永続）。以降はheadlessで再利用。並列時はページ（タブ）を2つ開く（同一context内）か、衝突回避のためprovider別contextに分ける（推奨: provider別 user_data_dir サブフォルダ `gemini/` `chatgpt/`）。
- **Provider抽象** (`deep_research_providers.py`):
  ```python
  class Provider(Protocol):
      name: str
      def start(self, page) -> None: ...            # 新規チャットを開き Deep Research モードを有効化
      def submit(self, page, prompt: str) -> None: ...  # 入力欄へ貼付して送信
      def wait_done(self, page, timeout_sec: int) -> None: ...  # 完了待ち
      def extract(self, page) -> str: ...           # 最終レポート本文を返す
  ```
- **セレクタ集約** (`deep_research_selectors.json`): provider別に `new_chat / input / deep_research_toggle / send / running_indicator / answer_container / copy_button`。UI変更時はJSON差し替えのみ。
- **完了検知**（数分かかる前提）:
  - 「調査中」スピナー/ストリーミングインジケータの消滅 **かつ** 回答コンテナの innerText 長が **安定窓**（例: 連続15秒変化なし）を満たしたら完了。
  - ハード上限 `--timeout-sec`（既定900秒=15分）。超過は TimeoutError で中断。
  - `wait_done` は純関数化した安定窓判定 `is_stable(samples, window_sec)` を内部利用（単体テスト可能にする）。
- **抽出**: provider の copy ボタン優先（Markdownでクリップボードへ）→ フォールバックで answer container innerText。改行・引用脚注を保持。
- **人間的ペーシング**: 入力後 1〜2秒待ってsend、ポーリング間隔は数秒。CAPTCHA検出時は即中断しログに `captcha` を残す（**回避はしない**）。

### 4.3 統合フェーズ（S）— Gemini APIで1本化
- `POST {base-url}/api/v1/races/{race_id}/research/synthesize` body `{reports:[{provider:"gemini",text:".."},{provider:"chatgpt",text:".."}]}`。
- backend `research_synthesizer.py`: 既存 `GeminiTextClient`（`settings.gemini_api_key/gemini_model`）で統合Markdownを生成。**トーン＝「一致を本線＋割れは明示」**: 両者が一致した馬を本線に据えつつ、評価が割れた馬は『割れている』と明示し最終見解も併記する。プロンプトに**「両レポートにない情報は新たに足さない（ハルシネーション禁止）」**を明記。
- 1本のときは統合せずそのまま返す（片方失敗時）。0本は422。
- 返却: `{ synthesized: "<統合Markdown>", providers_used:["gemini","chatgpt"] }`。

### 4.4 書き戻しフェーズ（C）
- `GET {base-url}/api/v1/races/{race_id}/entry` → `entry_horses=[{umaban,horse_name}]`。
- `POST .../research/parse` `{raw_text: 統合Markdown, entry_horses}` → `ResearchParsed`。
  - 失敗時（502/503/422）は parse_error を保持しつつ notes は統合Markdownだけでも保存（手動構造化へフォールバック可能に）。
- `PUT .../research/notes`:
  ```json
  { "savedAt": <now_ms>, "notes": "<統合Markdown>", "source": "auto-deep-research",
    "parsed": <ResearchParsed or null>, "parsed_at": <now_ms or null>,
    "parse_error": "<msg or null>",
    "raw_reports": [{"provider":"gemini","text":"..."},{"provider":"chatgpt","text":"..."}] }
  ```
  - `notes` 空は422になるため、統合結果が空なら**PUTせず中断**。
- 冪等: 実行前に `GET research/notes` し、`exists && source=="auto-deep-research" && !--force` ならスキップ。手動(source="manual")がある場合は**上書きしない**（ユーザー入力優先）。`--force` 時のみ上書き。**再実行なし方針**のため、updaterからは1Rにつき1回だけ起動。

### 4.5 updater 連携（最小・任意）
- `run_same_day_updater.py` に `--enable-deep-research`（既定False）。**`race_number >= 5`** かつ lookahead窓に入った各Rで1回だけ subprocess 起動:
  - `subprocess.run([... deep_research_runner.py --once --race-id .. --race-key .. --providers gemini,chatgpt --base-url ..], timeout=..)`
  - 例外/タイムアウトは捕捉してログのみ。**updaterのポーリングは絶対止めない**。
  - dedup は runner 側の冪等に委譲（updaterは状態を持たない）。再実行なし方針のため1Rにつき1回。
- ステータスJSON（既存 `--status-file`）に `deep_research: {race_id, state: ok|skip|fail|running, providers_used, at}` を任意追記してもよい。

### 4.6 オッズ大変動の手動再評価（経路2・Gemini APIのみ）
- **トリガー**: スマホ買い目タブの「オッズ変動を反映して再評価」ボタン（手動）。Deep Researchは一切呼ばない。
- **活性条件**: **常時押せる**。ただし `detectResearchDrift` がドリフト検出中はボタンを**強調表示**して誘導。
- backend `POST /api/v1/races/{race_id}/research/reassess` body:
  ```json
  { "parsed": <ResearchParsed>,
    "current_odds": [{"umaban":"6","odds":4.2}, ..],
    "body_weights": [{"umaban":"6","body_weight":"498","body_delta":"+4"}, ..],
    "drift": <detectResearchDrift結果（任意）> }
  ```
  - **入力範囲**: 現オッズ＋**直前公開の馬体重/増減**も渡して判断を濃くする。元の印・買い目・assumed値も含める。
- `research_reassessor.py`: 既存 `GeminiTextClient` で**軽量1回**。出力JSON:
  ```json
  { "mark_diffs": [{"umaban":"6","from":"◎","to":"〇","reason":"人気化で妙味減"}],
    "ticket_diffs": [{"action":"買い増し|見送り|入替","horses":["4"],"reason":".."}],
    "comment": "全体短評（1〜2文）" }
  ```
- **元 `parsed` は破壊しない**。提案は別カードで表示（採用はユーザー判断）。
- **永続化（サーバー）**: reassess は計算と同時に **research/notes バックアップへ保存**（`reassessment` フィールドに最新1件＋`odds_snapshot`＋`at`）。`GET /research/notes` 復元で他端末/再訪でも残る。localStorageにもミラーして即時描画。
- レート/コスト: 連打防止に短いクールダウン（例: 60秒）と前回オッズからの最小変動ガード。ガード未満は再呼び出しせず前回提案を再表示。

---

## 5. ToS / 安全・運用上の明記事項

- **本人の有料サブスクを本人PCで操作する個人利用に限定**。共有・商用提供すると各社ToS（自動操作禁止条項）とアカウント凍結リスクが顕在化する（[commercialization-hurdles.md](commercialization-hurdles.md) H1/H3に関連）。
- CAPTCHA・bot検知の**回避実装はしない**。検出時は中断。
- 既定OFF・低頻度（1Rに1回）・人間的ペーシング。キルスイッチ（フラグ/プロファイル削除）を用意。
- ログイン情報はcookieのみ（`scripts/.dr_profile/`、Git除外）。パスワードはコードに置かない。

---

## 6. セルフ検証計画（CODEX 実装後に必ず実施）

> 思想: **fragileなブラウザBフェーズは MockProvider で切り離し、A・C・連携・回帰はAIに触れず決定論的に検証**する。実Bは smoke/手動で最小確認。

### 6-1. MockProvider E2E（最重要・AI不要・決定論的）
`tmp/verify_deep_research_runner.py`（Playwright CLI verify形式 PASS/FAIL/WARN）:
- [ ] `--mock-provider` ＋ `--providers gemini,chatgpt` で runner 実行 → **2本の固定レポートが並列に返り**、統合(S)→書き戻し(C)まで完了。
- [ ] 片方の MockProvider を強制失敗 → 残り1本だけで統合・書き戻しが成功（degrade）。両方失敗 → 中断・notes不変。
- [ ] 統合(synthesize)はスタブGeminiで「一致点/相違点」マーカーを含む統合Markdownを返す。
- [ ] `GET /research/notes` で `source=="auto-deep-research"`, `notes`=統合結果, `raw_reports` に2本保持, `parsed.marks` 期待件数。
- [ ] スマホ詳細ページを開く → AI評価カード描画 / `marks` 反映 / ドリフト警告（assumed_oddsを当日と乖離させた固定値で）表示。
- [ ] 既存 `manual` バックアップがある状態で `--force` なし → **上書きされない**。`--force` あり → 上書きされる。

### 6-2. Markdown取得フェーズ（A）単体
- [ ] 当日Rの詳細URL（全クエリ付）を開き、textarea Markdownに `## 出馬表 / ## 近3走・指数 / ## 候補馬ランキング / ## 買い目` が全て含まれる。
- [ ] 出馬表行数 > 0、印付きRでは「印」列が出る。
- [ ] 必須クエリを1つ欠いたURLでは血統/特徴が「未取得」になる→中断ガードが効く（負例）。

### 6-3. backend契約テスト（pytest）
`test_research_notes_roundtrip.py`:
- [ ] サンプルレポート→`parse_research_report`（Geminiはモック/スタブ）→期待 `marks`。
- [ ] `save_research_notes_backup` + `load_research_notes_backup` のラウンドトリップで `source/parsed/backed_up_at/raw_reports` が保持。
- [ ] `notes` 空で `save_research_notes_backup` が ValueError。

`test_research_synthesize_reassess.py`（Geminiクライアントはスタブ）:
- [ ] `POST /research/synthesize` 2本→統合Markdown1本、`providers_used` 正しい。1本→そのまま返す。0本→422。
- [ ] `POST /research/reassess`→`mark_diffs/ticket_diffs/comment` のスキーマ通り。空オッズ/壊れたdrift→422 or 安全な空提案。
- [ ] Gemini未設定(`not_configured`)→503、API失敗→502 が伝播。
- [ ] 既存スイート緑（`$env:PYTHONPATH='.'; pytest tests -q`、現状40/40・既知pandas FutureWarning1件のみ）。

### 6-4. 完了検知ロジック単体（純関数・ブラウザ不要）
- [ ] `is_stable(samples, window_sec)`: 安定窓未達でFalse、達でTrue、テキスト増加中はFalse。
- [ ] タイムアウト経路: 無限ストリームを模擬→`--timeout-sec` 超過で TimeoutError かつ書き戻しを**行わない**。

### 6-5. 失敗隔離・冪等
- [ ] provider が例外/タイムアウト → runner 非ゼロ終了・ログ出力・**既存notesを破壊しない**。
- [ ] updater から呼ぶ模擬: subprocess失敗してもupdaterループが継続（status JSON が `idle/ok` を出し続ける）。
- [ ] 同一Rで2回 → 2回目はスキップ（`exists&&source=auto`）。

### 6-6. 回帰
- [ ] 既存**手動**貼付フロー無傷: textareaへ貼付→「保存して構造化」→印反映（Playwright）。
- [ ] `cd frontend; npm run lint` / `npm run build` 緑。
- [ ] 既存Phase1検証 `tmp/verify_phase1_warnings.py` 相当 PASS。

### 6-7. 実Bスモーク（手動・レース前日に1回／PASS/FAIL印字のみ）
- [ ] `--smoke --provider gemini`（または chatgpt）: 新規チャット到達・入力欄・Deep Researchトグル・送信ボタンの**存在確認のみ**（送信しない）。セレクタ生存確認。
- [ ] 初回ログイン: `--headed` で1度ログイン→cookie永続→次回headlessで再開できる。

### 6-8. 手動再評価E2E（経路2・`tmp/verify_research_reassess.py`）
- [ ] スマホ詳細を開き既存 `parsed` を復元 → 「オッズ変動を反映して再評価」ボタン押下（backendはスタブGeminiで固定差分）。
- [ ] 差分提案カードに `mark_diffs / ticket_diffs / comment` が描画され、**元の `parsed`・印は不変**。
- [ ] ボタンは**ドリフト無しでも押せる**。ドリフト検出時は強調表示になる。
- [ ] **サーバー保存**: 再評価後 `GET /research/notes` に `reassessment`（最新1件＋odds_snapshot＋at）が入り、リロード/別端末でも復元される。
- [ ] 入力に `body_weights` が含まれてPOSTされる（オッズのみでないこと）。
- [ ] クールダウン中の連打が抑止され、最小変動未満は前回提案を再表示（API再呼び出しなし）。390px横スクロールなし。

### 検証実行順（CODEX向け）
1. 6-3 → 6-4（速い・依存少：契約/純関数）
2. 6-1（Mock並列＋統合でE2E骨格確定）
3. 6-2（A実装確定）
4. 6-8（経路2 手動再評価）
5. 6-5 / 6-6（堅牢性・回帰）
6. 6-7（実B・最後に手動スモーク）

---

## 7. 決定済み / 残論点

### 決定済み（§方針の確定仕様）
- プロバイダ: Gemini + ChatGPT 両方を並列実行
- 統合: Gemini APIで1本に統合（一致点/相違点明示）
- 対象: 5R以降 / 再実行なし
- オッズ大変動: スマホ手動ボタン → Gemini API再評価（印・買い目の差分提案＋短評）
- プロファイル: `scripts/.dr_profile/`（Git除外・provider別サブフォルダ）

### 追加で決定済み
- 再評価結果の永続化: **サーバーバックアップにも保存**（`reassessment` フィールド・最新1件）＋localStorageミラー
- 再評価ボタン活性: **常時押せる**＋ドリフト検出時は強調
- 統合トーン: **一致を本線＋割れは明示**（最終見解併記・新情報は足さない）
- 再評価入力: **オッズ＋馬体重/直前情報**

### 残論点（実装時にCODEX判断でよい軽微事項）
1. **抽出形式**: Deep Research結果は copyボタンMarkdown優先 → 失敗時 answer container innerText（§4.2の通り既定でOK）。
2. **クールダウン秒数/最小変動閾値**: 既定 60秒 / 例 単勝±30%。運用で調整。
3. **synthesize/reassess の Gemini モデル**: 既存 `settings.gemini_model` を流用（コスト見て上げ下げ）。

---

## 8. リスクと緩和まとめ

| リスク | 緩和 |
|---|---|
| UI変更でB破綻 | セレクタJSON集約 + 6-7スモークを前日実施 + Aと連携(C)はBと疎結合で生存 |
| アカウント凍結(ToS) | 個人利用限定・低頻度・人間的ペース・CAPTCHA回避しない・既定OFF |
| 既存notes破壊 | source/manual優先・冪等・失敗時PUTしない・6-5で検証 |
| updater巻き込み停止 | subprocess隔離・timeout・例外握り潰し・6-5で検証 |
| parse失敗で空表示 | raw_text(統合結果)だけでも保存し手動構造化へフォールバック |
| ログイン情報漏洩 | cookieのみ・Git除外・パスワード非保持 |
| 片方プロバイダ落ち | 残り1本で統合・続行（degrade）。両落ちのみ中断 |
| 並列ログイン衝突 | provider別 user_data_dir サブフォルダで分離 |
| 統合でハルシネーション | 統合プロンプトで「両レポートにない情報は足さない」を明示・元2本を `raw_reports` に保持し追跡可能に |
| 再評価の連打/コスト | クールダウン＋最小変動ガード・元parsed不変で副作用なし |
