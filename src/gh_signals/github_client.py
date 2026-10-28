"""Async client for the GitHub REST API.

Example:
    async with GitHubClient() as client:
        repo = await client.get_repo("microsoft/vscode")
        print(repo.stargazers_count, repo.forks_count)
"""

import asyncio
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import time
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlencode

import aiohttp

from gh_signals.schemas import Contributor, Repo

API_URL = "https://api.github.com"
DEFAULT_CACHE_DIR = Path(__file__).parents[2] / ".cache" / "github"
Json = dict[str, Any] | list[Any]


class GitHubError(Exception):
    """Raised when the GitHub API returns an unsuccessful response."""

    def __init__(self, status: int, path: str, body: str) -> None:
        super().__init__(f"GitHub returned {status} for {path}: {body}")
        self.status = status
        self.path = path


class GitHubClient:
    """Fetches repository metadata, caching responses and respecting rate limits."""

    def __init__(
        self,
        token: str | None = None,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        cache_ttl_seconds: float = 24 * 60 * 60,
        min_remaining: int = 10,
    ) -> None:
        """Initializes the client.

        Args:
            token: A GitHub token
            cache_dir: Directory for cached responses. Pass ``None`` to disable caching.
            cache_ttl_seconds: How long a cached response stays fresh. Defaults to 24 hours.
            min_remaining: How many core requests to leave unused before waiting for the hourly
                quota to reset. Useful to prevent totally exhausting your GitHub usage.
                The search quota is separate and is only waited out when it is empty.
        """
        self._token = token
        self._cache_dir = cache_dir
        self._cache_ttl_seconds = cache_ttl_seconds
        self._min_remaining = min_remaining
        self._remaining_by_resource: dict[str, int] = {}
        self._reset_by_resource: dict[str, float] = {}
        self._session: aiohttp.ClientSession | None = None

    async def get_repo(self, repo: str) -> Repo:
        """Fetches the star and fork counts for a repository.

        Args:
            repo: A repository in ``owner/name`` form, such as ``microsoft/vscode``.

        Returns:
            The repository's current counts.

        Raises:
            GitHubError: If GitHub rejects the request, such as when the repository does not exist or is private.
        """
        response = await self._get(f"repos/{repo}")
        if not isinstance(response, dict):
            raise RuntimeError(f"Expected a repository object for {repo}")
        return Repo.model_validate(response)

    async def get_contributors(self, repo: str, per_page: int = 100) -> list[Contributor]:
        """Fetches one page of identifiable contributors, most active first.

        Args:
            repo: A repository in ``owner/name`` form.
            per_page: Page size. GitHub allows at most 100.

        Returns:
            Contributors with a login. Anonymous contributors are omitted.

        Raises:
            GitHubError: If GitHub rejects the request.
        """
        response = await self._get(
            f"repos/{repo}/contributors",
            {"per_page": str(per_page), "anon": "0"},
        )
        if not isinstance(response, list):
            raise RuntimeError(f"Expected a contributor list for {repo}")
        return [Contributor.model_validate(row) for row in response if isinstance(row, dict) and "login" in row]

    async def get_author_commit_date(self, repo: str, login: str, *, earliest: bool) -> str | None:
        """Returns one indexed author-date for a person's commits on a repository.

        The commit search index can miss commits. Only the timestamp is returned.
        Names and email addresses from the commit payload are discarded.

        Args:
            repo: A repository in ``owner/name`` form.
            login: Contributor login.
            earliest: When true, return the earliest indexed author date. Otherwise return the latest.

        Returns:
            An ISO timestamp, or ``None`` when the index has no matching commit.
        """
        response = await self._get(
            "search/commits",
            {
                "q": f"repo:{repo} author:{login}",
                "sort": "author-date",
                "order": "asc" if earliest else "desc",
                "per_page": "1",
            },
        )
        return _first_author_date(response)

    async def get_rate_limit(self) -> dict[str, Any]:
        """Returns GitHub's current rate-limit snapshot.

        This request is not cached. GitHub does not count it against the core quota.
        """
        response = await self._get("rate_limit", use_cache=False)
        if not isinstance(response, dict):
            raise RuntimeError("Expected a rate-limit object")
        return response

    async def __aenter__(self) -> Self:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        token = await self._resolve_token()
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        self._session = aiohttp.ClientSession(headers=headers)
        return self

    async def _resolve_token(self) -> str | None:
        """Returns the first token available from the constructor, the environment, or the GitHub CLI."""
        return self._token or os.environ.get("GITHUB_TOKEN") or await _gh_cli_token()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _get(
        self,
        path: str,
        params: Mapping[str, str] | None = None,
        *,
        use_cache: bool = True,
    ) -> Json:
        """Returns the JSON payload for an API path, from cache when it is still fresh."""
        if use_cache:
            cached = self._read_cache(path, params)
            if cached is not None:
                return cached
        payload = await self._request(path, params)
        if use_cache:
            self._write_cache(path, params, payload)
        return payload

    async def _request(
        self,
        path: str,
        params: Mapping[str, str] | None = None,
        allow_retry: bool = True,
    ) -> Json:
        """Issues a single GET, retrying once if GitHub asks us to back off."""
        session = self._session
        if session is None:
            raise RuntimeError("Use GitHubClient as an async context manager: async with GitHubClient() as client")

        resource = "search" if path.startswith("search/") else "core"
        await self._wait_for_quota(resource)
        async with session.get(f"{API_URL}/{path}", params=params) as response:
            self._record_quota(response.headers)
            retry_after = response.headers.get("Retry-After")
            if allow_retry and retry_after is not None and response.status in (403, 429):
                await asyncio.sleep(float(retry_after))
                return await self._request(path, params, allow_retry=False)
            if not response.ok:
                raise GitHubError(response.status, path, await response.text())
            return await response.json()

    def _record_quota(self, headers: Mapping[str, str]) -> None:
        """Stores how much of each quota is left, per GitHub's response headers."""
        remaining = headers.get("x-ratelimit-remaining")
        reset_at = headers.get("x-ratelimit-reset")
        resource = headers.get("x-ratelimit-resource", "core")
        if remaining is not None and reset_at is not None:
            self._remaining_by_resource[resource] = int(remaining)
            self._reset_by_resource[resource] = float(reset_at)

    async def _wait_for_quota(self, resource: str) -> None:
        """Sleeps until the relevant quota resets when too little of it is left.

        The core hourly quota keeps a buffer of ``min_remaining`` requests. Search
        has a much smaller limit, so it is waited out only when the bucket is empty.
        """
        remaining = self._remaining_by_resource.get(resource)
        if remaining is None:
            return
        floor = self._min_remaining if resource == "core" else 0
        if remaining > floor:
            return
        delay = self._reset_by_resource.get(resource, 0.0) - time.time()
        if delay > 0:
            await asyncio.sleep(delay)
        self._remaining_by_resource[resource] = floor + 1

    def _cache_path(self, path: str, params: Mapping[str, str] | None) -> Path | None:
        """Maps an API path and query to a cache file name."""
        if self._cache_dir is None:
            return None
        raw = path if not params else f"{path}?{urlencode(sorted(params.items()))}"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)
        if len(safe) > 180:
            digest = hashlib.sha256(raw.encode()).hexdigest()
            safe = f"{safe[:80]}_{digest}"
        return self._cache_dir / f"{safe}.json"

    def _read_cache(self, path: str, params: Mapping[str, str] | None) -> Json | None:
        cache_path = self._cache_path(path, params)
        if cache_path is None or not cache_path.exists():
            return None
        if time.time() - cache_path.stat().st_mtime > self._cache_ttl_seconds:
            return None
        with cache_path.open(encoding="utf-8") as file:
            payload = json.load(file)
        if isinstance(payload, (dict, list)):
            return payload
        return None

    def _write_cache(self, path: str, params: Mapping[str, str] | None, payload: Json) -> None:
        cache_path = self._cache_path(path, params)
        if cache_path is None:
            return
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file)


def _first_author_date(payload: Json) -> str | None:
    """Returns the author timestamp of the first search hit, ignoring names and emails."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    item = items[0]
    if not isinstance(item, dict):
        return None
    commit = item.get("commit")
    if not isinstance(commit, dict):
        return None
    author = commit.get("author")
    if not isinstance(author, dict):
        return None
    date = author.get("date")
    if not isinstance(date, str):
        return None
    return date


async def _gh_cli_token() -> str | None:
    """Returns the token from ``gh auth token``.

    Returns:
        The token, or ``None`` when the GitHub CLI is not installed or not logged in.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            "gh",
            "auth",
            "token",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, NotImplementedError):
        return None
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return None
    return stdout.decode().strip() or None
