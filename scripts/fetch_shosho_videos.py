"""丞相（プロ馬券師）YouTube 動画 文字起こし→要約→まとめ生成スクリプト。

3フェーズ構成:
  Phase A: チャンネル候補の解決＋全アップロード動画の列挙（人間が本人チャンネルを確認）
  Phase B: 各動画の日本語字幕を取得し「1動画＝1ファイル」で文字起こしを保存
  Phase C: 各動画ファイルを要約し、全体を統合した最終 md を生成

使い方:
  # 1. チャンネル候補と動画一覧を確認
  python scripts/fetch_shosho_videos.py --phase a
  # 2. 本人の channelId を指定して全動画を列挙＋文字起こし
  python scripts/fetch_shosho_videos.py --phase a --channel-id UCxxxx
  python scripts/fetch_shosho_videos.py --phase b
  # 3. 要約＋最終 md 生成
  python scripts/fetch_shosho_videos.py --phase c

公式 YouTube Data API では他人の動画の字幕を download できないため、文字起こしは
youtube-transcript-api（字幕トラック取得）を使用する。字幕が無効な動画はスキップして記録する。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.clients.gemini_client import GeminiTextClient  # noqa: E402
from app.core.config import settings  # noqa: E402

OUT_DIR = ROOT_DIR / "data" / "shosho_transcripts"
INDEX_PATH = OUT_DIR / "_index.json"
FINAL_MD_PATH = ROOT_DIR / "docs" / "shosho-baken-method.md"

YT_API = "https://www.googleapis.com/youtube/v3"
DEFAULT_QUERY = "丞相 プロ馬券師 競馬"

SUMMARY_SYSTEM = (
    "あなたは競馬の馬券戦略アナリストです。与えられた動画の文字起こしから、"
    "馬券の『買い方・券種選択・期待値の考え方・穴馬/単勝の選び方・資金配分・"
    "やってはいけない事』に関係する要点だけを日本語で抽出してください。"
    "雑談・挨拶・宣伝・個別レースの結果報告など方法論に無関係な部分は無視します。"
    "文字起こしに無い情報を創作してはいけません。該当内容が無ければ『該当なし』と書いてください。"
)


# --------------------------------------------------------------------------- #
# YouTube Data API helpers (raw requests; the existing client only does video  #
# keyword search, so channel/playlist endpoints are called directly here).     #
# --------------------------------------------------------------------------- #
def _yt_get(path: str, params: dict) -> dict:
    key = (settings.youtube_api_key or "").strip()
    if not key:
        raise SystemExit("ERROR: YOUTUBE_API_KEY が未設定です（.env を確認）。")
    params = {**params, "key": key}
    resp = requests.get(f"{YT_API}/{path}", params=params, timeout=20)
    if resp.status_code >= 400:
        raise SystemExit(f"ERROR: YouTube API http {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def find_channel_candidates(query: str) -> list[dict]:
    body = _yt_get(
        "search",
        {"q": query, "part": "snippet", "type": "channel", "maxResults": 10, "regionCode": "JP"},
    )
    channel_ids = []
    base = {}
    for item in body.get("items", []):
        cid = (item.get("id") or {}).get("channelId")
        sn = item.get("snippet", {})
        if cid:
            channel_ids.append(cid)
            base[cid] = {"channelId": cid, "title": sn.get("channelTitle") or sn.get("title", "")}
    if not channel_ids:
        return []
    stats = _yt_get(
        "channels",
        {"id": ",".join(channel_ids), "part": "snippet,statistics,contentDetails", "maxResults": 50},
    )
    out = []
    for ch in stats.get("items", []):
        cid = ch.get("id", "")
        sn = ch.get("snippet", {})
        st = ch.get("statistics", {})
        uploads = (ch.get("contentDetails", {}).get("relatedPlaylists", {}) or {}).get("uploads", "")
        out.append(
            {
                "channelId": cid,
                "title": sn.get("title", ""),
                "description": (sn.get("description", "") or "")[:160],
                "subscribers": st.get("subscriberCount", "?"),
                "videoCount": st.get("videoCount", "?"),
                "uploadsPlaylist": uploads,
            }
        )
    # keep the search ordering
    out.sort(key=lambda c: channel_ids.index(c["channelId"]) if c["channelId"] in channel_ids else 99)
    return out


def get_uploads_playlist(channel_id: str) -> str:
    body = _yt_get("channels", {"id": channel_id, "part": "contentDetails", "maxResults": 1})
    items = body.get("items", [])
    if not items:
        raise SystemExit(f"ERROR: channelId={channel_id} が見つかりません。")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def list_all_videos(uploads_playlist: str) -> list[dict]:
    videos: list[dict] = []
    page_token = None
    while True:
        params = {"playlistId": uploads_playlist, "part": "snippet,contentDetails", "maxResults": 50}
        if page_token:
            params["pageToken"] = page_token
        body = _yt_get("playlistItems", params)
        for item in body.get("items", []):
            cd = item.get("contentDetails", {})
            sn = item.get("snippet", {})
            vid = cd.get("videoId")
            if not vid:
                continue
            videos.append(
                {
                    "videoId": vid,
                    "title": sn.get("title", "").strip(),
                    "publishedAt": cd.get("videoPublishedAt") or sn.get("publishedAt", ""),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "transcript": None,
                    "transcriptLang": None,
                    "transcriptKind": None,
                }
            )
        page_token = body.get("nextPageToken")
        if not page_token:
            break
    # oldest first for stable numbering
    videos.sort(key=lambda v: v["publishedAt"] or "")
    return videos


# --------------------------------------------------------------------------- #
# Index helpers                                                                 #
# --------------------------------------------------------------------------- #
def load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {}


def save_index(data: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_slug(text: str, maxlen: int = 50) -> str:
    text = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", text)
    text = re.sub(r"\s+", "_", text).strip("_")
    return text[:maxlen] or "video"


def transcript_path(idx: int, video: dict) -> Path:
    return OUT_DIR / f"{idx:03d}_{video['videoId']}.md"


# --------------------------------------------------------------------------- #
# Phase A                                                                       #
# --------------------------------------------------------------------------- #
def phase_a(args) -> None:
    if not args.channel_id:
        print("=== チャンネル候補（本人を特定して --channel-id に指定してください） ===\n")
        cands = find_channel_candidates(args.query)
        if not cands:
            print("候補が見つかりませんでした。--query を調整してください。")
            return
        for c in cands:
            print(f"channelId : {c['channelId']}")
            print(f"  title   : {c['title']}")
            print(f"  subs    : {c['subscribers']} / videos: {c['videoCount']}")
            print(f"  desc    : {c['description']}")
            print()
        print("→ 本人の channelId を確認したら次を実行:")
        print(f"   python scripts/fetch_shosho_videos.py --phase a --channel-id <ID>")
        return

    print(f"channelId={args.channel_id} の全動画を列挙します...")
    uploads = get_uploads_playlist(args.channel_id)
    videos = list_all_videos(uploads)
    if args.limit:
        videos = videos[: args.limit]
    index = {
        "channelId": args.channel_id,
        "uploadsPlaylist": uploads,
        "videoCount": len(videos),
        "videos": videos,
    }
    save_index(index)
    print(f"動画 {len(videos)} 件を {INDEX_PATH} に保存しました。")
    for i, v in enumerate(videos, 1):
        print(f"  {i:03d}  {v['publishedAt'][:10]}  {v['title']}")


# --------------------------------------------------------------------------- #
# Phase B                                                                       #
# --------------------------------------------------------------------------- #
def _fetch_transcript(video_id: str) -> tuple[str | None, str | None, str | None]:
    """Return (text, lang, kind) or (None, None, None) if unavailable."""
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    api = YouTubeTranscriptApi()
    try:
        tlist = api.list(video_id)
    except (TranscriptsDisabled, VideoUnavailable, NoTranscriptFound):
        return None, None, None
    except Exception:
        return None, None, None

    # prefer manually created JA, then auto-generated JA, then any JA-ish, then anything
    order: list[tuple[list[str], bool]] = [(["ja", "ja-JP"], False), (["ja", "ja-JP"], True)]
    chosen = None
    kind = None
    for langs, generated in order:
        try:
            chosen = (
                tlist.find_generated_transcript(langs)
                if generated
                else tlist.find_manually_created_transcript(langs)
            )
            kind = "auto" if generated else "manual"
            break
        except Exception:
            continue
    if chosen is None:
        # fall back to first available transcript (may be another language)
        try:
            chosen = next(iter(tlist))
            kind = "auto" if getattr(chosen, "is_generated", False) else "manual"
        except Exception:
            return None, None, None
    try:
        fetched = chosen.fetch()
    except Exception:
        return None, None, None
    text = "\n".join(seg.text for seg in fetched if getattr(seg, "text", "").strip())
    lang = getattr(chosen, "language_code", "?")
    return (text or None), lang, kind


def phase_b(args) -> None:
    index = load_index()
    videos = index.get("videos", [])
    if not videos:
        raise SystemExit("ERROR: 先に --phase a で動画一覧を作成してください。")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = unavailable = 0
    for i, v in enumerate(videos, 1):
        path = transcript_path(i, v)
        if path.exists() and not args.force:
            ok += 1
            continue
        text, lang, kind = _fetch_transcript(v["videoId"])
        if text:
            v["transcript"] = "ok"
            v["transcriptLang"] = lang
            v["transcriptKind"] = kind
            header = (
                f"# {v['title']}\n\n"
                f"- 動画URL: {v['url']}\n"
                f"- 公開日: {v['publishedAt'][:10]}\n"
                f"- 字幕: {lang} ({kind})\n\n"
                f"---\n\n## 文字起こし\n\n"
            )
            path.write_text(header + text + "\n", encoding="utf-8")
            ok += 1
            print(f"  {i:03d} OK   ({lang}/{kind})  {v['title'][:40]}")
        else:
            v["transcript"] = "unavailable"
            header = (
                f"# {v['title']}\n\n"
                f"- 動画URL: {v['url']}\n"
                f"- 公開日: {v['publishedAt'][:10]}\n\n"
                f"---\n\n## 文字起こし\n\n*字幕が無効のため文字起こしを取得できませんでした。*\n"
            )
            path.write_text(header, encoding="utf-8")
            unavailable += 1
            print(f"  {i:03d} SKIP (字幕なし)  {v['title'][:40]}")
        save_index(index)
        time.sleep(args.sleep)
    print(f"\n完了: 取得 {ok} 件 / 字幕なし {unavailable} 件  → {OUT_DIR}")


# --------------------------------------------------------------------------- #
# Phase C                                                                       #
# --------------------------------------------------------------------------- #
def _gemini() -> GeminiTextClient:
    if not (settings.gemini_api_key or "").strip():
        raise SystemExit("ERROR: GEMINI_API_KEY が未設定です（.env を確認）。")
    return GeminiTextClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
        timeout_sec=60.0,
    )


def _generate_with_retry(
    client: GeminiTextClient, *, prompt: str, system_prompt: str, max_output_tokens: int, retries: int = 4
) -> str:
    delay = 4.0
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return client.generate_text(
                prompt=prompt, system_prompt=system_prompt, max_output_tokens=max_output_tokens
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            msg = str(exc)
            if "503" in msg or "overloaded" in msg or "high demand" in msg or "500" in msg:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last_exc if last_exc else RuntimeError("generate failed")


def _read_transcript_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "## 文字起こし"
    if marker in text:
        text = text.split(marker, 1)[1]
    return text.strip()


def phase_c(args) -> None:
    index = load_index()
    videos = index.get("videos", [])
    if not videos:
        raise SystemExit("ERROR: 先に --phase a / b を実行してください。")

    client = _gemini()
    per_video_summaries: list[dict] = []

    for i, v in enumerate(videos, 1):
        path = transcript_path(i, v)
        if not path.exists() or v.get("transcript") != "ok":
            continue
        body = _read_transcript_body(path)
        if not body or body.startswith("*字幕"):
            continue
        # truncate very long transcripts to keep within token limits
        excerpt = body[:18000]
        prompt = (
            f"次の競馬YouTube動画『{v['title']}』の文字起こしから、馬券の方法論に関する要点を"
            "箇条書きで抽出してください。各要点は簡潔な日本語1文。該当が無ければ『該当なし』のみ。\n\n"
            f"---文字起こし---\n{excerpt}"
        )
        try:
            summary = _generate_with_retry(
                client, prompt=prompt, system_prompt=SUMMARY_SYSTEM, max_output_tokens=900
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  {i:03d} 要約失敗: {exc}")
            continue

        # append 要約 section to the per-video file (idempotent: drop old one first)
        full = path.read_text(encoding="utf-8")
        full = full.split("\n## 要約\n", 1)[0].rstrip()
        path.write_text(full + "\n\n## 要約\n\n" + summary.strip() + "\n", encoding="utf-8")

        if "該当なし" not in summary or len(summary.strip()) > 12:
            per_video_summaries.append({"title": v["title"], "url": v["url"], "summary": summary.strip()})
        print(f"  {i:03d} 要約 OK  {v['title'][:40]}")

    if not per_video_summaries:
        print("要約対象（字幕ありかつ方法論を含む動画）がありませんでした。")
    _build_final_md(index, per_video_summaries, client)
    print(f"\n最終まとめを生成しました → {FINAL_MD_PATH}")


def _build_final_md(index: dict, summaries: list[dict], client: GeminiTextClient) -> None:
    joined = "\n\n".join(
        f"# 動画: {s['title']}\nURL: {s['url']}\n{s['summary']}" for s in summaries
    )[:120000]

    synth_prompt = (
        "以下は競馬予想家『丞相（プロ馬券師）』の複数YouTube動画から抽出した方法論の要点集です。"
        "これらを統合し、重複を排し、Markdownのまとめ本文（見出し・箇条書き）を作成してください。"
        "次の8セクションを必ず立てること:\n"
        "1. 概要 / プロフィール・発信媒体\n2. 基本思想\n3. 券種の選び方\n"
        "4. 期待値の考え方\n5. 期待値の高い馬（穴馬）の選び方\n6. 資金配分・買い目の組み立て\n"
        "7. やってはいけないこと / 注意点\n8. 補足\n"
        "各要点には可能なら出典動画タイトルを括弧書きで添えること。"
        "要点集に無い情報は創作しないこと。\n\n"
        f"---要点集---\n{joined}"
    )
    body = ""
    if summaries:
        try:
            body = _generate_with_retry(
                client,
                prompt=synth_prompt,
                system_prompt="あなたは競馬の馬券戦略を体系化する編集者です。",
                max_output_tokens=4096,
            )
        except Exception as exc:  # noqa: BLE001
            body = f"*Gemini統合に失敗しました: {exc}*"

    video_count = index.get("videoCount", len(index.get("videos", [])))
    ok_count = sum(1 for v in index.get("videos", []) if v.get("transcript") == "ok")
    na_count = sum(1 for v in index.get("videos", []) if v.get("transcript") == "unavailable")

    lines = [
        "# 丞相（プロ馬券師）｜馬券の買い方・期待値の高い馬の選び方 まとめ",
        "",
        "> **本まとめについて**: 丞相のYouTube動画の日本語字幕（自動生成含む）を文字起こしし、",
        "> Geminiで要約・統合したものです。動画音声の逐語の完全再現ではなく、字幕が無効な動画は",
        "> 対象外です。補助的に公開情報（公式LP / note / X）も併記しています。投資は自己責任で。",
        "",
        f"- 対象動画数: {video_count} 件（文字起こし取得 {ok_count} 件 / 字幕なし {na_count} 件）",
        "",
        "---",
        "",
        body.strip() if body.strip() else "*（要約対象の動画がありませんでした）*",
        "",
        "---",
        "",
        "## 参考: 公開情報（Web一次情報）",
        "",
        "動画字幕と矛盾しない範囲での補助情報（出典: 公式LP predict-master / note @keibareki29nen / X）:",
        "",
        "- 券種は**単勝中心**、狙いは**小穴（3〜7番人気）**、オッズ**10倍前後**を目安。",
        "- 期待値の核: **的中率10%で回収率100%**（10倍を当てれば収支均衡）という損益分岐の発想。",
        "- **「予想と馬券は別」** — 予想が下手でも買い方（オッズ妙味）で勝てる。",
        "- 人気馬を当て続けるのは不可能 → **ハズレ前提・1発回収**が合理的（穴予想の精度が前提）。",
        "",
        "## 出典動画一覧",
        "",
    ]
    for i, v in enumerate(index.get("videos", []), 1):
        status = {"ok": "✅", "unavailable": "🚫文字起こし不可"}.get(v.get("transcript"), "—")
        rel = f"../data/shosho_transcripts/{i:03d}_{v['videoId']}.md"
        lines.append(f"- {status} [{v['title']}]({v['url']}) — [文字起こし]({rel})")

    FINAL_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    FINAL_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser(description="丞相YouTube 文字起こし→要約→まとめ")
    p.add_argument("--phase", choices=["a", "b", "c"], required=True)
    p.add_argument("--channel-id", default="", help="本人チャンネルID（Phase A で確定後に指定）")
    p.add_argument("--query", default=DEFAULT_QUERY, help="チャンネル検索クエリ")
    p.add_argument("--limit", type=int, default=0, help="処理する動画数の上限（テスト用、0=全件）")
    p.add_argument("--sleep", type=float, default=1.0, help="字幕取得間の待機秒（レート制限回避）")
    p.add_argument("--force", action="store_true", help="既存の文字起こしファイルを上書き")
    args = p.parse_args()

    if args.phase == "a":
        phase_a(args)
    elif args.phase == "b":
        phase_b(args)
    elif args.phase == "c":
        phase_c(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
