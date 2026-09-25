from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple
import docx

from app.ai.ingestion.chunking import split_windows


@dataclass
class DocChunk:
    source_type: str = "documentation"
    title: str = "DBARS Documentation"
    section: str = "General"
    file: str = ""
    page: int = 1
    authority: str = "project_documentation"
    start_line: int = 1
    end_line: int = 1
    content: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "title": self.title,
            "section": self.section,
            "file": self.file,
            "page": self.page,
            "authority": self.authority,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
        }


def _section_chunks(
    rel_path: str,
    title: str,
    sections: List[Tuple[str, int, List[str]]],
    lines_per_page: int = 0,
) -> List[DocChunk]:
    """Window each (section, first_line_index, lines) into chunks.

    ``start_line``/``end_line`` index the same flattened lines ``content`` is
    made of, so an excerpt inside a chunk can be cited by its own line range.
    """
    chunks: List[DocChunk] = []
    for section, first, lines in sections:
        if len("\n".join(lines).strip()) <= 20:
            continue
        for a, b in split_windows(lines):
            text = "\n".join(lines[a:b + 1])
            if not text.strip():
                continue
            start = first + a + 1
            chunks.append(DocChunk(
                title=title,
                section=section,
                file=rel_path,
                page=1 + (start // lines_per_page) if lines_per_page else 1,
                start_line=start,
                end_line=first + b + 1,
                content=text,
            ))
    return chunks


class MarkdownDocParser:
    """Structure-aware parser for Markdown documentation files."""

    HEADER_REGEX = re.compile(r"^(#{1,4})\s+(.+)$")

    @staticmethod
    def parse_file(rel_path: str, content: str) -> List[DocChunk]:
        lines = content.splitlines()
        doc_title = Path(rel_path).stem.replace("-", " ").replace("_", " ").title()
        for line in lines[:10]:
            if line.startswith("# "):
                doc_title = line.lstrip("# ").strip()
                break

        sections: List[Tuple[str, int, List[str]]] = []
        current, first, buf = "Overview", 0, []
        for idx, line in enumerate(lines):
            m = MarkdownDocParser.HEADER_REGEX.match(line)
            if m and buf:
                sections.append((current, first, buf))
                buf = []
            if m:
                current, first = m.group(2).strip(), idx
            buf.append(line)
        if buf:
            sections.append((current, first, buf))
        return _section_chunks(rel_path, doc_title, sections)


def docx_blocks(file_path: Path) -> Iterator[Tuple[str, str]]:
    """Yield ("heading:<level>" | "para" | "table", text) in document order.

    ``Document.paragraphs`` skips tables entirely, and in the project documents
    tables hold over a third of the text -- the role matrix, the MongoDB
    settings, the security audit. Walking the body element keeps them, in
    place, next to the heading they belong to.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = docx.Document(file_path)
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style_name = para.style.name.lower() if para.style is not None else ""
            level = re.search(r"heading\s*(\d)", style_name)
            if level:
                yield f"heading:{level.group(1)}", text
            elif "title" == style_name:
                yield "heading:1", text
            else:
                yield "para", text
        elif tag == "tbl":
            rows: List[str] = []
            for row in Table(child, doc).rows:
                cells: List[str] = []
                for cell in row.cells:
                    value = " ".join(cell.text.split())
                    # Merged cells repeat across the row; keep one copy.
                    if value and (not cells or cells[-1] != value):
                        cells.append(value)
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                yield "table", "\n".join(rows)


class DocxParser:
    """Parser for Microsoft Word (.docx) technical specifications and defense notes."""

    @staticmethod
    def parse_file(rel_path: str, file_path: Path, sanitize=lambda text: text) -> List[DocChunk]:
        doc_title = Path(rel_path).stem.replace("_", " ").title()

        # Flatten to lines -- one per paragraph, one per table row -- tracking
        # the heading path so a chunk from deep in section 26 still carries
        # "26. Ticketing > Shakti" as its context.
        sections: List[Tuple[str, int, List[str]]] = []
        heading_path: List[str] = []
        current = "Executive Summary"
        first, buf, line_no = 0, [], 0
        for kind, text in docx_blocks(file_path):
            text = sanitize(text)
            is_heading = kind.startswith("heading") or (
                kind == "para" and len(text) < 100 and text.isupper() and any(c.isalpha() for c in text)
            )
            if is_heading:
                level = int(kind.split(":")[1]) if kind.startswith("heading:") else 2
                if buf:
                    sections.append((current, first, buf))
                heading_path = heading_path[: level - 1] + [text]
                current = " > ".join(heading_path)
                first, buf = line_no, []
            block_lines = text.split("\n")
            buf.extend(block_lines)
            line_no += len(block_lines)
        if buf:
            sections.append((current, first, buf))
        return _section_chunks(rel_path, doc_title, sections, lines_per_page=40)
