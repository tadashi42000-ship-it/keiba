"""
netkeiba から重賞/当日レース情報を取得するユーティリティ。

Streamlit 側で使用しやすいよう RaceInfo を返す。
race_id は必要時に別途解決する（schedule由来のレースは初期値 None）。
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import lru_cache
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

_WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")
_SCHEDULE_CACHE_VERSION = "2026-04-24-schedule-v2"
_SAME_DAY_CACHE_VERSION = "2026-04-24-sameday-v2"

_VENUE_CODE_TO_NAME = {
    "01": "札幌",
    "02": "函館",
    "03": "福島",
    "04": "新潟",
    "05": "東京",
    "06": "中山",
    "07": "中京",
    "08": "京都",
    "09": "阪神",
    "10": "小倉",
}
_VENUE_ORDER = {name: idx for idx, name in enumerate(_VENUE_CODE_TO_NAME.values())}


def _format_date_with_weekday(value: date) -> str:
    return f"{value:%Y/%m/%d}({_WEEKDAYS_JA[value.weekday()]})"


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _normalize_surface(text: str) -> str:
    normalized = _normalize_text(text)
    if "障" in normalized:
        return "障害"
    if "ダ" in normalized:
        return "ダート"
    if "芝" in normalized:
        return "芝"
    return ""


def _extract_distance(text: str) -> str:
    normalized = _normalize_text(text)
    m = re.search(r"(\d{3,4})\s*m", normalized, flags=re.IGNORECASE)
    if not m:
        return ""
    return f"{m.group(1)}m"


def _extract_grade(text: str) -> str:
    normalized = _normalize_text(text).upper()
    if re.search(r"\b(?:J)?G1\b|GⅠ|Ｇ1|GI", normalized):
        return "G1"
    if re.search(r"\b(?:J)?G2\b|GⅡ|Ｇ2|GII", normalized):
        return "G2"
    if re.search(r"\b(?:J)?G3\b|GⅢ|Ｇ3|GIII", normalized):
        return "G3"
    if "L" in normalized:
        return "L"
    if "オープン" in normalized or "OPEN" in normalized:
        return "OP"
    return "平場"


def _extract_race_number(text: str, fallback_race_id: str = "") -> str:
    normalized = _normalize_text(text)
    m = re.search(r"(\d{1,2})\s*R\b", normalized, flags=re.IGNORECASE)
    if m:
        return f"{int(m.group(1))}R"
    if re.fullmatch(r"\d{12}", fallback_race_id):
        return f"{int(fallback_race_id[-2:])}R"
    return ""


def _extract_venue_from_text(text: str) -> str:
    normalized = _normalize_text(text)
    for name in _VENUE_CODE_TO_NAME.values():
        if name and name in normalized:
            return name
    return ""


def _venue_from_race_id(race_id: str) -> str:
    rid = _normalize_text(race_id)
    if not re.fullmatch(r"\d{12}", rid):
        return ""
    return _VENUE_CODE_TO_NAME.get(rid[4:6], "")


def _request_text(url: str, timeout: int = 12) -> str:
    resp = requests.get(url, headers=_HEADERS, timeout=timeout)
    if resp.status_code != 200:
        return ""
    if not resp.encoding or resp.encoding.lower() in {"", "iso-8859-1", "ascii"}:
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def _parse_date_from_text(text: str, *, year: int, fallback_month: int) -> date | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    # 03/29(日) / 3/29(日)
    m = re.search(r"(?:(\d{1,2})/)?(\d{1,2})\([^)]+\)", normalized)
    if m:
        try:
            month = int(m.group(1)) if m.group(1) else fallback_month
            day = int(m.group(2))
            return date(year, month, day)
        except ValueError:
            return None

    # 3月29日(日)
    m = re.search(r"(\d{1,2})月(\d{1,2})日", normalized)
    if m:
        try:
            return date(year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None

    # YYYY/MM/DD
    m = re.search(r"(20\d{2})/(\d{1,2})/(\d{1,2})", normalized)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    return None


def _race_number_value(race_number: str) -> int:
    m = re.search(r"(\d{1,2})", _normalize_text(race_number))
    return int(m.group(1)) if m else 99


def _normalize_special_url(link: str) -> str:
    """
    race_id 解決用 URL を正規化し、netkeiba 配下のみ許可する。
    """
    link = _normalize_text(link)
    if not link:
        return ""

    lowered = link.lower()
    if lowered.startswith(("javascript:", "mailto:", "#")):
        return ""

    candidate = f"https:{link}" if link.startswith("//") else urljoin("https://race.netkeiba.com/", link)
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    host = parsed.netloc.split("@")[-1].split(":")[0]
    labels = host.split(".")
    if any((not label) or len(label) > 63 for label in labels):
        return ""

    if host != "netkeiba.com" and not host.endswith(".netkeiba.com"):
        return ""

    return candidate


def build_race_key(race_date: date, venue: str, race_name: str, race_number: str = "") -> str:
    base = f"{race_date.isoformat()}_{_normalize_text(venue)}_{_normalize_text(race_name)}".strip("_")
    number = _normalize_text(race_number)
    return f"{base}_{number}" if number else base


@dataclass
class RaceInfo:
    race_name: str
    grade: str
    date_str: str
    date: date
    venue: str
    distance: str
    surface: str
    race_id: str | None
    race_key: str
    race_number: str = ""
    csv_file: str = ""
    special_url: str = ""

    def __post_init__(self) -> None:
        if not self.csv_file and self.race_id:
            self.csv_file = f"data/race_{self.race_id}.csv"

    @property
    def display_label(self) -> str:
        race_no = f"{self.race_number} " if self.race_number else ""
        surface_distance = f"{self.surface}{self.distance}".strip()
        extra = f"{surface_distance}" if surface_distance else ""
        return f"{self.date_str} {self.venue} {race_no}{self.race_name} {self.grade} {extra}".strip()

    @property
    def display_name(self) -> str:
        race_no = f"{self.race_number} " if self.race_number else ""
        return f"{race_no}{self.race_name} {self.date.year}".strip()


def _parse_schedule_page(html: str, year: int, month: int) -> list[RaceInfo]:
    soup = BeautifulSoup(html, "html.parser")
    races: list[RaceInfo] = []
    seen_keys: set[str] = set()

    row_items = soup.select("table.race_table_01 tr[class^='schedule_list']")
    if not row_items:
        row_items = soup.select("tr[class^='schedule_list'], li.RaceList_DataItem, tr.RaceList_DataItem, div.RaceList_Item")

    current_date: date | None = None
    for item in row_items:
        text = _normalize_text(item.get_text(" ", strip=True))
        if not text:
            continue

        tds = item.find_all("td")

        row_date = None
        if tds:
            row_date = _parse_date_from_text(tds[0].get_text(" ", strip=True), year=year, fallback_month=month)
        if not row_date:
            row_date = _parse_date_from_text(text, year=year, fallback_month=month)
        if row_date:
            current_date = row_date
        race_date = row_date or current_date
        if not race_date:
            continue

        grade_source = text
        if len(tds) >= 3:
            grade_source = f"{tds[2].get_text(' ', strip=True)} {text}"
        grade = _extract_grade(grade_source)
        if grade not in {"G1", "G2", "G3"}:
            continue

        race_anchor = None
        if len(tds) >= 2:
            race_anchor = tds[1].find("a", href=True)
        if not race_anchor:
            race_anchor = item.find("a", href=True)
        if not race_anchor:
            continue

        race_name = _normalize_text(race_anchor.get_text(" ", strip=True))
        if not race_name:
            continue
        race_name = re.sub(r"\s*(?:J)?G[123ⅠⅡⅢ]\b.*$", "", race_name).strip()
        race_name = re.sub(r"^\d{1,2}\s*R\s*", "", race_name, flags=re.IGNORECASE).strip()
        if not race_name:
            continue

        special_url = _normalize_special_url(race_anchor.get("href", ""))

        venue = ""
        surface_distance_text = text
        if len(tds) >= 4:
            venue = _normalize_text(tds[3].get_text(" ", strip=True))
        if len(tds) >= 5:
            surface_distance_text = _normalize_text(tds[4].get_text(" ", strip=True))
        if not venue:
            venue = _extract_venue_from_text(text)

        race_number = _extract_race_number(text)
        distance = _extract_distance(surface_distance_text) or _extract_distance(text)
        surface = _normalize_surface(surface_distance_text) or _normalize_surface(text)
        race_key = build_race_key(race_date, venue, race_name, race_number)
        if race_key in seen_keys:
            continue
        seen_keys.add(race_key)

        races.append(
            RaceInfo(
                race_name=race_name,
                grade=grade,
                date_str=_format_date_with_weekday(race_date),
                date=race_date,
                venue=venue,
                distance=distance,
                surface=surface,
                race_id=None,
                race_key=race_key,
                race_number=race_number,
                special_url=special_url,
            )
        )

    return races


@lru_cache(maxsize=48)
def _fetch_graded_races_cached(year: int, month: int, cache_version: str) -> tuple[RaceInfo, ...]:
    del cache_version  # cache invalidation token
    url = f"https://race.netkeiba.com/top/schedule.html?year={year}&month={month}"
    try:
        html = _request_text(url, timeout=12)
    except requests.exceptions.RequestException:
        return tuple()
    if not html:
        return tuple()
    return tuple(_parse_schedule_page(html, year, month))


def fetch_graded_races(year: int, month: int) -> list[RaceInfo]:
    return [replace(race) for race in _fetch_graded_races_cached(year, month, _SCHEDULE_CACHE_VERSION)]


def clear_fetch_graded_races_cache() -> None:
    _fetch_graded_races_cached.cache_clear()


def _extract_race_name_from_list_row(row_text: str, race_number: str) -> str:
    text = _normalize_text(row_text)
    if not text:
        return ""
    if race_number:
        text = re.sub(rf"^{re.escape(race_number)}\s*", "", text, flags=re.IGNORECASE)
    # "11R 皐月賞 15:40 芝2000m 18頭" -> "皐月賞"
    text = re.split(r"\b\d{1,2}:\d{2}\b", text, maxsplit=1)[0].strip()
    text = re.sub(r"\s*(?:芝|ダート|ダ|障害|障)\s*\d{3,4}\s*m.*$", "", text, flags=re.IGNORECASE).strip()
    return text


def _normalize_race_name_for_match(name: str) -> str:
    text = _normalize_text(name)
    if not text:
        return ""
    text = text.replace("ステークス", "S").replace("ステーク", "S")
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"[\s・･\-]", "", text)
    return text.upper()


def _apply_schedule_grade_hints(races: list[RaceInfo], target_date: date) -> None:
    if not races:
        return
    try:
        graded_races = [
            race
            for race in fetch_graded_races(target_date.year, target_date.month)
            if race.date == target_date and race.grade in {"G1", "G2", "G3", "L", "OP"}
        ]
    except Exception:
        return
    if not graded_races:
        return

    by_venue: dict[str, list[tuple[str, str]]] = {}
    for graded in graded_races:
        normalized_name = _normalize_race_name_for_match(graded.race_name)
        if not normalized_name:
            continue
        by_venue.setdefault(graded.venue, []).append((normalized_name, graded.grade))

    for race in races:
        if race.grade in {"G1", "G2", "G3", "L", "OP"}:
            continue
        normalized_name = _normalize_race_name_for_match(race.race_name)
        if not normalized_name:
            continue

        candidates = by_venue.get(race.venue, [])
        if not candidates:
            continue

        direct_matches = [grade for candidate_name, grade in candidates if candidate_name == normalized_name]
        if len(direct_matches) == 1:
            race.grade = direct_matches[0]
            continue

        fuzzy_matches = [
            grade
            for candidate_name, grade in candidates
            if candidate_name and (candidate_name in normalized_name or normalized_name in candidate_name)
        ]
        unique_fuzzy = sorted(set(fuzzy_matches))
        if len(unique_fuzzy) == 1:
            race.grade = unique_fuzzy[0]


def _build_race_info_from_race_id(
    *,
    race_id: str,
    row_text: str,
    target_date: date,
    special_url: str,
) -> RaceInfo:
    race_number = _extract_race_number(row_text, fallback_race_id=race_id)
    race_name = _extract_race_name_from_list_row(row_text, race_number)
    if not race_name:
        race_name = race_number or f"race_{race_id[-2:]}"

    venue = _venue_from_race_id(race_id)
    distance = _extract_distance(row_text)
    surface = _normalize_surface(row_text)
    grade = _extract_grade(row_text)
    race_key = build_race_key(target_date, venue, race_name, race_number)

    return RaceInfo(
        race_name=race_name,
        grade=grade,
        date_str=_format_date_with_weekday(target_date),
        date=target_date,
        venue=venue,
        distance=distance,
        surface=surface,
        race_id=race_id,
        race_key=race_key,
        race_number=race_number,
        special_url=_normalize_special_url(special_url),
    )


def _parse_race_list_sub_page(html: str, target_date: date) -> list[RaceInfo]:
    soup = BeautifulSoup(html, "html.parser")
    races: list[RaceInfo] = []
    seen_ids: set[str] = set()

    for a_tag in soup.select("a[href*='race_id=']"):
        href = _normalize_text(a_tag.get("href", ""))
        if not href:
            continue
        if not re.search(r"/race/(?:shutuba|result)\.html", href):
            continue
        m = re.search(r"race_id=(\d{12})", href)
        if not m:
            continue
        race_id = m.group(1)
        if race_id in seen_ids:
            continue
        seen_ids.add(race_id)

        row_text = _normalize_text(a_tag.get_text(" ", strip=True))
        if not row_text:
            parent = a_tag.find_parent(["li", "tr", "div"])
            row_text = _normalize_text(parent.get_text(" ", strip=True) if parent else "")

        special_url = urljoin("https://race.netkeiba.com/top/", href)
        race = _build_race_info_from_race_id(
            race_id=race_id,
            row_text=row_text,
            target_date=target_date,
            special_url=special_url,
        )
        races.append(race)

    races.sort(key=lambda r: (_VENUE_ORDER.get(r.venue, 999), r.venue, _race_number_value(r.race_number), r.race_id or ""))
    return races


def _parse_db_race_list_page(html: str, target_date: date) -> list[RaceInfo]:
    soup = BeautifulSoup(html, "html.parser")
    races: list[RaceInfo] = []
    seen_ids: set[str] = set()

    for a_tag in soup.select("a[href*='/race/']"):
        href = _normalize_text(a_tag.get("href", ""))
        m = re.search(r"/race/(\d{12})/?", href)
        if not m:
            continue
        race_id = m.group(1)
        if race_id in seen_ids:
            continue
        seen_ids.add(race_id)

        row_text = _normalize_text(a_tag.get_text(" ", strip=True))
        special_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        race = _build_race_info_from_race_id(
            race_id=race_id,
            row_text=row_text,
            target_date=target_date,
            special_url=special_url,
        )
        if not race.venue:
            continue
        races.append(race)

    races.sort(key=lambda r: (_VENUE_ORDER.get(r.venue, 999), r.venue, _race_number_value(r.race_number), r.race_id or ""))
    return races


@lru_cache(maxsize=64)
def _fetch_races_by_date_cached(date_iso: str, cache_version: str) -> tuple[RaceInfo, ...]:
    del cache_version  # cache invalidation token
    target_date = datetime.strptime(date_iso, "%Y-%m-%d").date()
    ymd = target_date.strftime("%Y%m%d")

    # 主経路: race_list_sub（JRA当日レースを静的に取得可能）
    primary_url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={ymd}"
    try:
        primary_html = _request_text(primary_url, timeout=12)
    except requests.exceptions.RequestException:
        primary_html = ""
    if primary_html:
        races = _parse_race_list_sub_page(primary_html, target_date)
        if races:
            _apply_schedule_grade_hints(races, target_date)
            return tuple(races)

    # 補助経路: db.netkeiba
    fallback_url = f"https://db.netkeiba.com/race/list/{ymd}/"
    try:
        fallback_html = _request_text(fallback_url, timeout=12)
    except requests.exceptions.RequestException:
        fallback_html = ""
    if fallback_html:
        races = _parse_db_race_list_page(fallback_html, target_date)
        if races:
            _apply_schedule_grade_hints(races, target_date)
            return tuple(races)

    return tuple()


def fetch_races_by_date(target_date: date) -> list[RaceInfo]:
    """
    指定日の JRA レース一覧（主に 1R〜12R）を返す。
    race_id を含む RaceInfo を返すため、same-day モードで即利用できる。
    """
    if not isinstance(target_date, date):
        raise TypeError("target_date must be date")
    return [replace(race) for race in _fetch_races_by_date_cached(target_date.isoformat(), _SAME_DAY_CACHE_VERSION)]


def clear_fetch_races_by_date_cache() -> None:
    _fetch_races_by_date_cached.cache_clear()


def group_races_by_venue(races: list[RaceInfo]) -> dict[str, list[RaceInfo]]:
    grouped: dict[str, list[RaceInfo]] = {}
    for race in races or []:
        venue = _normalize_text(getattr(race, "venue", "")) or "不明"
        grouped.setdefault(venue, []).append(replace(race))

    ordered: dict[str, list[RaceInfo]] = {}
    for venue in sorted(grouped.keys(), key=lambda v: (_VENUE_ORDER.get(v, 999), v)):
        rows = grouped[venue]
        rows.sort(key=lambda r: (_race_number_value(r.race_number), r.race_name, r.race_id or ""))
        ordered[venue] = rows
    return ordered


def _resolve_race_id_from_special_url(special_url: str) -> str | None:
    try:
        normalized_url = _normalize_special_url(special_url)
        if not normalized_url:
            return None

        # URL自身に race_id があれば最優先で採用
        parsed = urlparse(normalized_url)
        query = parse_qs(parsed.query)
        race_ids = query.get("race_id") or []
        if race_ids:
            candidate = _normalize_text(race_ids[0])
            if re.fullmatch(r"\d{12}", candidate):
                return candidate

        resp_text = _request_text(normalized_url, timeout=10)
        if not resp_text:
            return None

        soup = BeautifulSoup(resp_text, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = _normalize_text(a_tag["href"])
            m = re.search(r"race_id=(\d{12})", href)
            if m:
                return m.group(1)
            m = re.search(r"/race/(\d{12})/?", href)
            if m:
                return m.group(1)

        # JS由来データの最終フォールバック
        m = re.search(r"myhorse_(\d{12})", resp_text)
        if m:
            return m.group(1)
        m = re.search(r"race_id=(\d{12})", resp_text)
        if m:
            return m.group(1)
        return None
    except (requests.exceptions.RequestException, ValueError):
        return None


@lru_cache(maxsize=512)
def _resolve_race_id_cached(race_key: str, special_url: str) -> str:
    del race_key  # cache keyとしてのみ使用
    resolved = _resolve_race_id_from_special_url(special_url)
    if not resolved:
        raise ValueError("race_id unresolved")
    return resolved


def resolve_race_id(race: RaceInfo) -> str | None:
    if race.race_id:
        return race.race_id
    if not race.special_url:
        return None
    try:
        return _resolve_race_id_cached(race.race_key, race.special_url)
    except ValueError:
        return None


def clear_resolve_race_id_cache() -> None:
    _resolve_race_id_cached.cache_clear()


def get_upcoming_races(
    months_ahead: int = 2,
    from_date: date | None = None,
    days_ahead: int | None = 14,
) -> list[RaceInfo]:
    start_date = from_date or date.today()
    end_date = (start_date + timedelta(days=days_ahead)) if days_ahead is not None else None

    all_races: list[RaceInfo] = []
    seen_keys: set[str] = set()

    required_months = 0
    if end_date is not None:
        required_months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
        required_months = max(required_months, 0)

    months_to_fetch = max(months_ahead, required_months)

    for offset in range(months_to_fetch + 1):
        y = start_date.year
        m = start_date.month + offset
        while m > 12:
            m -= 12
            y += 1

        fetched = fetch_graded_races(y, m)
        for race in fetched:
            if race.date < start_date:
                continue
            if end_date is not None and race.date > end_date:
                continue
            if race.race_key in seen_keys:
                continue
            seen_keys.add(race.race_key)
            all_races.append(race)

    all_races.sort(key=lambda r: (r.date, _VENUE_ORDER.get(r.venue, 999), _race_number_value(r.race_number), r.race_name))
    return all_races


def ensure_data_dir() -> None:
    os.makedirs("data", exist_ok=True)
