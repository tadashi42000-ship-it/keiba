# TASK Progress Tracker

## Project Snapshot
- Date (JST): 2026-04-18
- Branch: `nextjs-fastapi-migration`
- Current phase: Legacy Streamlit hardening (Satsuki Sho validation) + migration continuity
- Recent updates:
  - Switched race characteristics primary source to Umanity scraping, Gemini as fallback
  - Added Umanity racecard integration into Streamlit entry table (前走/2走前/3走前 + weight fallback)
  - Improved entry table readability (rank-focused past-race layout) and added odds sort options
  - Removed budget betting plan section from Markdown report output by request

## Milestones
| ID | Milestone | Target state | Progress % | Status | Due | Notes |
|---|---|---|---:|---|---|---|
| M1 | Foundation | FastAPI v1 + Next.js/PWA baseline | 100 | Done | 2026-04-20 | Completed |
| M2 | Race UI expansion | List/detail + CSV/odds operation UI | 100 | Done | 2026-04-27 | Completed |
| M3 | Streamlit logic migration | characteristics/cache normalization as APIs | 95 | InProgress | 2026-05-11 | Umanity-first characteristics + racecard enrichment merged in legacy Streamlit |
| M4 | External API migration | Tavily/Gemini/YouTube/X moved to backend services | 85 | InProgress | 2026-05-25 | YouTube relevance and fallback hardening completed in legacy flow |
| M5 | Deployment operations | Vercel/Render operational verification | 78 | InProgress | 2026-04-30 | full local stack checks passed; staging URL run pending |
| M6 | Legacy Streamlit stabilization | Satsuki Sho tabs (YouTube/report/bet plan) stable for practical use | 88 | InProgress | 2026-04-22 | UI/readability and report scope updates applied; external cross-check pending |

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
| T-LS-01 | Legacy Streamlit | Umanity-first race characteristics + fallback flow | Done | 100 | P0 | T-M3-05 | Primary scraping path stabilized, fallback retained | Codex |
| T-LS-02 | Legacy Streamlit | Entry table enrichment from Umanity racecard (前走〜3走前) | Done | 100 | P0 | T-LS-01 | Added racecard mapping + horse-wise merge + weight backfill | Codex |
| T-LS-03 | Legacy Streamlit UI | Improve past-race readability and add odds sort control | Done | 100 | P0 | T-LS-02 | Added rank-focused rendering + `馬番/オッズ昇順/オッズ降順` toggle + Playwright check | Codex |
| T-LS-04 | Legacy Streamlit Report | Exclude budget bet plan section from Markdown report | Done | 100 | P1 | T-LS-03 | Removed `💰 予算別買い目プラン` from `generate_markdown_report` | Codex |
| T-LS-05 | QA | Claude Code validation handoff (Satsuki Sho scenario) | InProgress | 60 | P0 | T-LS-01,T-LS-04 | Run checklist in `Claude Code Verification Checklist` section | User+Claude Code |

## Issue / Blocker Log
| IssueID | Date | Issue | Impact | Temporary action | Permanent fix | Status |
|---|---|---|---|---|---|---|
| IS-001 | 2026-04-15 | Next.js 16 + `next-pwa` Turbopack mismatch | Build instability | Force `next build --webpack` | Track Turbopack compatibility | Watching |
| IS-002 | 2026-04-15 | Some races fail `resolve-id` | Odds fetch blocked for edge races | UI warning and fallback flow | Backend fallback strategy implemented + tests | Closed |
| IS-003 | 2026-04-15 | Env operation drift risk | Reproducibility risk | Root `.env.example` as source-of-truth | Enforce via docs/checklist | Open |
| IS-004 | 2026-04-15 | Mixed local dependency conflicts | Local test friction | Use dedicated backend venv | Document isolated env workflow | Open |
| IS-005 | 2026-04-15 | Some future races stay unresolved (`race_id=null`) | Odds/CSV fetch cannot proceed for those races | UI warning and skip unresolved races | Upstream-dependent; retry closer to race date | Watching |
| IS-006 | 2026-04-15 | YouTube summary can include off-race videos despite race_name input | Summary/horse analysis quality drops for specific race verification | Use tighter query terms and max_results=2 during manual checks | Strengthened strict race filter + fallback query candidates + regression tests | Closed |
| IS-007 | 2026-04-18 | Legacy Streamlit Web article acquisition precision regressed vs earlier behavior | Horse-level evaluation quality decreases when low-quality sources dominate | Keep Umanity as primary structured source and cap noisy fetch paths | Investigate historical diffs + tune source weighting/query strategy | Open |
| IS-008 | 2026-04-18 | Some bet types show missing/unavailable odds (複勝/ワイド/馬連/三連複/三連単) | Budget plan can degrade or output warnings before market publication | Partial-success handling with explicit warnings | Improve odds endpoint fallback chain and recheck near race day | Watching |
| IS-009 | 2026-04-18 | Entry table readability for past-race performance was weak | Hard to compare finish positions quickly | Added rank-first visual layout with condensed race/course lines | Keep style tuning based on QA feedback | Closed |

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

## Operating Rules
- Update this file at session start/end.
- Keep max 2 tasks as InProgress at the same time.
- Any Blocked task must reference an IssueID.
- Done tasks must include one-line verification evidence.
- Always set one concrete next action before ending a session.
