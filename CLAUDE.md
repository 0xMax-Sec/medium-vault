# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Medium-Vault**: a domain-agnostic offline archiver + searchable knowledge base for Medium articles, exposed three ways from the same code — a **CLI**, an **MCP stdio server**, and an **AI skill**. It scrapes Medium (bypassing the RSS 10-item cap via monthly archive crawling), deduplicates, sanitizes HTML→Markdown for LLM token economy, downloads images in HD, and stores everything as local Markdown. No database — the filesystem *is* the store.

## Commands

```bash
# Tests (CI runs exactly this across Python 3.10–3.13)
pytest tests/ -v
pytest tests/test_sanitizer.py::test_name   # single test

# Lint (ruff cache present locally; not run in CI)
ruff check .

# Run the MCP server (stdio transport — this is what .mcp.json launches)
python3 server.py

# CLI (see medium_archiver.py parse_arguments for the full flag set)
python3 medium_archiver.py --search "FastAPI"          # query local KB, zero network
python3 medium_archiver.py --stats                     # article count, disk, images
python3 medium_archiver.py --audit                     # read-only markdown quality report
python3 medium_archiver.py --clean-markdown            # batch-fix: dedup Shiki blocks, mojibake, retag code fences
python3 medium_archiver.py --tag <topic> -c 6 -y       # archive a tag with 6 workers, non-interactive (--topic is an alias for --tag)
python3 medium_archiver.py --archive-file              # export KB → portable zip
# Single-URL archiving is MCP-only (medium_archive_url tool), not a CLI flag
```

A `.venv/` (Python 3.13) exists; `.mcp.json` and docs invoke the interpreter as `python3`.

## Architecture

**`medium_archiver.py` is the entire engine** (~2600 lines, one file by design). `server.py` and the skill are thin adapters that import from it — put core logic here, never duplicate it in the wrappers. The pipeline, in dependency order within that file:

1. **`MediumFeedDiscoverer`** — finds article URLs. RSS for recent, plus recursive monthly `/archive/YYYY/MM` crawling (2024–2026) to defeat the RSS 10-item limit. Also normalizes topic aliases across domains.
2. **`LibraryManager`** — the central index, persisted to `knowledge_base/.library_manifest.json`. **This manifest is the source of truth for dedup**, which runs at 3 levels: Medium post hash (e.g. `40a8201218a3`) → sanitized canonical URL (strips `utm_*`/`source`/`ref`/`gi`/`sk`/`responsesopen`) → fuzzy title match. `extract_post_hash()` is the primary key generator.
3. **`WebReaderClient`** — fetches through rotating reader mirrors with a circuit breaker (exponential backoff + jitter isolates failing hosts).
4. **`DOMSanitizerAndAssetBundler`** — BeautifulSoup strips scripts/ads/duplicate dark-theme code blocks, downloads inline images HD (25 MB cap per image = DoS guard), then `markdownify` + `clean_markdown_document`.
5. **`DownloadStateManager`** — checkpoints the queue to `.download_state.json` so `Ctrl+C` resumes exactly where it stopped (`--clean-state` to reset).
6. **`MediumArchiver`** — the coordinator that wires 1–5 together; both the CLI `main()` and the MCP server instantiate this.

Output layout: `knowledge_base/<topic>/<article-title>/article.md` (YAML frontmatter) + `images/*.png`, referenced with relative paths.

**MCP surface (`server.py`)** exposes 5 tools: `medium_search_articles`, `medium_get_article`, `medium_get_stats`, `medium_archive_url`, `medium_export_archive`. It has a compat shim importing `MCPServer` (MCP 2.x) with a `FastMCP` fallback (1.x), and forces console output to stderr so stdout stays clean for the stdio protocol. `MEDIUM_KNOWLEDGE_BASE` env var overrides the KB path.

**Skill (`skills/medium-knowledge-base/SKILL.md`)** documents the same tools/CLI for agents. When you add or rename a tool or flag, update `server.py`, `SKILL.md`, `README.md`, and `DOCUMENTATION.md` together — they drift easily.

## Security invariants (do not weaken)

This code fetches attacker-influenced URLs and writes files from remote content, so guards are load-bearing, not decoration:

- **`is_safe_url()`** — anti-SSRF / anti-DNS-rebinding. Every outbound fetch must route through it. Do not add a fetch path that skips it.
- **`PathSanitizer`** — confines all writes under the KB dir (anti-traversal). Any code deriving a filesystem path from remote data (title, slug, topic) must pass through it.
- **`medium_export_archive`** — zip exports are confined to `exports/`.
- Image download has a 25 MB cap; keep resource limits when touching the fetch/bundle path.

CI history shows Bandit + Semgrep SAST runs; changes to URL handling or file writes are the highest-risk edits here.

## Repo conventions

- **All data is gitignored** — `knowledge_base/`, `exports/`, `*.zip`, `.download_state.json`, `*.log`. The repo tracks *code only*; the archive lives on local disk (manifest currently indexes thousands of articles).
- **`medium-scraper/` and `MediumScraper/` are vendored reference repos** (own `.git`, gitignored) — not part of this project's build or tests. Don't edit them as if they were.
- **`graphify-out/`** is a generated code-knowledge-graph of this repo (open `graph.html`); regenerate rather than hand-edit.
- `DOCUMENTATION.md` (Spanish) is the deep technical spec — consult it for the threat model and pipeline internals; `README.md` is the user-facing overview.

## Note

A Codex config exists at `~/.codex/config.toml`. To import its MCP servers / commands / skills into Claude Code, reply `/import` to scan, then `/import --yes=<digest>` to apply.
