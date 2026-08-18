from pathlib import Path

from app.ml.predictor import BMTCBusPredictor


def test_predictor_returns_ordered_route(tmp_path: Path) -> None:
    csv_path = tmp_path / "routes.csv"
    csv_path.write_text(
        "\n".join(
            [
                "name,full_name,trip_count,trip_list,stop_count,stop_list,id,direction_id",
                "500-X,Silk Board -> Marathahalli,2,\"['08:00:00','09:00:00']\",4,\"['Silk Board','Agara','Bellandur','Marathahalli']\",1,0",
                "335-A,Majestic -> Whitefield,1,\"['08:30:00']\",4,\"['Majestic','Tin Factory','Kundalahalli','Whitefield']\",2,0",
            ]
        ),
        encoding="utf-8",
    )
    predictor = BMTCBusPredictor(csv_path, tmp_path / "artifacts")
    predictor.train(force=True)
    result = predictor.predict("Silk Board", "Marathahalli", 2)
    assert result["best_match"]["bus_number"] == "500-X"
    assert result["best_match"]["passes_in_requested_order"] is True


# ── The invariant behind the transfer-search early exit ──────────────────────
#
# _find_transfer_suggestions skips the entire one-transfer enumeration once
# enough direct journeys already serve the exact stops requested. That is only
# sound because route_rank_score sorts on (stop_exactness, transfers, ...) with
# `transfers` SECOND, so a transfer journey can never outrank a direct one in
# the same exactness tier however good it looks on frequency, trunk status or
# stop count.
#
# These two tests pin that ordering. They deliberately assert on OUTPUT, not on
# whether the guard ran: the guard is output-neutral by construction, so no
# assertion can distinguish it being present from absent. What they catch is
# the change that would make it unsafe -- someone reordering those key elements.


def _write_routes(csv_path: Path, rows: list[str]) -> None:
    header = "name,full_name,trip_count,trip_list,stop_count,stop_list,id,direction_id"
    csv_path.write_text("\n".join([header, *rows]), encoding="utf-8")


def test_direct_route_outranks_a_transfer_that_looks_better_on_everything_else(
    tmp_path: Path,
) -> None:
    """A slow, non-trunk, roundabout direct bus still beats a fast trunk transfer.

    The transfer journey here wins on every ranking element that sits BELOW
    `transfers`: it is a trunk series (500-*), runs 999 trips a day against 2,
    and covers fewer stops. It must still lose, because it requires changing
    buses. If this fails, `transfers` is no longer the second key and the
    early-exit guard in _find_transfer_suggestions must be deleted.
    """
    csv_path = tmp_path / "routes.csv"
    _write_routes(
        csv_path,
        [
            # Direct, but unattractive on every other axis.
            "9-Z,Alpha -> Beta,2,\"['08:00:00','09:00:00']\",5,"
            "\"['Alpha','Mid One','Mid Two','Mid Three','Beta']\",1,0",
            # A high-frequency trunk pair that connects the same two stops
            # via one change at Midpoint.
            "500-A,Alpha -> Midpoint,999,\"['08:00:00']\",2,\"['Alpha','Midpoint']\",2,0",
            "500-B,Midpoint -> Beta,999,\"['08:05:00']\",2,\"['Midpoint','Beta']\",3,0",
        ],
    )
    predictor = BMTCBusPredictor(csv_path, tmp_path / "artifacts")
    predictor.train(force=True)

    result = predictor.predict("Alpha", "Beta", 5)

    assert result["best_match"]["bus_number"] == "9-Z"
    assert result["best_match"].get("transfers", 0) == 0
    assert result["alternatives"][0]["transfers"] == 0


def test_no_transfer_journey_surfaces_when_direct_routes_fill_the_shortlist(
    tmp_path: Path,
) -> None:
    """With the shortlist full of direct routes, transfers cannot place at all.

    This is the precondition the early-exit guard tests for. The shortlist is
    `max(limit * 4, 100)`, so limit=5 gives 100 slots and the 120 direct routes
    below fill it outright -- at which point enumerating the transfer pair is
    provably wasted work, since none of it could reach the output.
    """
    csv_path = tmp_path / "routes.csv"
    direct = [
        f"D{i:03d},Alpha -> Beta,5,\"['08:00:00']\",3,"
        f"\"['Alpha','Waypoint {i}','Beta']\",{i + 10},0"
        for i in range(120)
    ]
    _write_routes(
        csv_path,
        [
            *direct,
            "500-A,Alpha -> Midpoint,999,\"['08:00:00']\",2,\"['Alpha','Midpoint']\",900,0",
            "500-B,Midpoint -> Beta,999,\"['08:05:00']\",2,\"['Midpoint','Beta']\",901,0",
        ],
    )
    predictor = BMTCBusPredictor(csv_path, tmp_path / "artifacts")
    predictor.train(force=True)

    # The fixture really does fill the shortlist: ask for far more than the
    # guard's threshold and confirm at least 100 distinct direct journeys exist.
    wide = predictor.predict("Alpha", "Beta", 200)
    direct_chains = {
        alt["bus_chain"] for alt in wide["alternatives"] if alt["transfers"] == 0
    }
    assert len(direct_chains) >= 100

    result = predictor.predict("Alpha", "Beta", 5)

    assert len(result["alternatives"]) == 5
    assert all(alt["transfers"] == 0 for alt in result["alternatives"])
    assert not any("500-A" in alt["bus_chain"] for alt in result["alternatives"])
