"""
netkeiba.com から直近の重賞レース一覧を取得するモジュール

スケジュールページをスクレイピングし、RaceInfo データクラスとして返す。
race_id はレース選択時に遅延解決する。
"""

import os
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import lru_cache
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

# netkeiba.com 共通ヘッダー
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

_WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")
_SCHEDULE_CACHE_VERSION = "2026-03-26-date-fix-1"


def _format_date_with_weekday(value: date) -> str:
    """YYYY/MM/DD(曜) 形式へ整形する。"""
    return f"{value:%Y/%m/%d}({_WEEKDAYS_JA[value.weekday()]})"


def _normalize_special_url(link: str) -> str:
    """race_id 解決用URLを正規化し、不正URLは空文字を返す。"""
    link = (link or "").strip()
    if not link:
        return ""

    lowered = link.lower()
    if lowered.startswith(("javascript:", "mailto:", "#")):
        return ""

    if link.startswith("//"):
        candidate = f"https:{link}"
    else:
        candidate = urljoin("https://race.netkeiba.com/", link)

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


@dataclass
class RaceInfo:
    race_name: str          # "高松宮記念"
    grade: str              # "G1" / "G2" / "G3"
    date_str: str           # "2026/03/29(日)"
    date: date              # parsed date
    venue: str              # "中京"
    distance: str           # "1200m"
    surface: str            # "芝" / "ダート"
    race_id: str | None     # "202607030811" — 出馬表ページから解決。未解決時は None
    race_key: str           # "{date}_{venue}_{race_name}" — キャッシュキー用
    csv_file: str = ""      # "data/race_202607030811.csv"
    special_url: str = ""   # 特別レースページURL（race_id 解決用）

    def __post_init__(self):
        if not self.csv_file and self.race_id:
            self.csv_file = f"data/race_{self.race_id}.csv"

    @property
    def display_label(self) -> str:
        """セレクトボックス用の表示ラベル"""
        return f"{self.date_str} {self.race_name} {self.grade} {self.venue} {self.surface}{self.distance}"

    @property
    def display_name(self) -> str:
        """検索クエリ等で使う 'レース名 年' 形式"""
        return f"{self.race_name} {self.date.year}"


def _parse_schedule_page(html: str, year: int, month: int) -> list[RaceInfo]:
    """スケジュールページのHTMLを解析し、重賞レース一覧を返す。"""
    soup = BeautifulSoup(html, 'html.parser')
    races: list[RaceInfo] = []

    def _parse_date_from_text(text: str, fallback_month: int) -> date | None:
        """日付文字列を date に変換する。対応例: 03/29(日), 3月29日(日)"""
        text = (text or "").strip()
        if not text:
            return None

        # 03/29(日) or 3/29(日)
        m = re.search(r'(?:(\d{1,2})/)?(\d{1,2})\([^)]+\)', text)
        if m:
            try:
                mth = int(m.group(1)) if m.group(1) else fallback_month
                day = int(m.group(2))
                return date(year, mth, day)
            except ValueError:
                return None

        # 3月29日(日)
        m = re.search(r'(\d{1,2})月(\d{1,2})日', text)
        if m:
            try:
                return date(year, int(m.group(1)), int(m.group(2)))
            except ValueError:
                return None

        return None

    # 現在のnetkeibaスケジュールは table.race_table_01 の tr.schedule_list* 形式
    row_items = soup.select('table.race_table_01 tr[class^="schedule_list"]')
    if not row_items:
        # フォールバック（旧DOM互換）
        row_items = soup.select('tr[class^="schedule_list"], li.RaceList_DataItem, tr.RaceList_DataItem, div.RaceList_Item')

    current_date: date | None = None
    seen_keys: set[str] = set()

    for item in row_items:
        text = item.get_text(" ", strip=True)
        if not text:
            continue

        tds = item.find_all('td')

        # 日付（行先頭の "03/29(日)" 優先）
        row_date = None
        if tds:
            row_date = _parse_date_from_text(tds[0].get_text(" ", strip=True), month)
        if not row_date:
            row_date = _parse_date_from_text(text, month)
        if row_date:
            current_date = row_date

        # グレード判定（専用列優先）
        grade_text = tds[2].get_text(" ", strip=True) if len(tds) >= 3 else ""
        grade_source = f"{grade_text} {text}"
        grade = None
        if re.search(r'\b(?:J)?G1\b|GⅠ|JGⅠ', grade_source):
            grade = 'G1'
        elif re.search(r'\b(?:J)?G2\b|GⅡ|JGⅡ', grade_source):
            grade = 'G2'
        elif re.search(r'\b(?:J)?G3\b|GⅢ|JGⅢ', grade_source):
            grade = 'G3'
        if not grade:
            continue

        # レース名
        race_name_tag = None
        if len(tds) >= 2:
            race_name_tag = tds[1].find('a')
        if not race_name_tag:
            race_name_tag = item.find('a') or item.find(class_='RaceName') or item.find(class_='Race_Name')
        if not race_name_tag:
            continue

        race_name = race_name_tag.get_text(strip=True)
        race_name = re.sub(r'\s*[（(]?(?:J)?G[ⅠⅡⅢ123][)）]?\s*', '', race_name).strip()
        if not race_name:
            continue

        # special_url
        link = race_name_tag.get('href', '') if race_name_tag.name == 'a' else ''
        if not link:
            a_tag = item.find('a', href=True)
            link = a_tag['href'] if a_tag else ''
        special_url = _normalize_special_url(link)

        # 会場・距離・馬場
        venue = tds[3].get_text(strip=True) if len(tds) >= 4 else ''
        surface_distance_text = tds[4].get_text(strip=True) if len(tds) >= 5 else text

        distance = ''
        surface = ''

        dist_m = re.search(r'(\d{3,4})m', surface_distance_text)
        if not dist_m:
            dist_m = re.search(r'(\d{3,4})m', text)
        if dist_m:
            distance = f"{dist_m.group(1)}m"

        if '芝' in surface_distance_text:
            surface = '芝'
        elif 'ダート' in surface_distance_text or re.search(r'^ダ\d{3,4}m', surface_distance_text):
            surface = 'ダート'
        elif '障' in surface_distance_text:
            surface = '障害'
        elif '芝' in text:
            surface = '芝'
        elif 'ダート' in text:
            surface = 'ダート'

        if not venue:
            venue_m = re.search(r'(東京|中山|阪神|京都|中京|小倉|新潟|福島|札幌|函館)', text)
            if venue_m:
                venue = venue_m.group(1)

        # 日付が取れない行を月初で埋めると、全レースが 03/01 のように壊れて見える。
        # 日付不明行は表示しないほうが安全。
        race_date = row_date or current_date
        if not race_date:
            continue
        date_str = _format_date_with_weekday(race_date)
        race_key = f"{race_date.isoformat()}_{venue}_{race_name}"

        if race_key in seen_keys:
            continue
        seen_keys.add(race_key)

        races.append(RaceInfo(
            race_name=race_name,
            grade=grade,
            date_str=date_str,
            date=race_date,
            venue=venue,
            distance=distance,
            surface=surface,
            race_id=None,
            race_key=race_key,
            special_url=special_url,
        ))

    return races


@lru_cache(maxsize=48)
def _fetch_graded_races_cached(year: int, month: int, cache_version: str) -> tuple[RaceInfo, ...]:
    """fetch_graded_races の内部キャッシュ実体。"""
    url = f"https://race.netkeiba.com/top/schedule.html?year={year}&month={month}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.encoding = 'EUC-JP'
        if resp.status_code != 200:
            return tuple()
        return tuple(_parse_schedule_page(resp.text, year, month))
    except requests.exceptions.RequestException:
        return tuple()


def fetch_graded_races(year: int, month: int) -> list[RaceInfo]:
    """
    netkeiba.com のスケジュールページから指定年月の重賞一覧を取得する。

    失敗時は空リストを返す。
    """
    # キャッシュオブジェクトをそのまま返すと呼び出し側で改変されるため copy を返す
    return [replace(race) for race in _fetch_graded_races_cached(year, month, _SCHEDULE_CACHE_VERSION)]


def clear_fetch_graded_races_cache() -> None:
    """fetch_graded_races の内部キャッシュをクリアする。"""
    _fetch_graded_races_cached.cache_clear()


def _resolve_race_id_from_special_url(special_url: str) -> str | None:
    """特別レースページから race_id を解決する（非キャッシュ）。"""
    try:
        normalized_url = _normalize_special_url(special_url)
        if not normalized_url:
            return None

        resp = requests.get(normalized_url, headers=_HEADERS, timeout=10)
        resp.encoding = 'EUC-JP'
        if resp.status_code != 200:
            return None

        # shutuba.html?race_id=XXXX のリンクを探す
        soup = BeautifulSoup(resp.text, 'html.parser')
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            m = re.search(r'race_id=(\d{12})', href)
            if m:
                return m.group(1)

        # race_list.html や result ページからも探す
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            m = re.search(r'/race/(?:shutuba|result)\.html\?race_id=(\d+)', href)
            if m:
                return m.group(1)

        return None
    except (requests.exceptions.RequestException, ValueError):
        return None


@lru_cache(maxsize=512)
def _resolve_race_id_cached(race_key: str, special_url: str) -> str | None:
    """resolve_race_id 用の内部キャッシュ。"""
    return _resolve_race_id_from_special_url(special_url)


def resolve_race_id(race: RaceInfo) -> str | None:
    """
    特別レースページから race_id を解決する。

    出馬表が未公開の場合は None を返す。
    """
    if race.race_id:
        return race.race_id

    if not race.special_url:
        return None

    return _resolve_race_id_cached(race.race_key, race.special_url)


def clear_resolve_race_id_cache() -> None:
    """resolve_race_id の内部キャッシュをクリアする。"""
    _resolve_race_id_cached.cache_clear()


def get_upcoming_races(
    months_ahead: int = 2,
    from_date: date | None = None,
    days_ahead: int | None = 14,
) -> list[RaceInfo]:
    """
    当日以降の重賞レースを取得し、日付順で返す。

    - from_date: 取得開始日（省略時は今日）
    - days_ahead: 取得終了日の相対日数（None なら上限なし）
    - months_ahead: 取得対象月の最小範囲（後方互換用途）
    """
    start_date = from_date or date.today()
    end_date = (start_date + timedelta(days=days_ahead)) if days_ahead is not None else None
    all_races: list[RaceInfo] = []
    seen_keys: set[str] = set()

    required_months = 0
    if end_date is not None:
        required_months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
        if required_months < 0:
            required_months = 0

    months_to_fetch = max(months_ahead, required_months)

    for offset in range(months_to_fetch + 1):
        m = start_date.month + offset
        y = start_date.year
        while m > 12:
            m -= 12
            y += 1
        fetched = fetch_graded_races(y, m)
        for race in fetched:
            if race.date < start_date:
                continue
            if end_date is not None and race.date > end_date:
                continue
            if race.race_key not in seen_keys:
                seen_keys.add(race.race_key)
                all_races.append(race)

    all_races.sort(key=lambda r: r.date)
    return all_races


def ensure_data_dir():
    """data/ ディレクトリが存在しなければ作成する。"""
    os.makedirs("data", exist_ok=True)
