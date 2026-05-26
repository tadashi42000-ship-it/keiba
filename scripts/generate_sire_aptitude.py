from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.clients.gemini_client import GeminiTextClient  # noqa: E402
from app.core.config import settings  # noqa: E402

OUTPUT_PATH = ROOT_DIR / "backend" / "app" / "data" / "sire_aptitude.json"

DEFAULT_SIRES = [
    "キタサンブラック",
    "ロードカナロア",
    "エピファネイア",
    "ドゥラメンテ",
    "モーリス",
    "ハーツクライ",
    "ディープインパクト",
    "キングカメハメハ",
    "ルーラーシップ",
    "ハービンジャー",
    "オルフェーヴル",
    "ゴールドシップ",
    "サトノダイヤモンド",
    "リアルスティール",
    "レイデオロ",
    "ブリックスアンドモルタル",
    "キズナ",
    "イスラボニータ",
    "ダイワメジャー",
    "ミッキーアイル",
    "ビッグアーサー",
    "ファインニードル",
    "アドマイヤマーズ",
    "サートゥルナーリア",
    "スワーヴリチャード",
    "ニューイヤーズデイ",
    "ドレフォン",
    "ヘニーヒューズ",
    "シニスターミニスター",
    "ホッコータルマエ",
    "パイロ",
    "マジェスティックウォリアー",
    "アジアエクスプレス",
    "コパノリッキー",
    "リオンディーズ",
    "シルバーステート",
    "ジャスタウェイ",
    "エイシンフラッシュ",
    "ブラックタイド",
    "スクリーンヒーロー",
    "ノヴェリスト",
    "バゴ",
    "カレンブラックヒル",
    "サウスヴィグラス",
    "マインドユアビスケッツ",
    "デクラレーションオブウォー",
    "ダノンレジェンド",
    "タリスマニック",
    "サンダースノー",
    "アルアイン",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate or extend sire aptitude DB with Gemini.")
    parser.add_argument("--add", action="append", default=[], help="Add one sire. Can be specified multiple times.")
    args = parser.parse_args()

    current = _load_existing()
    target_sires = args.add or DEFAULT_SIRES
    generated = _generate(target_sires)
    current.setdefault("sires", {}).update(generated.get("sires", {}))
    current["version"] = 1
    current["updated_at"] = _today()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved {len(current.get('sires', {}))} sires to {OUTPUT_PATH}")
    print("Please manually review generated marks before committing.")


def _load_existing() -> dict[str, Any]:
    if not OUTPUT_PATH.exists():
        return {"version": 1, "updated_at": "", "sires": {}}
    try:
        payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "updated_at": "", "sires": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "updated_at": "", "sires": {}}
    if not isinstance(payload.get("sires"), dict):
        payload["sires"] = {}
    return payload


def _generate(sires: list[str]) -> dict[str, Any]:
    client = GeminiTextClient(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        base_url=settings.gemini_base_url,
        timeout_sec=settings.external_api_timeout_sec,
    )
    merged: dict[str, Any] = {"version": 1, "updated_at": _today(), "sires": {}}
    for chunk in _chunks(sires, 8):
        generated = _generate_chunk(client, chunk)
        merged["sires"].update(generated.get("sires", {}))
    return merged


def _generate_chunk(client: GeminiTextClient, sires: list[str]) -> dict[str, Any]:
    prompt = f"""
以下の種牡馬について、日本競馬における産駒傾向をもとに適性タグを作ってください。
出力はJSONのみ。説明文やMarkdownは禁止。

評価記号は必ず "◎", "○", "△", "×" のいずれか。
キー構造:
{{
  "version": 1,
  "updated_at": "{_today()}",
  "sires": {{
    "種牡馬名": {{
      "surfaces": {{ "turf": "◎", "dirt": "△" }},
      "distances": {{ "sprint": "○", "mile": "◎", "intermediate": "◎", "long": "○" }},
      "course_shape": {{ "spacious": "○", "tight": "○" }},
      "going": {{ "firm": "◎", "soft": "○" }},
      "notes": "30字程度の根拠"
    }}
  }}
}}

距離区分:
- sprint: 1400m以下
- mile: 1401-1700m
- intermediate: 1701-2100m
- long: 2101m以上

対象:
{", ".join(sires)}
""".strip()
    text = client.generate_text(prompt=prompt)
    return _parse_json(text)


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    payload = json.loads(cleaned)
    if not isinstance(payload, dict) or not isinstance(payload.get("sires"), dict):
        raise ValueError("Gemini response did not contain sires object")
    return payload


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


if __name__ == "__main__":
    main()
