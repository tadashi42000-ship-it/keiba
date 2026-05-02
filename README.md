# keiba

Next.js + PWA + FastAPI migration workspace while preserving the existing Streamlit app.

## Structure

- `legacy/streamlit_app/`: current Streamlit implementation (kept as-is)
- `backend/`: FastAPI backend (JSON APIs)
- `frontend/`: Next.js (App Router) + TypeScript + Tailwind + PWA
- `docs/migration/`: migration and deployment docs

## Environment variables

Root `.env.example` is the source of truth.

- Copy root example if needed:
  - `Copy-Item .env.example .env`
- Sub-project examples (`frontend/.env.example`, `backend/.env.example`) are minimal mirrors.
- Detailed env operation rules: `docs/migration/env-operations.md`

## Python version

- Backend target: Python `3.11` (`backend/runtime.txt`)

## Run legacy Streamlit app

```powershell
cd legacy\streamlit_app
streamlit run app.py
```

## Run backend (FastAPI)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

## Run frontend (Next.js + PWA)

```powershell
cd frontend
npm install
npm run dev
```

## Connectivity checks (Windows)

Use PowerShell native command or `curl.exe`.

```powershell
Invoke-WebRequest http://localhost:8000/health
Invoke-WebRequest http://localhost:8000/api/v1/sample
Invoke-WebRequest http://localhost:8000/api/v1/races/upcoming
Invoke-WebRequest http://localhost:8000/api/v1/external/providers
Invoke-WebRequest http://localhost:8000/api/v1/external/x/accounts
```

or

```powershell
curl.exe http://localhost:8000/health
curl.exe http://localhost:8000/api/v1/sample
curl.exe http://localhost:8000/api/v1/races/upcoming
curl.exe http://localhost:8000/api/v1/external/providers
curl.exe http://localhost:8000/api/v1/external/x/accounts
```

Automated local/staging check script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-stack.ps1
# optional:
# powershell -ExecutionPolicy Bypass -File .\scripts\check-stack.ps1 -BackendBaseUrl https://your-render.onrender.com -SkipFrontend
# powershell -ExecutionPolicy Bypass -File .\scripts\check-stack.ps1 -IncludeExternalPosts
# powershell -ExecutionPolicy Bypass -File .\scripts\check-stack.ps1 -RequestTimeoutSec 20
```

## Tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest tests -q
```

CI automation:

- GitHub Actions `CI` runs backend tests and frontend `lint/build` on push/PR.
- Workflow file: `.github/workflows/ci.yml`

## Initial API list

- `GET /health`
- `GET /api/v1/health`
- `GET /api/v1/sample`
- `GET /api/v1/races/upcoming`
- `GET /api/v1/races/resolve-id?race_key=...`
- `POST /api/v1/races/fetch-csv`
- `GET /api/v1/races/{race_id}/odds`
- `GET /api/v1/races/characteristics?race_key=...`
- `GET /api/v1/races/cache?race_key=...`
- `PUT /api/v1/races/cache?race_key=...`
- `GET /api/v1/external/providers`
- `POST /api/v1/external/web-summary`
- `POST /api/v1/external/youtube/search`
- `POST /api/v1/external/youtube/summary`
- `POST /api/v1/external/youtube/horse-analysis`
- `GET /api/v1/external/x/accounts`
- `POST /api/v1/external/x/search`
- `POST /api/v1/external/x/summary`
- `POST /api/v1/external/x/horse-analysis`

## External API abstraction (T-M4-01)

- This backend now has a provider abstraction layer for:
  - Tavily web search
  - Gemini text summary
  - YouTube Data API search
  - X Recent Search
- Required env vars:
  - `TAVILY_API_KEY`
  - `GEMINI_API_KEY`
  - `YOUTUBE_API_KEY`
  - `X_BEARER_TOKEN`
  - optional `GEMINI_MODEL`, `EXTERNAL_API_TIMEOUT_SEC`
- Quick local test:

```powershell
Invoke-WebRequest http://localhost:8000/api/v1/external/providers
Invoke-WebRequest `
  -Method POST `
  -Uri http://localhost:8000/api/v1/external/web-summary `
  -ContentType "application/json" `
  -Body '{"query":"皐月賞 追い切り", "max_results": 3, "include_domains": ["netkeiba.com"]}'
Invoke-WebRequest `
  -Method POST `
  -Uri http://localhost:8000/api/v1/external/youtube/search `
  -ContentType "application/json" `
  -Body '{"query":"皐月賞 予想", "race_name":"皐月賞", "max_results": 5}'
Invoke-WebRequest `
  -Method POST `
  -Uri http://localhost:8000/api/v1/external/youtube/horse-analysis `
  -ContentType "application/json" `
  -Body '{"query":"皐月賞 予想", "race_name":"皐月賞", "max_results": 3, "horse_names": ["クロワデュノール","サトノシャイニング"]}'
Invoke-WebRequest `
  -Method POST `
  -Uri http://localhost:8000/api/v1/external/x/search `
  -ContentType "application/json" `
  -Body '{"race_name":"皐月賞", "max_tweets": 30}'
Invoke-WebRequest `
  -Method POST `
  -Uri http://localhost:8000/api/v1/external/x/horse-analysis `
  -ContentType "application/json" `
  -Body '{"race_name":"皐月賞", "max_tweets": 30, "horse_names": ["クロワデュノール","サトノシャイニング"]}'
```

## New UI Stage 1 (migrated feature)

On `http://localhost:3000`, use `レース取得ワークベンチ` card:

1. Fetch upcoming races from `/api/v1/races/upcoming`
2. Resolve selected `race_key` with `/api/v1/races/resolve-id`
3. Fetch odds with `/api/v1/races/{race_id}/odds` (CSV backend generation included)
4. Adjust odds table with sort, display count, horse-name filter, and missing-odds toggle
5. Open detail route `/races/[raceKey]` for per-race workflow and status visibility
6. On detail page, fetch minimal race characteristics via `/api/v1/races/characteristics`
7. On detail page, load/save cache via `/api/v1/races/cache` (GET/PUT)
8. On home page, use `External API Workbench` card to verify YouTube/X summary and horse-analysis APIs

## Troubleshooting (Windows)

1. Frontend が API に接続できない
   - `frontend/.env.local` の `NEXT_PUBLIC_API_BASE_URL` を確認
   - backend 側が `http://localhost:8000` で起動しているか確認
2. CORS エラーが出る
   - `backend/.env` の `FRONTEND_ORIGINS` に `http://localhost:3000` を含める
   - 変更後は backend を再起動
3. `race_id` が解決できない
   - 対象レースが `upcoming` 期間内か確認（UIの先読み月数/日数を増やす）
   - API 側で `race_key` 日付ベースのフォールバック解決を実装済み
   - それでも未解決の場合は netkeiba 側に `race_id` 導線が出ていない可能性あり
4. `streamlit run app.py` でファイルが見つからない
   - 現在の実行ディレクトリを確認し、`legacy/streamlit_app` に移動して実行
