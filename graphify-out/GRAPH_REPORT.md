# Graph Report - mediumm  (2026-09-19)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 125 nodes · 208 edges · 8 communities (7 shown, 1 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 4 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- LibraryManager
- medium_archiver.py
- Path
- MediumFeedDiscoverer
- WebReaderClient
- DownloadStateManager
- clean_markdown_document
- medium_archive_url

## God Nodes (most connected - your core abstractions)
1. `LibraryManager` - 16 edges
2. `DownloadStateManager` - 13 edges
3. `ArticleMetadata` - 12 edges
4. `MediumFeedDiscoverer` - 12 edges
5. `WebReaderClient` - 10 edges
6. `MediumArchiver` - 9 edges
7. `DOMSanitizerAndAssetBundler` - 8 edges
8. `medium_archive_url()` - 8 edges
9. `ArchivedEntry` - 7 edges
10. `main()` - 6 edges

## Surprising Connections (you probably didn't know these)
- `medium_archive_url()` --uses--> `LibraryManager`  [INFERRED]
  server.py → medium_archiver.py
- `medium_archive_url()` --uses--> `ArticleMetadata`  [INFERRED]
  server.py → medium_archiver.py
- `medium_archive_url()` --uses--> `MediumFeedDiscoverer`  [INFERRED]
  server.py → medium_archiver.py

## Import Cycles
- None detected.

## Communities (8 total, 1 thin omitted)

### Community 0 - "LibraryManager"
Cohesion: 0.14
Nodes (13): ArchivedEntry, LibraryManager, Metadata of an article stored in the local knowledge base., Manages local knowledge base indexing, cross-topic deduplication, verification…, Extract Medium post ID hash (e.g. 1bd085d4a126 from slug-1bd085d4a126)., Normalize title for fuzzy/case-insensitive comparison., Scan disk and synchronize local knowledge base manifest., Persist manifest JSON to disk. (+5 more)

### Community 1 - "medium_archiver.py"
Cohesion: 0.14
Nodes (16): ArticleMetadata, main(), MediumArchiver, parse_arguments(), PathSanitizer, Coordinates discovery, extraction, asset management, and Markdown creation., Create standard YAML frontmatter block for Obsidian and Local RAG., Archive a single article into topic_dir. (+8 more)

### Community 2 - "Path"
Cohesion: 0.13
Nodes (12): DOMSanitizerAndAssetBundler, Parses HTML, cleans DOM noise, downloads inline assets, and compiles Markdown., Determine whether an <img> element is an author avatar or non-content icon., Normalize Medium and mirror image URLs to request maximum resolution (HD).…, Download a remote image to dest_path. Returns (success: bool, final_filename:…, Cleans the DOM, downloads inline images in HD, updates references to relative…, Render a visual directory tree of the generated knowledge base., Path (+4 more)

### Community 3 - "MediumFeedDiscoverer"
Cohesion: 0.17
Nodes (9): Console, MediumFeedDiscoverer, Render a clean interactive summary table of discovered articles., Discovers and parses publicly syndicated articles from Medium tags., Strip tracking parameters such as source, utm_*, etc. from Medium URLs., Normalize topic to valid Medium tag slugs and cybersecurity acronym aliases., Extract publication year from feedparser entry., Fetch Medium articles for a topic tag or publication, optionally across related… (+1 more)

### Community 4 - "WebReaderClient"
Cohesion: 0.17
Nodes (8): Manages resilient HTTP requests with mirror fallbacks, circuit-breaking, and…, Check if mirror host is currently healthy (not on cool-down)., Put failing mirror on cool-down so other workers immediately avoid it., Sleep between requests to avoid rate limits., Generate browser headers with random User-Agent., Transforms canonical Medium URL into reader processed URL. Example:…, Fetch article HTML using reader mirrors with circuit-breaker failover,…, WebReaderClient

### Community 6 - "clean_markdown_document"
Cohesion: 0.22
Nodes (8): Any, clean_markdown_document(), fix_mojibake(), infer_code_language(), Repair UTF-8 byte sequences erroneously decoded as Latin-1 / ISO-8859-1…, Infers the real programming or format language for a Markdown code block. Fixes…, Audits and cleans a Markdown document: 1. Fixes mojibake in frontmatter and…, Audit and optionally clean in-place all article.md files across the knowledge…

### Community 7 - "medium_archive_url"
Cohesion: 0.22
Nodes (9): medium_archive_url(), medium_get_article(), medium_get_stats(), medium_search_articles(), Get full content of an article. Args: identifier: Post hash (e.g.…, Return knowledge base statistics and topic counts., Download and archive a specific article URL. Args: url: Full Medium article URL…, Search across all indexed Medium articles in the local knowledge base. Args:… (+1 more)

## Knowledge Gaps
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `WebReaderClient` connect `WebReaderClient` to `medium_archiver.py`, `MediumFeedDiscoverer`?**
  _High betweenness centrality (0.204) - this node is a cross-community bridge._
- **Why does `LibraryManager` connect `LibraryManager` to `medium_archiver.py`, `MediumFeedDiscoverer`, `clean_markdown_document`, `medium_archive_url`?**
  _High betweenness centrality (0.201) - this node is a cross-community bridge._
- **Why does `DownloadStateManager` connect `DownloadStateManager` to `medium_archiver.py`?**
  _High betweenness centrality (0.144) - this node is a cross-community bridge._
- **Should `LibraryManager` be split into smaller, more focused modules?**
  _Cohesion score 0.1383399209486166 - nodes in this community are weakly interconnected._
- **Should `medium_archiver.py` be split into smaller, more focused modules?**
  _Cohesion score 0.13852813852813853 - nodes in this community are weakly interconnected._
- **Should `Path` be split into smaller, more focused modules?**
  _Cohesion score 0.13071895424836602 - nodes in this community are weakly interconnected._