"""HTTP counters include retries and distinguish disk-cache hits."""

from collections.abc import AsyncIterator
from pathlib import Path
import socket

from aiohttp import web
import pytest

from gh_signals.github_client import GitHubClient, GitHubError


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[list[int]]:
    counts = [0]

    async def repo(request: web.Request) -> web.Response:
        counts[0] += 1
        if request.match_info["repo"] == "retry" and counts[0] == 1:
            return web.json_response({}, status=429, headers={"Retry-After": "0"})
        return web.json_response({"full_name": "a/b", "stargazers_count": 0, "forks_count": 12})

    app = web.Application()
    app.router.add_get("/repos/a/{repo}", repo)
    runner = web.AppRunner(app)
    await runner.setup()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    site = web.SockSite(runner, sock)
    await site.start()
    monkeypatch.setattr("gh_signals.github_client.API_URL", f"http://127.0.0.1:{sock.getsockname()[1]}")

    async def no_token(self: GitHubClient) -> None:
        return None

    monkeypatch.setattr(GitHubClient, "_resolve_token", no_token)
    try:
        yield counts
    finally:
        await runner.cleanup()


async def test_second_fetch_uses_cache(api: list[int], tmp_path: Path) -> None:
    async with GitHubClient(cache_dir=tmp_path) as client:
        assert (await client.get_repo("a/b")).stargazers_count == 0
        await client.get_repo("a/b")
        assert client.usage() == {"requests": 1, "cache_hits": 1, "wait_seconds": 0.0}
    assert api == [1]


async def test_retry_is_counted(api: list[int]) -> None:
    async with GitHubClient(cache_dir=None) as client:
        await client.get_repo("a/retry")
        assert client.usage()["requests"] == 2
    assert api == [2]


async def test_excessive_wait_returns_error() -> None:
    client = GitHubClient(max_wait_seconds=0)
    with pytest.raises(GitHubError, match="budget"):
        await client._wait(61)
