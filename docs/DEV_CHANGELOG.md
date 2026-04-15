# Development Changelog

このファイルは、`Codex` と `Claude Code` を交互利用する際の作業引き継ぎ用ログです。  
日時は `JST (+09:00)` で記録します。

## 2026-02-20

### 2026-02-20 15:23:26 +09:00
- 担当: Codex
- 変更概要:
  - Web検索を Tavily 優先 + Gemini フォールバック構成に変更
  - `TAVILY_API_KEY` 読み込みを追加（`.env`/Secrets対応）
  - 競馬系ドメイン allowlist（`WEB_SEARCH_ALLOWLIST`）を追加
  - `search_web_articles_with_tavily()` / `normalize_tavily_results()` を追加
  - `fetch_and_analyze_web_articles()` に検索エンジン切替ロジックと進捗メッセージを追加
- 対象ファイル:
  - `app.py`
  - `CLAUDE.md`
  - `DEV_CHANGELOG.md`（このファイル）
- 検証:
  - `python -c "import ast, pathlib; ast.parse(...)"` による構文確認 `OK`

### 2026-02-20 14:26:50 +09:00
- 担当: Codex
- 変更概要:
  - 勝率シミュレーター機能を削除（タブ・UI・関連処理）
  - 削除後の関連文言を整理（`app.py`, `CLAUDE.md`）
  - 情報入力タブの一括検索を「YouTube + Web」から「Webのみ」に変更
  - YouTubeタブ名を `YOUTUBEから情報入手` に変更
  - YouTubeタブを「検索後に一覧表示」→「動画ごとの `読み込み+概要取得` ボタンで個別解析」へ変更
  - オッズ取得処理を強化（失敗理由の表示、リトライ、フォールバック）
  - Playwright失敗時の対策として、別プロセスPlaywright実行と`requests`フォールバックを追加
  - オッズ品質チェック（数値オッズが十分に取れない結果は不採用）を追加
- 対象ファイル:
  - `app.py`
  - `CLAUDE.md`
  - `DEV_CHANGELOG.md`（このファイル）
- 検証:
  - `python -c "import ast, pathlib; ast.parse(...)"` による構文確認 `OK`
  - Playwrightで `http://localhost:8505` を操作し、`最新オッズを取得` 後に数値オッズ表示を確認

---

## 次回追記テンプレート

```md
### YYYY-MM-DD HH:mm:ss +09:00
- 担当: Codex / Claude Code
- 変更概要:
  - 
- 対象ファイル:
  - 
- 検証:
  - 
```
