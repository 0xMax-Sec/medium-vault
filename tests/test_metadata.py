import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from medium_archiver import ArticleMetadata, LibraryManager, MediumFeedDiscoverer


def test_article_metadata_dataclass():
    meta = ArticleMetadata(
        index=1,
        title="Testing IDOR in REST API",
        author="@pentester",
        published="2026-09-20",
        source_url="https://medium.com/@pentester/testing-idor-123456789abc",
        clean_url="https://medium.com/@pentester/testing-idor-123456789abc",
        topic="idor",
    )
    assert meta.index == 1
    assert meta.title == "Testing IDOR in REST API"
    assert meta.author == "@pentester"
    assert meta.topic == "idor"


def test_extract_post_hash_standard():
    url = "https://medium.com/@user/my-awesome-writeup-123456789abc"
    post_hash = LibraryManager.extract_post_hash(url)
    assert post_hash == "123456789abc"


def test_extract_post_hash_subdomain():
    url = "https://infosec.medium.com/how-i-found-ssrf-in-gitlab-abcdef123456"
    post_hash = LibraryManager.extract_post_hash(url)
    assert post_hash == "abcdef123456"


def test_extract_post_hash_with_query_params():
    url = "https://medium.com/@author/bypass-waf-with-unicode-9876543210fe?source=rss"
    post_hash = LibraryManager.extract_post_hash(url)
    assert post_hash == "9876543210fe"


def test_sanitize_url():
    raw_url = "https://medium.com/@user/post-123?source=rss&ref=feed"
    clean = MediumFeedDiscoverer.sanitize_url(raw_url)
    assert "source=rss" not in clean
    assert "ref=feed" not in clean
    assert clean == "https://medium.com/@user/post-123"
