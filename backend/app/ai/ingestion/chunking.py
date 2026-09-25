"""Size-bounded windows over a chunk's lines.

Structure-aware parsers produce chunks as long as the construct they wrap: the
AIAssistantModal component was one 26k-character chunk, a docs build script
56k. A chunk that size cannot be embedded meaningfully and cannot be shown to
the answer model whole, so oversized chunks are cut into overlapping windows
that each keep the parent's file and symbol.
"""

from __future__ import annotations

from typing import List, Tuple

# ~30-40 lines of code. Small enough that the whole window fits in the answer
# model's evidence budget and in the embedding model's input.
MAX_CHUNK_CHARS = 1500
TARGET_WINDOW_CHARS = 1200
OVERLAP_LINES = 4


def split_windows(lines: List[str], max_chars: int = MAX_CHUNK_CHARS) -> List[Tuple[int, int]]:
    """Return inclusive (start, end) line index pairs covering ``lines``.

    A text that fits returns a single window. Otherwise windows fill to about
    TARGET_WINDOW_CHARS, end at a blank line when one is near, and overlap by a
    few lines so a statement split across a boundary is whole in one of them.
    """
    if not lines:
        return []
    total = sum(len(line) + 1 for line in lines)
    if total <= max_chars:
        return [(0, len(lines) - 1)]

    windows: List[Tuple[int, int]] = []
    start = 0
    n = len(lines)
    while start < n:
        size = 0
        end = start
        while end < n and (size + len(lines[end]) + 1 <= TARGET_WINDOW_CHARS or end == start):
            size += len(lines[end]) + 1
            end += 1
        end -= 1  # inclusive
        if end < n - 1:
            # Prefer to finish on a blank line in the last third of the window.
            floor = start + max(1, (end - start) * 2 // 3)
            for k in range(end, floor - 1, -1):
                if not lines[k].strip():
                    end = k
                    break
        windows.append((start, end))
        if end >= n - 1:
            break
        next_start = end + 1 - OVERLAP_LINES
        start = next_start if next_start > start else end + 1
    return windows
