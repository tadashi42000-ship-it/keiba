# Claude Code 向け最終ダブルチェック指示

対象リポジトリ: `c:\WORK\keiba`

目的: 6/20・6/21東京現地運用で見つかった同日モード不具合の修正を、Codexとは別視点で再検証する。検証後、不要なローカル生成物を掃除して、しばらくプロジェクトを閉じられる状態にする。

## 前提
- 未コミット変更はユーザー/Codex作業として扱い、勝手に巻き戻さない。
- 既存の2軸評価、`ev_curve`、既存 `score`、top-level `tickets` は破壊しない。
- `data/same_day_sheets/` など ignored cache が存在する場合は検証用資産として使う。存在しない場合はバックテストだけ「キャッシュ不足で未実施」と明記する。
- 通常運用のために `node_modules`、`.venv`、tracked cache の `data/horse_sires_cache.json` は削除しない。

## 重点確認ポイント
1. やや重・重・不良の馬場ラベルが、血統適性・近走馬場適性・買い目理由へ反映されること。
2. オッズ更新後、詳細ページが古い `localStorage/sessionStorage` だけを優先せず、サーバ側の同日シートが新しければ `entry`、`bet_plan`、`track_bias` を取り直すこと。
3. レース詳細の前後レース移動ボタンが、同日シートから兄弟レースを取得できる場合に表示されること。
4. トラックバイアスが当日終了済みレースを拾えること。特に `race.start_time` が欠落しても `entry.start_time` で補完されること。
5. 波乱度が極端に高い時は3連複を縮小または停止し、単勝・ワイド・馬連寄りになること。

## 実行コマンド
PowerShellで実行する。

```powershell
cd c:\WORK\keiba
git status --short
```

```powershell
cd c:\WORK\keiba\backend
python -m pytest tests/test_same_day_api.py -q
```

```powershell
cd c:\WORK\keiba
$env:PYTHONIOENCODING = "utf-8"
python tmp/verify_shosho_6_14_offline.py
```

```powershell
cd c:\WORK\keiba
python scripts/backtest_shosho.py
```

`scripts/backtest_shosho.py` は `data/same_day_sheets/*_same_day_sheet.json` が必要。実行できた場合は、出力末尾に「キャッシュオッズを近似に使用・少数サンプルの方向性確認」の注記が出ることを確認する。

```powershell
cd c:\WORK\keiba
python scripts/purge_stale_bias_cache.py
```

```powershell
cd c:\WORK\keiba\frontend
npm run build
```

## モバイルUI確認
ローカルで起動できる場合だけでよい。

```powershell
cd c:\WORK\keiba
.\scripts\start_same_day_updater.ps1 -Date 2026-06-21 -Venue 東京 -SkipBuild -NoTunnel
```

確認:
- 390px幅で同日シートに横スクロールが出ない。
- カードに `能力上位` と `妙味推奨` が併記される。
- 詳細ページに前後レース移動が表示される。
- 買い目欄に「最新オッズで再計算」の時刻が表示される。
- トラックバイアス信頼度が `サンプル不足`、`暫定`、`中`、`高` のいずれかで崩れず表示される。

起動した場合は最後に停止する。

```powershell
cd c:\WORK\keiba
.\scripts\stop_same_day_updater.ps1
```

## 掃除方針
検証が終わってから削除する。削除対象は ignored/generated のみ。

削除してよい:
- `frontend/.next/`
- `tmp/*.png`, `tmp/*.html`, `tmp/*.json`, `tmp/*.log`, `tmp/*.pid`, `tmp/*.url`, `tmp/cloudflared.exe`
- 検証が完全に終わった後の `data/same_day_sheets/`
- 検証が完全に終わった後の `data/track_bias_results_cache.json`
- 検証が完全に終わった後の `data/shosho_transcripts/`, `data/research_notes/`, `data/shosho_backtest_payouts.json`

削除しない:
- `backend/app/data/*.json`
- `data/horse_sires_cache.json`
- `.venv/`
- `node_modules/`
- `tmp/*.py` の検証スクリプト

## 報告してほしいこと
- 実行したコマンドと結果。
- 失敗した検証があれば、原因がコード不具合か、ローカルキャッシュ不足か、外部サイト取得失敗か。
- 削除したローカル生成物。
- commit/push前に残っている未追跡ファイルまたは未コミット差分。
