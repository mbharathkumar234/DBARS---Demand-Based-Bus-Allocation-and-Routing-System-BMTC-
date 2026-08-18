from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_SPACE_RE = re.compile(r"\s+")

# Noise suffixes/prefixes that add no disambiguation value.
#
# IMPORTANT: this must stay an ordered sequence (tuple), never a set/frozenset.
# normalize_text() below iterates this collection and returns on the FIRST
# match, so iteration order determines the result. A plain set/frozenset in
# Python has no stable iteration order across process restarts (string hash
# randomization, PYTHONHASHSEED), which previously caused the exact same
# input to normalize differently on different runs -- e.g.
# "Kempegowda Bus Station" normalized to "kempegowda bus station" on some
# runs (correct -- matches the "Majestic" alias target) and to
# "kempegowda bus" on others (broken -- matches nothing), because whichever
# of "bus station" / "station" happened to be visited first in that
# process's hash order would win.
#
# Sorting by descending length (with an alphabetical tiebreak for words of
# equal length) guarantees the more specific, multi-word phrase (e.g.
# "bus station") is always checked before the shorter word it contains
# (e.g. "station"), identically on every run, every machine, every restart.
_NOISE_WORDS: tuple[str, ...] = tuple(
    sorted(
        {
            "bus stop", "bus station", "bus stand", "bus terminus",
            "stop", "station", "stand", "terminus", "halt", "depot",
            "circle", "junction", "layout", "stage", "gate",
            "arrival", "departure", "depature",
        },
        key=lambda word: (-len(word), word),
    )
)

# Single-word noise tokens (stripped one at a time from the end)
_NOISE_TOKENS = frozenset({
    "stop", "station", "stand", "terminus", "halt", "depot",
    "circle", "junction", "gate", "arrival", "departure", "depature",
})

ALIASES: dict[str, str] = {
    # ── Kempegowda / Majestic ──────────────────────────────────────────
    "kbs": "kempegowda bus station",
    "majestic": "kempegowda bus station",
    "majestic bus station": "kempegowda bus station",
    "kempegowda": "kempegowda bus station",
    "kempe gowda": "kempegowda bus station",
    "central bus stand": "kempegowda bus station",

    # ── Shivajinagara ──────────────────────────────────────────────────
    "shivajinagar": "shivajinagara",
    "shivaji nagar": "shivajinagara",
    "shivajinagarr": "shivajinagara",

    # ── Yeshwanthapura ─────────────────────────────────────────────────
    "yeshwantpur": "yeshawanthapura",
    "yeshwanthpur": "yeshawanthapura",
    "ypr": "yeshawanthapura",
    "yeshawanthpur": "yeshawanthapura",

    # ── Whitefield ─────────────────────────────────────────────────────
    "whitefield": "white field",
    "whitefiled": "white field",
    "white fields": "white field",

    # ── Silk Board ─────────────────────────────────────────────────────
    "silkboard": "silk board",
    "silk board junction": "silk board",
    "silk board flyover": "silk board",

    # ── KR Market ──────────────────────────────────────────────────────
    "k r market": "kr market",
    "krantiveera sangolli rayanna": "kr market",
    "city market": "kr market",

    # ── Hebbal ─────────────────────────────────────────────────────────
    "hebbala": "hebbal",
    "hebbal flyover": "hebbal",

    # ── Marathahalli ───────────────────────────────────────────────────
    "marathalli": "marathahalli",
    "marathhalli": "marathahalli",

    # ── Koramangala ────────────────────────────────────────────────────
    "koramangala": "koramangala",   # ensure canonical
    "kormanagala": "koramangala",
    "koramanagala": "koramangala",

    # ── Indiranagar ────────────────────────────────────────────────────
    "indiranagar": "indiranagar",
    "indira nagar": "indiranagar",

    # ── Jayanagar ──────────────────────────────────────────────────────
    "jayanagara": "jayanagar",
    "jaya nagar": "jayanagar",

    # ── JP Nagar ───────────────────────────────────────────────────────
    "jp nagar": "jp nagar",
    "j p nagar": "jp nagar",
    "jaypee nagar": "jp nagar",

    # ── BTM Layout ─────────────────────────────────────────────────────
    "btm": "btm layout",
    "btm lay out": "btm layout",

    # ── HSR Layout ─────────────────────────────────────────────────────
    "hsr": "hsr layout",
    "hsr lay out": "hsr layout",

    # ── Electronic City ────────────────────────────────────────────────
    "ecity": "electronic city",
    "e city": "electronic city",
    "electronics city": "electronic city",

    # ── Domlur ─────────────────────────────────────────────────────────
    "domlure": "domlur",

    # ── Rajajinagar ────────────────────────────────────────────────────
    "rajajinagara": "rajajinagar",
    "raja rajinagar": "rajajinagar",

    # ── Banashankari ───────────────────────────────────────────────────
    "banasankari": "banashankari",
    "bsk": "banashankari",
    "bsk 2nd stage": "banashankari 2nd stage",
    "bsk 3rd stage": "banashankari 3rd stage",

    # ── Basavanagudi ───────────────────────────────────────────────────
    "basavanaguḍi": "basavanagudi",

    # ── Vijayanagar ────────────────────────────────────────────────────
    "vijaya nagar": "vijayanagar",

    # ── Bommanahalli ───────────────────────────────────────────────────
    "bommanahali": "bommanahalli",

    # ── Bellandur ──────────────────────────────────────────────────────
    "bellandure": "bellandur",

    # ── Yelahanka ──────────────────────────────────────────────────────
    "yelahanka new town": "yelahanka",

    # ── Airport ────────────────────────────────────────────────────────
    "bial": "kempegowda international airport",
    "bia": "kempegowda international airport",
    "bengaluru airport": "kempegowda international airport",
    "bangalore airport": "kempegowda international airport",

    # ── Miscellaneous ──────────────────────────────────────────────────
    "mg road": "m g road",
    "mgroad": "m g road",
    "m.g. road": "m g road",
    "ub city": "ub city mall",
    "brigade road": "brigade road",
}


def repair_route_text(value: str) -> str:
    """Normalize common CSV mojibake without hiding the original route labels."""
    if not value:
        return ""
    return (
        str(value)
        .replace("\u00e2\u2020\u2019", "->")
        .replace("\u00e2\u2020'", "->")
        .replace("→", "->")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )


def _strip_noise(normalized: str) -> str:
    """Remove trailing/leading noise words from a normalized stop name.

    E.g. "majestic bus station" → "majestic bus station" (exact alias match wins),
    but "some stop bus stop" → "some stop".
    Called *after* alias lookup fails so aliases always take priority.
    """
    tokens = normalized.split()
    # Strip noise tokens from the end (up to 2)
    for _ in range(2):
        if len(tokens) > 1 and tokens[-1] in _NOISE_TOKENS:
            tokens = tokens[:-1]
        else:
            break
    return " ".join(tokens)


def normalize_text(value: str) -> str:
    value = repair_route_text(value).lower().strip()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = _PUNCT_RE.sub(" ", value)
    value = _SPACE_RE.sub(" ", value).strip()
    # Try exact alias first
    aliased = ALIASES.get(value)
    if aliased:
        return aliased
    # Try stripping multi-word noise suffixes
    for noise in _NOISE_WORDS:
        if value.endswith(" " + noise):
            stripped = value[: -(len(noise) + 1)].strip()
            aliased = ALIASES.get(stripped, stripped)
            return aliased
        if value.startswith(noise + " "):
            stripped = value[len(noise) + 1:].strip()
            aliased = ALIASES.get(stripped, stripped)
            return aliased
    # Try stripping single noise token from end
    stripped = _strip_noise(value)
    if stripped != value:
        aliased = ALIASES.get(stripped)
        if aliased:
            return aliased
        return stripped
    return value


def tokenize(value: str) -> list[str]:
    text = normalize_text(value)
    tokens = [part for part in text.split(" ") if part]
    bigrams = [f"{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1)]
    # Character 3-grams for robust misspelling recall
    char_ngrams = _char_ngrams(text, n=3)
    return tokens + bigrams + char_ngrams


def _char_ngrams(text: str, n: int = 3) -> list[str]:
    """Generate character n-grams from text (spaces removed) for typo robustness."""
    compact = text.replace(" ", "")
    if len(compact) < n:
        return []
    return [f"__ng_{compact[i:i + n]}" for i in range(len(compact) - n + 1)]


def fuzzy_ratio(left: str, right: str, left_norm: str | None = None, right_norm: str | None = None) -> float:
    left_norm = left_norm if left_norm is not None else normalize_text(left)
    right_norm = right_norm if right_norm is not None else normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    shorter_len = min(len(left_norm), len(right_norm))
    # A containment match only earns the high floor score below if the
    # contained (shorter) string is long enough to be real signal. Without
    # this guard: normalize_text's noise-word stripping can legitimately
    # collapse a stop name down to 1-2 characters (e.g. "I Gate" -> "i",
    # since "gate" is a recognized noise suffix) -- and a 1-character
    # string is trivially "contained in" almost any other string that
    # happens to share that letter. That let a small number of stops
    # (observed: "I Gate", "BK Circle", "KR Circle", "MC Layout",
    # "Depot-9") win a spuriously high ~0.86 score against nearly any
    # query, including genuine typos of completely unrelated stops
    # ("Majestik", "Whitefeild", and "Silk Bord" all matched "I Gate"
    # ahead of their real, intended stops). Below this length, fall
    # through to the token/sequence/n-gram scoring below instead, which
    # still finds reasonable matches but without an unearned floor.
    _MIN_CONTAINMENT_LENGTH = 4
    if shorter_len >= _MIN_CONTAINMENT_LENGTH and (left_norm in right_norm or right_norm in left_norm):
        longer = max(len(left_norm), len(right_norm))
        return max(0.86, shorter_len / max(longer, 1))
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    # Character n-gram similarity for extra typo tolerance
    left_ng = set(_char_ngrams(left_norm))
    right_ng = set(_char_ngrams(right_norm))
    ng_sim = len(left_ng & right_ng) / max(len(left_ng | right_ng), 1) if left_ng or right_ng else 0.0
    return max(sequence, overlap, ng_sim * 0.92)


def best_match(query: str, choices: list[str]) -> tuple[int, str, float]:
    best_index = -1
    best_value = ""
    best_score = 0.0
    for index, choice in enumerate(choices):
        score = fuzzy_ratio(query, choice)
        if score > best_score:
            best_index = index
            best_value = choice
            best_score = score
    return best_index, best_value, best_score


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))