import ast
import sys
from pathlib import Path

import pytest

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
    
    # Point server's library and archiver to the isolated temp directory
    server.library.base_dir = temp_kb
    server.library.manifest_path = temp_kb / ".library_manifest.json"
    server.library.entries = {entry.post_hash: entry}
    server.library.title_map = {server.library.normalize_title(entry.title): entry.post_hash}
    server.library.url_map = {entry.clean_url: entry.post_hash}
    server.library.save_manifest()
    server.archiver.output_dir = temp_kb
    server.archiver.library = server.library
    
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


def test_medium_export_archive():
    res = server.medium_export_archive(topic="bug-bounty", output_zip_path="test_export.zip")
    assert "[✓]" in res
    exports_dir = server.library.base_dir / "exports"
    out_zip = exports_dir / "test_export.zip"
    assert out_zip.exists()
    assert out_zip.stat().st_size > 0


def test_export_archive_path_traversal_blocked(tmp_path):
    # Attempting to write outside exports_dir via absolute path
    outside_zip = tmp_path / "evil.zip"
    res = server.medium_export_archive(topic="bug-bounty", output_zip_path=str(outside_zip))
    assert "Error de seguridad" in res
    assert not outside_zip.exists()

    # Attempting traversal via relative path
    res = server.medium_export_archive(topic="bug-bounty", output_zip_path="../../evil.zip")
    assert "Error de seguridad" in res

    # Attempting non-zip extension
    res = server.medium_export_archive(topic="bug-bounty", output_zip_path="payload.sh")
    assert "Error de seguridad" in res

    # Attempting topic traversal
    res = server.medium_export_archive(topic="../../etc")
    assert "Error de seguridad" in res or "no existe" in res


def test_archive_url_ssrf_blocked():
    # Loopback IP
    res = server.medium_archive_url("http://127.0.0.1:8080/admin")
    assert "Error de seguridad" in res
    assert "bloqueado" in res or "insegura" in res

    # Cloud metadata IP
    res = server.medium_archive_url("http://169.254.169.254/latest/meta-data")
    assert "Error de seguridad" in res

    # RFC 1918 Private range
    res = server.medium_archive_url("http://192.168.1.1/router")
    assert "Error de seguridad" in res

    # Non-http scheme
    res = server.medium_archive_url("file:///etc/passwd")
    assert "Error de seguridad" in res


def test_mcp_server_registers_exactly_the_five_documented_tools():
    """Drift guard: if a tool is added, removed, or renamed in server.py,
    this test fails. It pins only server.py's registered tool names — it does
    not inspect any doc's contents; failing is the signal to review the docs
    that describe this surface (README.md / SKILL.md / DOCUMENTATION.md / CLAUDE.md).

    Derives the registered tool names by parsing server.py's source via ast,
    rather than introspecting the live MCP server object, because server.py
    has a compat shim (MCPServer in MCP 2.x, FastMCP fallback in 1.x) whose
    registered-tool introspection APIs differ and are version-fragile.
    """
    tree = ast.parse((BASE_DIR / "server.py").read_text(encoding="utf-8"))
    tool_names = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "tool"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "server"
        ):
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    tool_names.add(kw.value.value)

    assert tool_names == {
        "medium_search_articles",
        "medium_get_article",
        "medium_get_stats",
        "medium_archive_url",
        "medium_export_archive",
    }


def test_archive_url_topic_traversal_sanitized():
    # Passing directory traversal in topic
    # PathSanitizer sanitizes "../../safe-topic" safely
    res = server.medium_archive_url("https://medium.com/@author/test-article-123456789abc", topic="../../safe-topic")
    assert "Error de seguridad: El tema" not in res
