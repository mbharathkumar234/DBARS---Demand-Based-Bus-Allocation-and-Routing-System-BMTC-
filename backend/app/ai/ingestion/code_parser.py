from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.ai.ingestion.chunking import split_windows


@dataclass
class CodeChunk:
    file: str
    language: str
    module: str
    symbol: str
    type: str  # function | method | class | interface | type | enum | component | constant | module_header | module_block | config
    start_line: int
    end_line: int
    content: str
    docstring: Optional[str] = None
    source: str = "repository"
    # For a window that starts after the definition line: that line, so an
    # excerpt from the middle of a long function still says which function.
    signature: Optional[str] = None

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
            "signature": self.signature,
        }


def _windowed(
    lines: List[str],
    start: int,
    end: int,
    make: "callable",
    signature_idx: Optional[int] = None,
) -> List[CodeChunk]:
    """Chunks for lines[start..end] (0-based inclusive), split if oversized.

    ``content`` is always an exact slice of the file, so a line offset inside a
    chunk maps back to a real line number -- citations can then point at the
    lines that answer the question rather than at the whole construct.
    """
    body = lines[start:end + 1]
    chunks: List[CodeChunk] = []
    for a, b in split_windows(body):
        chunk = make(start + a + 1, start + b + 1, "\n".join(body[a:b + 1]))
        if signature_idx is not None and start + a > signature_idx:
            chunk.signature = lines[signature_idx].rstrip()
        chunks.append(chunk)
    return chunks


def _leading_comment_start(lines: List[str], def_start: int, floor: int, prefixes: Tuple[str, ...]) -> int:
    """Walk up from a definition over the comment block that describes it."""
    k = def_start
    while k - 1 >= floor and lines[k - 1].strip().startswith(prefixes):
        k -= 1
    return k


class PythonCodeParser:
    """AST-based structural parser for Python files."""

    @staticmethod
    def _assigned_names(node: ast.stmt) -> List[str]:
        targets: List[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        names: List[str] = []
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    names.append(sub.id)
        return names

    @staticmethod
    def parse_file(rel_path: str, code: str) -> List[CodeChunk]:
        lines = code.splitlines()
        total_lines = len(lines)
        module_name = Path(rel_path).stem

        def chunk(symbol: str, ctype: str, docstring: Optional[str] = None):
            def make(s: int, e: int, text: str) -> CodeChunk:
                return CodeChunk(
                    file=rel_path, language="python", module=module_name, symbol=symbol,
                    type=ctype, start_line=s, end_line=e, content=text, docstring=docstring,
                )
            return make

        try:
            tree = ast.parse(code, filename=rel_path)
        except Exception:
            return _windowed(lines, 0, max(0, total_lines - 1), chunk(module_name, "module"))

        chunks: List[CodeChunk] = []

        def node_start(node: ast.AST) -> int:
            decorators = getattr(node, "decorator_list", None) or []
            first = min([d.lineno for d in decorators] + [node.lineno])
            return first - 1  # 0-based

        # 1. Module header: docstring, imports and the comments among them.
        body = list(tree.body)
        header_end = -1
        for node in body:
            is_doc = (
                node is body[0]
                and isinstance(node, ast.Expr)
                and isinstance(getattr(node, "value", None), ast.Constant)
                and isinstance(node.value.value, str)
            )
            if is_doc or isinstance(node, (ast.Import, ast.ImportFrom)):
                header_end = node.end_lineno - 1
            else:
                break
        if header_end >= 0:
            chunks.extend(_windowed(lines, 0, header_end, chunk(f"{module_name}.__init__", "module_header", ast.get_docstring(tree))))

        # 2. Top-level statements in order. Runs of plain statements (constants,
        # lookup tables, settings objects) become chunks of their own; they
        # were previously dropped, so QUERY_VOCABULARY or a settings default
        # was unreachable by any question.
        prev_end = header_end
        pending: List[ast.stmt] = []

        def flush_pending() -> None:
            if not pending:
                return
            names = [n for stmt in pending for n in PythonCodeParser._assigned_names(stmt)]
            first = pending[0]
            start = _leading_comment_start(lines, node_start(first), block_floor[0], ("#",))
            end = pending[-1].end_lineno - 1
            if names:
                symbol = names[0]
            elif isinstance(first, ast.If) and "__main__" in (ast.get_source_segment(code, first.test) or ""):
                symbol = "__main__"
            else:
                symbol = f"{module_name}:L{start + 1}-L{end + 1}"
            chunks.extend(_windowed(lines, start, end, chunk(symbol, "module_block")))
            pending.clear()

        block_floor = [prev_end + 1]
        for node in body:
            if node.end_lineno - 1 <= header_end:
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                flush_pending()
                start = _leading_comment_start(lines, node_start(node), prev_end + 1, ("#",))
                if isinstance(node, ast.ClassDef):
                    chunks.extend(PythonCodeParser._class_chunks(node, lines, start, chunk))
                else:
                    chunks.extend(_windowed(
                        lines, start, node.end_lineno - 1,
                        chunk(node.name, "function", ast.get_docstring(node)), node.lineno - 1,
                    ))
                prev_end = node.end_lineno - 1
                block_floor[0] = prev_end + 1
            else:
                if not pending:
                    block_floor[0] = prev_end + 1
                pending.append(node)
                prev_end = node.end_lineno - 1
        flush_pending()
        return chunks

    @staticmethod
    def _class_chunks(node: ast.ClassDef, lines: List[str], start: int, chunk) -> List[CodeChunk]:
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        chunks: List[CodeChunk] = []
        # The class chunk is everything before the first method -- docstring,
        # fields, enum members -- plus the constructor when it comes first,
        # since that is where a plain class declares its state and defaults.
        # It used to be the first 16 lines, which cut a 59-line settings
        # dataclass off before most of its fields.
        def def_start(fn: ast.AST) -> int:
            return min([d.lineno for d in fn.decorator_list] + [fn.lineno]) - 1

        if methods and methods[0].name == "__init__":
            header_end = methods[0].end_lineno - 1
            methods = methods[1:]
        elif methods:
            header_end = _leading_comment_start(lines, def_start(methods[0]), start, ("#",)) - 1
        else:
            header_end = node.end_lineno - 1
        header_end = max(header_end, start)
        chunks.extend(_windowed(
            lines, start, header_end, chunk(node.name, "class", ast.get_docstring(node)), node.lineno - 1,
        ))

        prev = header_end
        for method in methods:
            m_start = _leading_comment_start(lines, def_start(method), prev + 1, ("#",))
            chunks.extend(_windowed(
                lines, m_start, method.end_lineno - 1,
                chunk(f"{node.name}.{method.name}", "method", ast.get_docstring(method)), method.lineno - 1,
            ))
            prev = method.end_lineno - 1
        return chunks


class TypeScriptCodeParser:
    """Declaration-boundary parser for TypeScript and TSX files."""

    DECLARATION = re.compile(
        r"^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:async\s+)?(?:abstract\s+)?"
        r"(function\*?|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)"
    )
    FUNCTION_VALUE = re.compile(r"=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>|=\s*(?:async\s+)?function\b|=\s*(?:React\.)?(?:memo|forwardRef)\(")
    COMMENT_PREFIXES = ("//", "/*", "*", "*/", "@")

    @classmethod
    def _declaration_type(cls, keyword: str, name: str, line: str) -> str:
        if keyword.startswith("function"):
            return "component" if name[:1].isupper() else "function"
        if keyword in ("class", "interface", "type", "enum"):
            return keyword
        if cls.FUNCTION_VALUE.search(line):
            return "component" if name[:1].isupper() else "function"
        return "constant"

    @staticmethod
    def parse_file(rel_path: str, code: str) -> List[CodeChunk]:
        lines = code.splitlines()
        total_lines = len(lines)
        module_name = Path(rel_path).stem

        def chunk(symbol: str, ctype: str):
            def make(s: int, e: int, text: str) -> CodeChunk:
                return CodeChunk(
                    file=rel_path, language="typescript", module=module_name, symbol=symbol,
                    type=ctype, start_line=s, end_line=e, content=text,
                )
            return make

        # Top-level declarations only: they start in column 0. `const
        # MODE_CONFIG = {...}` used to be invisible here (only arrow functions
        # counted), so the object defining every assistant mode was folded
        # into the preceding interface's chunk and cited as "ChatMessage".
        symbols: List[Tuple[int, str, str, int]] = []  # (start incl. leading comments, name, type, declaration line)
        prev_start = 0
        for i, line in enumerate(lines):
            m = TypeScriptCodeParser.DECLARATION.match(line)
            if not m:
                continue
            keyword, name = m.group(1), m.group(2)
            start = _leading_comment_start(lines, i, prev_start, TypeScriptCodeParser.COMMENT_PREFIXES)
            symbols.append((start, name, TypeScriptCodeParser._declaration_type(keyword, name, line), i))
            prev_start = i + 1

        if not symbols:
            return _windowed(lines, 0, max(0, total_lines - 1), chunk(module_name, "module"))

        chunks: List[CodeChunk] = []
        first_start = symbols[0][0]
        if first_start > 0 and any(l.strip() for l in lines[:first_start]):
            chunks.extend(_windowed(lines, 0, first_start - 1, chunk(f"{module_name}.__init__", "module_header")))

        for idx, (start, name, sym_type, decl_line) in enumerate(symbols):
            end = symbols[idx + 1][0] - 1 if idx + 1 < len(symbols) else total_lines - 1
            if end < start:
                continue
            chunks.extend(_windowed(lines, start, end, chunk(name, sym_type), decl_line))
        return chunks


class GenericFileParser:
    """Parser for config, yaml, markdown, and script files."""

    @staticmethod
    def parse_file(rel_path: str, content: str, language: str = "config") -> List[CodeChunk]:
        lines = content.splitlines()
        module_name = Path(rel_path).name
        windows = split_windows(lines)
        single = len(windows) == 1
        return [
            CodeChunk(
                file=rel_path,
                language=language,
                module=module_name,
                symbol=module_name if single else f"{module_name}:L{a + 1}-L{b + 1}",
                type="config" if single else "config_block",
                start_line=a + 1,
                end_line=b + 1,
                content="\n".join(lines[a:b + 1]),
            )
            for a, b in windows
        ]
