from app.ml.text import fuzzy_ratio, normalize_text, repair_route_text


def test_normalize_aliases() -> None:
    assert normalize_text("Majestic") == "kempegowda bus station"
    assert normalize_text("SilkBoard") == "silk board"


def test_repair_route_text() -> None:
    assert repair_route_text("A â†’ B") == "A -> B"


def test_fuzzy_ratio_contains_match() -> None:
    assert fuzzy_ratio("Marathahalli", "Multiplex Marathahalli") >= 0.86
