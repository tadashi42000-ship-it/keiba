"""
Utilities for same-day mode source retrieval.

Policy:
- Primary source: netkeiba static pages.
- Umanity flat race sources are still unresolved, so kept as a no-op fallback.
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

_JRA_VENUE_CODE_MAP = {
    "札幌": "01",
    "函館": "02",
    "福島": "03",
    "新潟": "04",
    "東京": "05",
    "中山": "06",
    "中京": "07",
    "京都": "08",
    "阪神": "09",
    "小倉": "10",
}

_JRA_VENUES = tuple(_JRA_VENUE_CODE_MAP.keys())
_STYLE_ORDER = ("逃げ", "先行", "差し", "追込")
_POPULARITY_BUCKETS = ("1番人気", "2-3番人気", "4-6番人気", "7番人気以下")
_BODY_WEIGHT_BUCKETS = ("~439", "440-459", "460-479", "480-499", "500-519", "520+")


def build_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_HEADERS)
    return session


def _decode_response_text(response: requests.Response) -> str:
    content = response.content or b""
    if not content:
        return ""

    encoding = (response.encoding or "").strip()
    if not encoding or encoding.lower() in {"", "iso-8859-1", "ascii"}:
        meta_match = re.search(br"charset=['\"]?([a-zA-Z0-9_.-]+)", content[:4096], flags=re.IGNORECASE)
        if meta_match:
            try:
                encoding = meta_match.group(1).decode("ascii", errors="ignore")
            except Exception:
                encoding = ""
        if not encoding:
            encoding = response.apparent_encoding or "utf-8"

    try:
        return content.decode(encoding, errors="replace")
    except Exception:
        return content.decode(response.apparent_encoding or "utf-8", errors="replace")


def _request_html(
    url: str,
    timeout: int = 12,
    *,
    session: requests.Session | None = None,
) -> str:
    client = session or requests
    kwargs: dict[str, Any] = {"timeout": timeout}
    if session is None:
        kwargs["headers"] = _HEADERS
    resp = client.get(url, **kwargs)
    if resp.status_code != 200:
        return ""
    return _decode_response_text(resp)


def _extract_text_snippet(html: str, *, max_chars: int = 3000) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.find("body") or soup
    text = body.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def _safe_int(text: str | None) -> int | None:
    value = re.sub(r"[^\d]", "", str(text or ""))
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _extract_horse_id_from_href(href: str) -> str:
    match = re.search(r"/horse/(\d+)", str(href or ""))
    return match.group(1) if match else ""


def _extract_venue_name(text: str) -> str:
    normalized = re.sub(r"\s+", "", str(text or ""))
    for venue in _JRA_VENUES:
        if venue in normalized:
            return venue
    return ""


def _extract_corner_order(text: str) -> str:
    normalized = re.sub(r"\s+", "", str(text or ""))
    match = re.search(r"(\d{1,2}(?:-\d{1,2}){1,3})", normalized)
    return match.group(1) if match else ""


def fetch_netkeiba_race_column(
    race_id: str,
    *,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """
    Collect netkeiba same-day race pages and normalize as article-like payloads.
    """
    rid = str(race_id or "").strip()
    if not re.fullmatch(r"\d{12}", rid):
        return []

    candidates = [
        ("出馬表+過去", f"https://race.netkeiba.com/race/shutuba_past.html?race_id={rid}"),
        ("新聞", f"https://race.netkeiba.com/race/newspaper.html?race_id={rid}"),
        ("データトップ", f"https://race.netkeiba.com/race/data_top.html?race_id={rid}"),
    ]

    articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for label, url in candidates:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            html = _request_html(url, timeout=12, session=session)
        except requests.exceptions.RequestException:
            continue
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        title = (soup.title.get_text(" ", strip=True) if soup.title else "") or label
        snippet = _extract_text_snippet(html, max_chars=3500)
        if not snippet:
            continue
        articles.append(
            {
                "title": f"{label}: {title}",
                "snippet": snippet,
                "url": url,
                "source_name": "netkeiba.com",
                "source_type": "web",
            }
        )

    return articles


def fetch_race_horse_ids(
    race_id: str,
    *,
    session: requests.Session | None = None,
) -> list[dict[str, str]]:
    """Return horse_id and horse_name list for the race from shutuba page."""
    rid = str(race_id or "").strip()
    if not re.fullmatch(r"\d{12}", rid):
        return []

    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={rid}"
    try:
        html = _request_html(url, timeout=12, session=session)
    except requests.exceptions.RequestException:
        return []
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table.Shutuba_Table tr")
    if not rows:
        return []

    results: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for row in rows:
        horse_anchor = row.select_one("td.HorseInfo a[href*='/horse/']")
        if not horse_anchor:
            continue
        horse_name = re.sub(r"\s+", " ", horse_anchor.get_text(" ", strip=True)).strip()
        horse_id = _extract_horse_id_from_href(horse_anchor.get("href", ""))
        if not horse_id or horse_id in seen_ids:
            continue
        seen_ids.add(horse_id)
        results.append({"horse_name": horse_name, "horse_id": horse_id})
    return results


def fetch_horse_sire(
    horse_id: str,
    *,
    session: requests.Session | None = None,
) -> str | None:
    """Fetch sire name from the netkeiba horse profile page.

    The race result page (/horse/result/{id}/) does not include the pedigree
    table, so this function intentionally reads /horse/{id}/.
    """
    hid = str(horse_id or "").strip()
    if not re.fullmatch(r"\d+", hid):
        return None

    blood_table = None
    for url in (
        f"https://db.netkeiba.com/horse/{hid}/",
        f"https://db.netkeiba.com/horse/ped/{hid}/",
    ):
        try:
            html = _request_html(url, timeout=12, session=session)
        except requests.exceptions.RequestException:
            continue
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        blood_table = soup.select_one("table.blood_table")
        if blood_table:
            break
    if not blood_table:
        return None

    candidates = [
        "tr:nth-of-type(1) td:nth-of-type(1) a[href*='/horse/']",
        "tr:first-child td:first-child a[href*='/horse/']",
        "a[href*='/horse/']",
    ]
    for selector in candidates:
        anchor = blood_table.select_one(selector)
        if not anchor:
            continue
        sire_name = _clean_pedigree_name(anchor.get_text(" ", strip=True))
        if sire_name:
            return sire_name
    return None


def fetch_horse_pedigree(
    horse_id: str,
    *,
    session: requests.Session | None = None,
) -> dict[str, str]:
    """Fetch sire and broodmare sire names from the netkeiba pedigree table."""
    hid = str(horse_id or "").strip()
    if not re.fullmatch(r"\d+", hid):
        return {}

    blood_table = None
    for url in (
        f"https://db.netkeiba.com/horse/{hid}/",
        f"https://db.netkeiba.com/horse/ped/{hid}/",
    ):
        try:
            html = _request_html(url, timeout=12, session=session)
        except requests.exceptions.RequestException:
            continue
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        blood_table = soup.select_one("table.blood_table")
        if blood_table:
            break
    if not blood_table:
        return {}

    rows = blood_table.select("tr")
    sire_name = _pedigree_cell_name(rows, 0, 0)
    broodmare_sire_name = _pedigree_cell_name(rows, 16, 1)
    return {
        "sire_name": sire_name,
        "broodmare_sire_name": broodmare_sire_name,
    }


def _pedigree_cell_name(rows: list, row_index: int, cell_index: int) -> str:
    if row_index >= len(rows):
        return ""
    cells = rows[row_index].select("td")
    if cell_index >= len(cells):
        return ""
    anchor = cells[cell_index].select_one("a[href*='/horse/']")
    source = anchor.get_text(" ", strip=True) if anchor else cells[cell_index].get_text(" ", strip=True)
    return _clean_pedigree_name(source)


def _clean_pedigree_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"\s*\[[^\]]+\]\s*", " ", text)
    text = re.sub(r"\s+\d{4}\b.*$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_horse_profile(
    horse_id: str,
    *,
    session: requests.Session | None = None,
    max_recent_runs: int = 10,
) -> dict[str, Any]:
    """
    Fetch horse result page and compute structured stats.
    """
    hid = str(horse_id or "").strip()
    if not re.fullmatch(r"\d+", hid):
        return {}

    url = f"https://db.netkeiba.com/horse/result/{hid}/"
    try:
        html = _request_html(url, timeout=14, session=session)
    except requests.exceptions.RequestException:
        return {}
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    horse_name = ""
    name_match = re.match(r"(.+?)\s*(?:\(|\||の競走成績)", title or "")
    if name_match:
        horse_name = name_match.group(1).strip()
    if not horse_name:
        h1 = soup.select_one("h1")
        horse_name = re.sub(r"\s+", " ", h1.get_text(" ", strip=True) if h1 else "").strip()

    empty_payload = {
        "horse_id": hid,
        "horse_name": horse_name,
        "url": url,
        "total_starts": 0,
        "wins": 0,
        "top3": 0,
        "win_rate": 0.0,
        "top3_rate": 0.0,
        "surface_stats": {},
        "distance_stats": {},
        "venue_stats": {},
        "recent_runs": [],
    }

    result_table = soup.select_one("table.db_h_race_results")
    if not result_table:
        return empty_payload

    rows = result_table.select("tr")
    if len(rows) <= 1:
        return empty_payload

    headers = [re.sub(r"\s+", "", th.get_text(" ", strip=True)) for th in rows[0].select("th")]

    def _find_idx(*keywords: str) -> int:
        for idx, header in enumerate(headers):
            if any(keyword in header for keyword in keywords):
                return idx
        return -1

    idx_date = _find_idx("日付")
    idx_holding = _find_idx("開催")
    idx_race_name = _find_idx("レース名")
    idx_finish = _find_idx("着順")
    idx_popularity = _find_idx("人気")
    idx_distance = _find_idx("距離")
    idx_corner = _find_idx("通過")
    idx_last3f = _find_idx("上り")
    idx_body_weight = _find_idx("馬体重")

    # Header decode failure fallback (fixed columns in db_h_race_results)
    if idx_date < 0:
        idx_date = 0
    if idx_holding < 0:
        idx_holding = 1
    if idx_race_name < 0:
        idx_race_name = 4
    if idx_popularity < 0:
        idx_popularity = 10
    if idx_finish < 0:
        idx_finish = 11
    if idx_distance < 0:
        idx_distance = 14
    if idx_corner < 0:
        idx_corner = 25
    if idx_last3f < 0:
        idx_last3f = 27
    if idx_body_weight < 0:
        idx_body_weight = 23 if len(headers) > 23 else -1

    race_rows: list[dict[str, Any]] = []
    surface_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"starts": 0, "wins": 0, "top3": 0})
    distance_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"starts": 0, "wins": 0, "top3": 0})
    venue_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"starts": 0, "wins": 0, "top3": 0})
    total_starts = 0
    wins = 0
    top3 = 0

    for row in rows[1:]:
        cells = row.select("td")
        if not cells:
            continue
        texts = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in cells]
        if idx_finish >= len(texts):
            continue

        finish = _safe_int(texts[idx_finish])
        if finish is None:
            continue

        total_starts += 1
        is_win = int(finish == 1)
        is_top3 = int(finish <= 3)
        wins += is_win
        top3 += is_top3

        distance_text = texts[idx_distance] if 0 <= idx_distance < len(texts) else ""
        surface = ""
        if distance_text.startswith("芝"):
            surface = "芝"
        elif distance_text.startswith("ダ"):
            surface = "ダート"
        elif distance_text.startswith("障"):
            surface = "障害"

        distance_value_match = re.search(r"(\d{3,4})", distance_text)
        distance_key = distance_value_match.group(1) if distance_value_match else ""

        holding_text = texts[idx_holding] if 0 <= idx_holding < len(texts) else ""
        venue = _extract_venue_name(holding_text)

        if surface:
            surface_stats[surface]["starts"] += 1
            surface_stats[surface]["wins"] += is_win
            surface_stats[surface]["top3"] += is_top3
        if distance_key:
            distance_stats[distance_key]["starts"] += 1
            distance_stats[distance_key]["wins"] += is_win
            distance_stats[distance_key]["top3"] += is_top3
        if venue:
            venue_stats[venue]["starts"] += 1
            venue_stats[venue]["wins"] += is_win
            venue_stats[venue]["top3"] += is_top3

        race_rows.append(
            {
                "date": texts[idx_date] if 0 <= idx_date < len(texts) else "",
                "race_name": texts[idx_race_name] if 0 <= idx_race_name < len(texts) else "",
                "finish": finish,
                "popularity": _safe_int(texts[idx_popularity]) if 0 <= idx_popularity < len(texts) else None,
                "distance": distance_text,
                "venue": venue,
                "corner": _extract_corner_order(texts[idx_corner] if 0 <= idx_corner < len(texts) else ""),
                "last3f": texts[idx_last3f] if 0 <= idx_last3f < len(texts) else "",
                "body_weight": _extract_body_weight_kg(texts[idx_body_weight] if 0 <= idx_body_weight < len(texts) else ""),
            }
        )

    if total_starts <= 0:
        return empty_payload

    def _with_rate(payload: dict[str, dict[str, int]]) -> dict[str, dict[str, float | int]]:
        result: dict[str, dict[str, float | int]] = {}
        for key, stats in payload.items():
            starts = int(stats.get("starts", 0))
            wins_local = int(stats.get("wins", 0))
            top3_local = int(stats.get("top3", 0))
            result[key] = {
                "starts": starts,
                "wins": wins_local,
                "top3": top3_local,
                "win_rate": round((wins_local / starts) * 100, 2) if starts > 0 else 0.0,
                "top3_rate": round((top3_local / starts) * 100, 2) if starts > 0 else 0.0,
            }
        return result

    return {
        "horse_id": hid,
        "horse_name": horse_name,
        "url": url,
        "total_starts": total_starts,
        "wins": wins,
        "top3": top3,
        "win_rate": round((wins / total_starts) * 100, 2) if total_starts > 0 else 0.0,
        "top3_rate": round((top3 / total_starts) * 100, 2) if total_starts > 0 else 0.0,
        "surface_stats": _with_rate(surface_stats),
        "distance_stats": _with_rate(distance_stats),
        "venue_stats": _with_rate(venue_stats),
        "recent_runs": race_rows[: max(1, int(max_recent_runs))],
    }


def fetch_oikiri_comments(
    race_id: str,
    *,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch oikiri comments from netkeiba.
    Returns empty list when unavailable (before publication or unsupported race).
    """
    rid = str(race_id or "").strip()
    if not re.fullmatch(r"\d{12}", rid):
        return []

    candidate_urls = [
        f"https://race.netkeiba.com/race/oikiri.html?race_id={rid}&type=3",
        f"https://race.netkeiba.com/race/oikiri.html?race_id={rid}&type=1",
        f"https://race.netkeiba.com/race/oikiri.html?race_id={rid}",
    ]

    entries: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for url in candidate_urls:
        try:
            html = _request_html(url, timeout=12, session=session)
        except requests.exceptions.RequestException:
            continue
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        table = (
            soup.select_one("table.OikiriTable")
            or soup.select_one("table.Oikiri_Table")
            or soup.select_one("table.race_table_01")
        )
        if not table:
            continue

        for row in table.select("tr"):
            horse_anchor = (
                row.select_one(".HorseInfo a[href*='/horse/']")
                or row.select_one(".Horse_Name a[href*='/horse/']")
                or row.select_one("a[href*='/horse/']")
            )
            if not horse_anchor:
                continue

            horse_name = re.sub(r"\s+", " ", horse_anchor.get_text(" ", strip=True)).strip()
            horse_id = _extract_horse_id_from_href(horse_anchor.get("href", ""))
            if not horse_name:
                continue

            comment_cell = (
                row.select_one("td.Training_Critic")
                or row.select_one("td.Comment")
                or row.select_one("td.OikiriComment")
            )
            rank_cell = row.select_one("td[class*='Rank_']") or row.select_one("td.Evaluation")

            comment = re.sub(r"\s+", " ", comment_cell.get_text(" ", strip=True)).strip() if comment_cell else ""
            rank = re.sub(r"\s+", "", rank_cell.get_text(" ", strip=True)) if rank_cell else ""

            if not comment:
                tds = row.select("td")
                if tds:
                    # fallback: longest cell text as comment candidate
                    longest = max((re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tds), key=len, default="")
                    comment = longest if len(longest) >= 12 else ""
            if not comment:
                continue

            key = (horse_id or horse_name, comment)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            entries.append(
                {
                    "horse_id": horse_id,
                    "horse_name": horse_name,
                    "comment": comment,
                    "rank": rank,
                    "source_url": url,
                    "source_title": f"追い切りコメント: {horse_name}",
                    "source_type": "oikiri",
                }
            )

        if entries:
            break

    return entries


def _surface_to_track_code(surface: str) -> str:
    text = str(surface or "").strip()
    if "芝" in text:
        return "1"
    if "ダ" in text:
        return "2"
    if "障" in text:
        return "3"
    return ""


def _distance_to_value(distance: str) -> int | None:
    match = re.search(r"(\d{3,4})", str(distance or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _build_course_race_list_url(
    *,
    venue_code: str,
    distance: int,
    track_code: str,
    start_year: int,
    end_year: int,
) -> str:
    return (
        "https://db.netkeiba.com/?pid=race_list"
        f"&track[]={track_code}"
        f"&jyo[]={venue_code}"
        f"&kyori[]={distance}"
        f"&start_year={start_year}"
        "&start_mon=1"
        f"&end_year={end_year}"
        "&end_mon=12"
    )


def _fetch_course_race_ids(
    race_list_url: str,
    *,
    session: requests.Session | None = None,
) -> list[str]:
    try:
        html = _request_html(race_list_url, timeout=14, session=session)
    except requests.exceptions.RequestException:
        return []
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    ids: list[str] = []
    seen: set[str] = set()
    for a_tag in soup.select("a[href*='/race/']"):
        href = a_tag.get("href", "")
        match = re.search(r"/race/(\d{12})/?", href)
        if not match:
            continue
        race_id = match.group(1)
        if race_id in seen:
            continue
        seen.add(race_id)
        ids.append(race_id)
    return ids


def _classify_style_from_passing(passing: str) -> str:
    numbers = [int(x) for x in re.findall(r"\d{1,2}", str(passing or ""))]
    if not numbers:
        return ""
    # 通過順の最初の値を重視する
    base = numbers[0]
    if base <= 1:
        return "逃げ"
    if base <= 3:
        return "先行"
    if base <= 8:
        return "差し"
    return "追込"


def _popularity_bucket(popularity: int | None) -> str:
    if popularity is None:
        return ""
    if popularity == 1:
        return "1番人気"
    if popularity <= 3:
        return "2-3番人気"
    if popularity <= 6:
        return "4-6番人気"
    return "7番人気以下"


def _body_weight_bucket(weight: int | None) -> str:
    if weight is None:
        return ""
    if weight < 440:
        return "~439"
    if weight < 460:
        return "440-459"
    if weight < 480:
        return "460-479"
    if weight < 500:
        return "480-499"
    if weight < 520:
        return "500-519"
    return "520+"


def _extract_body_weight_kg(text: str) -> int | None:
    match = re.search(r"(\d{3})", str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def fetch_race_result_rows(
    race_id: str,
    *,
    session: requests.Session | None = None,
    race_meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result_url = f"https://db.netkeiba.com/race/{race_id}/"
    try:
        html = _request_html(result_url, timeout=14, session=session)
    except requests.exceptions.RequestException:
        return []
    if not html:
        return []
    return _parse_result_table_rows(html, race_id=str(race_id), race_meta=race_meta or {})


def _parse_result_table_rows(result_html: str, *, race_id: str, race_meta: dict[str, Any]) -> list[dict[str, Any]]:
    soup = BeautifulSoup(result_html, "html.parser")
    table = soup.select_one("table.race_table_01")
    if not table:
        return []

    rows = table.select("tr")
    if len(rows) <= 1:
        return []

    headers = [re.sub(r"\s+", "", th.get_text(" ", strip=True)) for th in rows[0].select("th")]

    def _find_idx(*keywords: str) -> int:
        for idx, header in enumerate(headers):
            if any(keyword in header for keyword in keywords):
                return idx
        return -1

    idx_finish = _find_idx("着順")
    idx_frame = _find_idx("枠番")
    idx_umaban = _find_idx("馬番")
    idx_popularity = _find_idx("人気")
    idx_passing = _find_idx("通過")
    idx_last3f = _find_idx("上り", "上がり")
    idx_body_weight = _find_idx("馬体重")

    if idx_finish < 0:
        idx_finish = 0
    if idx_frame < 0:
        idx_frame = 1
    if idx_umaban < 0:
        idx_umaban = 2
    if idx_passing < 0:
        idx_passing = 14 if len(headers) > 14 else -1
    if idx_last3f < 0:
        idx_last3f = 15 if len(headers) > 15 else -1
    if idx_popularity < 0:
        idx_popularity = 17 if len(headers) > 17 else -1
    if idx_body_weight < 0:
        idx_body_weight = 14 if len(headers) > 14 else -1
    if min(idx_finish, idx_frame, idx_umaban, idx_popularity, idx_passing) < 0:
        return []

    parsed_rows: list[dict[str, Any]] = []
    for row in rows[1:]:
        cells = row.select("td")
        if not cells:
            continue
        texts = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in cells]
        if max(idx_finish, idx_frame, idx_umaban, idx_popularity, idx_passing) >= len(texts):
            continue
        finish = _safe_int(texts[idx_finish])
        if finish is None:
            continue
        parsed_rows.append(
            {
                "race_id": str(race_id),
                "date": str(race_meta.get("date") or ""),
                "venue": str(race_meta.get("venue") or ""),
                "surface": str(race_meta.get("surface") or ""),
                "distance_m": int(race_meta.get("distance_m") or 0),
                "race_number": str(race_meta.get("race_number") or ""),
                "finish_pos": finish,
                "waku": _safe_int(texts[idx_frame]),
                "umaban": _safe_int(texts[idx_umaban]),
                "style": _classify_style_from_passing(texts[idx_passing]),
                "popularity": _safe_int(texts[idx_popularity]),
                "last3f": texts[idx_last3f] if 0 <= idx_last3f < len(texts) else "",
                "body_weight": texts[idx_body_weight] if 0 <= idx_body_weight < len(texts) else "",
            }
        )
    return parsed_rows


def _parse_result_table_stats(result_html: str) -> dict[str, Any]:
    soup = BeautifulSoup(result_html, "html.parser")
    table = soup.select_one("table.race_table_01")
    if not table:
        return {}

    rows = table.select("tr")
    if len(rows) <= 2:
        return {}

    headers = [re.sub(r"\s+", "", th.get_text(" ", strip=True)) for th in rows[0].select("th")]

    def _find_idx(*keywords: str) -> int:
        for idx, header in enumerate(headers):
            if any(keyword in header for keyword in keywords):
                return idx
        return -1

    idx_finish = _find_idx("着順")
    idx_frame = _find_idx("枠番")
    idx_popularity = _find_idx("人気")
    idx_passing = _find_idx("通過")
    idx_body_weight = _find_idx("馬体重")

    # Header decode fallback (netkeiba race result table)
    if idx_finish < 0:
        idx_finish = 0
    if idx_frame < 0:
        idx_frame = 1
    if idx_passing < 0:
        idx_passing = 14 if len(headers) > 14 else -1
    if idx_popularity < 0:
        idx_popularity = 17 if len(headers) > 17 else -1
    if idx_body_weight < 0:
        idx_body_weight = 14 if len(headers) > 14 else -1
    if min(idx_finish, idx_frame, idx_popularity, idx_passing) < 0:
        return {}

    frame_total: Counter[int] = Counter()
    frame_wins: Counter[int] = Counter()
    frame_top3: Counter[int] = Counter()
    style_total: Counter[str] = Counter()
    style_top3: Counter[str] = Counter()
    pop_total: Counter[str] = Counter()
    pop_top3: Counter[str] = Counter()
    body_total: Counter[str] = Counter()
    body_wins: Counter[str] = Counter()
    body_top3: Counter[str] = Counter()
    winner_style: Counter[str] = Counter()
    rows_parsed = 0

    for row in rows[1:]:
        cells = row.select("td")
        if not cells:
            continue
        texts = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in cells]
        if max(idx_finish, idx_frame, idx_popularity, idx_passing) >= len(texts):
            continue

        finish = _safe_int(texts[idx_finish])
        frame = _safe_int(texts[idx_frame])
        popularity = _safe_int(texts[idx_popularity])
        style = _classify_style_from_passing(texts[idx_passing])
        pop_bucket = _popularity_bucket(popularity)
        if finish is None:
            continue

        rows_parsed += 1
        if frame:
            frame_total[frame] += 1
        if style:
            style_total[style] += 1
        if pop_bucket:
            pop_total[pop_bucket] += 1
        if 0 <= idx_body_weight < len(texts):
            body_bucket = _body_weight_bucket(_extract_body_weight_kg(texts[idx_body_weight]))
            if body_bucket:
                body_total[body_bucket] += 1

        if finish <= 3:
            if frame:
                frame_top3[frame] += 1
            if style:
                style_top3[style] += 1
            if pop_bucket:
                pop_top3[pop_bucket] += 1
            if 0 <= idx_body_weight < len(texts):
                body_bucket = _body_weight_bucket(_extract_body_weight_kg(texts[idx_body_weight]))
                if body_bucket:
                    body_top3[body_bucket] += 1

        if finish == 1 and style:
            winner_style[style] += 1
        if finish == 1 and frame:
            frame_wins[frame] += 1
        if finish == 1 and 0 <= idx_body_weight < len(texts):
            body_bucket = _body_weight_bucket(_extract_body_weight_kg(texts[idx_body_weight]))
            if body_bucket:
                body_wins[body_bucket] += 1

    if rows_parsed < 8:
        return {}

    return {
        "frame_total": frame_total,
        "frame_wins": frame_wins,
        "frame_top3": frame_top3,
        "style_total": style_total,
        "style_top3": style_top3,
        "pop_total": pop_total,
        "pop_top3": pop_top3,
        "body_total": body_total,
        "body_wins": body_wins,
        "body_top3": body_top3,
        "winner_style": winner_style,
    }


def fetch_course_stats(
    venue: str,
    distance: str,
    surface: str,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    max_races: int = 60,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """
    Aggregate static course stats from netkeiba race_list + race result pages.
    """
    venue_name = str(venue or "").strip()
    venue_code = _JRA_VENUE_CODE_MAP.get(venue_name)
    distance_value = _distance_to_value(distance)
    track_code = _surface_to_track_code(surface)
    if not venue_code or not distance_value or not track_code:
        return {}

    current_year = date.today().year
    end_year = int(end_year or current_year)
    start_year = int(start_year or max(2001, end_year - 5))
    if start_year > end_year:
        start_year, end_year = end_year, start_year

    race_list_url = _build_course_race_list_url(
        venue_code=venue_code,
        distance=distance_value,
        track_code=track_code,
        start_year=start_year,
        end_year=end_year,
    )
    race_ids = _fetch_course_race_ids(race_list_url, session=session)
    if not race_ids:
        return {}

    frame_total: Counter[int] = Counter()
    frame_wins: Counter[int] = Counter()
    frame_top3: Counter[int] = Counter()
    style_total: Counter[str] = Counter()
    style_top3: Counter[str] = Counter()
    pop_total: Counter[str] = Counter()
    pop_top3: Counter[str] = Counter()
    body_total: Counter[str] = Counter()
    body_wins: Counter[str] = Counter()
    body_top3: Counter[str] = Counter()
    winner_style: Counter[str] = Counter()
    used_race_ids: list[str] = []

    race_limit = max(10, min(int(max_races), len(race_ids)))
    for race_id in race_ids[:race_limit]:
        result_url = f"https://db.netkeiba.com/race/{race_id}/"
        try:
            html = _request_html(result_url, timeout=14, session=session)
        except requests.exceptions.RequestException:
            continue
        if not html:
            continue

        parsed = _parse_result_table_stats(html)
        if not parsed:
            continue

        frame_total.update(parsed["frame_total"])
        frame_wins.update(parsed.get("frame_wins", Counter()))
        frame_top3.update(parsed["frame_top3"])
        style_total.update(parsed["style_total"])
        style_top3.update(parsed["style_top3"])
        pop_total.update(parsed["pop_total"])
        pop_top3.update(parsed["pop_top3"])
        body_total.update(parsed.get("body_total", Counter()))
        body_wins.update(parsed.get("body_wins", Counter()))
        body_top3.update(parsed.get("body_top3", Counter()))
        winner_style.update(parsed["winner_style"])
        used_race_ids.append(race_id)
        time.sleep(0.15)

    if not used_race_ids:
        return {}

    def _rate(top: int, total: int) -> float:
        return round((top / total) * 100, 2) if total > 0 else 0.0

    frame_rows = []
    for frame in range(1, 9):
        total = int(frame_total.get(frame, 0))
        if total <= 0:
            continue
        top = int(frame_top3.get(frame, 0))
        wins = int(frame_wins.get(frame, 0))
        other = max(total - top, 0)
        frame_rows.append({
            "label": f"{frame}枠",
            "starts": total,
            "wins": wins,
            "top3": top,
            "outside_top3": other,
            "win_rate": _rate(wins, total),
            "top3_rate": _rate(top, total),
            "outside_top3_rate": _rate(other, total),
        })

    style_rows = []
    for style in _STYLE_ORDER:
        total = int(style_total.get(style, 0))
        if total <= 0:
            continue
        top = int(style_top3.get(style, 0))
        style_rows.append({"label": style, "starts": total, "top3": top, "top3_rate": _rate(top, total)})

    popularity_rows = []
    for bucket in _POPULARITY_BUCKETS:
        total = int(pop_total.get(bucket, 0))
        if total <= 0:
            continue
        top = int(pop_top3.get(bucket, 0))
        popularity_rows.append({"label": bucket, "starts": total, "top3": top, "top3_rate": _rate(top, total)})

    body_rows = []
    for bucket in _BODY_WEIGHT_BUCKETS:
        total = int(body_total.get(bucket, 0))
        if total <= 0:
            continue
        top = int(body_top3.get(bucket, 0))
        wins = int(body_wins.get(bucket, 0))
        other = max(total - top, 0)
        body_rows.append({
            "label": bucket,
            "starts": total,
            "wins": wins,
            "top3": top,
            "outside_top3": other,
            "win_rate": _rate(wins, total),
            "top3_rate": _rate(top, total),
            "outside_top3_rate": _rate(other, total),
        })

    winner_front = int(winner_style.get("逃げ", 0) + winner_style.get("先行", 0))
    winner_close = int(winner_style.get("差し", 0) + winner_style.get("追込", 0))
    if winner_front >= winner_close * 1.2:
        pace_tendency = "前有利"
    elif winner_close >= winner_front * 1.2:
        pace_tendency = "差し有利"
    else:
        pace_tendency = "バランス"

    return {
        "target": {
            "venue": venue_name,
            "distance": f"{distance_value}m",
            "surface": "芝" if track_code == "1" else ("ダート" if track_code == "2" else "障害"),
        },
        "race_list_url": race_list_url,
        "sample_race_count": len(used_race_ids),
        "sample_race_ids": used_race_ids,
        "frame_stats": frame_rows,
        "style_stats": style_rows,
        "popularity_stats": popularity_rows,
        "body_weight_stats": body_rows,
        "winner_style_counts": {k: int(v) for k, v in winner_style.items()},
        "pace_tendency": pace_tendency,
    }


def fetch_umanity_flat_racecard(race_id: str) -> dict[str, Any] | None:
    """
    Umanity flat race URL schema is unresolved. Placeholder only.
    """
    _ = race_id
    return None
