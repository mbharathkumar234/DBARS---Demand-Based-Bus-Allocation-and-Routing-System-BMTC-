"""GTFS export.

Turns the BMTC route catalogue this project already trains on into a GTFS
static feed, and the service alerts it already publishes into GTFS-realtime.

The point of this package is that it produces something usable by parties
who will never run DBARS -- Google Maps, Transit, OpenTripPlanner, any
journey planner that speaks GTFS. Everything here is derived data, and the
feed says so about itself in three separate places (see builder.py's
PROVENANCE_README).
"""

from .builder import GtfsFeedBuilder, GtfsParameters, GtfsBuildReport

__all__ = ["GtfsFeedBuilder", "GtfsParameters", "GtfsBuildReport"]
