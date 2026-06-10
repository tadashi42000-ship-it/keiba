from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import ROOT_DIR
from app.schemas.races import ResearchNotesBackup, ResearchNotesBackupResponse


RESEARCH_NOTES_DIR = ROOT_DIR / "data" / "research_notes"


def load_research_notes_backup(race_id: str) -> ResearchNotesBackupResponse:
    path = _backup_path(race_id)
    if not path.exists():
        return ResearchNotesBackupResponse(race_id=race_id, exists=False)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ResearchNotesBackupResponse(race_id=race_id, exists=False)
    if not isinstance(payload, dict):
        return ResearchNotesBackupResponse(race_id=race_id, exists=False)
    payload.setdefault("race_id", race_id)
    payload["exists"] = True
    return ResearchNotesBackupResponse(**payload)


def save_research_notes_backup(race_id: str, payload: ResearchNotesBackup) -> ResearchNotesBackupResponse:
    text = (payload.notes or "").strip()
    if not text:
        raise ValueError("notes is empty")
    now = datetime.now().isoformat(timespec="seconds")
    data: dict[str, Any] = payload.model_dump(mode="json")
    data.update({"race_id": race_id, "exists": True, "backed_up_at": now})
    path = _backup_path(race_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return ResearchNotesBackupResponse(**data)


def _backup_path(race_id: str) -> Path:
    safe_id = re.sub(r"[^0-9A-Za-z_-]", "_", str(race_id or "").strip())
    if not safe_id:
        safe_id = "unknown"
    return RESEARCH_NOTES_DIR / f"{safe_id}.json"
