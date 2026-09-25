"""Text analysis shared by indexing and querying.

Both sides of retrieval must tokenize identically, or a term indexed one way is
searched for another and silently never matches. Everything that turns text
into terms lives here for that reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Set, Tuple

STOP_WORDS: FrozenSet[str] = frozenset({
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "what", "which", "who", "whom", "this", "that", "these",
    "those", "it", "its", "as", "if", "then", "else", "when", "where", "how", "all",
    "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just", "about",
    "i", "me", "my", "we", "our", "you", "your", "there", "here", "into", "out", "up",
    "get", "gets", "tell", "show", "explain", "describe", "work", "works", "used", "use", "uses",
    "dbars", "please", "would", "could", "should", "want", "need", "know",
    # Question framing ("how big", "how many", "how long"): rare in the corpus,
    # so as terms they carried the highest weight while meaning nothing.
    "big", "many", "much", "large", "long", "exactly", "happen", "happens", "mean", "means", "kind",
    "say", "says", "said",
})

# `name: int = 30`, `NAME = ...`, `self.name = ...`, `const name =`, `"name": ...`
_DEFINED_NAME = re.compile(
    r"^\s*(?:self\.)?([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=\n]*)?=(?!=)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    r"|^\s*\"([A-Za-z_][\w]*)\"\s*:",
    re.M,
)


def defined_names(content: str) -> List[str]:
    """Names a chunk assigns or declares: fields, constants, settings keys."""
    return [next(g for g in m.groups() if g) for m in _DEFINED_NAME.finditer(content)]

_WORD = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_QUOTED = re.compile(r"[\"“‘'`]([^\"”’'`]{2,80})[\"”’'`]")
_FILENAME = re.compile(r"\b[\w\-]+\.(?:py|tsx?|jsx?|json|md|ya?ml|ini|docx|ps1|bat|toml|cfg)\b", re.I)
_IDENTIFIER = re.compile(r"\b(?:[a-z]+_[a-z0-9_]+|_[a-z0-9_]+|[a-z]+[A-Z]\w*|[A-Z][a-z0-9]+[A-Z]\w*|[A-Z]{2,}[a-z]\w*)\b")


# Identifiers abbreviate; questions spell out. `max_spreadover_minutes` should
# answer "what is the maximum spreadover". Applied on both sides, like stemming.
ABBREVIATIONS: Dict[str, str] = {
    "maximum": "max",
    "minimum": "min",
    "configuration": "config",
    "configurations": "config",
    "parameter": "param",
    "parameters": "param",
    "params": "param",
    "information": "info",
    "authentication": "auth",
    "authorization": "auth",
    "database": "db",
    "environment": "env",
    "directory": "dir",
    "repository": "repo",
    "identifier": "id",
    "initialize": "init",
    "initialise": "init",
    "initialization": "init",
    "temporary": "temp",
    "statistics": "stats",
    "application": "app",
}


def stem(word: str) -> str:
    """Conservative suffix stripping: plurals, -ed, -ing, -ion, final e.

    Not linguistics -- it only has to map the forms people type ("computed",
    "computes", "computation") onto one key, identically on both sides.
    """
    w = ABBREVIATIONS.get(word, word)
    if len(w) <= 3 or not w.isalpha():
        return w
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("ses") and len(w) > 4 and w[:-2].endswith("s"):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suffix in ("ing", "ed"):
        stem_part = w[: -len(suffix)]
        if w.endswith(suffix) and len(stem_part) >= 3 and any(v in stem_part for v in "aeiouy"):
            w = stem_part
            if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
                w = w[:-1]
            break
    if w.endswith("ion") and len(w) > 6 and w[-4] in "ts":
        w = w[:-3]
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


def split_identifier(raw: str) -> List[str]:
    """``AIAssistantModal`` -> ai, assistant, modal; ``route_rank_score`` -> route, rank, score."""
    parts: List[str] = []
    for piece in raw.split("_"):
        if piece:
            parts.extend(p.lower() for p in _CAMEL_PART.findall(piece))
    return parts


def tokenize(text: str, filter_stops: bool = True) -> List[str]:
    """Terms for BM25: the whole identifier plus its camel/snake parts, stemmed."""
    terms: List[str] = []
    for raw in _WORD.findall(text):
        whole = raw.lower()
        parts = split_identifier(raw)
        candidates = [whole] + (parts if len(parts) > 1 else [])
        for term in candidates:
            if filter_stops and term in STOP_WORDS:
                continue
            terms.append(stem(term))
    return terms


def normalize_for_phrases(text: str) -> str:
    """Identifiers split, words stemmed, punctuation collapsed.

    ``label: "Quiet Hours"`` -> `` label quiet hour ``, and ``CrowdingLevel`` ->
    `` crowd level `` -- so "crowding levels" in a question matches the enum
    that defines them.
    """
    words: List[str] = []
    for raw in _WORD.findall(text):
        parts = split_identifier(raw)
        words.extend(stem(p) for p in (parts if parts else [raw.lower()]))
    return " " + " ".join(words) + " "


_AI_LAYER_TOPIC = re.compile(
    r"\b(?:ai|assistant|copilot|chatbot|llm|gemini|rag|retriev\w*|embedding\w*|grounding|"
    r"citations?|guardrails?|prompts?|orchestrat\w*|agents?|hallucinat\w*|intelligence layer|"
    r"session memory|conversation\w*|benchmark\w*|evaluation)\b",
    re.I,
)


@dataclass
class AnalyzedQuery:
    raw: str
    terms: List[str]
    phrases: List[str]
    quoted: List[str]
    filenames: List[str]
    identifiers: List[str]
    mentions_tests: bool = False
    about_ai_layer: bool = False
    term_set: Set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.term_set = set(self.terms)


def analyze_query(query: str) -> AnalyzedQuery:
    words = _WORD.findall(query)
    # Adjacent content words form candidate phrases. A UI label ("Smart
    # Auto"), a table row ("best_option_rate") or a message ("reach the
    # server") is matched far more reliably as a phrase than as loose terms.
    phrases: List[str] = []
    run: List[str] = []
    for w in words:
        lw = w.lower()
        if lw in STOP_WORDS:
            if len(run) >= 2:
                phrases.append(" ".join(run))
            run = []
        else:
            run.extend(stem(p) for p in (split_identifier(w) or [lw]))
    if len(run) >= 2:
        phrases.append(" ".join(run))
    bigrams: List[str] = []
    for phrase in phrases:
        tokens = phrase.split()
        for i in range(len(tokens) - 1):
            bigrams.append(f"{tokens[i]} {tokens[i + 1]}")
    quoted = [normalize_for_phrases(q).strip() for q in _QUOTED.findall(query)]
    all_phrases = list(dict.fromkeys([p for p in phrases + bigrams + quoted if p]))
    return AnalyzedQuery(
        raw=query,
        terms=list(dict.fromkeys(tokenize(query))),
        phrases=all_phrases,
        quoted=[q for q in quoted if q],
        filenames=[f.lower() for f in _FILENAME.findall(query)],
        identifiers=list(dict.fromkeys(m for m in _IDENTIFIER.findall(query))),
        mentions_tests=bool(re.search(r"\btests?\b|\btesting\b|pytest|test_", query, re.I)),
        about_ai_layer=bool(_AI_LAYER_TOPIC.search(query)),
    )


def chunk_search_text(meta: Mapping[str, Any]) -> str:
    """What a chunk is indexed under: its location and name, then its text.

    The path and symbol carry meaning the body often lacks -- a window from the
    middle of a component never repeats the component's name -- so they are
    indexed with every chunk rather than only the first.
    """
    header = " ".join(
        str(meta.get(key) or "")
        for key in ("file", "title", "section", "symbol", "type")
    )
    doc = meta.get("docstring") or ""
    return f"{header}\n{doc}\n{meta.get('content', '')}"


def term_weights(query: AnalyzedQuery, idf: Mapping[str, float]) -> Dict[str, float]:
    """IDF weight per query term; unknown terms get the rarest weight seen."""
    ceiling = max(idf.values(), default=1.0)
    return {t: idf.get(t, ceiling) for t in query.terms}


def best_excerpt(
    content: str,
    query: AnalyzedQuery,
    weights: Mapping[str, float],
    max_chars: int = 1000,
) -> Tuple[str, int, int]:
    """The window of ``content`` that best answers the query.

    Returns (text, first_line, last_line), line numbers 0-based within
    ``content``. Handing the answer model the head of a chunk -- the old
    ``content[:350]`` -- cut a UI label out of the very chunk that defined it.
    """
    lines = content.splitlines() or [""]
    if len(content) <= max_chars:
        return content, 0, len(lines) - 1

    scores: List[float] = []
    for line in lines:
        line_terms = set(tokenize(line))
        score = sum(weights.get(t, 0.0) for t in line_terms & query.term_set)
        if query.phrases:
            normalized = normalize_for_phrases(line)
            score += sum(2.0 * max(weights.values(), default=1.0) for p in query.phrases if f" {p} " in normalized)
        scores.append(score)

    lengths = [len(line) + 1 for line in lines]
    best_sum, best_i, best_j = -1.0, 0, 0
    i, window_sum, window_len = 0, 0.0, 0
    for j in range(len(lines)):
        window_sum += scores[j]
        window_len += lengths[j]
        while window_len > max_chars and i < j:
            window_sum -= scores[i]
            window_len -= lengths[i]
            i += 1
        if window_sum > best_sum:
            best_sum, best_i, best_j = window_sum, i, j

    # Trim zero-score edges, then grow outward for context while budget allows.
    while best_i < best_j and scores[best_i] == 0:
        best_i += 1
    while best_j > best_i and scores[best_j] == 0:
        best_j -= 1
    used = sum(lengths[best_i:best_j + 1])
    grow_up = True
    while True:
        if grow_up and best_i > 0 and used + lengths[best_i - 1] <= max_chars:
            best_i -= 1
            used += lengths[best_i]
        elif not grow_up and best_j < len(lines) - 1 and used + lengths[best_j + 1] <= max_chars:
            best_j += 1
            used += lengths[best_j]
        elif (best_i == 0 or used + lengths[best_i - 1] > max_chars) and (
            best_j == len(lines) - 1 or used + lengths[best_j + 1] > max_chars
        ):
            break
        grow_up = not grow_up

    text = "\n".join(lines[best_i:best_j + 1])
    if len(text) > max_chars:
        text = text[:max_chars]
    return text, best_i, best_j
