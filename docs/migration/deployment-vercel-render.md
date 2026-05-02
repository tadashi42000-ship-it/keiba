# Deployment guide (Vercel + Render)

## Frontend (Vercel)
1. Connect GitHub repository to Vercel.
2. Set project root to `frontend`.
3. Add environment variable:
   - `NEXT_PUBLIC_API_BASE_URL=https://<your-render-service>.onrender.com`
4. Deploy.

## Backend (Render)
1. Create new Web Service from this repository.
2. Set root directory to `backend`.
3. Build command:
   - `pip install -r requirements.txt`
4. Start command:
   - `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Environment variables:
   - `APP_ENV=production`
   - `FRONTEND_ORIGINS=https://<your-vercel-domain>`
   - `TAVILY_API_KEY=<your-key>`
   - `GEMINI_API_KEY=<your-key>`
   - `GEMINI_MODEL=gemini-2.5-flash`
   - `YOUTUBE_API_KEY=<your-key>`
   - `X_BEARER_TOKEN=<your-token>`
   - `X_ACCOUNTS_PATH=legacy/streamlit_app/x_accounts.json`

## Health checks
- `GET /health`
- `GET /api/v1/health`

## Post-deploy smoke check (Windows)

From repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-stack.ps1 `
  -BackendBaseUrl https://<your-render-service>.onrender.com `
  -FrontendBaseUrl https://<your-vercel-app>.vercel.app `
  -IncludeExternalPosts `
  -RequestTimeoutSec 20
```
