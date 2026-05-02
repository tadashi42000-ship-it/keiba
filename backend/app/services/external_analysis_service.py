from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

from app.clients import (
    SearchDocument,
    TextAnalysisClient,
    WebSearchClient,
    XClient,
    XTweet,
    YouTubeClient,
    YouTubeVideo,
)

ROOT_DIR = Path(__file__).resolve().parents[3]
X_TOPIC_EXPR = "(\u7af6\u99ac OR \u4e88\u60f3 OR \u672c\u547d OR \u5370 OR \u8abf\u6559 OR \u8ffd\u3044\u5207\u308a OR \u8ffd\u5207)"


class ExternalAnalysisService:
    def __init__(
        self,
        *,
        web_search_client: WebSearchClient,
        text_analysis_client: TextAnalysisClient,
        youtube_client: YouTubeClient,
        x_client: XClient,
        x_accounts_path: str,
    ) -> None:
        self._web_search = web_search_client
        self._text = text_analysis_client
        self._youtube = youtube_client
        self._x = x_client
        self._x_accounts_path = (x_accounts_path or "").strip()

    def provider_status(self) -> dict:
        accounts, default_max_tweets = self.load_x_accounts()
        return {
            "tavily": {"configured": self._web_search.is_configured},
            "gemini": {"configured": self._text.is_configured},
            "youtube": {"configured": self._youtube.is_configured},
            "x": {
                "configured": self._x.is_configured,
                "accounts_count": len(accounts),
                "default_max_tweets": default_max_tweets,
            },
        }

    def web_summary(
        self,
        *,
        query: str,
        max_results: int = 5,
        include_domains: list[str] | None = None,
    ) -> dict:
        docs = self._web_search.search(
            query=query,
            max_results=max_results,
            include_domains=include_domains,
        )
        if not docs:
            return {
                "query": query,
                "summary": "No search results were found.",
                "sources": [],
            }

        prompt = _build_web_summary_prompt(query=query, docs=docs)
        summary = self._text.generate_text(
            prompt=prompt,
            system_prompt=(
                "You are a horse-racing information assistant. "
                "Summarize only from the provided sources."
            ),
        )
        return {
            "query": query,
            "summary": summary.strip(),
            "sources": [
                {
                    "title": d.title,
                    "url": d.url,
                    "score": d.score,
                    "published_date": d.published_date,
                }
                for d in docs
            ],
        }

    def youtube_search(
        self,
        *,
        query: str,
        max_results: int = 5,
        race_name: str = "",
    ) -> dict:
        search_pool_size = max(max_results, min(25, max_results * 3))
        query_candidates = _build_youtube_query_candidates(query=query, race_name=race_name)
        merged_videos: list[YouTubeVideo] = []
        seen_video_ids: set[str] = set()
        total_fetched = 0
        for candidate_query in query_candidates:
            videos = self._youtube.search_videos(query=candidate_query, max_results=search_pool_size)
            total_fetched += len(videos)
            for video in videos:
                if video.video_id in seen_video_ids:
                    continue
                seen_video_ids.add(video.video_id)
                merged_videos.append(video)
            # enough candidates collected, no need to continue API calls
            provisional = _filter_relevant_videos(merged_videos, race_name=race_name, query=query)
            if len(provisional) >= max_results:
                break

        filtered = _filter_relevant_videos(merged_videos, race_name=race_name, query=query)
        selected = filtered[: max(1, min(max_results, 10))]
        return {
            "query": query,
            "race_name": race_name,
            "videos": [_youtube_video_to_dict(v) for v in selected],
            "total_fetched": total_fetched,
            "total_after_filter": len(filtered),
        }

    def youtube_summary(
        self,
        *,
        query: str,
        max_results: int = 5,
        race_name: str = "",
    ) -> dict:
        result = self.youtube_search(query=query, max_results=max_results, race_name=race_name)
        videos = result["videos"]
        if not videos:
            result["summary"] = "No relevant videos were found."
            return result

        prompt = _build_youtube_summary_prompt(query=query, race_name=race_name, videos=videos)
        summary = self._text.generate_text(
            prompt=prompt,
            system_prompt=(
                "You summarize horse-racing YouTube metadata. "
                "Use title/description only and avoid over-claiming."
            ),
        )
        result["summary"] = summary.strip()
        return result

    def youtube_horse_analysis(
        self,
        *,
        query: str,
        race_name: str,
        horse_names: list[str] | None = None,
        max_results: int = 5,
    ) -> dict:
        result = self.youtube_search(query=query, max_results=max_results, race_name=race_name)
        videos = result["videos"]
        if not videos:
            result["analysis_items"] = []
            result["video_conclusions"] = []
            result["warnings"] = []
            return result

        normalized_horses = _normalize_horse_names(horse_names or [])
        analysis_items: list[dict] = []
        conclusions: list[dict] = []
        warnings: list[str] = []

        for video in videos:
            prompt = _build_youtube_horse_prompt(
                race_name=race_name,
                video=video,
                horse_names=normalized_horses,
            )
            text = self._text.generate_text(
                prompt=prompt,
                system_prompt=(
                    "You are a horse-racing analyst. "
                    "Return strict JSON only. No markdown."
                ),
            )
            try:
                parsed = _parse_json_response(text, expected="dict")
            except ValueError as exc:
                warnings.append(f"youtube parse error ({video.get('video_id', '')}): {exc}")
                continue

            raw_conclusion = parsed.get("conclusion", parsed if isinstance(parsed, dict) else {})
            conclusion = _normalize_video_conclusion(raw_conclusion)
            if conclusion:
                conclusion["video_id"] = video.get("video_id", "")
                conclusion["video_title"] = video.get("title", "")
                conclusion["video_url"] = video.get("video_url", "")
                conclusions.append(conclusion)

            raw_items = parsed.get("horse_analysis", [])
            if not isinstance(raw_items, list) and isinstance(parsed, dict):
                raw_items = parsed.get("horses", [])
            if not isinstance(raw_items, list) and isinstance(parsed, dict):
                raw_items = [parsed]

            for row in raw_items:
                item = _normalize_horse_item(
                    row,
                    source_type="youtube",
                    source_title=video.get("title", ""),
                    source_url=video.get("video_url", ""),
                )
                if item:
                    analysis_items.append(item)

        result["analysis_items"] = analysis_items
        result["video_conclusions"] = conclusions
        result["warnings"] = warnings
        return result

    def load_x_accounts(self) -> tuple[list[dict[str, str]], int]:
        candidates = _candidate_x_accounts_paths(self._x_accounts_path)
        for path in candidates:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            raw_accounts = data.get("accounts", []) if isinstance(data, dict) else []
            default_max_tweets = _coerce_int(data.get("default_max_tweets"), 30) if isinstance(data, dict) else 30
            accounts: list[dict[str, str]] = []
            if isinstance(raw_accounts, list):
                for item in raw_accounts:
                    if not isinstance(item, dict):
                        continue
                    username = str(item.get("username") or "").strip().lstrip("@")
                    if not username:
                        continue
                    label = str(item.get("label") or username).strip()
                    accounts.append({"username": username, "label": label})
            if accounts:
                return accounts, max(5, min(default_max_tweets, 100))
            return [], max(5, min(default_max_tweets, 100))
        return [], 30

    def x_search(
        self,
        *,
        race_name: str,
        max_tweets: int = 30,
        since_id: str | None = None,
    ) -> dict:
        accounts, default_max_tweets = self.load_x_accounts()
        limit = max(5, min(int(max_tweets), 100))
        if not accounts:
            return {
                "race_name": race_name,
                "tweets": [],
                "newest_id": None,
                "dropped_count": 0,
                "used_queries": [],
                "accounts_count": 0,
                "default_max_tweets": default_max_tweets,
            }

        all_tweets: list[XTweet] = []
        seen_ids: set[str] = set()
        newest_id: str | None = None
        used_queries: list[str] = []

        for include_lang_ja in (True, False):
            queries = _build_x_queries(
                race_name=race_name,
                accounts=accounts,
                include_lang_ja=include_lang_ja,
            )
            for query in queries:
                if len(all_tweets) >= limit:
                    break
                used_queries.append(query)
                next_token: str | None = None
                while len(all_tweets) < limit:
                    batch_size = max(10, min(100, limit - len(all_tweets)))
                    payload = self._x.search_recent(
                        query=query,
                        max_results=batch_size,
                        since_id=since_id,
                        next_token=next_token,
                    )
                    users_map = _build_x_user_map(payload)
                    rows = payload.get("data", []) if isinstance(payload, dict) else []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        tweet_id = str(row.get("id") or "").strip()
                        if not tweet_id or tweet_id in seen_ids:
                            continue
                        seen_ids.add(tweet_id)
                        username = users_map.get(str(row.get("author_id") or ""), "")
                        x_tweet = XTweet(
                            tweet_id=tweet_id,
                            text=str(row.get("text") or "").strip(),
                            author_username=username,
                            author_label=_label_for_username(accounts, username),
                            created_at=str(row.get("created_at") or "").strip(),
                            url=f"https://x.com/{username}/status/{tweet_id}" if username else "",
                            public_metrics=row.get("public_metrics", {}) if isinstance(row.get("public_metrics"), dict) else {},
                        )
                        all_tweets.append(x_tweet)
                        if _is_newer_tweet_id(tweet_id, newest_id):
                            newest_id = tweet_id
                        if len(all_tweets) >= limit:
                            break
                    meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
                    next_token = str(meta.get("next_token") or "").strip() or None
                    if not next_token or len(all_tweets) >= limit:
                        break
            if all_tweets:
                break

        filtered, dropped_count = _filter_tweets_by_race_name(all_tweets, race_name)
        filtered = filtered[:limit]
        return {
            "race_name": race_name,
            "tweets": [_x_tweet_to_dict(t) for t in filtered],
            "newest_id": newest_id,
            "dropped_count": dropped_count,
            "used_queries": used_queries,
            "accounts_count": len(accounts),
            "default_max_tweets": default_max_tweets,
        }

    def x_summary(
        self,
        *,
        race_name: str,
        max_tweets: int = 30,
        since_id: str | None = None,
    ) -> dict:
        result = self.x_search(race_name=race_name, max_tweets=max_tweets, since_id=since_id)
        tweets = result["tweets"]
        if not tweets:
            result["summary"] = "No tweets matched the selected race."
            return result

        prompt = _build_x_summary_prompt(race_name=race_name, tweets=tweets)
        summary = self._text.generate_text(
            prompt=prompt,
            system_prompt=(
                "You summarize horse-racing social posts. "
                "Keep it concise and avoid speculation."
            ),
        )
        result["summary"] = summary.strip()
        return result

    def x_horse_analysis(
        self,
        *,
        race_name: str,
        horse_names: list[str] | None = None,
        max_tweets: int = 30,
        since_id: str | None = None,
    ) -> dict:
        result = self.x_search(race_name=race_name, max_tweets=max_tweets, since_id=since_id)
        tweets = result["tweets"]
        if not tweets:
            result["analysis_items"] = []
            result["warnings"] = []
            return result

        normalized_horses = _normalize_horse_names(horse_names or [])
        prompt = _build_x_horse_prompt(
            race_name=race_name,
            tweets=tweets,
            horse_names=normalized_horses,
        )
        text = self._text.generate_text(
            prompt=prompt,
            system_prompt="Return strict JSON only. No markdown.",
        )
        warnings: list[str] = []
        try:
            parsed = _parse_json_response(text, expected="list")
        except ValueError as exc:
            result["analysis_items"] = []
            result["warnings"] = [f"x parse error: {exc}"]
            return result

        analysis_items: list[dict] = []
        for row in parsed:
            item = _normalize_horse_item(
                row,
                source_type="x",
                source_title="X search",
                source_url="",
            )
            if not item:
                continue
            indices = row.get("source_index", []) if isinstance(row, dict) else []
            if isinstance(indices, list) and indices:
                first = _coerce_int(indices[0], 0) - 1
                if 0 <= first < len(tweets):
                    item["source_url"] = tweets[first].get("url", "")
                    item["source_title"] = f"X @{tweets[first].get('author_username', '')}"
            analysis_items.append(item)

        result["analysis_items"] = analysis_items
        result["warnings"] = warnings
        return result


def _build_web_summary_prompt(*, query: str, docs: list[SearchDocument]) -> str:
    lines = [
        f"Query: {query}",
        "",
        "Summarize these web search results.",
        "- Max 5 bullet lines",
        "- Mention key points",
        "- Add source URLs at the end",
        "",
        "Search results:",
    ]
    for idx, doc in enumerate(docs, start=1):
        lines.extend(
            [
                f"[{idx}] title: {doc.title}",
                f"[{idx}] url: {doc.url}",
                f"[{idx}] content: {doc.content[:1200]}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _build_youtube_summary_prompt(*, query: str, race_name: str, videos: list[dict[str, Any]]) -> str:
    lines = [
        f"Query: {query}",
        f"Race: {race_name or 'N/A'}",
        "",
        "Summarize these YouTube videos using title and description only.",
        "Return: overall summary, frequently mentioned horses, and main talking points.",
        "",
    ]
    for idx, item in enumerate(videos, start=1):
        lines.extend(
            [
                f"[{idx}] title: {item.get('title', '')}",
                f"[{idx}] channel: {item.get('channel_title', '')}",
                f"[{idx}] published_at: {item.get('published_at', '')}",
                f"[{idx}] description: {str(item.get('description', ''))[:800]}",
                f"[{idx}] url: {item.get('video_url', '')}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def _build_youtube_horse_prompt(
    *,
    race_name: str,
    video: dict[str, Any],
    horse_names: list[str],
) -> str:
    horse_block = "\n".join(f"- {name}" for name in horse_names[:30]) if horse_names else "- (unknown)"
    return (
        "Analyze one horse-racing YouTube video.\n"
        f"Race: {race_name}\n"
        f"Title: {video.get('title', '')}\n"
        f"Description: {str(video.get('description', ''))[:2500]}\n"
        f"Channel: {video.get('channel_title', '')}\n\n"
        "Target horses:\n"
        f"{horse_block}\n\n"
        "Return strict JSON only with this shape:\n"
        "{\n"
        '  "conclusion": {\n'
        '    "head_pick": "horse or unknown",\n'
        '    "second_pick": "horse or unknown",\n'
        '    "dark_horse": "horse or unknown",\n'
        '    "danger_horse": "horse or unknown",\n'
        '    "bet_strategy": "short sentence"\n'
        "  },\n"
        '  "horse_analysis": [\n'
        "    {\n"
        '      "horse": "horse name",\n'
        '      "plus": "positive points",\n'
        '      "minus": "negative points"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _build_x_summary_prompt(*, race_name: str, tweets: list[dict[str, Any]]) -> str:
    lines = [
        f"Race: {race_name}",
        "",
        "Summarize these X posts.",
        "- overall sentiment",
        "- frequently mentioned horses",
        "- training/workout mentions",
        "- risk points",
        "",
        "Posts:",
    ]
    for idx, tweet in enumerate(tweets, start=1):
        lines.append(
            f"[{idx}] @{tweet.get('author_username', '')} "
            f"({tweet.get('created_at', '')}): {tweet.get('text', '')}"
        )
    return "\n".join(lines).strip()


def _build_x_horse_prompt(*, race_name: str, tweets: list[dict[str, Any]], horse_names: list[str]) -> str:
    horse_block = "\n".join(f"- {name}" for name in horse_names[:40]) if horse_names else "- (unknown)"
    lines = [
        f"Race: {race_name}",
        "Target horses:",
        horse_block,
        "",
        "Posts:",
    ]
    for idx, tweet in enumerate(tweets, start=1):
        lines.append(f"[{idx}] @{tweet.get('author_username', '')}: {tweet.get('text', '')}")
    lines.extend(
        [
            "",
            "Return strict JSON array only:",
            "[",
            "  {",
            '    "horse": "horse name",',
            '    "plus": "positive points",',
            '    "minus": "negative points",',
            '    "source_index": [1, 3]',
            "  }",
            "]",
        ]
    )
    return "\n".join(lines)


def _build_youtube_query_candidates(*, query: str, race_name: str) -> list[str]:
    base_query = str(query or "").strip()
    race = str(race_name or "").strip()
    candidates: list[str] = []

    def _add(value: str) -> None:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or text in candidates:
            return
        candidates.append(text)

    _add(base_query)
    if race:
        if base_query and race not in base_query:
            _add(f"{race} 競馬 {base_query}")
        _add(f"{race} 競馬 予想")
        _add(f"{race} 予想")

    if not candidates:
        _add("競馬 予想")
    return candidates[:4]


def _filter_relevant_videos(videos: list[YouTubeVideo], *, race_name: str, query: str) -> list[YouTubeVideo]:
    if not videos:
        return []

    include_keywords = ["yosou", "\u4e88\u60f3", "\u672c\u547d", "\u5c55\u958b", "\u8abf\u6559", "\u8ffd\u5207"]
    exclude_keywords = ["\u516c\u5f0f", "\u30e9\u30a4\u30d6", "\u30cf\u30a4\u30e9\u30a4\u30c8", "results"]
    exclude_channel_tokens = ["jra", "netkeiba", "\u30b0\u30ea\u30fc\u30f3\u30c1\u30e3\u30f3\u30cd\u30eb"]
    strict_race = bool(str(race_name or "").strip())
    race_terms = _build_youtube_race_terms(race_name=race_name, query=query)

    scored: list[tuple[int, YouTubeVideo]] = []
    desc_only_candidates: list[tuple[int, YouTubeVideo]] = []
    for video in videos:
        title_raw = str(video.title or "")
        desc_raw = str(video.description or "")[:800]
        title = title_raw.lower()
        desc = desc_raw.lower()
        channel = (video.channel_title or "").lower()
        text = f"{title} {desc}"

        if any(token in channel for token in exclude_channel_tokens):
            continue

        title_has_target = any(_text_contains_term(title_raw, term) for term in race_terms)
        desc_has_target = any(_text_contains_term(desc_raw, term) for term in race_terms)
        text_has_target = title_has_target or desc_has_target

        if strict_race and not text_has_target:
            continue
        if strict_race and not title_has_target:
            if _title_has_non_target_race_mentions(title_raw, race_terms):
                continue
            if desc_has_target:
                desc_only_candidates.append((1, video))
            continue

        score = 0
        for kw in include_keywords:
            if _text_contains_term(text, kw):
                score += 2
        if title_has_target:
            score += 5
        if desc_has_target:
            score += 2
        for kw in exclude_keywords:
            if _text_contains_term(text, kw):
                score -= 3

        threshold = 3 if strict_race else 2
        if score >= threshold:
            scored.append((score, video))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return [v for _, v in scored]

    if strict_race and desc_only_candidates:
        desc_only_candidates.sort(key=lambda x: x[0], reverse=True)
        return [v for _, v in desc_only_candidates]

    if race_terms:
        relaxed = [
            v
            for v in videos
            if any(_text_contains_term(f"{v.title} {v.description}", term) for term in race_terms)
        ]
        if relaxed:
            return relaxed
    return [] if strict_race else videos


def _build_youtube_race_terms(*, race_name: str, query: str) -> list[str]:
    source = str(race_name or "").strip() or str(query or "").strip()
    if not source:
        return []
    normalized = unicodedata.normalize("NFKC", source)
    compact = re.sub(r"\s+", "", normalized)
    no_year = re.sub(r"(20\d{2}|\u4ee4\u548c\d+\u5e74?)", "", compact)
    no_round = re.sub(r"\u7b2c\d+\u56de", "", no_year)

    terms: list[str] = []
    for item in (normalized, compact, no_year, no_round):
        val = item.strip(" #")
        if not val or val in terms:
            continue
        terms.append(val)
    return terms[:8]


def _normalize_text_for_match(text: str) -> tuple[str, str]:
    raw = unicodedata.normalize("NFKC", str(text or "")).lower()
    spaced = re.sub(r"\s+", " ", raw).strip()
    compact = re.sub(r"\s+", "", spaced)
    return spaced, compact


def _text_contains_term(text: str, term: str) -> bool:
    text_spaced, text_compact = _normalize_text_for_match(text)
    term_spaced, term_compact = _normalize_text_for_match(term)
    if not term_spaced:
        return False
    if term_spaced in text_spaced:
        return True
    if term_compact and term_compact in text_compact:
        return True
    if term_compact and f"#{term_compact}" in text_compact:
        return True
    return False


def _extract_race_like_mentions(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    pattern = re.compile(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff]{2,30}(?:\u8cde|\u30b9\u30c6\u30fc\u30af\u30b9|\u30ab\u30c3\u30d7|\u8a18\u5ff5|\u30b8\u30e3\u30f3\u30d7|\u30c8\u30ed\u30d5\u30a3\u30fc)")
    found = pattern.findall(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in found:
        key = re.sub(r"\s+", "", item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _title_has_non_target_race_mentions(title: str, race_terms: list[str]) -> bool:
    mentions = _extract_race_like_mentions(title)
    if not mentions:
        return False
    target_compacts = {_normalize_text_for_match(term)[1] for term in race_terms if term}
    target_compacts = {x for x in target_compacts if x}
    if not target_compacts:
        return False
    for mention in mentions:
        mention_compact = _normalize_text_for_match(mention)[1]
        if not mention_compact:
            continue
        if any(tc in mention_compact or mention_compact in tc for tc in target_compacts):
            continue
        return True
    return False


def _candidate_x_accounts_paths(configured_path: str) -> list[Path]:
    candidates: list[Path] = []
    raw = (configured_path or "").strip()
    if raw:
        p = Path(raw)
        candidates.append(p if p.is_absolute() else ROOT_DIR / p)
    candidates.extend(
        [
            ROOT_DIR / "x_accounts.json",
            ROOT_DIR / "legacy" / "streamlit_app" / "x_accounts.json",
        ]
    )
    uniq: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(path)
    return uniq


def _build_x_queries(*, race_name: str, accounts: list[dict[str, str]], include_lang_ja: bool) -> list[str]:
    if not accounts:
        return []
    account_chunks = _chunk_accounts_for_query(
        race_name=race_name,
        accounts=accounts,
        include_lang_ja=include_lang_ja,
    )
    race_terms = _build_x_race_terms(race_name)
    race_expr = " OR ".join(f"\"{term}\"" for term in race_terms) if race_terms else f"\"{race_name or 'keiba'}\""
    queries: list[str] = []
    for chunk in account_chunks:
        from_expr = " OR ".join(f"from:{acc['username']}" for acc in chunk)
        query = f"({from_expr}) ({race_expr}) {X_TOPIC_EXPR} -is:retweet"
        if include_lang_ja:
            query += " lang:ja"
        queries.append(query)
    return queries


def _chunk_accounts_for_query(
    *,
    race_name: str,
    accounts: list[dict[str, str]],
    include_lang_ja: bool,
    max_query_len: int = 512,
) -> list[list[dict[str, str]]]:
    if not accounts:
        return []
    race_terms = _build_x_race_terms(race_name)
    race_expr = " OR ".join(f"\"{term}\"" for term in race_terms) if race_terms else f"\"{race_name}\""
    lang_tail = " lang:ja" if include_lang_ja else ""

    chunks: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for account in accounts:
        trial = current + [account]
        from_expr = " OR ".join(f"from:{acc['username']}" for acc in trial)
        q = f"({from_expr}) ({race_expr}) {X_TOPIC_EXPR} -is:retweet{lang_tail}"
        if len(q) <= max_query_len:
            current = trial
            continue
        if current:
            chunks.append(current)
            current = [account]
        else:
            chunks.append([account])
            current = []
    if current:
        chunks.append(current)
    return chunks


def _build_x_race_terms(race_name: str) -> list[str]:
    text = str(race_name or "").strip()
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text)
    compact = re.sub(r"\s+", "", normalized)
    no_year = re.sub(r"(20\d{2}|\u4ee4\u548c\d+\u5e74?)", "", compact)
    no_round = re.sub(r"\u7b2c\d+\u56de", "", no_year)

    terms: list[str] = []
    for t in [normalized, compact, no_year, no_round]:
        t = t.strip(" #")
        if t and t not in terms:
            terms.append(t)
    return terms[:6]


def _tweet_matches_race_name(tweet_text: str, race_name: str) -> bool:
    terms = _build_x_race_terms(race_name)
    if not terms:
        return True
    spaced_text, compact_text = _normalize_text_for_match(tweet_text)
    for term in terms:
        t_spaced, t_compact = _normalize_text_for_match(term)
        if not t_spaced:
            continue
        if t_spaced in spaced_text:
            return True
        if t_compact and t_compact in compact_text:
            return True
        if f"#{t_compact}" in compact_text:
            return True
    return False


def _filter_tweets_by_race_name(tweets: list[XTweet], race_name: str) -> tuple[list[XTweet], int]:
    filtered: list[XTweet] = []
    dropped = 0
    for tweet in tweets:
        if _tweet_matches_race_name(tweet.text, race_name):
            filtered.append(tweet)
        else:
            dropped += 1
    return filtered, dropped


def _build_x_user_map(payload: dict) -> dict[str, str]:
    users: dict[str, str] = {}
    includes = payload.get("includes", {}) if isinstance(payload, dict) else {}
    raw_users = includes.get("users", []) if isinstance(includes, dict) else []
    if not isinstance(raw_users, list):
        return users
    for user in raw_users:
        if not isinstance(user, dict):
            continue
        uid = str(user.get("id") or "").strip()
        username = str(user.get("username") or "").strip()
        if uid and username:
            users[uid] = username
    return users


def _label_for_username(accounts: list[dict[str, str]], username: str) -> str:
    for account in accounts:
        if account.get("username") == username:
            return account.get("label") or username
    return username


def _x_tweet_to_dict(tweet: XTweet) -> dict:
    return {
        "tweet_id": tweet.tweet_id,
        "text": tweet.text,
        "author_username": tweet.author_username,
        "author_label": tweet.author_label,
        "created_at": tweet.created_at,
        "url": tweet.url,
        "public_metrics": tweet.public_metrics,
    }


def _youtube_video_to_dict(video: YouTubeVideo) -> dict:
    return {
        "video_id": video.video_id,
        "title": video.title,
        "description": video.description,
        "channel_title": video.channel_title,
        "published_at": video.published_at,
        "thumbnail_url": video.thumbnail_url,
        "video_url": video.video_url,
    }


def _is_newer_tweet_id(candidate_id: str | None, current_id: str | None) -> bool:
    if not candidate_id:
        return False
    if not current_id:
        return True
    try:
        return int(candidate_id) > int(current_id)
    except (TypeError, ValueError):
        cand = str(candidate_id)
        curr = str(current_id)
        if len(cand) != len(curr):
            return len(cand) > len(curr)
        return cand > curr


def _coerce_int(value: object, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(math.floor(float(str(value))))
    except (TypeError, ValueError):
        return default


def _normalize_horse_names(horse_names: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for name in horse_names:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_horse_item(
    item: Any,
    *,
    source_type: str,
    source_title: str,
    source_url: str,
) -> dict | None:
    if not isinstance(item, dict):
        return None
    horse = _first_non_empty(item, ["horse", "horse_name", "\u99ac\u540d"]).strip()
    plus = _first_non_empty(item, ["plus", "plus_info", "\u30d7\u30e9\u30b9\u60c5\u5831"]).strip()
    minus = _first_non_empty(item, ["minus", "minus_info", "\u30de\u30a4\u30ca\u30b9\u60c5\u5831"]).strip()
    if not horse and not plus and not minus:
        return None
    return {
        "horse": horse or "unknown",
        "plus": plus,
        "minus": minus,
        "source_type": source_type,
        "source_title": source_title,
        "source_url": source_url,
    }


def _normalize_video_conclusion(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    head_pick = _first_non_empty(payload, ["head_pick", "honmei", "\u672c\u547d"]).strip()
    second_pick = _first_non_empty(payload, ["second_pick", "taikou", "\u5bfe\u6297"]).strip()
    dark_horse = _first_non_empty(payload, ["dark_horse", "tanana", "\u5358\u7a74"]).strip()
    danger_horse = _first_non_empty(payload, ["danger_horse", "kiken", "\u5371\u967a\u306a\u4eba\u6c17\u99ac"]).strip()
    bet_strategy = _first_non_empty(payload, ["bet_strategy", "strategy", "\u8cb7\u3044\u76ee\u65b9\u91dd"]).strip()
    if not any([head_pick, second_pick, dark_horse, danger_horse, bet_strategy]):
        return {}
    return {
        "head_pick": head_pick,
        "second_pick": second_pick,
        "dark_horse": dark_horse,
        "danger_horse": danger_horse,
        "bet_strategy": bet_strategy,
    }


def _first_non_empty(data: dict, keys: list[str]) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _parse_json_response(text: str, *, expected: str) -> Any:
    if not text or not text.strip():
        raise ValueError("empty response text")

    candidates = [_strip_code_fences(text), text]
    extracted = _extract_json_fragment(text)
    if extracted:
        candidates.append(extracted)

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if expected == "list" and isinstance(parsed, list):
            return parsed
        if expected == "dict" and isinstance(parsed, dict):
            return parsed
    raise ValueError(f"could not parse {expected} JSON")


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped, count=1)
        stripped = re.sub(r"\s*```$", "", stripped, count=1)
    return stripped.strip()


def _extract_json_fragment(text: str) -> str:
    for opening, closing in (("{", "}"), ("[", "]")):
        fragment = _find_balanced_block(text, opening=opening, closing=closing)
        if fragment:
            return fragment
    return ""


def _find_balanced_block(text: str, *, opening: str, closing: str) -> str:
    start = text.find(opening)
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == "\"":
                    in_string = False
                continue
            if ch == "\"":
                in_string = True
                continue
            if ch == opening:
                depth += 1
                continue
            if ch == closing:
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
        start = text.find(opening, start + 1)
    return ""
