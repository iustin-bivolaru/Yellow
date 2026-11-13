import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from yellow.models import Digest, DigestItem, TechRef
from yellow.render import load_digests, render_site, save_digest, templates_dir
from yellow.tech_registry import annotate_digest, update_registry

DAY = date(2026, 11, 13)


def _digest(day: date = DAY) -> Digest:
    def item(i: str, **kw) -> DigestItem:
        return DigestItem(
            id=i,
            url=f"https://example.com/{i}",
            source="rss",
            source_name="Example",
            published=datetime(day.year, day.month, day.day, 6, tzinfo=UTC),
            **{"title": f"Story {i}", **kw},
        )

    return Digest(
        date=day,
        generated_at=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
        analyzer="test",
        nutshell="One. Two. Three.",
        top5=["a", "b"],
        items=[
            item(
                "a",
                category="Models",
                summary="Sum a",
                importance=5,
                score=10,
                technologies=["Llama 4"],
                snippet="snip",
                discussion_url="https://example.com/talk",
            ),
            item("b", category="Tools", title="<script>alert(1)</script>", importance=2),
            item("c"),
        ],
    )


def _build(tmp_path: Path, cfg, digests: list[Digest]) -> Path:
    registry: dict = {}
    for d in reversed(digests):
        registry = update_registry(registry, d)
    digests = [annotate_digest(d, registry, cfg.registry) for d in digests]
    out = tmp_path / "site"
    render_site(out, digests, registry, cfg)
    return out


def test_renders_all_files(tmp_path, cfg):
    out = _build(tmp_path, cfg, [_digest()])
    for name in (
        "index.html",
        "day/2026-11-13.html",
        "tech/llama-4.html",
        "style.css",
        "app.js",
        "sw.js",
        "manifest.json",
        "icon.svg",
        "icon-192.png",
        "icon-512.png",
    ):
        assert (out / name).is_file(), name
    assert (out / "icon-192.png").read_bytes().startswith(b"\x89PNG")


def test_untrusted_title_is_escaped(tmp_path, cfg):
    out = _build(tmp_path, cfg, [_digest()])
    html = (out / "index.html").read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_links_are_relative(tmp_path, cfg):
    out = _build(tmp_path, cfg, [_digest()])
    index = (out / "index.html").read_text()
    assert 'href="tech/llama-4.html"' in index
    assert 'href="day/2026-11-13.html"' in index
    for page in ("day/2026-11-13.html", "tech/llama-4.html"):
        html = (out / page).read_text()
        assert 'href="../style.css"' in html
        assert 'href="/' not in html
    assert 'href="../tech/llama-4.html"' in (out / "day/2026-11-13.html").read_text()


def test_tech_page_lists_stories(tmp_path, cfg):
    out = _build(tmp_path, cfg, [_digest()])
    html = (out / "tech/llama-4.html").read_text()
    assert "Story a" in html and "2026-11-13" in html and "Example" in html


def test_manifest(tmp_path, cfg):
    out = _build(tmp_path, cfg, [_digest()])
    m = json.loads((out / "manifest.json").read_text())
    assert m["theme_color"] == "#FFD400"
    assert m["start_url"] == "./" and m["scope"] == "./"


def test_cards_degrade_without_optional_fields(tmp_path, cfg):
    out = _build(tmp_path, cfg, [_digest()])
    assert "Story c" in (out / "index.html").read_text()


def test_empty_digest_and_no_digests(tmp_path, cfg):
    empty = _digest().model_copy(update={"items": [], "top5": []})
    out = _build(tmp_path, cfg, [empty])
    assert "Quiet day" in (out / "index.html").read_text()
    out2 = tmp_path / "none"
    render_site(out2, [], {}, cfg)
    assert "No digest yet" in (out2 / "index.html").read_text()
    assert (out2 / "sw.js").is_file()


def test_new_and_trending_chips(tmp_path, cfg):
    d = _digest().model_copy(
        update={"trending_tech": [TechRef(name="Llama 4", slug="llama-4", count_today=3)]}
    )
    out = tmp_path / "site"
    render_site(out, [d], update_registry({}, d), cfg)
    assert "Trending" in (out / "index.html").read_text()


def test_rerender_removes_stale_pages(tmp_path, cfg):
    out = _build(tmp_path, cfg, [_digest(), _digest(date(2026, 11, 12))])
    assert (out / "day/2026-11-12.html").exists()
    render_site(out, [_digest()], {}, cfg)
    assert not (out / "day/2026-11-12.html").exists()


def test_save_and_load_round_trip_newest_first(tmp_path):
    older, newer = _digest(date(2026, 11, 12)), _digest()
    save_digest(tmp_path, older)
    path = save_digest(tmp_path, newer)
    assert path.name == "2026-11-13.json"
    loaded = load_digests(tmp_path)
    assert [d.date for d in loaded] == [newer.date, older.date]
    assert loaded[0] == newer
    assert len(load_digests(tmp_path, limit=1)) == 1


def test_corrupt_digest_is_skipped(tmp_path, caplog):
    save_digest(tmp_path, _digest())
    (tmp_path / "2026-11-14.json").write_text("{not json")
    with caplog.at_level(logging.WARNING):
        loaded = load_digests(tmp_path)
    assert [d.date for d in loaded] == [DAY]
    assert "2026-11-14.json" in caplog.text
    assert load_digests(tmp_path / "missing") == []


def test_templates_never_use_safe_filter():
    for path in templates_dir().iterdir():
        assert "|safe" not in path.read_text().replace(" ", ""), path.name


def test_unsafe_registry_slug_is_never_written(tmp_path, cfg):
    digest = _digest()
    registry = update_registry({}, digest)
    some = next(iter(registry.values()))
    registry["../evil"] = some.model_copy(update={"slug": "../evil"})
    out = tmp_path / "site"
    render_site(out, [annotate_digest(digest, registry, cfg.registry)], registry, cfg)
    assert not (tmp_path / "evil.html").exists()
    assert not list(tmp_path.rglob("evil.html"))
    assert "evil" not in (out / "index.html").read_text()


def test_symlinked_output_subdir_is_unlinked_not_followed(tmp_path, cfg):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    out = tmp_path / "site"
    out.mkdir()
    (out / "day").symlink_to(outside, target_is_directory=True)
    render_site(out, [_digest()], update_registry({}, _digest()), cfg)
    assert (outside / "keep.txt").exists()
    assert list(outside.iterdir()) == [outside / "keep.txt"]
    assert not (out / "day").is_symlink()


def test_digest_pages_have_an_h1(tmp_path, cfg):
    out = _build(tmp_path, cfg, [_digest()])
    assert '<h1 class="sr-only">' in (out / "index.html").read_text()


def test_older_items_show_their_date(cfg):
    from datetime import UTC, datetime

    from yellow.render import _env

    localtime = _env(cfg).filters["localtime"]
    noon = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)  # 12:00 in Europe/Bucharest
    assert localtime(noon, date(2026, 11, 13)) == "12:00"
    assert localtime(noon, date(2026, 11, 14)) == "13 Nov 12:00"


def test_templates_come_from_project_root_not_file_location(tmp_path, cfg, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("YELLOW_ROOT", str(repo))
    monkeypatch.chdir(tmp_path)
    assert templates_dir() == repo / "templates"
    out = _build(tmp_path, cfg, [_digest()])
    assert (out / "index.html").is_file()
