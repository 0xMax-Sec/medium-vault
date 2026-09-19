---
name: medium-knowledge-base
description: "Offline Medium bug bounty and cybersecurity writeup knowledge base. Use when hunting vulnerabilities, researching prior-art on bug classes (IDOR, SSRF, GraphQL, 2FA bypass, RCE, OAuth, Business Logic, CSPT), looking up CVEs, or archiving new writeups locally with HD images."
---

# Medium Bug Bounty & Security Knowledge Base (MCP + Skill)

Use this skill whenever you need real-world bug bounty writeups, exploitation methodologies, verified CVE breakdowns, or authorization bypass techniques from over **1,275+ categorized offline Medium articles** and **6,300+ local HD diagrams**.

---

## 🎯 When to Use

- **Vulnerability Hunting & Prior Art:** When analyzing a target technology (e.g., Jenkins, GraphQL, Next.js, Django, Spring Boot, Supabase, OAuth providers) or discovering an endpoint, query the local base first to find how other hunters exploited similar endpoints.
- **Payload & Bypass Discovery:** When testing tricky filters (e.g., SSRF bypasses, WAF evasion, mXSS, blind file uploads, 2FA bypasses, CSPT / path traversal), lookup writeups containing concrete proof-of-concept requests and responses.
- **Report Drafting & Severity Justification:** When writing reports for Bugcrowd, HackerOne, or YesWeHack, reference local writeups to articulate real-world business impact and CVSS score alignment.
- **Saving New Research:** When discovering a valuable Medium article online, archive it locally with full offline assets and HD diagrams so it's permanently available.
- **Auditing & Cleaning Markdown Quality:** When preparing articles for LLM consumption (Claude Code, Oz, Antigravity) without token waste or encoding corruption.
- **Packaging & Sharing (/archivefile):** When you need to bundle or export the knowledge base into a zip file for backup or cross-workspace transfer.

---

## 🛠️ Tooling & Capabilities

### 1. Model Context Protocol (MCP) Tools

When connected via MCP (`medium-knowledge-base`), use the following tools:

| MCP Tool | Description | Example Arguments |
| :--- | :--- | :--- |
| `medium_search_articles` | Search indexed writeups by vulnerability, keyword, author, or topic (zero network latency). | `{"query": "GraphQL IDOR", "limit": 5}` |
| `medium_get_article` | Retrieve full article markdown, YAML frontmatter, and code blocks. | `{"identifier": "36fb7ad6bc03"}` |
| `medium_get_stats` | Inspect current count of articles, topics, and local HD images. | `{}` |
| `medium_archive_url` | Download and bundle a single Medium writeup with local HD images. | `{"url": "https://medium.com/@...", "topic": "bug-bounty"}` |
| `medium_export_archive` | Export knowledge base into a portable zip archive file (/archivefile). | `{"topic": "bug-bounty"}` |

### 2. CLI Direct Execution

If running directly in a terminal or when MCP is not attached:

```bash
# 1. Search local writeups
python3 medium_archiver.py --search "SSRF"
python3 medium_archiver.py --search "Client-Side Path Traversal"
python3 medium_archiver.py --search "Account Takeover"

# 2. View local library statistics & disk usage
python3 medium_archiver.py --stats

# 3. Audit Markdown quality & encoding (read-only)
python3 medium_archiver.py --audit

# 4. Clean & fix Markdown in batch (dedup Shiki blocks, fix UTF-8 mojibake, retag syntax)
python3 medium_archiver.py --clean-markdown

# 5. Archive new topic batch with parallel workers (bypassing RSS 10 limit)
python3 medium_archiver.py --tag bug-bounty -c 6 -y

# 6. Export knowledge base into a single zip file (/archivefile)
python3 medium_archiver.py --archive-file
```

---

## 🔬 Standard Bug Bounty Research Workflow

```
1. Reconnaissance / Surface Discovery
   │
   ├─ Target technology identified: e.g., "GraphQL /graphql" or "Django"
   │
   ▼
2. Query Local Medium Knowledge Base (0 network overhead)
   │
   ├─ Call `medium_search_articles(query="GraphQL bypass", limit=5)`
   ├─ Inspect returned excerpts, titles, and post hashes
   │
   ▼
3. Retrieve Detailed Writeup
   │
   ├─ Call `medium_get_article(identifier="<post_hash>")`
   ├─ Extract exact HTTP request structures, parameter anomalies, and payloads
   │
   ▼
4. Test in Target Scope
   │
   ├─ Adapt payloads to authorized target boundaries
   └─ Document findings with reference to prior-art writeup
```

---

## 💎 Markdown Quality Guarantees for LLMs & Harnesses

All archived `.md` files in the library follow rigorous standards optimized for LLM token economy and syntactic comprehension:

1. **Zero Consecutive Duplicate Code Blocks:** Strips dual-theme Shiki (`github-light` / `github-dark`) artifacts rendered by web mirrors, saving ~13%–30% in prompt token overhead.
2. **Accurate Code Block Highlighting:** Code fences are intelligently tagged (`bash`, `http`, `json`, `sql`, `javascript`, `python`, or unadorned text) rather than incorrectly forced to `python`.
3. **Pristine UTF-8 Encoding:** Transparent repair of Latin-1/ISO-8859-1 mojibake ensures em-dashes (`—`), curly quotes (`’`), arrows (`→`), and special symbols remain intact for exact embedding matches.
4. **Offline Asset Resolution:** Images are stored locally (`./images/image_*.png`) and referenced with relative markdown syntax, preventing broken external CDNs.
