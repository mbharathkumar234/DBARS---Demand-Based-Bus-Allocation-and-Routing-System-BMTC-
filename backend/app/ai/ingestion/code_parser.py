from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CodeChunk:
    file: str
    language: str
    module: str
    symbol: str
    type: str  # function | method | class | interface | type | component | config | module
    start_line: int
    end_line: int
    content: str
    docstring: Optional[str] = None
    source: str = "repository"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "language": self.language,
            "module": self.module,
            "symbol": self.symbol,
            "type": self.type,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "docstring": self.docstring,
            "source": self.source,
            "content": self.content,
        }


class PythonCodeParser:
    """AST-based structural parser for Python files."""

    @staticmethod
    def parse_file(rel_path: str, code: str) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []
        lines = code.splitlines()
        total_lines = len(lines)
        module_name = Path(rel_path).stem

        try:
            tree = ast.parse(code, filename=rel_path)
        except Exception:
            # Fallback for files that cannot be parsed as valid AST
            return [
                CodeChunk(
                    file=rel_path,
                    language="python",
                    module=module_name,
                    symbol=module_name,
                    type="module",
                    start_line=1,
                    end_line=total_lines,
                    content=code,
                )
            ]

        # 1. Module docstring & imports chunk
        module_doc = ast.get_docstring(tree)
        imports = []
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(ast.get_source_segment(code, node) or "")

        if imports or module_doc:
            import_content = "\n".join(filter(None, [f'"""{module_doc}"""' if module_doc else "", *imports]))
            chunks.append(
                CodeChunk(
                    file=rel_path,
                    language="python",
                    module=module_name,
                    symbol=f"{module_name}.__init__",
                    type="module_header",
                    start_line=1,
                    end_line=min(total_lines, max(10, len(imports) + 5)),
                    content=import_content,
                    docstring=module_doc,
                )
            )

        # 2. Iterate top-level AST nodes
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_doc = ast.get_docstring(node)
                class_start = getattr(node, "lineno", 1)
                class_end = getattr(node, "end_lineno", class_start)

                # Class overview chunk
                class_header_lines = lines[class_start - 1 : min(class_end, class_start + 15)]
                chunks.append(
                    CodeChunk(
                        file=rel_path,
                        language="python",
                        module=module_name,
                        symbol=node.name,
                        type="class",
                        start_line=class_start,
                        end_line=class_end,
                        content="\n".join(class_header_lines),
                        docstring=class_doc,
                    )
                )

                # Methods inside class
                for sub_node in node.body:
                    if isinstance(sub_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_doc = ast.get_docstring(sub_node)
                        m_start = getattr(sub_node, "lineno", class_start)
                        m_end = getattr(sub_node, "end_lineno", m_start)
                        method_code = "\n".join(lines[m_start - 1 : m_end])
                        chunks.append(
                            CodeChunk(
                                file=rel_path,
                                language="python",
                                module=module_name,
                                symbol=f"{node.name}.{sub_node.name}",
                                type="method",
                                start_line=m_start,
                                end_line=m_end,
                                content=method_code,
                                docstring=method_doc,
                            )
                        )

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_doc = ast.get_docstring(node)
                f_start = getattr(node, "lineno", 1)
                f_end = getattr(node, "end_lineno", f_start)
                func_code = "\n".join(lines[f_start - 1 : f_end])
                chunks.append(
                    CodeChunk(
                        file=rel_path,
                        language="python",
                        module=module_name,
                        symbol=node.name,
                        type="function",
                        start_line=f_start,
                        end_line=f_end,
                        content=func_code,
                        docstring=func_doc,
                    )
                )

        return chunks


class TypeScriptCodeParser:
    """Structure-aware parser for TypeScript and TSX files."""

    INTERFACE_REGEX = re.compile(r"^(?:export\s+)?interface\s+(\w+)", re.MULTILINE)
    TYPE_REGEX = re.compile(r"^(?:export\s+)?type\s+(\w+)", re.MULTILINE)
    FUNC_REGEX = re.compile(r"^(?:export\s+)?(?:default\s+)?function\s+(\w+)", re.MULTILINE)
    CONST_FUNC_REGEX = re.compile(r"^(?:export\s+)?const\s+(\w+)\s*=\s*(?:\([^)]*\)|[a-zA-Z0-9_]+)\s*=>", re.MULTILINE)

    @staticmethod
    def parse_file(rel_path: str, code: str) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []
        lines = code.splitlines()
        total_lines = len(lines)
        module_name = Path(rel_path).stem

        # Extract top-level symbols and line numbers
        symbols: List[tuple[int, str, str]] = []  # (line_no, symbol_name, type)

        for i, line in enumerate(lines, start=1):
            m = TypeScriptCodeParser.INTERFACE_REGEX.match(line)
            if m:
                symbols.append((i, m.group(1), "interface"))
                continue
            m = TypeScriptCodeParser.TYPE_REGEX.match(line)
            if m:
                symbols.append((i, m.group(1), "type"))
                continue
            m = TypeScriptCodeParser.FUNC_REGEX.match(line)
            if m:
                name = m.group(1)
                sym_type = "component" if name[0].isupper() else "function"
                symbols.append((i, name, sym_type))
                continue
            m = TypeScriptCodeParser.CONST_FUNC_REGEX.match(line)
            if m:
                name = m.group(1)
                sym_type = "component" if name[0].isupper() else "function"
                symbols.append((i, name, sym_type))
                continue

        if not symbols:
            # Chunk into ~60 line segments if no prominent symbols
            step = 60
            for start in range(0, total_lines, step):
                end = min(total_lines, start + step)
                chunks.append(
                    CodeChunk(
                        file=rel_path,
                        language="typescript",
                        module=module_name,
                        symbol=f"{module_name}:L{start+1}-L{end}",
                        type="code_segment",
                        start_line=start + 1,
                        end_line=end,
                        content="\n".join(lines[start:end]),
                    )
                )
            return chunks

        # Chunk between detected symbol boundaries
        for idx, (line_no, sym_name, sym_type) in enumerate(symbols):
            next_line = symbols[idx + 1][0] - 1 if idx + 1 < len(symbols) else total_lines
            content = "\n".join(lines[line_no - 1 : next_line])
            chunks.append(
                CodeChunk(
                    file=rel_path,
                    language="typescript",
                    module=module_name,
                    symbol=sym_name,
                    type=sym_type,
                    start_line=line_no,
                    end_line=next_line,
                    content=content,
                )
            )

        return chunks


class GenericFileParser:
    """Parser for config, yaml, markdown, and script files."""

    @staticmethod
    def parse_file(rel_path: str, content: str, language: str = "config") -> List[CodeChunk]:
        lines = content.splitlines()
        total_lines = len(lines)
        module_name = Path(rel_path).name

        if total_lines <= 80:
            return [
                CodeChunk(
                    file=rel_path,
                    language=language,
                    module=module_name,
                    symbol=module_name,
                    type="config",
                    start_line=1,
                    end_line=total_lines,
                    content=content,
                )
            ]

        chunks: List[CodeChunk] = []
        step = 60
        for start in range(0, total_lines, step):
            end = min(total_lines, start + step)
            chunks.append(
                CodeChunk(
                    file=rel_path,
                    language=language,
                    module=module_name,
                    symbol=f"{module_name}:L{start+1}-L{end}",
                    type="config_block",
                    start_line=start + 1,
                    end_line=end,
                    content="\n".join(lines[start:end]),
                )
            )
        return chunks
