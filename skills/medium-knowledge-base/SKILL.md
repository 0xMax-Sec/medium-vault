---
name: medium-knowledge-base
description: "Universal & agnostic offline Medium knowledge base archiver and search engine. Use when researching technical topics (AI/LLM, software engineering, architecture, data science, cybersecurity, systems design), looking up tutorials or writeups, and archiving new articles locally with HD images."
---

# Medium-Vault: Universal Knowledge Base & Archiver (MCP + Skill)

Use this skill whenever you need in-depth articles, tutorials, technical writeups, architecture blueprints, or research breakdowns from over **1,275+ categorized offline Medium articles** and **6,300+ local HD diagrams**, or when archiving new articles from Medium.

---

## 🎯 When to Use

- **Technical Research & Prior Art:** When exploring libraries, frameworks, architectures, or methodologies (e.g. Transformers, LangChain, FastAPI, Kubernetes, React, System Design, OAuth, Distributed Systems), query the local knowledge base with zero latency.
- **Deep-Dives & Tutorial Retrieval:** Retrieve complete, clean, offline Markdown representations of engineering guides, case studies, and post-mortems with local HD diagrams.
- **Saving Online Research:** When discovering a valuable Medium article online, archive it locally on-demand with all inline images and diagrams downloaded in HD.
- **Token-Optimized Markdown for LLMs:** Clean and audit articles for consumption by AI agents (Claude Code, Antigravity, Cursor, Windsurf) without token bloat, Shiki dual-theme duplication, or encoding corruption.
- **Packaging & Portability (/archivefile):** Export knowledge collections or topic folders into standalone, portable zip archives for backups, team sharing, or syncing to Obsidian vaults.

---

## 🛠️ Tooling & Capabilities

### 1. Model Context Protocol (MCP) Tools

When connected via MCP (`medium-knowledge-base`), use the following tools:

| MCP Tool | Description | Example Arguments |
| :--- | :--- | :--- |
| `medium_search_articles` | Search indexed articles by keyword, technology, author, or topic (zero network latency). | `{"query": "Transformers Attention", "limit": 5}` |
| `medium_get_article` | Retrieve full article markdown, YAML frontmatter, and code blocks. | `{"identifier": "36fb7ad6bc03"}` |
| `medium_get_stats` | Inspect current metrics: article count, topics, disk usage, and local HD images. | `{}` |
| `medium_archive_url` | Download and bundle a single Medium article with local HD images. | `{"url": "https://medium.com/@...", "topic": "ai"}` |
| `medium_export_archive` | Export knowledge base into a portable zip archive file (/archivefile). | `{"topic": "python"}` |

### 2. CLI Direct Execution

If running directly in a terminal or when MCP is not attached:

```bash
# 1. Search local articles across any topic
python3 medium_archiver.py --search "FastAPI"
python3 medium_archiver.py --search "Transformers"
python3 medium_archiver.py --search "Architecture"

# 2. View local library statistics & disk usage
python3 medium_archiver.py --stats

# 3. Audit Markdown quality & encoding (read-only)
python3 medium_archiver.py --audit

# 4. Clean & fix Markdown in batch (dedup Shiki blocks, fix UTF-8 mojibake, retag syntax)
python3 medium_archiver.py --clean-markdown

# 5. Archive new topic batch with parallel workers (bypassing RSS 10 limit)
python3 medium_archiver.py --tag artificial-intelligence -c 6 -y
python3 medium_archiver.py --tag python -c 6 -y

# 6. Export knowledge base into a single zip file (/archivefile)
python3 medium_archiver.py --archive-file
```

---

## 🔬 Universal AI Research & Study Workflow

```
1. Concept or Problem Discovery
   │
   ├─ Technology or problem identified: e.g., "Next.js Server Actions" or "Vector Databases"
   │
   ▼
2. Query Local Medium Knowledge Base (0 network latency / 0 external requests)
   │
   ├─ Call `medium_search_articles(query="Vector Databases", limit=5)`
   ├─ Inspect returned excerpts, authors, topics, and post hashes
   │
   ▼
3. Retrieve Complete In-Depth Article
   │
   ├─ Call `medium_get_article(identifier="<post_hash>")`
   ├─ Extract exact code samples, architectural diagrams, and configuration patterns
   │
   ▼
4. Synthesis & Implementation
   │
   ├─ Apply patterns directly to current task or development project
   └─ Reference authoritative sources and original research
```

---

## 💎 Markdown Quality Guarantees for LLMs & Harnesses

All archived `.md` files in the library follow rigorous standards optimized for LLM token economy and syntactic comprehension:

1. **Zero Consecutive Duplicate Code Blocks:** Strips dual-theme Shiki (`github-light` / `github-dark`) artifacts rendered by web mirrors, saving ~13%–30% in prompt token overhead.
2. **Accurate Code Block Highlighting:** Code fences are intelligently tagged (`bash`, `http`, `json`, `sql`, `javascript`, `python`, or unadorned text) rather than incorrectly forced to `python`.
3. **Pristine UTF-8 Encoding:** Transparent repair of Latin-1/ISO-8859-1 mojibake ensures em-dashes (`—`), curly quotes (`’`), arrows (`→`), and special symbols remain intact for exact embedding matches.
4. **Offline Asset Resolution:** Images are stored locally (`./images/image_*.png`) and referenced with relative markdown syntax, preventing broken external CDNs.
