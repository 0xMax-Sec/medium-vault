import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from medium_archiver import ArchivedEntry, ArticleMetadata, LibraryManager


def test_library_manager_init_and_persist(tmp_path):
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    
    manager = LibraryManager(str(kb_dir))
    assert manager.manifest_file.exists() is False
    
    # Add a mock article directory and markdown
    article_folder = kb_dir / "idor" / "testing-idor-123456789abc"
    article_folder.mkdir(parents=True)
    article_file = article_folder / "article.md"
    article_file.write_text(
        "---\ntitle: Testing IDOR\nauthor: @alice\n---\n\n# Content about IDOR",
        encoding="utf-8"
    )
    
    entry = ArchivedEntry(
        title="Testing IDOR",
        author="@alice",
        published="2026-09-20",
        source_url="https://medium.com/@alice/testing-idor-123456789abc",
        clean_url="https://medium.com/@alice/testing-idor-123456789abc",
        post_hash="123456789abc",
        topic="idor",
        folder_rel_path="idor/testing-idor-123456789abc",
        retrieved_at="2026-09-20T12:00:00Z",
        file_size_kb=0.5,
        images_count=0
    )
    
    manager.add_entry(entry)
    assert manager.manifest_file.exists() is True
    
    # Reload library from manifest
    new_manager = LibraryManager(str(kb_dir))
    new_manager.load_or_rebuild()
    
    assert "123456789abc" in new_manager.entries
    loaded_entry = new_manager.entries["123456789abc"]
    assert loaded_entry.title == "Testing IDOR"
    assert loaded_entry.author == "@alice"
    assert loaded_entry.topic == "idor"


def test_library_manager_check_archived(tmp_path):
    kb_dir = tmp_path / "knowledge_base"
    kb_dir.mkdir()
    
    manager = LibraryManager(str(kb_dir))
    meta = ArticleMetadata(
        index=1,
        title="GraphQL Batching Attack",
        author="@bob",
        published="2026-09-20",
        source_url="https://medium.com/@bob/graphql-batching-attack-abcdef123456",
        clean_url="https://medium.com/@bob/graphql-batching-attack-abcdef123456",
        topic="graphql",
    )
    
    # Not archived initially
    is_archived, _ = manager.check_archived(meta)
    assert is_archived is False
    
    # Register entry
    entry = ArchivedEntry(
        title=meta.title,
        author=meta.author,
        published=meta.published,
        source_url=meta.source_url,
        clean_url=meta.clean_url,
        post_hash="abcdef123456",
        topic="graphql",
        folder_rel_path="graphql/graphql-batching-attack-abcdef123456",
        retrieved_at="2026-09-20T12:00:00Z",
        file_size_kb=1.0,
        images_count=0
    )
    manager.add_entry(entry)
    
    # Now check again
    is_archived_now, found_entry = manager.check_archived(meta)
    assert is_archived_now is True
    assert found_entry.post_hash == "abcdef123456"
