from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import docx


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


class MarkdownDocParser:
    """Structure-aware parser for Markdown documentation files."""

    HEADER_REGEX = re.compile(r"^(#{1,4})\s+(.+)$")

    @staticmethod
    def parse_file(rel_path: str, content: str) -> List[DocChunk]:
        chunks: List[DocChunk] = []
        lines = content.splitlines()
        total_lines = len(lines)

        # Detect document title from first h1 or filename
        doc_title = Path(rel_path).stem.replace("-", " ").replace("_", " ").title()
        for line in lines[:10]:
            if line.startswith("# "):
                doc_title = line.lstrip("# ").strip()
                break

        current_section = "Overview"
        current_lines: List[str] = []
        section_start_line = 1

        for idx, line in enumerate(lines, start=1):
            m = MarkdownDocParser.HEADER_REGEX.match(line)
            if m:
                # Save previous section if it has content
                if current_lines:
                    text = "\n".join(current_lines).strip()
                    if len(text) > 20:
                        chunks.append(
                            DocChunk(
                                source_type="documentation",
                                title=doc_title,
                                section=current_section,
                                file=rel_path,
                                start_line=section_start_line,
                                end_line=idx - 1,
                                content=text,
                            )
                        )
                current_section = m.group(2).strip()
                current_lines = [line]
                section_start_line = idx
            else:
                current_lines.append(line)

        # Append final section
        if current_lines:
            text = "\n".join(current_lines).strip()
            if len(text) > 20:
                chunks.append(
                    DocChunk(
                        source_type="documentation",
                        title=doc_title,
                        section=current_section,
                        file=rel_path,
                        start_line=section_start_line,
                        end_line=total_lines,
                        content=text,
                    )
                )

        return chunks


class DocxParser:
    """Parser for Microsoft Word (.docx) technical specifications and defense notes."""

    @staticmethod
    def parse_file(rel_path: str, file_path: Path) -> List[DocChunk]:
        chunks: List[DocChunk] = []
        doc = docx.Document(file_path)

        doc_title = Path(rel_path).stem.replace("_", " ").title()
        current_section = "Executive Summary"
        current_paras: List[str] = []
        page_approx = 1
        para_count = 0

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            para_count += 1
            if para_count % 8 == 0:
                page_approx += 1

            style_name = para.style.name.lower() if para.style else ""
            is_heading = "heading" in style_name or (len(text) < 100 and (text.startswith("Section") or text.isupper()))

            if is_heading:
                if current_paras:
                    section_content = "\n".join(current_paras).strip()
                    if len(section_content) > 30:
                        chunks.append(
                            DocChunk(
                                source_type="documentation",
                                title=doc_title,
                                section=current_section,
                                file=rel_path,
                                page=max(1, page_approx),
                                start_line=max(1, para_count - len(current_paras)),
                                end_line=para_count,
                                content=section_content,
                            )
                        )
                current_section = text
                current_paras = []
            else:
                current_paras.append(text)

        if current_paras:
            section_content = "\n".join(current_paras).strip()
            if len(section_content) > 30:
                chunks.append(
                    DocChunk(
                        source_type="documentation",
                        title=doc_title,
                        section=current_section,
                        file=rel_path,
                        page=max(1, page_approx),
                        start_line=max(1, para_count - len(current_paras)),
                        end_line=para_count,
                        content=section_content,
                    )
                )

        return chunks
