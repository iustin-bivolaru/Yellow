import pytest

from yellow.text import canonical_url, html_to_text, is_http_url


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("https://www.Example.com/post/", "https://example.com/post"),
        ("https://example.com/post?utm_source=x&utm_medium=y", "https://example.com/post"),
        ("https://example.com/post#comments", "https://example.com/post"),
        ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2"),
        ("HTTPS://EXAMPLE.com/p?fbclid=abc", "https://example.com/p"),
        ("http://example.com/post", "https://example.com/post"),
    ],
)
def test_canonical_url_equivalents(a: str, b: str) -> None:
    assert canonical_url(a) == canonical_url(b)


@pytest.mark.parametrize("param", ["ref", "source", "id"])
def test_canonical_url_keeps_content_params(param: str) -> None:
    assert canonical_url(f"https://e.com/p?{param}=a") != canonical_url(
        f"https://e.com/p?{param}=b"
    )


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://example.com/a", True),
        ("http://example.com/a", True),
        ("javascript:alert(1)", False),
        ("JavaScript:alert(1)", False),
        ("data:text/html,<script>alert(1)</script>", False),
        ("/relative/path", False),
        ("", False),
        (None, False),
    ],
)
def test_is_http_url(url: str | None, ok: bool) -> None:
    assert is_http_url(url) is ok


def test_canonical_url_keeps_meaningful_query() -> None:
    assert canonical_url("https://news.ycombinator.com/item?id=1") != canonical_url(
        "https://news.ycombinator.com/item?id=2"
    )


def test_html_to_text() -> None:
    assert html_to_text("<p>Hello&nbsp;<b>world</b></p>\n\n") == "Hello world"
    assert html_to_text("") is None
    assert html_to_text("<br/>") is None
    long = html_to_text("x" * 50, limit=10)
    assert long is not None and len(long) == 10 and long.endswith("…")
