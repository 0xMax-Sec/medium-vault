# Graph Report - medium-vault  (2026-09-25)

## Corpus Check
- Corpus is ~16,894 words - fits in a single context window. You may not need a graph.

## Summary
- 196 nodes · 412 edges · 10 communities
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 28 edges (avg confidence: 0.9)
- Token cost: 158,902 input · 0 output

## Community Hubs (Navigation)
- Library Index & Dedup
- MCP Server & Security
- Archiver Coordinator & CLI
- Markdown Cleaning & Assets
- Path Sanitizing & Mojibake
- Feed Discovery
- Web Reader & Circuit Breaker
- Download State & Resume
- MCP Test Fixtures

## God Nodes (most connected - your core abstractions)
1. `LibraryManager` - 30 edges
2. `Medium-Vault Developer Guidance (CLAUDE.md)` - 20 edges
3. `Medium-Vault Technical Specification` - 20 edges
4. `PathSanitizer` - 19 edges
5. `MediumFeedDiscoverer` - 19 edges
6. `medium_archive_url()` - 19 edges
7. `DownloadStateManager` - 17 edges
8. `ArticleMetadata` - 16 edges
9. `Medium-Vault README Overview` - 16 edges
10. `clean_markdown_document()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `feedparser` --conceptually_related_to--> `MediumFeedDiscoverer`  [INFERRED]
  requirements.txt → medium_archiver.py
- `Filesystem-as-Store (No Database)` --rationale_for--> `LibraryManager`  [INFERRED]
  CLAUDE.md → medium_archiver.py
- `Deterministic UTF-8 Mojibake Repair` --conceptually_related_to--> `fix_mojibake()`  [EXTRACTED]
  DOCUMENTATION.md → medium_archiver.py
- `Medium-Vault Technical Specification` --references--> `fix_mojibake()`  [EXTRACTED]
  DOCUMENTATION.md → medium_archiver.py
- `Medium-Vault Developer Guidance (CLAUDE.md)` --references--> `clean_markdown_document()`  [EXTRACTED]
  CLAUDE.md → medium_archiver.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Medium Archiving Pipeline** — medium_archiver_mediumfeeddiscoverer, medium_archiver_librarymanager, medium_archiver_webreaderclient, medium_archiver_domsanitizerandassetbundler, medium_archiver_downloadstatemanager, medium_archiver_mediumarchiver [EXTRACTED 0.85]
- **Defensive Security Gates (Zero-Trust Hardening)** — medium_archiver_is_safe_url, medium_archiver_pathsanitizer, documentation_threat_model [EXTRACTED 0.85]
- **MCP Tool Documentation Surface (drift-coupled)** — documentation_spec, readme_overview, skills_medium_knowledge_base_skill_skill [INFERRED 0.85]

## Communities (10 total, 0 thin omitted)

### Community 0 - "Library Index & Dedup"
Cohesion: 0.09
Nodes (27): Any, Filesystem-as-Store (No Database), Library Manifest (.library_manifest.json), 3-Level Deduplication, ArchivedEntry, ArticleMetadata, LibraryManager, Metadata representing a discovered article from the RSS feed or archive. (+19 more)

### Community 1 - "MCP Server & Security"
Cohesion: 0.13
Nodes (35): CI Test Pipeline, Medium-Vault Developer Guidance (CLAUDE.md), Anti-SSRF / Anti-DNS-Rebinding Validation Gate, 25MB Image Download DoS Guard, Graphify Architecture Knowledge Graph, Filesystem Path Confinement Gate, Medium-Vault Technical Specification, Agentic Zero-Trust Threat Model (+27 more)

### Community 2 - "Archiver Coordinator & CLI"
Cohesion: 0.10
Nodes (16): Single-Engine Thin-Adapter Architecture, Console, main(), MediumArchiver, parse_arguments(), Download a remote image to dest_path. Returns (success: bool, final_filename:…, Coordinates discovery, extraction, asset management, and Markdown creation., Create standard YAML frontmatter block for Obsidian and Local RAG. (+8 more)

### Community 3 - "Markdown Cleaning & Assets"
Cohesion: 0.11
Nodes (20): 5-Stage HTML to Markdown Sanitization Pipeline, Shiki Dual-Theme Code Block Deduplication, Code-Fence Syntax Classification, clean_markdown_document(), DOMSanitizerAndAssetBundler, infer_code_language(), Parses HTML, cleans DOM noise, downloads inline assets, and compiles Markdown., Determine whether an <img> element is an author avatar or non-content icon. (+12 more)

### Community 4 - "Path Sanitizing & Mojibake"
Cohesion: 0.18
Nodes (15): Deterministic UTF-8 Mojibake Repair, fix_mojibake(), PathSanitizer, Repair UTF-8 byte sequences erroneously decoded as Latin-1 / ISO-8859-1…, Provides cross-platform filesystem path sanitization., Convert string to URL/filename safe slug., Alias for filename sanitization., Sanitize a string for safe usage as a directory or file name across Windows,… (+7 more)

### Community 5 - "Feed Discovery"
Cohesion: 0.17
Nodes (10): RSS 10-Item Cap Bypass via Monthly Archive Crawling, MediumFeedDiscoverer, Extract publication year from feedparser entry., Fetch Medium articles for a topic tag or publication, optionally across related…, Discover Medium articles across year/month static archive pages (e.g.…, Render a clean interactive summary table of discovered articles., Discovers and parses publicly syndicated articles from Medium tags., Strip tracking parameters such as source, utm_*, etc. from Medium URLs. (+2 more)

### Community 6 - "Web Reader & Circuit Breaker"
Cohesion: 0.16
Nodes (9): Mirror Rotation Circuit Breaker with Backoff+Jitter, Manages resilient HTTP requests with mirror fallbacks, circuit-breaking, and…, Check if mirror host is currently healthy (not on cool-down)., Put failing mirror on cool-down so other workers immediately avoid it., Sleep between requests to avoid rate limits., Generate browser headers with random User-Agent., Transforms canonical Medium URL into reader processed URL. Example:…, Fetch article HTML using reader mirrors with circuit-breaker failover,… (+1 more)

### Community 7 - "Download State & Resume"
Cohesion: 0.20
Nodes (4): Download State File (.download_state.json), Resumable Download Checkpointing, DownloadStateManager, Manages persistent state and checkpointing for batch downloads, enabling…

### Community 8 - "MCP Test Fixtures"
Cohesion: 0.67
Nodes (3): fixture, Isolate server.library to a temporary knowledge base directory., setup_isolated_kb()

## Knowledge Gaps
- **1 isolated node(s):** `MCP stdio Server Configuration`
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LibraryManager` connect `Library Index & Dedup` to `MCP Server & Security`, `Archiver Coordinator & CLI`, `Markdown Cleaning & Assets`?**
  _High betweenness centrality (0.218) - this node is a cross-community bridge._
- **Why does `Medium-Vault Developer Guidance (CLAUDE.md)` connect `MCP Server & Security` to `Library Index & Dedup`, `Archiver Coordinator & CLI`, `Markdown Cleaning & Assets`, `Path Sanitizing & Mojibake`, `Feed Discovery`, `Web Reader & Circuit Breaker`, `Download State & Resume`?**
  _High betweenness centrality (0.137) - this node is a cross-community bridge._
- **Why does `Medium-Vault Technical Specification` connect `MCP Server & Security` to `Library Index & Dedup`, `Archiver Coordinator & CLI`, `Markdown Cleaning & Assets`, `Path Sanitizing & Mojibake`, `Feed Discovery`, `Web Reader & Circuit Breaker`, `Download State & Resume`?**
  _High betweenness centrality (0.137) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `LibraryManager` (e.g. with `Filesystem-as-Store (No Database)` and `medium_archive_url()`) actually correct?**
  _`LibraryManager` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `PathSanitizer` (e.g. with `medium_archive_url()` and `medium_export_archive()`) actually correct?**
  _`PathSanitizer` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `MediumFeedDiscoverer` (e.g. with `feedparser` and `medium_archive_url()`) actually correct?**
  _`MediumFeedDiscoverer` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `MCP stdio Server Configuration` to the rest of the system?**
  _1 weakly-connected nodes found - possible documentation gaps or missing edges._