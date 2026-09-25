import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from medium_archiver import (
    TRACKING_PARAM_PREFIXES,
    TRACKING_PARAMS,
    ArticleMetadata,
    LibraryManager,
    MediumFeedDiscoverer,
)


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


def test_tracking_params_constant_is_pinned():
    # Arrange / Act / Assert: fails if the stripped-param set drifts from docs
    assert TRACKING_PARAMS == frozenset({"source", "ref", "gi", "responsesopen"})
    assert TRACKING_PARAM_PREFIXES == ("utm_", "sk")


def test_sanitize_url_strips_all_tracking_families_keeps_others():
    # Arrange
    raw_url = (
        "https://medium.com/@u/post-abc?utm_source=x&sk=deadbeef&responsesopen=1"
        "&gi=z&source=rss&ref=feed&page=2"
    )

    # Act
    clean = MediumFeedDiscoverer.sanitize_url(raw_url)

    # Assert
    assert "utm_source" not in clean
    assert "sk=" not in clean
    assert "responsesopen" not in clean
    assert "gi=" not in clean
    assert "source=" not in clean
    assert "ref=" not in clean
    assert "page=2" in clean
