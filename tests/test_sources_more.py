"""Reddit, arXiv, Hugging Face, GitHub and the X stub: parsed from saved real responses."""

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from tests.conftest import FIXTURES
from yellow.config import Config
from yellow.sources import arxiv, github_trending, huggingface, reddit, x

SINCE = datetime(2026, 11, 10, tzinfo=UTC)
FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- Reddit --------------------------------------------------------------------------------


def test_reddit_link_posts_point_outside_media_posts_at_thread() -> None:
    items = reddit.parse((FIXTURES / "reddit.xml").read_bytes(), SINCE)
    assert len(items) == 4
    for it in items:
        assert it.source == "reddit" and it.source_name == "r/LocalLLaMA"
        assert it.discussion_url and "reddit.com/r/LocalLLaMA/comments/" in it.discussion_url
        assert "redd.it" not in it.url  # image posts link to the thread, not the raw image
        assert it.snippet is None or "submitted by" not in it.snippet
    external = [it for it in items if "reddit.com" not in it.url]
    media = [it for it in items if it.url == it.discussion_url]
    assert len(external) == 2 and len(media) == 2


SELF_POST = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Which local model for coding?</title>
<category term="LocalLLaMA" label="r/LocalLLaMA"/>
<link href="https://www.reddit.com/r/LocalLLaMA/comments/abc/which/"/>
<published>2026-11-12T10:00:00+00:00</published>
<content type="html">&lt;div class="md"&gt;&lt;p&gt;Asking for a friend.&lt;/p&gt;&lt;/div&gt;
submitted by &lt;a href="https://www.reddit.com/user/u"&gt;/u/u&lt;/a&gt;
&lt;a href="https://www.reddit.com/r/LocalLLaMA/comments/abc/which/"&gt;[link]&lt;/a&gt;
&lt;a href="https://www.reddit.com/r/LocalLLaMA/comments/abc/which/"&gt;[comments]&lt;/a&gt;
</content></entry></feed>"""


def test_reddit_text_post_links_to_thread_with_body_snippet() -> None:
    [it] = reddit.parse(SELF_POST, SINCE)
    assert it.url == it.discussion_url == "https://www.reddit.com/r/LocalLLaMA/comments/abc/which/"
    assert it.snippet == "Asking for a friend."


def test_reddit_one_combined_request_and_retry_on_429(
    cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert reddit.parse((FIXTURES / "reddit.xml").read_bytes(), FUTURE) == []
    good = (FIXTURES / "reddit.xml").read_bytes()
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        return httpx.Response(429) if len(paths) == 1 else httpx.Response(200, content=good)

    monkeypatch.setattr(reddit.time, "sleep", lambda s: None)
    cfg = cfg.model_copy(deep=True)
    cfg.sources.reddit.subreddits = ["LocalLLaMA", "MachineLearning"]
    items = reddit.RedditSource(cfg, _client(handler)).fetch(SINCE)
    assert paths == ["/r/LocalLLaMA+MachineLearning/top/.rss"] * 2
    assert items and {i.source_name for i in items} == {"r/LocalLLaMA"}


def test_reddit_gives_up_after_second_429(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reddit.time, "sleep", lambda s: None)
    assert reddit.RedditSource(cfg, _client(lambda r: httpx.Response(429))).fetch(SINCE) == []


# --- arXiv ---------------------------------------------------------------------------------


def test_arxiv_parses_and_strips_version(cfg: Config) -> None:
    items = arxiv.parse((FIXTURES / "arxiv.xml").read_bytes(), SINCE)
    assert items
    for it in items:
        assert it.source_name == "arXiv"
        assert it.url.startswith("https://arxiv.org/abs/") and not it.url[-2:].startswith("v")
        assert "\n" not in it.title
    assert arxiv.parse((FIXTURES / "arxiv.xml").read_bytes(), FUTURE) == []


def test_arxiv_fetch_queries_all_categories_and_caps(cfg: Config) -> None:
    sent: dict[str, str] = {}
    body = (FIXTURES / "arxiv.xml").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        sent.update(req.url.params)
        return httpx.Response(200, content=body)

    cfg = cfg.model_copy(deep=True)
    cfg.sources.arxiv.max_items = 2
    items = arxiv.ArxivSource(cfg, _client(handler)).fetch(SINCE)
    assert len(items) == 2
    assert sent["search_query"] == "cat:cs.AI OR cat:cs.CL OR cat:cs.LG"


# --- Hugging Face --------------------------------------------------------------------------


def test_hf_papers_parse_with_upvotes() -> None:
    data = json.loads((FIXTURES / "hf_papers.json").read_text())
    items = huggingface.parse_papers(data, SINCE)
    assert len(items) == len(data)
    for it in items:
        assert it.url.startswith("https://huggingface.co/papers/")
        assert it.source_name == "HF Papers" and it.score is not None
    assert huggingface.parse_papers(data, FUTURE) == []
    # A midnight-stamped daily list still counts for a `since` later that same day.
    day = huggingface.parse_iso_utc(data[0]["paper"]["submittedOnDailyAt"])
    assert huggingface.parse_papers(data[:1], day.replace(hour=7))


def test_hf_models_respect_age_cutoff() -> None:
    data = json.loads((FIXTURES / "hf_models.json").read_text())
    cutoff = datetime(2026, 11, 1, tzinfo=UTC)
    items = huggingface.parse_models(data, cutoff)
    assert items and len(items) < len(data)  # the fixture has older trending models too
    for it in items:
        assert it.published >= cutoff
        assert it.url.startswith("https://huggingface.co/") and it.source_name == "HF Models"


def test_hf_switches(cfg: Config) -> None:
    papers = (FIXTURES / "hf_papers.json").read_bytes()
    models = (FIXTURES / "hf_models.json").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=papers if "daily_papers" in req.url.path else models)

    cfg = cfg.model_copy(deep=True)
    cfg.sources.huggingface.models = False
    items = huggingface.HuggingFaceSource(cfg, _client(handler)).fetch(SINCE)
    assert items and {i.source_name for i in items} == {"HF Papers"}


# --- GitHub --------------------------------------------------------------------------------


def test_github_parses_repos() -> None:
    data = json.loads((FIXTURES / "github.json").read_text())
    items = github_trending.parse(data)
    assert len(items) == len(data["items"])
    for it in items:
        assert it.url.startswith("https://github.com/") and it.source_name == "GitHub"
        assert it.score and it.score >= 50
        assert it.published.tzinfo is not None


def test_github_skips_forks_and_bad_dates() -> None:
    repo = {
        "full_name": "a/b",
        "html_url": "https://github.com/a/b",
        "created_at": "2026-11-12T00:00:00Z",
    }
    assert github_trending.parse({"items": [repo | {"fork": True}]}) == []
    assert github_trending.parse({"items": [repo | {"created_at": "nope"}]}) == []
    assert len(github_trending.parse({"items": [repo]})) == 1


def test_github_sends_query_and_token(cfg: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}
    body = (FIXTURES / "github.json").read_bytes()

    def handler(req: httpx.Request) -> httpx.Response:
        seen["q"] = req.url.params["q"]
        seen["auth"] = req.headers.get("Authorization", "")
        return httpx.Response(200, content=body)

    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    assert github_trending.GithubTrendingSource(cfg, _client(handler)).fetch(SINCE)
    assert "created:>" in seen["q"] and "stars:>=100" in seen["q"]
    assert seen["auth"] == "Bearer t0ken"


# --- X stub --------------------------------------------------------------------------------


def test_x_stub_returns_nothing(cfg: Config) -> None:
    assert x.XSource(cfg, _client(lambda r: httpx.Response(500))).fetch(SINCE) == []


@pytest.mark.parametrize(
    "cls", [arxiv.ArxivSource, huggingface.HuggingFaceSource, github_trending.GithubTrendingSource]
)
def test_http_error_returns_empty(cfg: Config, cls: type) -> None:
    assert cls(cfg, _client(lambda r: httpx.Response(503))).fetch(SINCE) == []
