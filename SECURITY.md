# Security Policy & Hardening Guidelines

## 1. Supported Versions

| Version | Supported | Security Audit Status |
| :--- | :---: | :--- |
| `main` (Latest) | ✅ Yes | Audited via Cloudflare `security-audit-skill` (Run 2: 0 active findings) |
| `< 1.0` | ❌ No | Deprecated / Vulnerable to unconfined writes and SSRF |

---

## 2. Security Architecture & Threat Model

`medium-vault` operates as both an offline web knowledge base archiver and a **Model Context Protocol (MCP)** server. In an agentic environment, untrusted input may originate from:
- AI agents executing autonomous actions based on LLM outputs or prompt-injected contexts.
- Remote content fetched from syndicated feeds or reader mirrors.

### Trust Boundaries & Defensive Controls

```
[MCP Client / AI Agent]
         │
         │ (1) Untrusted parameters (url, topic, output_zip_path)
         ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                      Defensive Gates                        │
 ├──────────────────────────────┬──────────────────────────────┤
 │   is_safe_url() Validation   │   PathSanitizer Confinement  │
 │   • Scheme allowlist (HTTP/S)│   • Directory traversal strip│
 │   • Localhost & Loopback blk │   • Strict exports/ bounds   │
 │   • RFC1918 & Cloud Metadata │   • relative_to() check      │
 │   • Anti-DNS Rebinding check │   • .zip extension check     │
 └──────────────┬───────────────┴──────────────┬───────────────┘
                │                              │
         (2) Outbound HTTP              (3) Filesystem I/O
                ▼                              ▼
        [External Web]               [Isolated Knowledge Base]
```

1. **Boundary B1: MCP Caller to Host Filesystem**:
   - `output_zip_path` in `medium_export_archive` is strictly confined within `knowledge_base/exports/`. Absolute escapes and relative path traversals (`../../`) are blocked.
   - Non-`.zip` extensions are rejected to prevent arbitrary file overwrites or executable drops.
   - `topic` parameters in `medium_archive_url` are sanitized with `PathSanitizer.sanitize()` and asserted with `topic_dir.relative_to(output_dir)`.

2. **Boundary B2: Archiver to Network Perimeter (Anti-SSRF)**:
   - `is_safe_url()` intercepts all outbound target URLs before dispatching HTTP requests.
   - Blocks RFC1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback addresses (`127.0.0.0/8`, `::1`), link-local metadata endpoints (`169.254.169.254`, `metadata.google.internal`), carrier-grade NAT (`100.64.0.0/10`), and IPv6 ULAs (`fc00::/7`).
   - Prevents DNS Rebinding and decimal/hex alternative notation bypasses (e.g. `2130706433`) through pre-request `socket.getaddrinfo` validation.

3. **Boundary B3: Asset Ingestion to Storage Availability**:
   - Downloads of inline images are capped at **25 MB** per asset with real-time stream chunk monitoring to prevent disk exhaustion attacks.

---

## 3. Cloudflare Security Audit Certification

The codebase has undergone a full 6-phase audit following the Cloudflare `security-audit-skill` standard:
- **Audit Run 1**: Identified 3 candidate vulnerabilities (High: arbitrary file overwrite; Medium: SSRF via fallback; Low: topic directory traversal).
- **Hardening & Retest (Run 2)**: All 3 vulnerabilities were verified as **RESOLVED** and refuted (`rejected`) against local execution invariants.
- **Audit Artifacts**:
  - [`audits/mediumm-run-2/REPORT.md`](audits/mediumm-run-2/REPORT.md)
  - [`audits/mediumm-run-2/FINDINGS-DETAIL.md`](audits/mediumm-run-2/FINDINGS-DETAIL.md)
  - [`audits/mediumm-run-2/coverage-ledger.json`](audits/mediumm-run-2/coverage-ledger.json)
  - [`audits/mediumm-run-2/findings.json`](audits/mediumm-run-2/findings.json)

---

## 4. Reporting a Vulnerability

If you discover a security vulnerability within `medium-vault`, please adhere to responsible disclosure practices:

1. **Do not create a public GitHub issue.**
2. Report the vulnerability via GitHub Private Security Advisory or send an email with the subject `[SECURITY] medium-vault vulnerability report` containing:
   - Affected component (`server.py`, `medium_archiver.py`).
   - Proof of Concept (PoC) or reproduction steps.
   - Potential impact and affected threat boundary.
3. We will acknowledge receipt within 48 hours and coordinate a fix and release.
