#!/usr/bin/env python3
"""
server.py - Universal Model Context Protocol (MCP) Server for Medium Knowledge Base.

Enables AI agents across Antigravity, Claude Code, Gemini CLI, Cursor, Codex,
and Open Code to search, retrieve, archive, and export offline Medium articles,
tutorials, and research across any domain.

Usage:
    # Run with stdio transport (standard for MCP clients):
    python3 server.py
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional
import zipfile

# Support both MCP 2.x (MCPServer) and MCP 1.x (FastMCP)
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

# Ensure mediumm directory is in sys.path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from bs4 import BeautifulSoup
from rich.console import Console

from medium_archiver import (
    ArticleMetadata,
    LibraryManager,
    MediumArchiver,
    MediumFeedDiscoverer,
    PathSanitizer,
    fix_mojibake,
    is_safe_url,
)

# Base knowledge base path (can be overridden via environment variable)
DEFAULT_KB_DIR = Path(
    os.environ.get("MEDIUM_KNOWLEDGE_BASE", CURRENT_DIR / "knowledge_base")
).resolve()

server = MCPServer(
    name="medium-knowledge-base",
    instructions=(
        "Universal knowledge base toolset for searching, reading, archiving, "
        "and exporting offline Medium articles, technical writeups, tutorials, and research across any domain."
    ),
)

# Global archiver instance (quiet console for stdio compliance)
quiet_console = Console(file=sys.stderr, quiet=True)
archiver = MediumArchiver(
    output_dir=str(DEFAULT_KB_DIR),
    concurrency=4,
    console=quiet_console,
)
library: LibraryManager = archiver.library


@server.tool(
    name="medium_search_articles",
    description=(
        "Search offline local Medium knowledge base for articles, tutorials, writeups, or topics. "
        "Matches by title, author, topic, or keyword within the article content."
    ),
)
def medium_search_articles(
    query: str,
    topic: str = "",
    author: str = "",
    limit: int = 10,
) -> str:
    """
    Search across all indexed Medium articles in the local knowledge base.

    Args:
        query: Search term (e.g. 'LLM', 'FastAPI', 'Transformers', 'OAuth', 'Rust').
        topic: Optional topic filter (e.g. 'ai', 'programming', 'technology', 'security').
        author: Optional author name filter.
        limit: Maximum results to return (default: 10, max: 50).
    """
    library.load_or_rebuild()
    q_norm = query.lower().strip()
    topic_filter = topic.lower().strip()
    author_filter = author.lower().strip()
    max_results = max(1, min(limit, 50))

    results: List[Dict[str, Any]] = []

    # Priority 1: Match metadata (title, author, topic, hash)
    for entry in library.entries.values():
        if topic_filter and topic_filter not in entry.topic.lower():
            continue
        if author_filter and author_filter not in entry.author.lower():
            continue

        score = 0
        title_lower = entry.title.lower()
        if q_norm in title_lower:
            score += 10
        if q_norm in entry.post_hash.lower():
            score += 15
        if q_norm in entry.author.lower():
            score += 5

        # Priority 2: Fallback search into article markdown content if query not in title
        article_file = library.base_dir / entry.folder_rel_path / "article.md"
        excerpt = ""
        if article_file.exists():
            try:
                content = article_file.read_text(encoding="utf-8", errors="replace")
                if q_norm in content.lower():
                    score += 3
                    # Extract 180-char context window around the match
                    idx = content.lower().find(q_norm)
                    start = max(0, idx - 60)
                    end = min(len(content), idx + 120)
                    excerpt = "..." + content[start:end].replace("\n", " ").strip() + "..."
            except Exception:
                pass

        if score > 0 or not q_norm:
            results.append({
                "score": score,
                "title": entry.title,
                "author": entry.author,
                "topic": entry.topic,
                "published": entry.published,
                "post_hash": entry.post_hash,
                "source_url": entry.source_url,
                "path": entry.folder_rel_path + "/article.md",
                "images_count": entry.images_count,
                "excerpt": excerpt,
            })

    # Sort by relevance score descending
    results.sort(key=lambda x: x["score"], reverse=True)
    selected = results[:max_results]

    if not selected:
        return (
            f"No se encontraron artículos en la biblioteca local para la consulta: '{query}'.\n"
            f"Total de artículos disponibles en la base: {len(library.entries)}."
        )

    output = [
        f"### Resultados en Biblioteca Local Medium ({len(selected)} de {len(results)} coincidentes):\n"
    ]
    for idx, r in enumerate(selected, 1):
        output.append(
            f"**{idx}. {r['title']}**\n"
            f"- **Autor**: {r['author']} | **Tema**: #{r['topic']} | **Publicado**: {r['published']}\n"
            f"- **Hash/ID**: `{r['post_hash']}` | **Imágenes**: {r['images_count']}\n"
            f"- **Ruta local**: `{r['path']}`\n"
            f"- **URL Original**: {r['source_url']}"
        )
        if r["excerpt"]:
            output.append(f"- **Extracto**: *{r['excerpt']}*")
        output.append("")

    return "\n".join(output)


@server.tool(
    name="medium_get_article",
    description=(
        "Retrieve the full markdown text and YAML frontmatter of an article from the local library "
        "using its post hash ID, exact title, or relative path."
    ),
)
def medium_get_article(identifier: str) -> str:
    """
    Get full content of an article.

    Args:
        identifier: Post hash (e.g. '41899a8bd558'), article title, or relative path.
    """
    library.load_or_rebuild()
    ident = identifier.strip()

    # 1. Match by post_hash
    target_entry = library.entries.get(ident.lower())

    # 2. Match by normalized title
    if not target_entry:
        norm_title = library.normalize_title(ident)
        key = library.title_map.get(norm_title)
        if key:
            target_entry = library.entries.get(key)

    # 3. Match by relative path
    if not target_entry:
        clean_p = ident.replace("/article.md", "").strip("/")
        for entry in library.entries.values():
            if entry.folder_rel_path == clean_p or entry.folder_rel_path.endswith(clean_p):
                target_entry = entry
                break

    if not target_entry:
        return f"Error: No se encontró el artículo '{identifier}' en la biblioteca local."

    article_path = library.base_dir / target_entry.folder_rel_path / "article.md"
    if not article_path.exists():
        return f"Error: El archivo físico no existe en `{article_path}`."

    try:
        content = article_path.read_text(encoding="utf-8", errors="replace")
        return (
            f"# [Local Article] {target_entry.title}\n"
            f"- **Ruta**: `{article_path}`\n"
            f"- **Imágenes locales**: `{target_entry.images_count}` fotos en carpeta `images/`\n\n"
            f"{content}"
        )
    except Exception as e:
        return f"Error leyendo el archivo `{article_path}`: {e}"


@server.tool(
    name="medium_get_stats",
    description="Get statistics, topics breakdown, total articles, images, and disk usage of the local Medium library.",
)
def medium_get_stats() -> str:
    """Return knowledge base statistics and topic counts."""
    library.load_or_rebuild()
    topics: Dict[str, int] = {}
    total_size_kb = 0.0
    total_images = 0
    with library._lock:
        for entry in library.entries.values():
            topics[entry.topic] = topics.get(entry.topic, 0) + 1
            total_size_kb += entry.file_size_kb
            total_images += entry.images_count

    total_articles = len(library.entries)
    total_mb = total_size_kb / 1024.0
    topic_lines = [f"- **#{t}**: {count} artículos" for t, count in sorted(topics.items())]

    return (
        "### 📚 Estadísticas de la Biblioteca Local de Medium\n"
        f"- **Directorio Base**: `{library.base_dir}`\n"
        f"- **Total Artículos Guardados**: {total_articles}\n"
        f"- **Total Imágenes Locales**: {total_images}\n"
        f"- **Espacio Ocupado (Markdown)**: {total_mb:.2f} MB\n\n"
        "**Distribución por Temas:**\n"
        + ("\n".join(topic_lines) if topic_lines else "- Sin temas registrados.")
    )


@server.tool(
    name="medium_archive_url",
    description=(
        "Archive a single Medium article URL directly into the local knowledge base. "
        "Extracts full clean Markdown, saves HD images locally, and indexes it in the library."
    ),
)
def medium_archive_url(url: str, topic: str = "general") -> str:
    """
    Download and archive a specific article URL.

    Args:
        url: Full Medium article URL (e.g. 'https://medium.com/@user/my-article-123456789abc').
        topic: Topic folder name to store under (default: 'general').
    """
    # SSRF & protocol validation
    safe, reason = is_safe_url(url)
    if not safe:
        return f"Error de seguridad: URL insegura o no permitida ({reason}): '{url}'"

    # Sanitize topic parameter to prevent path traversal
    clean_topic = PathSanitizer.sanitize(topic) if topic else "general"
    if not clean_topic:
        clean_topic = "general"

    topic_dir = (archiver.output_dir / clean_topic).resolve()
    try:
        topic_dir.relative_to(archiver.output_dir.resolve())
    except ValueError:
        return f"Error de seguridad: El tema especificado '{topic}' intenta escapar del directorio de almacenamiento."

    # If user passed a mirror URL, extract the canonical Medium URL
    if "freedium" in url.lower() and "http" in url[8:]:
        m_url = re.search(r"https?://(?:www\.)?medium\.com/\S+", url)
        if m_url:
            url = m_url.group(0)

    library.load_or_rebuild()
    clean_url = MediumFeedDiscoverer.sanitize_url(url)
    post_hash = LibraryManager.extract_post_hash(clean_url)

    # Check if already exists in library
    dummy_meta = ArticleMetadata(
        index=0,
        title="",
        author="",
        published="",
        source_url=url,
        clean_url=clean_url,
        topic=clean_topic,
    )
    already, entry = library.check_archived(dummy_meta)
    if already and entry:
        return (
            f"[✓] El artículo ya existe en la biblioteca local:\n"
            f"- **Título**: {entry.title}\n"
            f"- **Ruta**: `{entry.folder_rel_path}/article.md`\n"
            f"- **Tema**: #{entry.topic}"
        )

    # Fetch through reader mirror
    html_content, base_url = archiver.reader_client.fetch_article_html(clean_url)
    if not html_content:
        return f"Error: No se pudo obtener el contenido HTML para '{clean_url}' a través de los mirrors."

    # Parse title & metadata from HTML
    soup = BeautifulSoup(html_content, "html.parser")
    title = ""
    h1_tag = soup.find("h1")
    if h1_tag:
        title = h1_tag.get_text(strip=True)
    elif soup.find("title"):
        title = soup.find("title").get_text(strip=True)

    title = re.sub(r"\s*-\s*Freedium.*$", "", title, flags=re.I).strip()
    title, _ = fix_mojibake(title)
    if not title:
        # Fallback to slug
        slug = clean_url.split("/")[-1].split("?")[0]
        title = re.sub(r"-[a-f0-9]{8,16}$", "", slug).replace("-", " ").title()

    author = ""
    author_elem = soup.find(attrs={"data-testid": "authorName"}) or soup.find(class_=re.compile(r"author", re.I))
    if author_elem:
        author = author_elem.get_text(strip=True)
    if not author or author.lower() in ["medium author", "unknown author", "freedium"]:
        m_auth = re.search(r"/@([^/?#]+)", clean_url)
        if m_auth:
            author = f"@{m_auth.group(1)}"
        else:
            author = "Medium Author"

    # Date parsing
    pub_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for date_cand in soup.find_all(["p", "time", "span"], class_=re.compile(r"(gray|date|time|published)", re.I)):
        dt_text = date_cand.get_text(strip=True)
        try:
            from datetime import datetime as dt_parser
            parsed_dt = dt_parser.strptime(dt_text, "%B %d, %Y")
            pub_date = parsed_dt.strftime("%Y-%m-%d")
            break
        except Exception:
            pass

    metadata = ArticleMetadata(
        index=1,
        title=title,
        author=author,
        published=pub_date,
        source_url=url,
        clean_url=clean_url,
        topic=clean_topic,
    )

    success, article_dir = archiver.archive_article(metadata, topic_dir)
    if not success:
        return f"Error: Falló el procesamiento del artículo para '{url}'."

    library.load_or_rebuild()
    images_count = len(list((article_dir / "images").glob("*"))) if (article_dir / "images").exists() else 0

    return (
        f"### [✓] Artículo archivado exitosamente!\n"
        f"- **Título**: {title}\n"
        f"- **Autor**: {author}\n"
        f"- **Fecha**: {pub_date}\n"
        f"- **Ruta**: `{article_dir.relative_to(library.base_dir)}/article.md`\n"
        f"- **Imágenes locales**: {images_count} descargadas en HD\n"
        f"- **Hash ID**: `{post_hash or 'N/A'}`"
    )


@server.tool(
    name="medium_export_archive",
    description=(
        "Export and bundle the local Medium knowledge base (or a specific topic) into a single "
        "portable zip archive file (/archivefile). Ideal for offline backups, sharing, or syncing."
    ),
)
def medium_export_archive(topic: str = "", output_zip_path: str = "") -> str:
    """
    Create a zip archive file of the knowledge base or topic.

    Args:
        topic: Specific topic folder to export (e.g. 'ai', 'python', 'security'). Leave empty for entire library.
        output_zip_path: Optional destination zip file path within the exports directory.
    """
    library.load_or_rebuild()
    source_dir = library.base_dir
    clean_topic = ""
    if topic:
        clean_topic = PathSanitizer.sanitize(topic)
        source_dir = (library.base_dir / clean_topic).resolve()
        try:
            source_dir.relative_to(library.base_dir.resolve())
        except ValueError:
            return f"Error de seguridad: El tema '{topic}' intenta escapar del directorio base."
        if not source_dir.exists():
            return f"Error: El tema '{topic}' no existe en `{library.base_dir}`."

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target_name = clean_topic or "all_topics"

    exports_dir = (library.base_dir / "exports").resolve()
    exports_dir.mkdir(parents=True, exist_ok=True)

    if output_zip_path:
        target_path = Path(output_zip_path)
        if not target_path.is_absolute():
            zip_file = (exports_dir / target_path).resolve()
        else:
            zip_file = target_path.resolve()

        try:
            zip_file.relative_to(exports_dir)
        except ValueError:
            return (
                f"Error de seguridad: La ruta de destino '{output_zip_path}' debe encontrarse "
                f"dentro del directorio seguro de exportaciones `{exports_dir}`."
            )
        if zip_file.suffix.lower() != ".zip":
            return "Error de seguridad: El archivo de exportación debe tener extensión '.zip'."
        zip_file.parent.mkdir(parents=True, exist_ok=True)
    else:
        zip_file = exports_dir / f"medium_knowledge_{target_name}_{timestamp}.zip"

    files_count = 0
    with zipfile.ZipFile(zip_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            if "exports" in Path(root).parts:
                continue
            for f in files:
                full_path = Path(root) / f
                arc_name = full_path.relative_to(library.base_dir)
                zf.write(full_path, arc_name)
                files_count += 1

    size_mb = zip_file.stat().st_size / (1024 * 1024)
    return (
        f"### [✓] Paquete de Archivo Generado con Éxito (/archivefile)\n"
        f"- **Archivo Zip**: `{zip_file}`\n"
        f"- **Archivos Comprimidos**: {files_count} (artículos Markdown + imágenes HD + manifiesto)\n"
        f"- **Tamaño del Archivo**: {size_mb:.2f} MB\n"
        f"- **Alcance**: {'Toda la biblioteca' if not clean_topic else f'Tema #{clean_topic}'}"
    )


def main() -> None:
    """Start MCP stdio server."""
    # FastMCP/MCPServer defaults to stdio transport
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
