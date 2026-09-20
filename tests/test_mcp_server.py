import os
import pytest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import server
from medium_archiver import ArchivedEntry


@pytest.fixture(autouse=True)
def setup_isolated_kb(tmp_path, monkeypatch):
    """Isolate server.library to a temporary knowledge base directory."""
    temp_kb = tmp_path / "test_kb"
    temp_kb.mkdir()
    
    # Create a mock article
    art_dir = temp_kb / "bug-bounty" / "sample-idor-article-111122223333"
    art_dir.mkdir(parents=True)
    (art_dir / "article.md").write_text(
        "# How I found an IDOR\n\nThis is a sample writeup on IDOR vulnerability in an API endpoint.",
        encoding="utf-8"
    )
    
    entry = ArchivedEntry(
        title="How I found an IDOR",
        author="@researcher",
        published="2026-09-20",
        source_url="https://medium.com/@researcher/sample-idor-article-111122223333",
        clean_url="https://medium.com/@researcher/sample-idor-article-111122223333",
        post_hash="111122223333",
        topic="bug-bounty",
        folder_rel_path="bug-bounty/sample-idor-article-111122223333",
        retrieved_at="2026-09-20T12:00:00Z",
        file_size_kb=0.2,
        images_count=0,
    )
    
    # Point server's library to the isolated temp directory
    server.library.base_dir = temp_kb
    server.library.manifest_path = temp_kb / ".library_manifest.json"
    server.library.entries = {entry.post_hash: entry}
    server.library.title_map = {server.library.normalize_title(entry.title): entry.post_hash}
    server.library.url_map = {entry.clean_url: entry.post_hash}
    server.library.save_manifest()
    
    yield temp_kb


def test_medium_search_articles():
    # Search by keyword in title
    res = server.medium_search_articles(query="IDOR")
    assert "How I found an IDOR" in res
    assert "@researcher" in res
    assert "111122223333" in res


def test_medium_get_article_by_hash():
    content = server.medium_get_article(identifier="111122223333")
    assert "How I found an IDOR" in content
    assert "API endpoint" in content


def test_medium_get_article_by_title():
    content = server.medium_get_article(identifier="How I found an IDOR")
    assert "How I found an IDOR" in content


def test_medium_get_stats():
    stats = server.medium_get_stats()
    assert "**Total Artículos Guardados**: 1" in stats
    assert "#bug-bounty" in stats


def test_medium_export_archive(tmp_path):
    out_zip = tmp_path / "test_export.zip"
    res = server.medium_export_archive(topic="bug-bounty", output_zip_path=str(out_zip))
    assert "[✓]" in res
    assert out_zip.exists()
    assert out_zip.stat().st_size > 0
