"""
netkeiba から出馬表CSVと近3走データを取得するユーティリティ。

主用途:
- fetch_race_csv: race/shutuba.html から出馬表をCSV保存
- fetch_recent_runs: race/shutuba_past.html から馬ごとの近3走を取得
  - 主経路: shutuba_past.html（1リクエスト）
  - 副経路: shutuba.html -> horse_id -> db.netkeiba.com/horse/result/{id}/
"""

from __future__ import annotations

import argparse
import os
import re
import time
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

DEFAULT_RACE_ID = "202605010811"
DEFAULT_OUTPUT_FILE = "february_s_info.csv"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
_TRACK_CONDITIONS = {"良", "稍重", "重", "不良", "稍"}


def _request_soup(url: str, *, timeout: int = 12) -> BeautifulSoup | None:
    try:
        response = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.exceptions.RequestException:
        return None
    if response.status_code != 200:
        return None
    if not response.encoding or response.encoding.lower() in {"", "iso-8859-1", "ascii"}:
        response.encoding = response.apparent_encoding or "utf-8"
    return BeautifulSoup(response.text, "html.parser")


def get_race_info(url: str) -> BeautifulSoup | None:
    return _request_soup(url)


def _find_td_by_class_prefix(row, prefix: str):
    for td in row.find_all("td"):
        classes = td.get("class") or []
        if any(str(c).startswith(prefix) for c in classes):
            return td
    return None


def _cell_text(cells, index: int) -> str:
    if index < 0 or index >= len(cells):
        return ""
    return cells[index].get_text(" ", strip=True)


def _split_body_weight(text: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", "", str(text or ""))
    if not normalized or normalized in {"--", "---", "計不"}:
        return "", ""
    match = re.match(r"(?P<weight>\d{3})(?:\((?P<delta>[+-]?\d+)\))?", normalized)
    if not match:
        return normalized, ""
    weight = match.group("weight") or ""
    delta = match.group("delta") or ""
    if delta and not delta.startswith(("+", "-")):
        delta = f"+{delta}"
    return weight, delta


def parse_shutuba_table(soup: BeautifulSoup | None) -> list[dict[str, str]]:
    if soup is None:
        return []

    shutuba_table = soup.find("table", class_="Shutuba_Table")
    if not shutuba_table:
        return []

    horses_data: list[dict[str, str]] = []
    rows = shutuba_table.find_all("tr")
    for row in rows:
        horse_name_tag = row.find("td", class_="HorseInfo")
        if not horse_name_tag:
            continue

        horse_link = horse_name_tag.find("a")
        if not horse_link:
            continue
        horse_name = horse_link.get_text(strip=True)
        if not horse_name:
            continue

        cells = row.find_all("td")
        waku_tag = _find_td_by_class_prefix(row, "Waku")
        umaban_tag = _find_td_by_class_prefix(row, "Umaban")
        barei_tag = row.find("td", class_="Barei")
        body_weight_tag = row.find("td", class_="Weight")
        jockey_tag = row.find("td", class_="Jockey")
        trainer_tag = row.find("td", class_="Trainer")
        odds_tag = row.find("td", class_="Popular")
        body_weight, body_delta = _split_body_weight(
            body_weight_tag.get_text(" ", strip=True) if body_weight_tag else ""
        )

        jockey = ""
        if jockey_tag:
            jockey_link = jockey_tag.find("a")
            jockey = jockey_link.get_text(strip=True) if jockey_link else jockey_tag.get_text(" ", strip=True)

        trainer = ""
        if trainer_tag:
            trainer_link = trainer_tag.find("a")
            trainer = trainer_link.get_text(strip=True) if trainer_link else trainer_tag.get_text(" ", strip=True)

        horse_data = {
            "枠番": (waku_tag.get_text(strip=True) if waku_tag else ""),
            "馬番": (umaban_tag.get_text(strip=True) if umaban_tag else ""),
            "馬名": horse_name,
            "性齢": (barei_tag.get_text(strip=True) if barei_tag else ""),
            "斤量": _cell_text(cells, 5),
            "騎手": jockey,
            "調教師": trainer,
            "馬体重": body_weight,
            "増減": body_delta,
            "オッズ": (odds_tag.get_text(strip=True) if odds_tag else "---.-"),
        }
        horses_data.append(horse_data)

    return horses_data


def save_to_csv(data: list[dict[str, Any]], filename: str) -> None:
    if not data:
        return

    parent = os.path.dirname(filename)
    if parent:
        os.makedirs(parent, exist_ok=True)

    df = pd.DataFrame(data)
    df.to_csv(filename, index=False, encoding="utf-8-sig")


def fetch_race_csv(race_id: str, output_file: str) -> str:
    race_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    soup = get_race_info(race_url)
    if soup is None:
        raise RuntimeError(
            f"レース情報の取得に失敗しました (race_id={race_id})。"
            "ネットワークまたはレースIDを確認してください。"
        )

    time.sleep(1)
    horses_data = parse_shutuba_table(soup)
    if not horses_data:
        raise RuntimeError(
            f"出馬表データが見つかりませんでした (race_id={race_id})。"
            "出馬表が未公開の可能性があります。"
        )

    save_to_csv(horses_data, output_file)
    return output_file


def fetch_race_metadata(race_id: str) -> dict[str, Any]:
    """race/shutuba.html から発走時刻・天候・馬場状態などの軽量メタ情報を取得する。"""
    if not race_id:
        return {}
    race_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    soup = get_race_info(race_url)
    if soup is None:
        return {}

    data01 = soup.select_one(".RaceData01")
    data02 = soup.select_one(".RaceData02")
    raw01 = re.sub(r"\s+", " ", data01.get_text(" ", strip=True)).strip() if data01 else ""
    raw02 = re.sub(r"\s+", " ", data02.get_text(" ", strip=True)).strip() if data02 else ""
    normalized = raw01.replace("\xa0", " ")

    start_time = ""
    m_start = re.search(r"(\d{1,2}:\d{2})\s*発走", normalized)
    if m_start:
        start_time = m_start.group(1)

    weather = ""
    m_weather = re.search(r"天候\s*[:：]\s*([^\s/]+)", normalized)
    if m_weather:
        weather = m_weather.group(1)

    track_conditions: dict[str, str] = {}
    for surface, condition in re.findall(r"(芝|ダート|ダ|障害|障)\s*[:：]\s*([^\s/]+)", normalized):
        key = "ダート" if surface == "ダ" else ("障害" if surface == "障" else surface)
        track_conditions[key] = condition
    if not track_conditions:
        generic_condition = re.search(r"馬場\s*[:：]\s*([^\s/]+)", normalized)
        if generic_condition:
            if "芝" in normalized:
                track_conditions["芝"] = generic_condition.group(1)
            elif "ダート" in normalized or "ダ" in normalized:
                track_conditions["ダート"] = generic_condition.group(1)

    return {
        "start_time": start_time,
        "weather": weather,
        "track_conditions": track_conditions,
        "race_data01": raw01,
        "race_data02": raw02,
    }


def _parse_past_run_cell(cell_text: str) -> str:
    text = re.sub(r"\s+", " ", str(cell_text or "").replace("\xa0", " ")).strip()
    if not text:
        return ""

    date_match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", text)
    if not date_match:
        return ""

    yy = date_match.group(1)[2:]
    mm = date_match.group(2)
    dd = date_match.group(3)

    tail = text[date_match.end():].strip()
    tokens = tail.split()
    if len(tokens) < 3:
        return f"{yy}/{mm}/{dd} - {tail[:40]}".strip()

    rank = tokens[1] if tokens[1].isdigit() else "-"
    surface_idx = -1
    for idx, token in enumerate(tokens):
        if re.match(r"^(芝|ダ|障)\d{3,4}$", token):
            surface_idx = idx
            break

    if surface_idx <= 2:
        race_name = " ".join(tokens[2:5]).strip() or "レース"
        course = ""
    else:
        race_name = " ".join(tokens[2:surface_idx]).strip()
        course = tokens[surface_idx]

    track = ""
    if surface_idx >= 0 and (surface_idx + 2) < len(tokens) and tokens[surface_idx + 2] in _TRACK_CONDITIONS:
        track = tokens[surface_idx + 2]

    course_info = f"{course}/{track}" if (course and track) else course
    if course_info:
        return f"{yy}/{mm}/{dd} {rank} {race_name} {course_info}".strip()
    return f"{yy}/{mm}/{dd} {rank} {race_name}".strip()


def _extract_corner_positions(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or ""))
    match = re.search(r"(?<![\d.])(\d{1,2}(?:-\d{1,2}){1,3})(?![-\d])", normalized)
    return match.group(1) if match else ""


def _extract_field_size(text: str) -> str:
    match = re.search(r"(\d{1,2})\s*頭", str(text or ""))
    return match.group(1) if match else ""


def _extract_last3f(text: str) -> str:
    normalized = str(text or "")
    matches = re.findall(r"\((\d{2}\.\d)\)", normalized)
    return matches[0] if matches else ""


def _extract_horse_ids_from_shutuba(soup: BeautifulSoup | None) -> dict[str, str]:
    if soup is None:
        return {}
    table = soup.find("table", class_="Shutuba_Table")
    if not table:
        return {}

    horse_ids: dict[str, str] = {}
    for row in table.find_all("tr"):
        horse_cell = row.find("td", class_="HorseInfo") or row.find("td", class_="Horse_Info")
        if not horse_cell:
            continue
        a_tag = horse_cell.find("a", href=lambda href: href and "/horse/" in href)
        if not a_tag:
            continue
        horse_name = re.sub(r"\s+", " ", a_tag.get_text(" ", strip=True)).strip()
        m = re.search(r"/horse/(\d+)", a_tag.get("href", ""))
        if horse_name and m:
            horse_ids[horse_name] = m.group(1)
    return horse_ids


def _fetch_recent_runs_from_shutuba_past(race_id: str, max_runs: int = 3) -> dict[str, dict[str, str]]:
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
    soup = _request_soup(url)
    if soup is None:
        return {}

    table = soup.find("table", class_="Shutuba_Table")
    if not table:
        return {}

    result: dict[str, dict[str, str]] = {}
    rows = table.select("tbody tr") or table.find_all("tr")
    for row in rows:
        horse_cell = row.find("td", class_="HorseInfo") or row.find("td", class_="Horse_Info")
        if not horse_cell:
            continue
        horse_link = horse_cell.find("a", href=lambda href: href and "/horse/" in href) or horse_cell.find("a")
        horse_name = horse_link.get_text(strip=True) if horse_link else horse_cell.get_text(" ", strip=True)
        horse_name = re.sub(r"\s+", " ", str(horse_name or "")).strip()
        if not horse_name:
            continue
        horse_id_match = re.search(r"/horse/(\d+)", horse_link.get("href", "") if horse_link else "")
        horse_id = horse_id_match.group(1) if horse_id_match else ""

        cells = row.find_all("td")
        run_values: list[str] = []
        corner_values: list[str] = []
        last3f_values: list[str] = []
        field_size_values: list[str] = []
        for cell in cells[5:]:
            cell_text = cell.get_text(" ", strip=True)
            parsed = _parse_past_run_cell(cell_text)
            if parsed:
                run_values.append(parsed)
                corner_values.append(_extract_corner_positions(cell_text))
                last3f_values.append(_extract_last3f(cell_text))
                field_size_values.append(_extract_field_size(cell_text))
            if len(run_values) >= max_runs:
                break

        while len(run_values) < max_runs:
            run_values.append("")
        while len(corner_values) < max_runs:
            corner_values.append("")
        while len(last3f_values) < max_runs:
            last3f_values.append("")
        while len(field_size_values) < max_runs:
            field_size_values.append("")

        result[horse_name] = {
            "前走": run_values[0],
            "2走前": run_values[1],
            "3走前": run_values[2],
            "前走上り": last3f_values[0],
            "2走前上り": last3f_values[1],
            "3走前上り": last3f_values[2],
            "corners": corner_values[:max_runs],
            "last3fs": last3f_values[:max_runs],
            "field_sizes": field_size_values[:max_runs],
            "horse_id": horse_id,
        }

    return result


def _fetch_horse_recent_runs(horse_id: str, max_runs: int = 3) -> list[dict[str, str]]:
    if not horse_id:
        return []
    url = f"https://db.netkeiba.com/horse/result/{horse_id}/"
    soup = _request_soup(url)
    if soup is None:
        return []

    table = soup.select_one("table.db_h_race_results")
    if not table:
        return []

    results: list[dict[str, str]] = []
    for row in table.select("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 17:
            continue

        date_text = re.sub(r"\s+", "", cells[0].get_text(" ", strip=True))
        m_date = re.match(r"(\d{4})/(\d{2})/(\d{2})", date_text)
        if not m_date:
            continue
        yy = m_date.group(1)[2:]
        mm = m_date.group(2)
        dd = m_date.group(3)

        race_name = re.sub(r"\s+", " ", cells[4].get_text(" ", strip=True)).strip()
        rank = re.sub(r"\s+", "", cells[11].get_text(" ", strip=True))
        course = re.sub(r"\s+", "", cells[14].get_text(" ", strip=True))
        track = re.sub(r"\s+", "", cells[16].get_text(" ", strip=True))
        course_info = f"{course}/{track}" if (course and track in _TRACK_CONDITIONS) else course

        rank = rank if rank.isdigit() else "-"
        item = f"{yy}/{mm}/{dd} {rank} {race_name} {course_info}".strip()
        row_text = " ".join(td.get_text(" ", strip=True) for td in cells)
        corner_text = re.sub(r"\s+", "", cells[25].get_text(" ", strip=True)) if len(cells) > 25 else ""
        last3f_text = re.sub(r"\s+", "", cells[27].get_text(" ", strip=True)) if len(cells) > 27 else ""
        results.append(
            {
                "run": item,
                "corner": _extract_corner_positions(corner_text),
                "last3f": last3f_text,
                "field_size": _extract_field_size(row_text),
            }
        )
        if len(results) >= max_runs:
            break

    return results


def _fetch_recent_runs_via_horse_pages(race_id: str, max_runs: int = 3) -> dict[str, dict[str, str]]:
    shutuba_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    shutuba_soup = _request_soup(shutuba_url)
    horse_ids = _extract_horse_ids_from_shutuba(shutuba_soup)
    if not horse_ids:
        return {}

    result: dict[str, dict[str, str]] = {}
    for horse_name, horse_id in horse_ids.items():
        runs = _fetch_horse_recent_runs(horse_id, max_runs=max_runs)
        run_values = [
            re.sub(r"\s+", " ", str(item.get("run", ""))).strip() if isinstance(item, dict) else ""
            for item in runs
        ]
        corner_values = [
            re.sub(r"\s+", "", str(item.get("corner", ""))).strip() if isinstance(item, dict) else ""
            for item in runs
        ]
        last3f_values = [
            re.sub(r"\s+", "", str(item.get("last3f", ""))).strip() if isinstance(item, dict) else ""
            for item in runs
        ]
        field_size_values = [
            re.sub(r"\s+", "", str(item.get("field_size", ""))).strip() if isinstance(item, dict) else ""
            for item in runs
        ]
        while len(run_values) < max_runs:
            run_values.append("")
        while len(corner_values) < max_runs:
            corner_values.append("")
        while len(last3f_values) < max_runs:
            last3f_values.append("")
        while len(field_size_values) < max_runs:
            field_size_values.append("")
        result[horse_name] = {
            "前走": run_values[0],
            "2走前": run_values[1],
            "3走前": run_values[2],
            "前走上り": last3f_values[0],
            "2走前上り": last3f_values[1],
            "3走前上り": last3f_values[2],
            "corners": corner_values[:max_runs],
            "last3fs": last3f_values[:max_runs],
            "field_sizes": field_size_values[:max_runs],
            "horse_id": horse_id,
        }
    return result


def fetch_recent_runs(race_id: str, max_runs: int = 3) -> dict[str, dict[str, str]]:
    """
    馬ごとの直近成績（前走/2走前/3走前）を返す。

    返り値:
    {
      "馬名": {"前走": "...", "2走前": "...", "3走前": "..."},
      ...
    }

    仕様:
    - 主経路: shutuba_past.html
    - 失敗時: horse/result フォールバック
    - 新馬戦などで成績が無い場合は空文字を返す（例外は送出しない）
    """
    if not race_id:
        return {}

    try:
        primary = _fetch_recent_runs_from_shutuba_past(race_id, max_runs=max_runs)
        if primary:
            return primary
    except Exception:
        pass

    try:
        fallback = _fetch_recent_runs_via_horse_pages(race_id, max_runs=max_runs)
        if fallback:
            return fallback
    except Exception:
        pass

    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="netkeiba.com から出馬表を取得してCSV保存")
    parser.add_argument("--race-id", default=DEFAULT_RACE_ID, help=f"レースID (default: {DEFAULT_RACE_ID})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help=f"出力CSV (default: {DEFAULT_OUTPUT_FILE})")
    args = parser.parse_args()

    print("=" * 60)
    print("競馬レース 出馬表取得ツール")
    print(f"  レースID: {args.race_id}")
    print(f"  出力先:   {args.output}")
    print("=" * 60)

    try:
        fetch_race_csv(args.race_id, args.output)
    except RuntimeError as e:
        print(f"[NG] {e}")
        return

    print("[OK] 出力完了")


if __name__ == "__main__":
    main()
