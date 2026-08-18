"""Vehicle location: where the buses actually are.

Everything operational in this project has until now rested on BusSimulator --
a physics toy that moves markers along stop coordinates. That is honest as far
as it goes (see GET /tracking/source, which says so outright), but it means
schedule adherence, real ETAs and a publishable GTFS-realtime vehicle feed are
all out of reach.

This package makes the source of vehicle positions a swappable adapter. The
simulator becomes one implementation of VehicleFeed among several rather than
the only thing that exists, and `is_live` on the active feed is what every
honesty gate in the codebase now keys off -- so swapping in a real BMTC feed is
a configuration change, and nothing anywhere claims to be live until one is.
"""

from .base import VehicleFeed, VehicleObservation
from .store import VehicleStateStore, vehicle_store

__all__ = ["VehicleFeed", "VehicleObservation", "VehicleStateStore", "vehicle_store"]
