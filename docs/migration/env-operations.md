# Environment Variables 運用ルール

## 正本
- 正本はリポジトリルートの `.env.example`。
- `frontend/.env.example` と `backend/.env.example` は参照用の最小ミラー。

## ローカル開発 (Windows)

### 1) 初回作成
```powershell
Copy-Item .env.example .env
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env.local
```

### 2) 変更時ルール
- 新しい環境変数を追加する場合:
  1. ルート `.env.example` に追加
  2. 必要なら `backend/.env.example` / `frontend/.env.example` に反映
  3. `README.md` の説明を更新

## デプロイ時
- frontend (Vercel): `NEXT_PUBLIC_*` のみ設定する。
- backend (Render): 秘密情報 (`*_API_KEY`, `*_TOKEN`) を設定する。
- `.env` 実体はコミットしない。

## 主要キー
- Backend:
  - `APP_ENV`, `APP_PORT`, `FRONTEND_ORIGINS`
  - `TAVILY_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL`
  - `YOUTUBE_API_KEY`, `X_BEARER_TOKEN`, `X_ACCOUNTS_PATH`
- Frontend:
  - `NEXT_PUBLIC_API_BASE_URL`
