"""
Module: app/tools/google_search.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# Google 搜索工具：调用搜索 API 获取文本摘要。

from __future__ import annotations

import json
from collections.abc import Iterable

import httpx

from app.core.config import settings


class GoogleSearchTool:
    name = "google_search"

    async def call(self, args: dict) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return json.dumps(
                {"ok": False, "error": "missing query", "query": ""},
                ensure_ascii=False,
            )

        errors: list[str] = []
        async with httpx.AsyncClient(
            timeout=12.0,
            follow_redirects=True,
            headers={"User-Agent": "Project-Avis/1.0"},
        ) as client:
            primary = await self._search_primary(client, query, errors)
            if primary is not None:
                return json.dumps(
                    {
                        "ok": True,
                        "source": "configured_search_api",
                        "query": query,
                        **primary,
                    },
                    ensure_ascii=False,
                )

            fallback = await self._search_duckduckgo(client, query, errors)
            if fallback is not None:
                return json.dumps(
                    {
                        "ok": True,
                        "source": "duckduckgo_instant",
                        "query": query,
                        **fallback,
                    },
                    ensure_ascii=False,
                )

            wiki = await self._search_wikipedia(client, query, errors)
            if wiki is not None:
                return json.dumps(
                    {
                        "ok": True,
                        "source": "wikipedia_opensearch",
                        "query": query,
                        **wiki,
                    },
                    ensure_ascii=False,
                )

        return json.dumps(
            {
                "ok": False,
                "query": query,
                "error": "search unavailable or no useful result",
                "details": errors[:2],
            },
            ensure_ascii=False,
        )

    async def _search_primary(
        self,
        client: httpx.AsyncClient,
        query: str,
        errors: list[str],
    ) -> dict | None:
        try:
            resp = await client.get(settings.search_api_url, params={"q": query})
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            errors.append(f"primary failed: {exc}")
            return None

        summary = self._pick_summary(data)
        results = self._pick_results(data)
        if not summary and not results:
            return None
        return {"summary": summary, "results": results}

    async def _search_duckduckgo(
        self,
        client: httpx.AsyncClient,
        query: str,
        errors: list[str],
    ) -> dict | None:
        try:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": 1,
                    "no_redirect": 1,
                    "skip_disambig": 0,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            errors.append(f"duckduckgo failed: {exc}")
            return None

        summary = self._first_non_empty(
            data.get("AbstractText"),
            data.get("Answer"),
            data.get("Heading"),
        )

        results: list[dict[str, str]] = []
        direct_results = data.get("Results")
        if isinstance(direct_results, list):
            for item in direct_results:
                parsed = self._normalize_item(item)
                if parsed is not None:
                    results.append(parsed)

        def iter_related(items: Iterable[object]) -> Iterable[dict]:
            for item in items:
                if not isinstance(item, dict):
                    continue
                topics = item.get("Topics")
                if isinstance(topics, list):
                    for sub in iter_related(topics):
                        yield sub
                    continue
                yield item

        related = data.get("RelatedTopics")
        if isinstance(related, list):
            for item in iter_related(related):
                parsed = self._normalize_item(item)
                if parsed is not None:
                    results.append(parsed)

        dedup: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in results:
            key = (item.get("title", ""), item.get("url", ""))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(item)
            if len(dedup) >= 5:
                break

        if not summary and not dedup:
            return None
        return {"summary": summary, "results": dedup}

    async def _search_wikipedia(
        self,
        client: httpx.AsyncClient,
        query: str,
        errors: list[str],
    ) -> dict | None:
        try:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                headers={"User-Agent": "Project-Avis/1.0 (dev@example.com)"},
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": 5,
                    "namespace": 0,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            errors.append(f"wikipedia failed: {exc}")
            return None

        if not isinstance(data, list) or len(data) < 4:
            return None

        titles = data[1] if isinstance(data[1], list) else []
        snippets = data[2] if isinstance(data[2], list) else []
        urls = data[3] if isinstance(data[3], list) else []

        results: list[dict[str, str]] = []
        for idx in range(min(len(titles), len(urls), 5)):
            title = str(titles[idx] or "").strip()
            url = str(urls[idx] or "").strip()
            snippet = str(snippets[idx] or "").strip() if idx < len(snippets) else ""
            if not title and not snippet:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                }
            )

        if not results:
            return None

        summary = results[0].get("snippet", "") or results[0].get("title", "")
        return {"summary": summary, "results": results}

    @staticmethod
    def _pick_summary(data: object) -> str:
        if not isinstance(data, dict):
            return ""
        return GoogleSearchTool._first_non_empty(
            data.get("summary"),
            data.get("answer"),
            data.get("abstract"),
            data.get("content"),
            data.get("message"),
        )

    @staticmethod
    def _pick_results(data: object) -> list[dict[str, str]]:
        if not isinstance(data, dict):
            return []
        keys = ("results", "items", "organic_results", "data")
        raw: object = []
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                raw = value
                break

        if not isinstance(raw, list):
            return []

        picked: list[dict[str, str]] = []
        for item in raw:
            parsed = GoogleSearchTool._normalize_item(item)
            if parsed is None:
                continue
            picked.append(parsed)
            if len(picked) >= 5:
                break
        return picked

    @staticmethod
    def _normalize_item(item: object) -> dict[str, str] | None:
        if not isinstance(item, dict):
            return None

        title = GoogleSearchTool._first_non_empty(
            item.get("title"),
            item.get("name"),
            item.get("Heading"),
            item.get("Text"),
        )
        url = GoogleSearchTool._first_non_empty(
            item.get("url"),
            item.get("link"),
            item.get("href"),
            item.get("FirstURL"),
        )
        snippet = GoogleSearchTool._first_non_empty(
            item.get("snippet"),
            item.get("description"),
            item.get("body"),
            item.get("Text"),
        )

        if not title and not snippet:
            return None
        return {
            "title": title,
            "url": url,
            "snippet": snippet,
        }

    @staticmethod
    def _first_non_empty(*values: object) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""
