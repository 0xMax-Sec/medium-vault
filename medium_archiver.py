#!/usr/bin/env python3
"""
medium_archiver.py - Topic-based Web Reader and Knowledge Base Archiver for Medium.

Discovers publicly syndicated Medium posts by topic/tag, fetches and parses
full article content via resilient reader fallbacks, downloads inline media locally,
and archives structured GitHub-Flavored Markdown with YAML frontmatter for Obsidian
vaults and Local RAG pipelines.

Usage:
    python3 medium_archiver.py --tag security --limit 3
    python3 medium_archiver.py --tag python --output-dir my_vault -y
    python3 medium_archiver.py  # Interactive prompt mode
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ipaddress
import json
import logging
import mimetypes
import os
from pathlib import Path
import random
import re
import signal
import socket
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
import feedparser
from markdownify import markdownify as md
import requests
from requests.adapters import HTTPAdapter
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.tree import Tree
import urllib3
import yaml

# Suppress insecure request warnings if encountered during fallback
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Standard desktop User-Agents for clean browser emulation
DESKTOP_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0"
    ),
]

DEFAULT_READERS = [
    "https://freedium-mirror.cfd/",
    "https://freedium.cfd/",
]

BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def is_safe_url(url: str) -> Tuple[bool, str]:
    """
    Validates outbound URLs to prevent SSRF against loopback, private networks,
    and cloud instance metadata endpoints (RFC 1918 / RFC 3927).
    """
    if not url:
        return False, "URL vacía"
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"Esquema no permitido: '{parsed.scheme}' (solo http/https)"
        hostname = parsed.hostname
        if not hostname:
            return False, "Nombre de host ausente en la URL"

        lower_host = hostname.lower().strip(".")
        if lower_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"):
            return False, "Acceso a localhost/loopback o metadatos bloqueado por seguridad"

        # Check IP literal directly
        try:
            ip_obj = ipaddress.ip_address(lower_host)
            for net in BLOCKED_IP_NETWORKS:
                if ip_obj in net:
                    return False, f"Dirección IP privada o reservada bloqueada: {ip_obj}"
        except ValueError:
            pass

        # Resolve hostname to detect DNS rebinding to internal addresses
        try:
            addr_info = socket.getaddrinfo(lower_host, None)
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                ip_obj = ipaddress.ip_address(ip_str)
                for net in BLOCKED_IP_NETWORKS:
                    if ip_obj in net:
                        return False, f"El host '{hostname}' resuelve a una IP interna ({ip_obj})"
        except socket.gaierror:
            # Domain could not be resolved (will fail safely on fetch, not internal)
            pass

        return True, "OK"
    except Exception as exc:
        return False, f"Error validando URL: {exc}"


@dataclass
class ArticleMetadata:
    """Metadata representing a discovered article from the RSS feed or archive."""

    index: int
    title: str
    author: str
    published: str
    source_url: str
    clean_url: str
    topic: str
    summary_html: str = ""
    year: Optional[int] = None
    already_archived: bool = False
    archived_location: Optional[str] = None


@dataclass
class ArchivedEntry:
    """Metadata of an article stored in the local knowledge base."""

    title: str
    author: str
    published: str
    source_url: str
    clean_url: str
    post_hash: str
    topic: str
    folder_rel_path: str
    retrieved_at: str
    file_size_kb: float
    images_count: int


# Backward compatibility alias
LibraryEntry = ArchivedEntry


def fix_mojibake(text: str) -> Tuple[str, int]:
    """
    Repair UTF-8 byte sequences erroneously decoded as Latin-1 / ISO-8859-1 (Mojibake).
    E.g. 'â€™' -> '’', 'â€”' -> '—', 'â€“' -> '–', 'Ã¡' -> 'á', 'Ã©' -> 'é'.
    """
    fixes = 0

    def _rep(m):
        nonlocal fixes
        raw = m.group(0)
        try:
            decoded = raw.encode("latin1").decode("utf-8")
            fixes += 1
            return decoded
        except UnicodeError:
            return raw

    pattern = re.compile(r"[\xc2-\xf4][\x80-\xbf]{1,3}")
    new_text = pattern.sub(_rep, text)
    return new_text, fixes


def infer_code_language(code: str, current_lang: str = "") -> str:
    """
    Infers the real programming or format language for a Markdown code block.
    Fixes erroneous hardcoded 'python' tags and tags bash, http, json, sql, html, javascript, etc.
    """
    stripped = code.strip()
    if not stripped:
        return ""

    # Check HTTP request / response
    if re.match(r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+/\S*\s+HTTP/\d", stripped) or stripped.startswith("HTTP/1.") or stripped.startswith("HTTP/2"):
        return "http"

    # Check JSON
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        try:
            json.loads(stripped)
            return "json"
        except Exception:
            pass

    # Check Bash / Shell
    bash_triggers = (
        r"^\s*(\$|#)\s+",
        r"#!/bin/(bash|sh|zsh)",
        r"^\s*(?:sudo\s+)?(curl\s+(?:-[a-zA-Z]|https?://|\"[^\"]+\"|\'[^\']+\')|git\s+[a-z]+|docker\s+[a-z]+|kubectl\s+[a-z]+|npm\s+[a-z]+|npx\s+[a-z]+|yarn\s+[a-z]+|pnpm\s+[a-z]+|pip\s+install|python3?\s+\S+\.py|chmod\s+[0-9+x]+|chown\s+|cat\s+\S+|grep\s+|mkdir\s+-?p?|rm\s+-rf?|cd\s+\S+|echo\s+[\"']|export\s+[A-Z_]+=)",
        r"^\s*(subfinder|nuclei|httpx|ffuf|gobuster|dirsearch|sqlmap|amass|katana|gau|waybackurls|burpsuite|wfuzz)\s+(?:-[a-zA-Z]|https?://|\S+)",
    )
    for b_pat in bash_triggers:
        if re.search(b_pat, stripped, re.MULTILINE):
            return "bash"

    # Check SQL
    if re.search(r"\b(SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+.+\s+SET|DELETE\s+FROM|UNION\s+(ALL\s+)?SELECT|DROP\s+TABLE|CREATE\s+TABLE)\b", stripped, re.IGNORECASE):
        return "sql"

    # Check HTML/XML
    if re.match(r"^\s*<(!DOCTYPE|html|head|body|div|script|svg|iframe|a|p|span|table|form|\?xml)\b", stripped, re.IGNORECASE):
        return "html"

    # Check JavaScript / TypeScript
    js_triggers = (
        r"\b(console\.log|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|document\.getElementById|window\.location|addEventListener|fetch\(|require\()\b",
        r"=>\s*\{",
        r"function\s+\w+\s*\(",
    )
    for js_pat in js_triggers:
        if re.search(js_pat, stripped):
            return "javascript"

    # Check Real Python
    py_triggers = (
        r"^\s*(import\s+\w+|from\s+\w+\s+import|def\s+\w+\s*\(.*?\)\s*:|class\s+\w+.*?:|if\s+__name__\s*==\s*['\"]__main__['\"]:)",
        r"^\s*elif\s+.*:",
        r"\bprint\s*\(",
    )
    for py_pat in py_triggers:
        if re.search(py_pat, stripped, re.MULTILINE):
            return "python"

    # If currently tagged python but none of the python triggers matched:
    if current_lang.lower() == "python":
        return ""

    return current_lang


def clean_markdown_document(text: str) -> Tuple[str, Dict[str, int]]:
    """
    Audits and cleans a Markdown document:
    1. Fixes mojibake in frontmatter and body.
    2. Deduplicates consecutive identical code blocks (Freedium Shiki artifacts).
    3. Infers correct code block syntax highlighting languages.
    4. Normalizes redundant blank lines.
    """
    stats = {"mojibake_fixed": 0, "dups_removed": 0, "code_langs_retagged": 0}

    # 1. Fix Mojibake
    text, stats["mojibake_fixed"] = fix_mojibake(text)

    # 2. Dedup consecutive identical code blocks and retag language
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            fence_start = line.rstrip()
            raw_lang = fence_start[3:].strip()
            block_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block_lines.append(lines[i])
                i += 1
            i += 1
            block_content = "".join(block_lines)

            # Lookahead: remove identical consecutive code blocks
            while True:
                j = i
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                if j < len(lines) and lines[j].strip().startswith("```"):
                    next_block_lines = []
                    k = j + 1
                    while k < len(lines) and not lines[k].strip().startswith("```"):
                        next_block_lines.append(lines[k])
                        k += 1
                    next_block_content = "".join(next_block_lines)
                    if block_content.strip() and block_content.strip() == next_block_content.strip():
                        stats["dups_removed"] += 1
                        i = k + 1
                        continue
                break

            new_lang = infer_code_language(block_content, raw_lang)
            if new_lang != raw_lang:
                stats["code_langs_retagged"] += 1

            out.append(f"```{new_lang}\n" if new_lang else "```\n")
            out.extend(block_lines)
            out.append("```\n")
        else:
            out.append(line)
            i += 1

    res = "".join(out)
    res = re.sub(r"\n{3,}", "\n\n", res).strip() + "\n"
    return res, stats


class LibraryManager:
    """
    Manages local knowledge base indexing, cross-topic deduplication,
    verification of already downloaded articles, and internal search.
    """

    def __init__(self, base_dir: Union[str, Path], console: Optional[Console] = None):
        self.base_dir = Path(base_dir)
        self.console = console or Console(file=sys.stderr, quiet=True)
        self._lock = threading.RLock()
        self.manifest_path = self.base_dir / ".library_manifest.json"
        self.entries: Dict[str, ArchivedEntry] = {}
        self.url_map: Dict[str, str] = {}
        self.title_map: Dict[str, str] = {}
        self.load_or_rebuild()

    @property
    def manifest_file(self) -> Path:
        return self.manifest_path

    @manifest_file.setter
    def manifest_file(self, value: Union[str, Path]) -> None:
        self.manifest_path = Path(value)

    @staticmethod
    def extract_post_hash(url: str) -> Optional[str]:
        """Extract Medium post ID hash (e.g. 1bd085d4a126 from slug-1bd085d4a126)."""
        if not url:
            return None
        m = re.search(r"-([a-f0-9]{8,16})(?:[/?#]|$)", url)
        if m:
            return m.group(1).lower()
        return None

    @staticmethod
    def normalize_title(title: str) -> str:
        """Normalize title for fuzzy/case-insensitive comparison."""
        if not title:
            return ""
        t = re.sub(r"[^\w\s]", "", title.lower())
        return re.sub(r"\s+", " ", t).strip()

    def load_or_rebuild(self, force_rebuild: bool = False) -> None:
        """Scan disk and synchronize local knowledge base manifest."""
        with self._lock:
            if not self.base_dir.exists():
                return

            if not force_rebuild and self.manifest_path.exists():
                try:
                    with open(self.manifest_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.entries.clear()
                    self.url_map.clear()
                    self.title_map.clear()
                    for item in data.get("articles", []):
                        entry = ArchivedEntry(**item)
                        key = entry.post_hash or entry.clean_url or self.normalize_title(entry.title)
                        if key:
                            self.entries[key] = entry
                            if entry.clean_url:
                                self.url_map[entry.clean_url] = key
                            norm_title = self.normalize_title(entry.title)
                            if norm_title:
                                self.title_map[norm_title] = key
                    return
                except Exception:
                    pass

            self.entries.clear()
            self.url_map.clear()
            self.title_map.clear()

            for article_path in self.base_dir.rglob("article.md"):
                try:
                    folder = article_path.parent
                    rel_path = str(folder.relative_to(self.base_dir))
                    text = article_path.read_text(encoding="utf-8", errors="replace")

                    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
                    if not m:
                        continue
                    fm = yaml.safe_load(m.group(1)) or {}

                    title = fm.get("title", folder.name)
                    author = fm.get("author", "Unknown Author")
                    published = fm.get("published", "")
                    source_url = fm.get("source_url", "")
                    clean_url = MediumFeedDiscoverer.sanitize_url(source_url) if source_url else ""
                    topic = fm.get("topic", folder.parent.name)
                    retrieved_at = fm.get("retrieved_at", "")

                    post_hash = self.extract_post_hash(source_url) or self.extract_post_hash(clean_url)
                    key = post_hash or clean_url or self.normalize_title(title)
                    if not key:
                        continue

                    images_dir = folder / "images"
                    img_count = len(list(images_dir.glob("*"))) if images_dir.exists() else 0
                    size_kb = article_path.stat().st_size / 1024.0

                    entry = ArchivedEntry(
                        title=title,
                        author=author,
                        published=published,
                        source_url=source_url,
                        clean_url=clean_url,
                        post_hash=post_hash or "",
                        topic=topic,
                        folder_rel_path=rel_path,
                        retrieved_at=retrieved_at,
                        file_size_kb=size_kb,
                        images_count=img_count,
                    )
                    self.entries[key] = entry
                    if clean_url:
                        self.url_map[clean_url] = key
                    norm_title = self.normalize_title(title)
                    if norm_title:
                        self.title_map[norm_title] = key
                except Exception:
                    continue

            if self.entries or self.manifest_path.exists():
                self.save_manifest()

    def add_entry(self, entry: ArchivedEntry) -> None:
        """Add or update an archived entry directly in the library."""
        with self._lock:
            key = entry.post_hash or entry.clean_url or self.normalize_title(entry.title)
            if key:
                self.entries[key] = entry
                if entry.clean_url:
                    self.url_map[entry.clean_url] = key
                norm_t = self.normalize_title(entry.title)
                if norm_t:
                    self.title_map[norm_t] = key
                self.save_manifest()

    def save_manifest(self) -> None:
        """Persist manifest JSON to disk."""
        with self._lock:
            if not self.base_dir.exists():
                return
            data = {
                "version": "1.0",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "total_articles": len(self.entries),
                "articles": [asdict(e) for e in self.entries.values()],
            }
            try:
                temp_manifest = self.manifest_path.with_suffix(".tmp")
                with open(temp_manifest, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                temp_manifest.replace(self.manifest_path)
            except Exception:
                pass

    def check_archived(self, metadata: ArticleMetadata) -> Tuple[bool, Optional[ArchivedEntry]]:
        """
        Check if an article is already downloaded in the knowledge base,
        matching by post ID hash, clean URL, or normalized title across all topics.
        """
        with self._lock:
            post_hash = self.extract_post_hash(metadata.clean_url) or self.extract_post_hash(metadata.source_url)
            if post_hash and post_hash in self.entries:
                return True, self.entries[post_hash]

            if metadata.clean_url in self.url_map:
                key = self.url_map[metadata.clean_url]
                return True, self.entries.get(key)

            norm_title = self.normalize_title(metadata.title)
            if norm_title and norm_title in self.title_map:
                key = self.title_map[norm_title]
                return True, self.entries.get(key)

            return False, None

    def register_article(self, metadata: ArticleMetadata, article_dir: Path) -> None:
        """Register newly archived article in manifest."""
        with self._lock:
            rel_path = str(article_dir.relative_to(self.base_dir))
            article_file = article_dir / "article.md"
            size_kb = article_file.stat().st_size / 1024.0 if article_file.exists() else 0.0
            images_dir = article_dir / "images"
            img_count = len(list(images_dir.glob("*"))) if images_dir.exists() else 0

            post_hash = self.extract_post_hash(metadata.clean_url) or self.extract_post_hash(metadata.source_url)
            key = post_hash or metadata.clean_url or self.normalize_title(metadata.title)

            entry = ArchivedEntry(
                title=metadata.title,
                author=metadata.author,
                published=metadata.published,
                source_url=metadata.source_url,
                clean_url=metadata.clean_url,
                post_hash=post_hash or "",
                topic=metadata.topic,
                folder_rel_path=rel_path,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                file_size_kb=size_kb,
                images_count=img_count,
            )
            self.entries[key] = entry
            if metadata.clean_url:
                self.url_map[metadata.clean_url] = key
            norm_t = self.normalize_title(metadata.title)
            if norm_t:
                self.title_map[norm_t] = key
            self.save_manifest()

    def search(self, query: str) -> List[ArchivedEntry]:
        """Search local library by title, author, topic, or source URL."""
        q = query.lower().strip()
        results = []
        with self._lock:
            for entry in self.entries.values():
                searchable = (
                    f"{entry.title} {entry.author} {entry.topic} {entry.source_url} {entry.folder_rel_path}"
                ).lower()
                if q in searchable:
                    results.append(entry)
        return results

    def render_search_results(self, query: str, results: List[ArchivedEntry]) -> None:
        """Render beautiful search results table."""
        if not results:
            self.console.print(
                Panel.fit(
                    f"[yellow]No se encontraron artículos en la biblioteca local con el término:[/] [bold cyan]\"{query}\"[/bold cyan]\n"
                    f"[dim]Total artículos en biblioteca:[/] {len(self.entries)}",
                    border_style="yellow",
                )
            )
            return

        table = Table(
            title=f":mag: [bold cyan]Buscador Interno de Biblioteca:[/] \"{query}\" ([green]{len(results)} artículos encontrados[/green])",
            border_style="bright_blue",
            header_style="bold magenta",
            show_lines=True,
        )
        table.add_column("#", justify="center", style="bold yellow", width=4)
        table.add_column("Título", style="bold white", ratio=4)
        table.add_column("Autor", style="green", ratio=2)
        table.add_column("Tema", style="cyan", ratio=2)
        table.add_column("Imgs", justify="center", style="magenta", width=6)
        table.add_column("Ruta Local / Carpeta", style="dim underline", ratio=3)

        for idx, item in enumerate(results, 1):
            table.add_row(
                str(idx),
                item.title,
                item.author,
                f"#{item.topic}",
                str(item.images_count),
                item.folder_rel_path,
            )

        self.console.print()
        self.console.print(table)
        self.console.print()

    def render_library_stats(self) -> None:
        """Display library statistics table and summary."""
        topics: Dict[str, int] = {}
        total_size_kb = 0.0
        total_images = 0
        for entry in self.entries.values():
            topics[entry.topic] = topics.get(entry.topic, 0) + 1
            total_size_kb += entry.file_size_kb
            total_images += entry.images_count

        table = Table(
            title=":books: [bold cyan]Estado de la Biblioteca Local de Medium[/bold cyan]",
            border_style="bright_blue",
            header_style="bold magenta",
            show_lines=True,
        )
        table.add_column("Tema / Colección", style="bold cyan", ratio=3)
        table.add_column("Artículos Guardados", justify="center", style="bold green", ratio=2)

        for top, count in sorted(topics.items(), key=lambda x: -x[1]):
            table.add_row(f"#{top}", str(count))

        self.console.print()
        self.console.print(table)
        self.console.print(
            Panel.fit(
                f"[bold white]Total Artículos en Biblioteca:[/] [bold green]{len(self.entries)}[/bold green] | "
                f"[bold white]Imágenes Locales:[/] [bold magenta]{total_images}[/bold magenta] | "
                f"[bold white]Espacio Markdown:[/] [bold cyan]{total_size_kb / 1024:.2f} MB[/bold cyan]\n"
                f"[dim]Directorio Base:[/] {self.base_dir.resolve()}",
                border_style="green",
            )
        )
        self.console.print()

    def audit_and_clean_markdown(self, fix: bool = False, verbose: bool = False) -> Dict[str, Any]:
        """
        Audit and optionally clean in-place all article.md files across the knowledge base.
        Deduplicates code blocks, fixes mojibake UTF-8 corruption, and retags code syntax.
        """
        article_paths = list(self.base_dir.rglob("article.md"))
        total_scanned = len(article_paths)
        if total_scanned == 0:
            self.console.print("[yellow][!] No se encontraron artículos en la base de conocimiento.[/yellow]")
            return {"total_scanned": 0}

        mode_title = "Modo Reparación en Lote (--clean-markdown)" if fix else "Modo Auditoría Solo-Lectura (--audit)"
        self.console.print(
            Panel.fit(
                f"[bold cyan]Auditoría de Calidad y Formato Markdown para LLMs/Harnesses[/bold cyan]\n"
                f"[white]Modo:[/white] [bold yellow]{mode_title}[/bold yellow] | "
                f"[white]Total de Artículos:[/white] [bold green]{total_scanned}[/bold green]",
                border_style="cyan",
            )
        )

        total_dups = 0
        total_mojibake = 0
        total_retagged = 0
        files_affected = 0
        bytes_saved = 0

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:
            task = progress.add_task("[cyan]Analizando y auditando artículos...", total=total_scanned)

            for path in article_paths:
                try:
                    orig_text = path.read_text(encoding="utf-8", errors="replace")
                    cleaned_text, stats = clean_markdown_document(orig_text)

                    has_real_issues = (
                        stats["dups_removed"] > 0
                        or stats["mojibake_fixed"] > 0
                        or stats["code_langs_retagged"] > 0
                    )
                    if has_real_issues:
                        files_affected += 1
                        total_dups += stats["dups_removed"]
                        total_mojibake += stats["mojibake_fixed"]
                        total_retagged += stats["code_langs_retagged"]
                        char_diff = len(orig_text) - len(cleaned_text)
                        if char_diff > 0:
                            bytes_saved += char_diff

                    if fix and cleaned_text != orig_text:
                        path.write_text(cleaned_text, encoding="utf-8")
                except Exception as exc:
                    if verbose:
                        self.console.print(f"[red][!] Error procesando {path}: {exc}[/red]")
                finally:
                    progress.advance(task)

        summary_table = Table(title="Resultado de Auditoría de Markdown", border_style="cyan")
        summary_table.add_column("Métrica de Calidad", style="bold white")
        summary_table.add_column("Valor Detectado / Procesado", style="cyan")

        summary_table.add_row("Total de Artículos Analizados", str(total_scanned))
        summary_table.add_row(
            "Artículos con Defectos o Anomalías",
            f"{files_affected} ({files_affected/total_scanned*100:.1f}%)" if total_scanned else "0",
        )
        summary_table.add_row(
            "Bloques de Código Duplicados (Shiki Dark/Light)",
            f"{total_dups} eliminados" if fix else f"{total_dups} detectados",
        )
        summary_table.add_row(
            "Corrupciones Mojibake Reparadas (UTF-8)",
            f"{total_mojibake} reparadas" if fix else f"{total_mojibake} detectadas",
        )
        summary_table.add_row(
            "Lenguajes de Código Corregidos (bash/http/json)",
            f"{total_retagged} re-etiquetados" if fix else f"{total_retagged} detectados",
        )
        summary_table.add_row(
            "Reducción de Caracteres / Ahorro de Tokens",
            f"~{bytes_saved / 1024:.2f} KB ({bytes_saved} caracteres)",
        )

        self.console.print()
        self.console.print(summary_table)

        if not fix and files_affected > 0:
            self.console.print(
                Panel.fit(
                    f"[bold yellow][!] Recomendación para Harnesses (Oz, Claude Code, Antigravity):[/bold yellow]\n"
                    f"Se detectaron {files_affected} artículos con bloques duplicados o problemas de encoding.\n"
                    f"Ejecuta [bold green]python3 medium_archiver.py --clean-markdown[/bold green] para repararlos y optimizarlos automáticamente.",
                    border_style="yellow",
                )
            )
        elif fix:
            self.console.print(
                Panel.fit(
                    f"[bold green][✓] Limpieza y Optimización Completada con Éxito:[/bold green]\n"
                    f"Los {files_affected} artículos afectados han sido normalizados.\n"
                    f"Ahora el contenido es 100% legible, sin duplicación de tokens y compatible con cualquier harness LLM.",
                    border_style="green",
                )
            )
            self.load_or_rebuild()

        return {
            "total_scanned": total_scanned,
            "files_affected": files_affected,
            "total_dups": total_dups,
            "total_mojibake": total_mojibake,
            "total_retagged": total_retagged,
            "bytes_saved": bytes_saved,
        }


class PathSanitizer:
    """Provides cross-platform filesystem path sanitization."""

    @staticmethod
    def slugify(text: str, max_len: int = 80) -> str:
        """Convert string to URL/filename safe slug."""
        if not text:
            return ""
        import unicodedata
        t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        t = re.sub(r"[^\w\s-]", "", t.lower())
        t = re.sub(r"[-\s]+", "-", t).strip("-_")
        if max_len and len(t) > max_len:
            t = t[:max_len].rsplit("-", 1)[0].strip("-_")
            if not t:
                t = t[:max_len]
        return t

    @classmethod
    def sanitize_filename(cls, name: str, max_length: int = 90) -> str:
        """Alias for filename sanitization."""
        return cls.sanitize(name, max_length)

    @staticmethod
    def sanitize(name: str, max_length: int = 90) -> str:
        """
        Sanitize a string for safe usage as a directory or file name
        across Windows, macOS, and Linux.
        """
        if not name:
            return "untitled"

        # Remove control characters and reserved filesystem characters: <>:"/\|?* and null
        cleaned = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "", name)
        # Normalize whitespace and hyphens
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")
        if not cleaned:
            cleaned = f"article_{int(time.time())}"

        # Truncate to maximum length safely without cutting mid-word if possible
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length].rsplit(" ", 1)[0].strip(" ._-")
            if not cleaned:
                cleaned = name[:max_length].strip(" ._-")

        return cleaned or "untitled"


class MediumFeedDiscoverer:
    """Discovers and parses publicly syndicated articles from Medium tags."""

    def __init__(self, console: Console):
        self.console = console

    @staticmethod
    def sanitize_url(raw_url: str) -> str:
        """Strip tracking parameters such as source, utm_*, etc. from Medium URLs."""
        if not raw_url:
            return ""
        parsed = urlsplit(raw_url)
        # Filter out tracking query parameters
        kept_params = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            lower_k = k.lower()
            if (
                lower_k.startswith("utm_")
                or lower_k in {"source", "ref", "gi", "responsesopen"}
                or lower_k.startswith("sk")
            ):
                continue
            kept_params.append((k, v))

        clean_query = urlencode(kept_params)
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, clean_query, "")
        )

    TOPIC_CLUSTERS: Dict[str, List[str]] = {
        "bug-bounty": [
            "bug-bounty",
            "bugbounty",
            "bugbounty-tips",
            "bug-bounty-tips",
            "bugbountytips",
            "bug-hunting",
            "infosec-writeups",
        ],
        "cybersecurity": [
            "cybersecurity",
            "infosec",
            "security",
            "ethical-hacking",
            "penetration-testing",
        ],
        "python": [
            "python",
            "python3",
            "python-programming",
        ],
    }

    SECURITY_ALIASES: Dict[str, List[str]] = {
        "client-side path traversal": ["cspt", "client-side-path-traversal", "path-traversal"],
        "client-side-path-traversal": ["cspt", "client-side-path-traversal", "path-traversal"],
        "cspt": ["cspt", "client-side-path-traversal", "path-traversal"],
        "path traversal": ["path-traversal", "directory-traversal", "cspt"],
        "path-traversal": ["path-traversal", "directory-traversal", "cspt"],
        "directory traversal": ["directory-traversal", "path-traversal"],
        "directory-traversal": ["directory-traversal", "path-traversal"],
        "remote code execution": ["rce", "remote-code-execution"],
        "remote-code-execution": ["rce", "remote-code-execution"],
        "rce": ["rce", "remote-code-execution"],
        "insecure direct object reference": ["idor", "insecure-direct-object-reference"],
        "insecure-direct-object-reference": ["idor", "insecure-direct-object-reference"],
        "idor": ["idor", "insecure-direct-object-reference"],
        "server side request forgery": ["ssrf", "server-side-request-forgery"],
        "server-side-request-forgery": ["ssrf", "server-side-request-forgery"],
        "ssrf": ["ssrf", "server-side-request-forgery"],
        "cross site scripting": ["xss", "cross-site-scripting"],
        "cross-site-scripting": ["xss", "cross-site-scripting"],
        "xss": ["xss", "cross-site-scripting"],
        "cross site request forgery": ["csrf", "cross-site-request-forgery"],
        "cross-site-request-forgery": ["csrf", "cross-site-request-forgery"],
        "csrf": ["csrf", "cross-site-request-forgery"],
        "account takeover": ["ato", "account-takeover"],
        "account-takeover": ["ato", "account-takeover"],
        "ato": ["ato", "account-takeover"],
        "sql injection": ["sqli", "sql-injection"],
        "sql-injection": ["sqli", "sql-injection"],
        "sqli": ["sqli", "sql-injection"],
        "subdomain takeover": ["subdomain-takeover"],
        "subdomain-takeover": ["subdomain-takeover"],
        "business logic": ["business-logic", "business-logic-flaw", "business-logic-bugs"],
        "race condition": ["race-condition", "race-conditions"],
        "2fa bypass": ["2fa", "mfa", "mfa-bypass", "authentication-bypass"],
    }

    @classmethod
    def resolve_topic_candidates(cls, topic: str) -> List[str]:
        """Normalize topic to valid Medium tag slugs and cybersecurity acronym aliases."""
        if not topic:
            return []
        raw = topic.strip().lower()
        slug = re.sub(r"[^\w\s-]", "", raw).strip()
        clean_slug = re.sub(r"[\s_]+", "-", slug)

        candidates = []
        if raw in cls.SECURITY_ALIASES:
            candidates.extend(cls.SECURITY_ALIASES[raw])
        if clean_slug in cls.SECURITY_ALIASES:
            for alias in cls.SECURITY_ALIASES[clean_slug]:
                if alias not in candidates:
                    candidates.append(alias)

        if clean_slug and clean_slug not in candidates:
            candidates.append(clean_slug)

        return candidates

    CLUSTER_PUBLICATIONS: Dict[str, List[str]] = {
        "bug-bounty": [
            "https://infosecwriteups.com/feed",
            "https://medium.com/feed/bugbountywriteup",
        ]
    }

    @staticmethod
    def extract_year(entry) -> Optional[int]:
        """Extract publication year from feedparser entry."""
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return entry.published_parsed.tm_year
        raw_published = entry.get("published", "") or entry.get("updated", "")
        if raw_published:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(raw_published)
                return dt.year
            except Exception:
                pass
            m = re.search(r"\b(20\d{2})\b", raw_published)
            if m:
                return int(m.group(1))
        return None

    def fetch_feed(
        self,
        topic: Optional[str] = None,
        publication: Optional[str] = None,
        limit: Optional[int] = None,
        min_year: Optional[int] = 2024,
        max_year: Optional[int] = 2026,
        deep: bool = False,
        timeout: int = 20,
    ) -> List[ArticleMetadata]:
        """
        Fetch Medium articles for a topic tag or publication, optionally across related tags and publications,
        filtering strictly by publication year (e.g. 2024-2026).
        """
        feed_targets: List[str] = []
        normalized_topic = (topic or "").strip().lower()
        normalized_pub = (publication or "").strip().lower()
        target_name = normalized_pub if publication else normalized_topic

        if publication:
            if normalized_pub.startswith("http://") or normalized_pub.startswith("https://"):
                feed_targets.append(
                    normalized_pub if normalized_pub.endswith("/feed") else f"{normalized_pub.rstrip('/')}/feed"
                )
            else:
                no_hyphen = normalized_pub.replace("-", "")
                feed_targets.extend([
                    f"https://{normalized_pub}.com/feed",
                    f"https://{no_hyphen}.com/feed",
                    f"https://medium.com/feed/{normalized_pub}",
                    f"https://medium.com/feed/{no_hyphen}",
                    f"https://{normalized_pub}.medium.com/feed",
                ])
        elif deep and normalized_topic in self.TOPIC_CLUSTERS:
            # Aggregate primary tag + cluster synonyms
            for tag in self.TOPIC_CLUSTERS[normalized_topic]:
                feed_targets.append(f"https://medium.com/feed/tag/{tag}")
            for pub in self.CLUSTER_PUBLICATIONS.get(normalized_topic, []):
                feed_targets.append(pub)
        else:
            candidates = self.resolve_topic_candidates(normalized_topic)
            for cand in candidates:
                feed_targets.append(f"https://medium.com/feed/tag/{cand}")

        headers = {
            "User-Agent": random.choice(DESKTOP_USER_AGENTS),
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        }

        seen_urls = set()
        articles: List[ArticleMetadata] = []

        for feed_url in feed_targets:
            try:
                response = requests.get(feed_url, headers=headers, timeout=timeout)
                if response.status_code != 200:
                    continue
                parsed = feedparser.parse(response.content)
            except Exception as exc:
                self.console.print(f"[dim yellow][!] Warning fetching {feed_url}: {exc}[/dim yellow]")
                continue

            for entry in parsed.entries:
                raw_link = entry.get("link", "").strip()
                clean_link = self.sanitize_url(raw_link)
                if not clean_link or clean_link in seen_urls:
                    continue

                year = self.extract_year(entry)

                # Filter by publication year (2024 - 2026)
                if min_year is not None and year is not None and year < min_year:
                    continue
                if max_year is not None and year is not None and year > max_year:
                    continue

                seen_urls.add(clean_link)
                raw_title = entry.get("title", "Untitled Article").strip()
                author = entry.get("author", "Unknown Author").strip()
                published = entry.get("published", "").strip()
                summary_html = entry.get("summary", "")

                articles.append(
                    ArticleMetadata(
                        index=len(articles) + 1,
                        title=raw_title,
                        author=author,
                        published=published,
                        source_url=raw_link,
                        clean_url=clean_link,
                        topic=target_name,
                        summary_html=summary_html,
                        year=year,
                    )
                )

                if limit and len(articles) >= limit:
                    break

            if limit and len(articles) >= limit:
                break

        return articles

    def fetch_archive(
        self,
        topic: Optional[str] = None,
        publication: Optional[str] = None,
        from_year: int = 2024,
        to_year: int = 2026,
        limit: Optional[int] = None,
        timeout: int = 20,
    ) -> List[ArticleMetadata]:
        """
        Discover Medium articles across year/month static archive pages (e.g. 2024-2026)
        to overcome the strict 10-item RSS limit and retrieve all available writeups.
        Extracts post metadata using BeautifulSoup DOM parsing, __APOLLO_STATE__ hydration,
        and GraphQL archive feed queries with polite rate-limiting.
        """
        normalized_topic = (topic or "").strip().lower()
        normalized_pub = (publication or "").strip().lower()
        target_name = normalized_pub if publication else normalized_topic

        session = requests.Session()
        session.headers.update({
            "User-Agent": random.choice(DESKTOP_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://medium.com/",
            "Origin": "https://medium.com",
        })

        try:
            session.get("https://medium.com/", timeout=timeout)
        except Exception:
            pass

        seen_urls = set()
        articles: List[ArticleMetadata] = []
        now = datetime.now()
        curr_year = now.year
        curr_month = now.month

        start_year = min(from_year, to_year)
        end_year = max(from_year, to_year)

        candidates = [normalized_pub] if publication else self.resolve_topic_candidates(normalized_topic)

        for year in range(end_year, start_year - 1, -1):
            max_m = curr_month if year == curr_year else 12
            min_m = 1
            for month in range(max_m, min_m - 1, -1):
                if limit and len(articles) >= limit:
                    break

                month_str = f"{year}/{month:02d}"
                batch_posts = []

                for cand in candidates:
                    archive_url = (
                        f"https://medium.com/{cand}/archive/{year}/{month:02d}"
                        if publication
                        else f"https://medium.com/tag/{cand}/archive/{year}/{month:02d}"
                    )

                    try:
                        resp = session.get(archive_url, timeout=timeout)
                        if resp.status_code == 200:
                            # 1. Parse __APOLLO_STATE__ from HTML
                            m = re.search(r'window\.__APOLLO_STATE__\s*=\s*(\{.*?\});', resp.text)
                            if m:
                                try:
                                    apollo_data = json.loads(m.group(1))
                                    user_map = {
                                        k: v.get("name", "Unknown Author")
                                        for k, v in apollo_data.items()
                                        if isinstance(v, dict) and v.get("__typename") == "User"
                                    }
                                    for k, v in apollo_data.items():
                                        if isinstance(v, dict) and v.get("__typename") == "Post":
                                            u = v.get("mediumUrl")
                                            if u and not any(
                                                x in u for x in ["/jobs-at-medium/", "/policy.", "/m/signin", "/about"]
                                            ):
                                                title = v.get("title", "").strip() or "Untitled Article"
                                                creator_ref = (v.get("creator") or {}).get("__ref")
                                                author = user_map.get(creator_ref, "Unknown Author")
                                                ts = v.get("firstPublishedAt")
                                                pub_date = (
                                                    datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
                                                    if ts else f"{year}-{month:02d}"
                                                )
                                                batch_posts.append({
                                                    "title": title,
                                                    "author": author,
                                                    "url": u,
                                                    "published": pub_date,
                                                    "year": year,
                                                })
                                except Exception:
                                    pass

                            # 2. Extract <a> tags with BeautifulSoup
                            soup = BeautifulSoup(resp.text, "html.parser")
                            for a in soup.find_all("a", href=True):
                                href = a["href"]
                                if re.search(r"-[a-f0-9]{8,12}(?:[/?#]|$)", href) or a.get("data-post-id"):
                                    if not any(
                                        x in href for x in ["/jobs-at-medium/", "policy.medium.com", "/m/signin", "/about"]
                                    ):
                                        full_url = href if href.startswith("http") else urljoin("https://medium.com", href)
                                        clean_u = self.sanitize_url(full_url)
                                        title_cand = a.get_text(strip=True)
                                        if not title_cand or len(title_cand) < 4 or "response icon" in title_cand.lower():
                                            title_cand = "Medium Article"
                                        batch_posts.append({
                                            "title": title_cand,
                                            "author": "Medium Author",
                                            "url": clean_u,
                                            "published": f"{year}-{month:02d}",
                                            "year": year,
                                        })
                        elif resp.status_code == 403 or not batch_posts:
                            # Fallback to GraphQL TagArchiveFeedQuery
                            try:
                                gql_query = """
                                query TagArchiveFeedQuery($tagSlug: String!, $timeRange: TagPostsTimeRange!, $sortOrder: TagPostsSortOrder!, $first: Int!, $after: String) {
                                  tagFromSlug(tagSlug: $tagSlug) {
                                    id
                                    sortedFeed: posts(
                                      timeRange: $timeRange
                                      sortOrder: $sortOrder
                                      first: $first
                                      after: $after
                                    ) {
                                      edges { cursor node { id title creator { name id } firstPublishedAt mediumUrl } }
                                      pageInfo { hasNextPage endCursor }
                                    }
                                  }
                                }
                                """
                                payload = [{
                                    "operationName": "TagArchiveFeedQuery",
                                    "query": gql_query,
                                    "variables": {
                                        "after": "",
                                        "first": 25,
                                        "sortOrder": "NEWEST",
                                        "tagSlug": cand,
                                        "timeRange": {
                                            "inMonth": {"month": month, "year": year},
                                            "kind": "IN_MONTH",
                                        },
                                    },
                                }]
                                gql_resp = session.post("https://medium.com/_/graphql", json=payload, timeout=timeout)
                                if gql_resp.status_code == 200:
                                    gql_data = gql_resp.json()
                                    edges = gql_data[0].get("data", {}).get("tagFromSlug", {}).get("sortedFeed", {}).get("edges", [])
                                    for e in edges:
                                        node = e.get("node", {})
                                        u = node.get("mediumUrl")
                                        if u:
                                            ts = node.get("firstPublishedAt")
                                            pub_date = (
                                                datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
                                                if ts else f"{year}-{month:02d}"
                                            )
                                            author = (node.get("creator") or {}).get("name", "Unknown Author")
                                            batch_posts.append({
                                                "title": node.get("title", "Untitled Article"),
                                                "author": author,
                                                "url": u,
                                                "published": pub_date,
                                                "year": year,
                                            })
                            except Exception:
                                pass
                    except Exception as exc:
                        self.console.print(f"[dim yellow][!] Warning fetching archive {month_str}: {exc}[/dim yellow]")

                # Deduplicate and register articles
                added_this_month = 0
                for item in batch_posts:
                    raw_url = item["url"]
                    clean_link = self.sanitize_url(raw_url)
                    if not clean_link or clean_link in seen_urls:
                        continue
                    seen_urls.add(clean_link)
                    articles.append(
                        ArticleMetadata(
                            index=len(articles) + 1,
                            title=item["title"],
                            author=item["author"],
                            published=item["published"],
                            source_url=raw_url,
                            clean_url=clean_link,
                            topic=target_name,
                            summary_html="",
                            year=item["year"],
                        )
                    )
                    added_this_month += 1
                    if limit and len(articles) >= limit:
                        break

                if added_this_month > 0:
                    self.console.print(
                        f"[dim cyan]  [Archive {month_str}][/dim cyan] +{added_this_month} artículos descubiertos "
                        f"[dim](total acumulado: {len(articles)})[/dim]"
                    )

                # Polite delay between monthly archive queries (0.5s - 1.0s)
                time.sleep(random.uniform(0.5, 1.0))

            if limit and len(articles) >= limit:
                break

        # Fallback to feed if archive discovery returned 0 articles
        if not articles:
            self.console.print(
                "[yellow][!] Archivo mensual no retornó resultados directos. "
                "Activando fallback a feeds RSS y clusters...[/yellow]"
            )
            return self.fetch_feed(
                topic=topic if not publication else None,
                publication=publication,
                limit=limit,
                min_year=start_year,
                max_year=end_year,
                deep=True,
                timeout=timeout,
            )

        return articles


    def render_summary_table(
        self,
        articles: List[ArticleMetadata],
        target_name: str,
        is_publication: bool = False,
        min_year: Optional[int] = 2024,
        max_year: Optional[int] = 2026,
    ) -> None:
        """Render a clean interactive summary table of discovered articles."""
        prefix = "pub:" if is_publication else "#"
        year_range_str = f" [{min_year}–{max_year}]" if min_year and max_year else ""
        already_count = sum(1 for a in articles if a.already_archived)
        new_count = len(articles) - already_count

        if already_count > 0:
            count_info = (
                f"([bold green]{new_count} nuevos[/bold green] | "
                f"[yellow]{already_count} en biblioteca[/yellow] / {len(articles)} total)"
            )
        else:
            count_info = f"([bold green]{len(articles)} artículos encontrados[/bold green])"

        table = Table(
            title=f"Discovered Medium Articles: [bold cyan]{prefix}{target_name}[/bold cyan]{year_range_str} {count_info}",
            border_style="bright_blue",
            header_style="bold magenta",
            show_lines=True,
        )

        table.add_column("#", justify="center", style="bold yellow", width=4)
        table.add_column("Title", style="bold white", ratio=4)
        table.add_column("Author", style="green", ratio=2)
        table.add_column("Year", justify="center", style="bold cyan", width=6)
        table.add_column("Published Date", style="dim cyan", ratio=2)
        table.add_column("Biblioteca", justify="center", style="bold", ratio=2)
        table.add_column("Clean URL", style="blue underline", ratio=4)

        for article in articles:
            year_display = str(article.year) if article.year else "N/A"
            if article.already_archived:
                loc_txt = f"\n[dim]({article.archived_location})[/dim]" if article.archived_location else ""
                status_display = f"[dim yellow]✔ GUARDADO[/dim yellow]{loc_txt}"
            else:
                status_display = "[bold green]NUEVO[/bold green]"

            table.add_row(
                str(article.index),
                article.title,
                article.author,
                year_display,
                article.published or "N/A",
                status_display,
                article.clean_url,
            )

        self.console.print()
        self.console.print(table)
        self.console.print()


class WebReaderClient:
    """Manages resilient HTTP requests with mirror fallbacks, circuit-breaking, and exponential backoff."""

    def __init__(
        self,
        reader_mirrors: Optional[List[str]] = None,
        timeout: int = 20,
        max_retries: int = 2,
        delay_min: float = 0.5,
        delay_max: float = 1.5,
        console: Optional[Console] = None,
    ):
        self.reader_mirrors = reader_mirrors or list(DEFAULT_READERS)
        self.timeout = timeout
        self.max_retries = max_retries
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.console = console or Console()

        self._cooldown_lock = threading.Lock()
        self._mirror_cooldowns: Dict[str, float] = {}

        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=1, pool_connections=35, pool_maxsize=35)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def is_mirror_healthy(self, base_url: str) -> bool:
        """Check if mirror host is currently healthy (not on cool-down)."""
        host = urlsplit(base_url).netloc or base_url
        with self._cooldown_lock:
            cooldown_until = self._mirror_cooldowns.get(host, 0.0)
            return time.time() >= cooldown_until

    def mark_mirror_unhealthy(
        self, base_url: str, duration: float = 300.0, reason: str = ""
    ) -> None:
        """Put failing mirror on cool-down so other workers immediately avoid it."""
        host = urlsplit(base_url).netloc or base_url
        with self._cooldown_lock:
            already_cooling = self._mirror_cooldowns.get(host, 0.0) > time.time()
            self._mirror_cooldowns[host] = time.time() + duration
        if not already_cooling and reason:
            self.console.print(
                f"[dim yellow][!] Mirror {host} degradado ({reason}). "
                f"Omitiendo en las siguientes solicitudes por {int(duration)}s.[/dim yellow]"
            )

    def polite_sleep(self) -> None:
        """Sleep between requests to avoid rate limits."""
        sleep_sec = random.uniform(self.delay_min, self.delay_max)
        time.sleep(sleep_sec)

    def get_headers(self) -> Dict[str, str]:
        """Generate browser headers with random User-Agent."""
        return {
            "User-Agent": random.choice(DESKTOP_USER_AGENTS),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://medium.com/",
            "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
        }

    def build_reader_url(self, base_mirror: str, target_url: str) -> str:
        """
        Transforms canonical Medium URL into reader processed URL.
        Example: https://freedium-mirror.cfd/https://medium.com/@user/article-slug
        """
        clean_base = base_mirror.rstrip("/") + "/"
        clean_target = target_url.strip()
        return f"{clean_base}{clean_target}"

    def fetch_article_html(
        self, target_url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Fetch article HTML using reader mirrors with circuit-breaker failover,
        filtering out inactive or unresolvable hosts immediately.
        Returns a tuple: (html_content, active_base_url).
        """
        # Validate outbound URL safety against SSRF
        safe, reason = is_safe_url(target_url)
        if not safe:
            self.console.print(f"[bold red][!] URL no permitida por seguridad (SSRF): {reason}[/bold red]")
            return None, None

        # Formulate candidate endpoints, prioritizing healthy mirrors
        endpoints: List[Tuple[str, str, str]] = []
        for idx, mirror in enumerate(self.reader_mirrors):
            mirror_base = mirror.rstrip("/") + "/"
            if not self.is_mirror_healthy(mirror_base):
                continue
            reader_url = self.build_reader_url(mirror_base, target_url)
            role = "Primary Reader" if idx == 0 else f"Secondary Mirror #{idx}"
            endpoints.append((reader_url, mirror_base, role))

        # If all configured mirrors are temporarily down, try the primary anyway
        if not endpoints and self.reader_mirrors:
            mirror_base = self.reader_mirrors[0].rstrip("/") + "/"
            endpoints.append((self.build_reader_url(mirror_base, target_url), mirror_base, "Fallback Reader"))

        # Direct medium URL as last resort before RSS fallback
        endpoints.append((target_url, target_url, "Direct Medium Fallback"))

        for candidate_url, base_url, role in endpoints:
            cand_safe, _ = is_safe_url(candidate_url)
            if not cand_safe:
                continue

            host = urlsplit(candidate_url).netloc or candidate_url

            for attempt in range(1, self.max_retries + 1):
                try:
                    headers = self.get_headers()
                    response = self.session.get(
                        candidate_url, headers=headers, timeout=self.timeout
                    )
                    # Force UTF-8 encoding to prevent requests from defaulting to ISO-8859-1 for text/html
                    response.encoding = "utf-8"

                    # Successful response with substantial content
                    if (
                        response.status_code == 200
                        and len(response.text.strip()) > 500
                    ):
                        if (
                            "<article" in response.text
                            or "<main" in response.text
                            or "prose" in response.text
                        ):
                            return response.text, base_url

                    # Handle HTTP 4xx / 5xx error responses
                    if response.status_code >= 400:
                        status_msg = f"HTTP {response.status_code}"
                        if response.status_code in [502, 503, 504]:
                            self.mark_mirror_unhealthy(base_url, duration=120.0, reason=status_msg)
                            break
                        if attempt == self.max_retries or response.status_code in [404, 403]:
                            break
                        time.sleep(0.5 * attempt)
                        continue

                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.RequestException) as exc:
                    err_msg = str(exc)
                    # Immediate circuit breaker on unresolvable DNS / dead domain
                    if "NameResolutionError" in err_msg or "Failed to resolve" in err_msg:
                        self.mark_mirror_unhealthy(
                            base_url, duration=600.0, reason="DNS resolution failed"
                        )
                        break

                    if isinstance(exc, requests.exceptions.Timeout):
                        if attempt == self.max_retries:
                            self.mark_mirror_unhealthy(
                                base_url, duration=180.0, reason="Connection timeout"
                            )
                            break

                    if attempt == self.max_retries:
                        break
                    else:
                        backoff = (1.2**attempt) + random.uniform(0.1, 0.3)
                        time.sleep(backoff)

            time.sleep(0.2)

        return None, None


class DOMSanitizerAndAssetBundler:
    """Parses HTML, cleans DOM noise, downloads inline assets, and compiles Markdown."""

    def __init__(
        self,
        session: requests.Session,
        console: Console,
        timeout: int = 15,
    ):
        self.session = session
        self.console = console
        self.timeout = timeout

    @staticmethod
    def is_avatar(img_tag: Tag) -> bool:
        """
        Determine whether an <img> element is an author avatar or non-content icon.
        """
        classes = " ".join(img_tag.get("class") or []).lower()
        alt = (img_tag.get("alt") or "").lower()
        src = (img_tag.get("src") or "").lower()

        # Class heuristics
        if any(
            token in classes
            for token in [
                "rounded-full",
                "avatar",
                "user-avatar",
                "author-image",
                "profile",
            ]
        ):
            return True

        # Alt heuristics
        if "avatar" in alt or "profile picture" in alt:
            return True

        # Dimension heuristics (avatars are typically small, e.g. <= 64px)
        width = img_tag.get("width")
        height = img_tag.get("height")
        try:
            if width and int(width) <= 64:
                return True
            if height and int(height) <= 64:
                return True
        except (ValueError, TypeError):
            pass

        # Ancestor heuristics
        for parent in img_tag.parents:
            if parent.name in ["header", "nav"]:
                p_classes = " ".join(parent.get("class") or []).lower()
                if "author" in p_classes or "user" in p_classes:
                    return True
            p_class = " ".join(parent.get("class") or []).lower()
            if "avatar" in p_class or "author-card" in p_class:
                return True

        return False

    @staticmethod
    def normalize_hd_image_url(url: str) -> str:
        """
        Normalize Medium and mirror image URLs to request maximum resolution (HD).
        Replaces /max/800/, /resize:fit:700/, /fit/c/160/160/, /img/medium/700/ with HD equivalents.
        """
        if not url:
            return url
        # Medium CDN patterns: miro.medium.com, cdn-images-1.medium.com
        url = re.sub(r"/max/\d+/", "/max/1600/", url)
        url = re.sub(r"/resize:fit:\d+/", "/resize:fit:1600/", url)
        url = re.sub(r"/resize:fill:\d+:\d+/", "/resize:fit:1600/", url)
        url = re.sub(r"/fit/c/\d+/\d+/", "/max/1600/", url)
        # Mirror paths: /img/medium/700/ -> /img/medium/4000/
        url = re.sub(r"/img/medium/\d+/", "/img/medium/4000/", url)
        return url

    def download_image(
        self, img_url: str, dest_path: Path
    ) -> Tuple[bool, str]:
        """
        Download a remote image to dest_path.
        Returns (success: bool, final_filename: str).
        """
        # SSRF check on image source URL
        safe, reason = is_safe_url(img_url)
        if not safe:
            return False, ""

        headers = {
            "User-Agent": random.choice(DESKTOP_USER_AGENTS),
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": "https://medium.com/",
        }

        try:
            res = self.session.get(
                img_url, headers=headers, timeout=self.timeout, stream=True
            )
            if res.status_code == 200:
                # Detect proper extension from Content-Type if necessary
                content_type = res.headers.get(
                    "Content-Type", ""
                ).split(";")[0].strip()
                ext = mimetypes.guess_extension(content_type) or ""
                if ext == ".jpe":
                    ext = ".jpg"

                # If dest_path has no extension or generic extension, adjust it
                if ext and not dest_path.suffix:
                    dest_path = dest_path.with_suffix(ext)

                max_bytes = 25 * 1024 * 1024  # 25 MB max per asset
                downloaded = 0
                with open(dest_path, "wb") as f:
                    for chunk in res.iter_content(chunk_size=16384):
                        if chunk:
                            downloaded += len(chunk)
                            if downloaded > max_bytes:
                                dest_path.unlink(missing_ok=True)
                                return False, ""
                            f.write(chunk)
                return True, dest_path.name
        except Exception as exc:
            self.console.print(
                f"[dim yellow][!] Asset download failed for {img_url[:60]}...: {exc}[/dim yellow]"
            )

        return False, ""

    def process_and_convert(
        self,
        raw_html: str,
        base_url: str,
        images_dir: Path,
        article_title: str,
    ) -> str:
        """
        Cleans the DOM, downloads inline images in HD, updates references to relative paths,
        and converts the result to Markdown.
        """
        soup = BeautifulSoup(raw_html, "html.parser")

        # Locate primary content container: Prioritize Freedium's clean container
        container = soup.find("div", class_="main-content")
        if not container or len(container.get_text(strip=True)) < 100:
            container = soup.find("article")
        if not container or len(container.get_text(strip=True)) < 100:
            container = soup.find("main")
        if not container or len(container.get_text(strip=True)) < 100:
            # Fallback to high density div
            candidates = soup.find_all(
                "div",
                class_=lambda c: c
                and any(k in str(c).lower() for k in ["prose", "post", "content"]),
            )
            if candidates:
                container = max(candidates, key=lambda c: len(c.get_text()))
            else:
                container = soup.find("body") or soup

        # Decompose Freedium dark-mode duplicate code blocks (Shiki dual theme: github-dark / dark:block)
        for dark_el in container.find_all(class_=re.compile(r"(github-dark|dark:block)")):
            dark_el.decompose()

        # Decompose unwanted elements (scripts, styles, interactive UI, ads, buttons)
        for noise in container.find_all(
            [
                "script",
                "style",
                "noscript",
                "iframe",
                "form",
                "input",
                "button",
                "svg",
            ]
        ):
            noise.decompose()

        # Remove Freedium / reader action bars, TOC download buttons, telegram, donation links
        for el in container.find_all(["div", "section", "header", "p", "a", "aside"]):
            el_text = el.get_text(strip=True).lower()
            if any(term in el_text for term in ["download article", "buy me a coffee", "donate", "telegram channel"]):
                el.decompose()

        # Ensure images directory exists
        images_dir.mkdir(parents=True, exist_ok=True)

        # Process and download images concurrently
        all_imgs = container.find_all("img")
        downloaded_cache: Dict[str, str] = {}
        img_tasks = []
        img_counter = 1

        for img in all_imgs:
            if self.is_avatar(img):
                img.decompose()
                continue

            # Prioritize high-resolution source
            raw_src = (
                img.get("data-zoom-src")
                or img.get("src")
                or img.get("data-src")
                or ""
            ).strip()

            if not raw_src or raw_src.startswith("data:"):
                continue

            # Resolve relative URLs and normalize to HD
            full_img_url = urljoin(base_url, raw_src)
            full_img_url = self.normalize_hd_image_url(full_img_url)

            # Check if this URL was already downloaded in this article
            if full_img_url in downloaded_cache:
                local_rel_name = downloaded_cache[full_img_url]
                img["src"] = f"./images/{local_rel_name}"
                for attr in ["srcset", "data-src", "data-zoom-src", "sizes"]:
                    if img.has_attr(attr):
                        del img[attr]
                continue

            # Determine initial file extension from URL
            url_path = urlsplit(full_img_url).path
            initial_ext = Path(url_path).suffix.lower()
            if initial_ext not in [
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
                ".gif",
                ".svg",
            ]:
                initial_ext = ".jpg"

            target_filename = f"image_{img_counter}{initial_ext}"
            target_filepath = images_dir / target_filename
            img_tasks.append((img, full_img_url, target_filepath))
            img_counter += 1

        # Download inline images concurrently
        if img_tasks:
            def _fetch_img(task_item):
                tag, u, dest = task_item
                ok, final_name = self.download_image(u, dest)
                return tag, u, ok, final_name

            with ThreadPoolExecutor(max_workers=min(4, len(img_tasks))) as img_exec:
                results = list(img_exec.map(_fetch_img, img_tasks))

            for tag, u, ok, final_name in results:
                if ok:
                    downloaded_cache[u] = final_name
                    tag["src"] = f"./images/{final_name}"
                    for attr in ["srcset", "data-src", "data-zoom-src", "sizes"]:
                        if tag.has_attr(attr):
                            del tag[attr]
                else:
                    tag["src"] = u

        def _get_code_language(el):
            code_el = el.find("code")
            classes = (el.get("class", []) if el else []) + (code_el.get("class", []) if code_el else [])
            for c in classes:
                if isinstance(c, str):
                    if c.startswith("language-"):
                        return c.replace("language-", "")
                    if c.startswith("lang-"):
                        return c.replace("lang-", "")
            return ""

        # Convert cleaned HTML DOM to GitHub-Flavored Markdown
        markdown_text = md(
            str(container),
            heading_style="ATX",
            code_language_callback=_get_code_language,
            strip=["script", "style"],
        )

        # Post-process: mojibake repair, duplicate code block deduplication, language inference, spacing
        cleaned_markdown, _ = clean_markdown_document(markdown_text)

        return cleaned_markdown


class DownloadStateManager:
    """
    Manages persistent state and checkpointing for batch downloads,
    enabling seamless resume and progress tracking.
    """

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.lock = threading.RLock()
        self.data: dict = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def is_resumable(self) -> bool:
        with self.lock:
            pending = self.data.get("pending_urls", [])
            completed = self.data.get("completed_urls", [])
            return bool(pending) and bool(completed)

    def init_session(
        self,
        target: str,
        articles: List[ArticleMetadata],
        force_reset: bool = False,
    ) -> None:
        with self.lock:
            if force_reset or not self.data:
                self.data = {
                    "target": target,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "total_count": len(articles),
                    "completed_urls": [],
                    "failed_urls": {},
                    "pending_urls": [a.clean_url for a in articles],
                }
                self._save()
            else:
                # Merge newly discovered items into pending if not yet completed
                completed_set = set(self.data.get("completed_urls", []))
                pending_set = set(self.data.get("pending_urls", []))
                for a in articles:
                    if a.clean_url not in completed_set and a.clean_url not in pending_set:
                        self.data.setdefault("pending_urls", []).append(a.clean_url)
                self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save()

    def mark_completed(self, clean_url: str) -> None:
        with self.lock:
            pending = self.data.get("pending_urls", [])
            if clean_url in pending:
                pending.remove(clean_url)
            completed = self.data.setdefault("completed_urls", [])
            if clean_url not in completed:
                completed.append(clean_url)
            self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def mark_failed(self, clean_url: str, error_msg: str) -> None:
        with self.lock:
            pending = self.data.get("pending_urls", [])
            if clean_url in pending:
                pending.remove(clean_url)
            self.data.setdefault("failed_urls", {})[clean_url] = error_msg
            self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def get_pending_urls(self) -> Set[str]:
        with self.lock:
            return set(self.data.get("pending_urls", []))

    def get_completed_urls(self) -> Set[str]:
        with self.lock:
            return set(self.data.get("completed_urls", []))

    def clear(self) -> None:
        with self.lock:
            if self.state_file.exists():
                try:
                    self.state_file.unlink()
                except Exception:
                    pass
            self.data = {}

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.state_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.state_file)
        except Exception:
            pass


class MediumArchiver:
    """Coordinates discovery, extraction, asset management, and Markdown creation."""

    def __init__(
        self,
        output_dir: str = "knowledge_base",
        readers: Optional[List[str]] = None,
        concurrency: int = 4,
        timeout: int = 20,
        delay_min: float = 0.5,
        delay_max: float = 1.5,
        console: Optional[Console] = None,
    ):
        script_dir = Path(__file__).resolve().parent
        if str(output_dir) == "knowledge_base":
            self.output_dir = script_dir / "knowledge_base"
        else:
            self.output_dir = Path(output_dir).resolve()
        self.console = console or Console()
        self.concurrency = max(1, min(concurrency, 10))
        self.timeout = timeout
        self.library = LibraryManager(self.output_dir, self.console)
        self.discoverer = MediumFeedDiscoverer(self.console)
        self.reader_client = WebReaderClient(
            reader_mirrors=readers,
            timeout=timeout,
            delay_min=delay_min,
            delay_max=delay_max,
            console=self.console,
        )
        self.sanitizer = DOMSanitizerAndAssetBundler(
            session=self.reader_client.session,
            console=self.console,
            timeout=timeout,
        )

    @staticmethod
    def generate_frontmatter(metadata: ArticleMetadata) -> str:
        """Create standard YAML frontmatter block for Obsidian and Local RAG."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {
            "title": metadata.title,
            "author": metadata.author,
            "published": metadata.published,
            "source_url": metadata.clean_url,
            "topic": metadata.topic,
            "retrieved_at": now_iso,
        }
        yaml_str = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        return f"---\n{yaml_str}---\n\n"

    def archive_article(
        self, metadata: ArticleMetadata, topic_dir: Path
    ) -> Tuple[bool, Path]:
        """Archive a single article into topic_dir."""
        # Validate that topic_dir stays strictly within output_dir
        resolved_topic_dir = topic_dir.resolve()
        if not resolved_topic_dir.is_relative_to(self.output_dir.resolve()):
            self.console.print(f"[bold red][!] Ruta de tema insegura fuera del directorio base: {topic_dir}[/bold red]")
            return False, topic_dir

        sanitized_title = PathSanitizer.sanitize(metadata.title)
        article_dir = (resolved_topic_dir / sanitized_title).resolve()
        if not article_dir.is_relative_to(self.output_dir.resolve()):
            return False, article_dir

        images_dir = article_dir / "images"

        article_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        # Fetch full article HTML through reader client
        html_content, base_url = self.reader_client.fetch_article_html(
            metadata.clean_url
        )

        # Fallback to RSS summary if all reader endpoints failed
        if not html_content:
            if metadata.summary_html:
                self.console.print(
                    f"[yellow][!] Usando resumen RSS para '{metadata.title[:40]}...'[/yellow]"
                )
                html_content = (
                    f"<article><h1>{metadata.title}</h1>"
                    f"{metadata.summary_html}</article>"
                )
                base_url = metadata.clean_url
            else:
                return False, article_dir

        # Process DOM and download assets
        markdown_body = self.sanitizer.process_and_convert(
            raw_html=html_content,
            base_url=base_url or metadata.clean_url,
            images_dir=images_dir,
            article_title=metadata.title,
        )

        # Build complete markdown document
        frontmatter = self.generate_frontmatter(metadata)
        full_content = frontmatter + markdown_body + "\n"

        article_file = article_dir / "article.md"
        with open(article_file, "w", encoding="utf-8") as f:
            f.write(full_content)

        # Register in library manifest
        self.library.register_article(metadata, article_dir)

        return True, article_dir

    def run(
        self,
        topic: Optional[str] = None,
        publication: Optional[str] = None,
        limit: Optional[int] = None,
        min_year: Optional[int] = 2024,
        max_year: Optional[int] = 2026,
        deep: bool = False,
        archive: bool = False,
        force: bool = False,
        clean_state: bool = False,
        list_only: bool = False,
        non_interactive: bool = False,
    ) -> List[Path]:
        """Execute the complete discovery and archiving workflow for a tag or publication."""
        is_pub = bool(publication)
        target_name = publication.strip() if is_pub else (topic or "bug-bounty").strip()
        sanitized_target = PathSanitizer.sanitize(target_name).lower()
        prefix = "pub:" if is_pub else "#"

        limit_desc = str(limit) if limit else "Todos (sin límite)"
        year_desc = f"{min_year}–{max_year}" if min_year and max_year else "Todos"
        if archive:
            mode_desc = f"Archivo Mensual Profundo ({year_desc})"
        elif is_pub:
            mode_desc = "Publicación Directa"
        elif deep:
            mode_desc = "Cluster Expandido (Deep)"
        else:
            mode_desc = "Feed de Tag Directo"

        self.console.print(
            Panel.fit(
                f"[bold cyan]Medium Topic & Publication Archiver[/bold cyan]\n"
                f"Target: [bold green]{prefix}{sanitized_target}[/bold green] | "
                f"Modo: [bold blue]{mode_desc}[/bold blue]\n"
                f"Filtro Años: [bold yellow]{year_desc}[/bold yellow] | "
                f"Límite: [bold magenta]{limit_desc}[/bold magenta] | "
                f"Workers Paralelos: [bold green]{self.concurrency}[/bold green]\n"
                f"Output: [dim]{self.output_dir}[/dim]",
                border_style="cyan",
            )
        )

        # Phase 1: Discovery
        if archive:
            self.console.print(
                f"[bold cyan]Buscando artículos en el Archivo de Medium para {prefix}{sanitized_target} [{year_desc}]...[/bold cyan]"
            )
            articles = self.discoverer.fetch_archive(
                topic=topic if not is_pub else None,
                publication=publication if is_pub else None,
                from_year=min_year or 2024,
                to_year=max_year or 2026,
                limit=limit,
                timeout=self.timeout,
            )
        else:
            with self.console.status(
                f"[bold cyan]Buscando artículos en Medium para {prefix}{sanitized_target} [{year_desc}]...[/bold cyan]",
                spinner="dots",
            ):
                articles = self.discoverer.fetch_feed(
                    topic=topic if not is_pub else None,
                    publication=publication if is_pub else None,
                    limit=limit,
                    min_year=min_year,
                    max_year=max_year,
                    deep=deep,
                    timeout=self.timeout,
                )

        if not articles:
            self.console.print(
                f"[bold yellow][!] No se descubrieron artículos para '{prefix}{sanitized_target}' "
                f"en el rango de años {year_desc}.[/bold yellow]"
            )
            return []

        # Cross-reference with local library for deduplication across all topics
        for a in articles:
            already, entry = self.library.check_archived(a)
            if already and entry:
                a.already_archived = True
                a.archived_location = f"#{entry.topic}"

        already_count = sum(1 for a in articles if a.already_archived)
        new_count = len(articles) - already_count

        self.discoverer.render_summary_table(
            articles,
            target_name=sanitized_target,
            is_publication=is_pub,
            min_year=min_year,
            max_year=max_year,
        )

        if list_only:
            self.console.print(
                f"[bold green][i] Modo listado completado: {len(articles)} artículos encontrados "
                f"({new_count} nuevos, {already_count} en biblioteca).[/bold green]"
            )
            return []

        # Determine articles to download (skip existing unless --force is given)
        articles_to_download = articles if force else [a for a in articles if not a.already_archived]

        if not articles_to_download:
            self.console.print(
                Panel.fit(
                    f"[bold green][✓] ¡Los {len(articles)} artículos descubiertos ya están en tu biblioteca local![/bold green]\n"
                    f"[dim]No se descargará ningún archivo redundante (todos preservados en '{self.output_dir}').[/dim]\n"
                    f"Para forzar la re-descarga de todos, usa el argumento: [cyan]--force[/cyan]",
                    border_style="green",
                )
            )
            return []

        if already_count > 0 and not force:
            self.console.print(
                f"[bold yellow][i] Omitiendo {already_count} artículos ya existentes en la biblioteca (evitando duplicados).[/bold yellow]\n"
                f"[bold cyan]Se descargarán únicamente los {len(articles_to_download)} artículos nuevos.[/bold cyan]\n"
            )

        # Phase 2 - 4: Extraction, Parsing, Bundling, and Storage
        target_dir = self.output_dir / sanitized_target
        target_dir.mkdir(parents=True, exist_ok=True)

        state_file = target_dir / ".download_state.json"
        state_mgr = DownloadStateManager(state_file)

        if clean_state:
            state_mgr.clear()

        # Check for previous resumable session
        if state_mgr.is_resumable() and not force:
            pending_urls = state_mgr.get_pending_urls()
            completed_urls = state_mgr.get_completed_urls()
            resumable_articles = [a for a in articles_to_download if a.clean_url in pending_urls]
            if resumable_articles:
                self.console.print(
                    Panel.fit(
                        f"[bold yellow][i] Sesión previa incompleta detectada[/bold yellow]\n"
                        f"Artículos ya completados: [bold green]{len(completed_urls)}[/bold green] | "
                        f"Pendientes por descargar: [bold cyan]{len(resumable_articles)}[/bold cyan]\n"
                        f"[dim]Reanudando automáticamente el trabajo pendiente sin redescargas redundantes.[/dim]",
                        border_style="yellow",
                    )
                )
                articles_to_download = resumable_articles

        state_mgr.init_session(sanitized_target, articles_to_download, force_reset=force or clean_state)

        # Request user confirmation unless non_interactive flag is set
        if not non_interactive:
            confirmed = Confirm.ask(
                f"¿Deseas descargar y archivar localmente estos [bold cyan]{len(articles_to_download)}[/bold cyan] artículos nuevos y sus imágenes con [bold green]{self.concurrency} workers[/bold green] en paralelo?",
                default=True,
            )
            if not confirmed:
                self.console.print("[yellow]Operación de archivado cancelada por el usuario.[/yellow]")
                return []

        archived_paths: List[Path] = []
        failed_count = 0
        cancel_event = threading.Event()

        # Signal handler for graceful stop (Ctrl+C)
        original_sigint = signal.getsignal(signal.SIGINT)

        def _handle_sigint(sig, frame):
            cancel_event.set()
            self.console.print(
                "\n[bold yellow][!] Interrupción detectada (Ctrl+C). Finalizando descargas activas y guardando estado...[/bold yellow]"
            )

        signal.signal(signal.SIGINT, _handle_sigint)

        t_start = time.time()

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=None),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self.console,
            ) as progress:
                task = progress.add_task(
                    f"[cyan]Descargando {prefix}{sanitized_target} ({self.concurrency} workers)...",
                    total=len(articles_to_download),
                )

                def _worker_task(item: ArticleMetadata) -> Tuple[bool, Path, str, ArticleMetadata]:
                    if cancel_event.is_set():
                        return False, Path(), "Cancelado", item
                    try:
                        self.reader_client.polite_sleep()
                        if cancel_event.is_set():
                            return False, Path(), "Cancelado", item

                        success, path = self.archive_article(item, target_dir)
                        if success:
                            state_mgr.mark_completed(item.clean_url)
                            return True, path, "", item
                        else:
                            state_mgr.mark_failed(item.clean_url, "Error extrayendo contenido")
                            return False, path, "Error al extraer contenido", item
                    except Exception as exc:
                        state_mgr.mark_failed(item.clean_url, str(exc))
                        return False, Path(), str(exc), item

                with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                    futures = [executor.submit(_worker_task, item) for item in articles_to_download]

                    for future in as_completed(futures):
                        try:
                            success, path, err, item = future.result()
                            if success:
                                archived_paths.append(path)
                                progress.update(
                                    task,
                                    description=f"[cyan]Guardado:[/] [green]{item.title[:35]}[/green]...",
                                )
                            else:
                                if not cancel_event.is_set():
                                    failed_count += 1
                                    progress.update(
                                        task,
                                        description=f"[yellow]Omitido (sin contenido):[/] [dim]{item.title[:35]}[/dim]...",
                                    )
                        except Exception:
                            failed_count += 1

                        progress.advance(task)
                        if cancel_event.is_set():
                            break
        finally:
            signal.signal(signal.SIGINT, original_sigint)

        elapsed_total = time.time() - t_start
        speed = len(archived_paths) / elapsed_total if elapsed_total > 0 else 0.0

        if cancel_event.is_set():
            self.console.print(
                Panel.fit(
                    f"[bold yellow][!] Descarga pausada de forma segura[/bold yellow]\n"
                    f"Artículos archivados en esta sesión: [bold green]{len(archived_paths)}[/bold green]\n"
                    f"Estado guardado en: [dim]{state_file}[/dim]\n"
                    f"[bold cyan]Para reanudar exactamente desde donde quedó, simplemente vuelve a ejecutar el mismo comando.[/bold cyan]",
                    border_style="yellow",
                )
            )
            return archived_paths

        # Session finished cleanly
        state_mgr.clear()

        self.console.print()
        self.console.print(
            Panel.fit(
                f"[bold green][✓] ¡Descarga y archivado completados con éxito![/bold green]\n"
                f"[bold white]Artículos descargados:[/bold white] [bold green]{len(archived_paths)}[/bold green] / {len(articles_to_download)}\n"
                f"[bold white]Artículos en biblioteca previa:[/bold white] [yellow]{already_count}[/yellow]\n"
                f"[bold white]Fallidos / sin contenido:[/bold white] [dim]{failed_count}[/dim]\n"
                f"[bold white]Tiempo total:[/bold white] [cyan]{elapsed_total:.1f}s[/cyan] ([bold white]{speed:.2f} arts/seg[/bold white])\n"
                f"[bold white]Destino local:[/bold white] [cyan]{target_dir.resolve()}[/cyan]",
                border_style="green",
            )
        )

        return archived_paths

    def render_directory_tree(self, root_path: Path) -> None:
        """Render a visual directory tree of the generated knowledge base."""
        if not root_path.exists():
            return

        tree = Tree(
            f":open_file_folder: [bold cyan]{root_path}[/bold cyan]",
            guide_style="bright_blue",
        )

        def add_nodes(current_path: Path, current_tree: Tree) -> None:
            entries = sorted(
                current_path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    branch = current_tree.add(
                        f":file_folder: [bold yellow]{entry.name}/[/bold yellow]"
                    )
                    add_nodes(entry, branch)
                else:
                    size_kb = entry.stat().st_size / 1024
                    icon = ":memo:" if entry.suffix == ".md" else ":frame_with_picture:"
                    current_tree.add(
                        f"{icon} [white]{entry.name}[/white] [dim]({size_kb:.1f} KB)[/dim]"
                    )

        add_nodes(root_path, tree)
        self.console.print()
        self.console.print(tree)
        self.console.print()


def parse_arguments() -> argparse.Namespace:
    """Configure and parse CLI flags."""
    parser = argparse.ArgumentParser(
        description="Medium Topic & Publication Archiver: Generate structured Markdown and local assets."
    )
    parser.add_argument(
        "-t",
        "--tag",
        "--topic",
        dest="tag",
        type=str,
        default=None,
        help="Medium tag or topic to archive (e.g. security, python, bug-bounty).",
    )
    parser.add_argument(
        "-p",
        "--publication",
        dest="publication",
        type=str,
        default=None,
        help="Medium publication name or custom domain (e.g. infosec-writeups, bugbountywriteup).",
    )
    parser.add_argument(
        "-s",
        "--search",
        type=str,
        default=None,
        help="Search across your local knowledge base by title, author, topic, or keyword.",
    )
    parser.add_argument(
        "--stats",
        "--library",
        action="store_true",
        default=False,
        help="Display statistics and breakdown of your local knowledge base.",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        default=False,
        help="Auditar la calidad, encoding y formato Markdown de los artículos en la biblioteca sin modificar archivos.",
    )
    parser.add_argument(
        "--clean-markdown",
        "--fix-markdown",
        dest="clean_markdown",
        action="store_true",
        default=False,
        help="Auditar y limpiar en lote todos los archivos article.md (deduplicar bloques de código, reparar mojibake/UTF-8 y etiquetar sintaxis correctamente).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force re-downloading articles even if they already exist in the local library.",
    )
    parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of articles to archive (default: None / all found).",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        default=False,
        help="Use Medium static monthly archive discovery (2024-2026) to bypass RSS 10-item limit.",
    )
    parser.add_argument(
        "--from-year",
        dest="from_year",
        type=int,
        default=None,
        help="Starting publication year for archive discovery (e.g. 2024).",
    )
    parser.add_argument(
        "--to-year",
        dest="to_year",
        type=int,
        default=None,
        help="Ending publication year for archive discovery (e.g. 2026).",
    )
    parser.add_argument(
        "--feed-only",
        "--rss",
        dest="feed_only",
        action="store_true",
        default=False,
        help="Fetch only the latest RSS feed (capped at 10 items).",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=2024,
        help="Minimum publication year to include (default: 2024).",
    )
    parser.add_argument(
        "--max-year",
        type=int,
        default=2026,
        help="Maximum publication year to include (default: 2026).",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        default=False,
        help="Search across topic clusters and publications for comprehensive article discovery.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        default=False,
        help="List all matching articles and total count without downloading.",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        "--workers",
        dest="concurrency",
        type=int,
        default=4,
        help="Número de workers concurrentes para descarga en paralelo (default: 4, máx: 10).",
    )
    parser.add_argument(
        "--clean-state",
        dest="clean_state",
        action="store_true",
        default=False,
        help="Reiniciar la cola y descargar desde cero sin reanudar sesión previa.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default="knowledge_base",
        help="Target output directory for the knowledge base (default: knowledge_base).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        dest="non_interactive",
        action="store_true",
        help="Skip interactive confirmation prompts and proceed automatically.",
    )
    parser.add_argument(
        "-r",
        "--reader-url",
        action="append",
        dest="reader_urls",
        help="Custom web reader mirror base URL (can be specified multiple times).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP request timeout in seconds (default: 20).",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=0.5,
        help="Minimum polite delay in seconds between requests (default: 0.5).",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=1.5,
        help="Maximum polite delay in seconds between requests (default: 1.5).",
    )
    parser.add_argument(
        "--archive-file",
        "--export-zip",
        dest="archive_file",
        nargs="?",
        const="",
        default=None,
        help="Package the local knowledge base into a single zip archive file (/archivefile).",
    )

    return parser.parse_args()


def main() -> None:
    """CLI Entrypoint."""
    console = Console()
    args = parse_arguments()

    # Determine reader mirrors (CLI args override env var, which overrides defaults)
    readers = args.reader_urls
    if not readers:
        env_readers = os.environ.get("READER_URLS") or os.environ.get(
            "MEDIUM_READER_URL"
        )
        if env_readers:
            readers = [u.strip() for u in env_readers.split(",") if u.strip()]

    archiver = MediumArchiver(
        output_dir=args.output_dir,
        readers=readers,
        concurrency=args.concurrency,
        timeout=args.timeout,
        delay_min=args.delay_min,
        delay_max=args.delay_max,
        console=console,
    )

    # 0. Direct Archive-File Bundle Mode
    if args.archive_file is not None:
        import zipfile
        out_path = args.archive_file
        target_name = args.tag or "all_topics"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if out_path:
            zip_dest = Path(out_path).resolve()
            zip_dest.parent.mkdir(parents=True, exist_ok=True)
        else:
            exp_dir = archiver.output_dir / "exports"
            exp_dir.mkdir(parents=True, exist_ok=True)
            zip_dest = exp_dir / f"medium_knowledge_{target_name}_{timestamp}.zip"

        source_dir = archiver.output_dir / args.tag if args.tag else archiver.output_dir
        with console.status(f"[bold cyan]Empaquetando archivo zip en {zip_dest}...[/bold cyan]"):
            count = 0
            with zipfile.ZipFile(zip_dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for root, dirs, files in os.walk(source_dir):
                    if "exports" in Path(root).parts:
                        continue
                    for f in files:
                        p = Path(root) / f
                        zf.write(p, p.relative_to(archiver.output_dir))
                        count += 1
            size_mb = zip_dest.stat().st_size / (1024 * 1024)
        console.print(
            Panel.fit(
                f"[bold green][✓] Paquete de Archivo Generado (/archivefile):[/bold green]\n"
                f"[white]Archivo:[/white] [cyan]{zip_dest}[/cyan]\n"
                f"[white]Archivos Comprimidos:[/white] {count} | [white]Tamaño:[/white] {size_mb:.2f} MB",
                border_style="green",
            )
        )
        sys.exit(0)

    # 1. Direct Stats Mode
    if args.stats:
        archiver.library.render_library_stats()
        sys.exit(0)

    # 1.5. Direct Audit & Clean Markdown Mode
    if getattr(args, "audit", False) or getattr(args, "clean_markdown", False):
        should_fix = getattr(args, "clean_markdown", False)
        archiver.library.audit_and_clean_markdown(fix=should_fix)
        sys.exit(0)

    # 2. Direct Search Mode
    if args.search:
        results = archiver.library.search(args.search)
        archiver.library.render_search_results(args.search, results)
        sys.exit(0)

    topic = args.tag
    publication = args.publication

    # Interactive prompt if neither tag, publication, search, nor stats was specified
    if not topic and not publication:
        console.print(
            "[bold cyan]Medium Archiver - Menú Principal:[/] Selecciona una opción:"
        )
        choice = Prompt.ask(
            "Opción: ([green]1[/green] Descargar por Tag, [green]2[/green] Descargar por Publicación, [green]3[/green] Buscar en Biblioteca Local, [green]4[/green] Ver Estadísticas, [green]5[/green] Auditar / Limpiar Markdown)",
            choices=["1", "2", "3", "4", "5"],
            default="1",
        )
        if choice == "1":
            topic = Prompt.ask(
                "Ingresa tema/tag de Medium (ej. [green]bug-bounty[/green], [green]security[/green])"
            )
        elif choice == "2":
            publication = Prompt.ask(
                "Ingresa nombre de la Publicación (ej. [green]infosec-writeups[/green], [green]bugbountywriteup[/green])"
            )
        elif choice == "3":
            query = Prompt.ask("Ingresa término a buscar en tu biblioteca (ej. [green]SSRF[/green], [green]2FA[/green])")
            results = archiver.library.search(query)
            archiver.library.render_search_results(query, results)
            sys.exit(0)
        elif choice == "4":
            archiver.library.render_library_stats()
            sys.exit(0)
        elif choice == "5":
            do_fix = Confirm.ask(
                "¿Deseas reparar y limpiar los archivos automáticamente? (No = Solo auditar)",
                default=True,
            )
            archiver.library.audit_and_clean_markdown(fix=do_fix)
            sys.exit(0)

    if topic:
        topic = topic.strip()
    if publication:
        publication = publication.strip()

    if not topic and not publication:
        console.print("[bold red][-] Error: Tag o publicación no pueden estar vacíos.[/bold red]")
        sys.exit(1)

    min_year = args.from_year if args.from_year is not None else args.min_year
    max_year = args.to_year if args.to_year is not None else args.max_year

    # Determine whether to use archive discovery:
    if args.feed_only:
        archive_mode = False
    elif args.archive or args.from_year is not None or args.to_year is not None:
        archive_mode = True
    elif topic and not publication and not args.deep:
        archive_mode = True
    else:
        archive_mode = False

    archived_dirs = archiver.run(
        topic=topic,
        publication=publication,
        limit=args.limit,
        min_year=min_year,
        max_year=max_year,
        deep=args.deep,
        archive=archive_mode,
        force=args.force,
        clean_state=args.clean_state,
        list_only=args.list_only,
        non_interactive=args.non_interactive,
    )

    if archived_dirs:
        active_target = publication or topic or "archive"
        target_folder = Path(args.output_dir) / PathSanitizer.sanitize(active_target).lower()
        archiver.render_directory_tree(target_folder)


if __name__ == "__main__":
    main()
