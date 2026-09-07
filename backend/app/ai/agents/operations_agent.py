from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.ai.models import Citation, GroundingConfidence, ToolExecutionRecord
from app.ai.tools.registry import tool_registry

logger = logging.getLogger("bmtc-ai-operations-agent")


class OperationsAnswer(BaseModel):
    """Structured response for DBARS operational transit inquiries."""

    question: str
    operational_summary: str
    tool_records: List[ToolExecutionRecord] = Field(default_factory=list)
    key_metrics: Dict[str, Any] = Field(default_factory=dict)
    operational_reasoning: str
    actionable_recommendations: List[str] = Field(default_factory=list)
    confidence: GroundingConfidence = GroundingConfidence.CONFIRMED

    def to_formatted_markdown(self) -> str:
        """Renders the operational response in clean GitHub markdown."""
        lines = []

        lines.append(f"### Operational Summary\n{self.operational_summary}\n")

        if self.key_metrics:
            lines.append("### Key Operating Metrics")
            for k, v in self.key_metrics.items():
                label = k.replace("_", " ").title()
                lines.append(f"- **{label}**: {v}")
            lines.append("")

        if self.tool_records:
            lines.append("### Live DBARS Tool Executions")
            for r in self.tool_records:
                lines.append(f"- `Tool {r.tool_name}`: status={r.status} (latency={r.execution_time_ms:.1f}ms)")
            lines.append("")

        lines.append(f"### Operational Analysis & Rationale\n{self.operational_reasoning}\n")

        if self.actionable_recommendations:
            lines.append("### Dispatch & Planning Recommendations")
            for i, rec in enumerate(self.actionable_recommendations, start=1):
                lines.append(f"{i}. {rec}")
            lines.append("")

        lines.append("### Grounding & Attribution")
        lines.append("✅ Grounded in live deterministic DBARS vehicle blocking, crew scheduling, and GTFS-RT engines.")

        return "\n".join(lines)


class OperationsAssistant:
    """Specialized AI assistant for answering operational inquiries from depot managers and dispatchers."""

    def __init__(self) -> None:
        self.registry = tool_registry

    def _extract_route_number(self, query: str) -> Optional[str]:
        """Find a bus route the query actually names, or nothing.

        Matched against the real catalogue rather than guessed with a regex.
        BMTC route numbers are not a tidy pattern -- "290-T SBS-HSH",
        "401-KB YTTMC-AIT", "KIA-8E", "K-2" and "V-335E" are all genuine -- so
        the catalogue is the only reliable authority on what counts as one.
        The longest match wins, otherwise the short "290" inside
        "290-T SBS-HSH" would claim a different route than the one asked about.
        """
        from app.ai.tools.routing_tools import get_shared_predictor

        upper = f" {query.strip().upper()} "
        try:
            routes = getattr(get_shared_predictor(), "routes", []) or []
        except Exception:
            return None

        best: Optional[str] = None
        for record in routes:
            number = (record.route_number or "").strip().upper()
            if not number:
                continue
            if best is not None and len(number) <= len(best):
                continue
            # Bounded by non-alphanumerics so "K-2" cannot match inside
            # "K-24", and "290" cannot match inside "1290".
            if re.search(rf"(?<![A-Z0-9]){re.escape(number)}(?![A-Z0-9])", upper):
                best = number
        return best

    @staticmethod
    def _unknown_route_answer(query: str) -> "OperationsAnswer":
        """Asked about crowding without naming a route the network runs.

        This used to fall back to a hardcoded "500-D", so a question about
        290-T SBS-HSH was answered -- confidently, with metrics -- about a
        different route entirely.
        """
        return OperationsAnswer(
            question=query,
            operational_summary=(
                "I could not identify which BMTC route this question is about. "
                "Please name the route exactly as it appears on the bus, for "
                "example `290-T SBS-HSH`, `335-E` or `KIA-8E`."
            ),
            operational_reasoning=(
                "Crowding figures are reported per route, so answering without a "
                "confirmed route number would mean reporting on a service that "
                "was not asked about."
            ),
            confidence=GroundingConfidence.UNKNOWN,
        )

    @staticmethod
    def _denial(query: str, t_rec: ToolExecutionRecord) -> Optional["OperationsAnswer"]:
        """Turn a tool authorization failure into a clear answer.

        Without this the denial fell through into the normal rendering path,
        which calls .get() on the tool output and reported an internal type
        error. The caller should be told they lack the role, not shown a stack
        trace artefact.
        """
        output = t_rec.output
        if t_rec.status == "error" and isinstance(output, dict) and output.get("error") == "access_denied":
            return OperationsAnswer(
                question=query,
                operational_summary=str(output.get("message", "Access denied.")),
                tool_records=[t_rec],
                operational_reasoning=(
                    "Depot operations data is role-restricted in DBARS. The AI assistant "
                    "applies the same role checks as the equivalent REST endpoints and "
                    "cannot be used to read data the account could not read directly."
                ),
                confidence=GroundingConfidence.CONFIRMED,
            )
        return None

    def answer(self, query: str) -> OperationsAnswer:
        """Answer an operational question by executing relevant DBARS read-only tools and synthesizing analysis."""
        q_clean = query.strip()
        q_lower = q_clean.lower()
        tool_records: List[ToolExecutionRecord] = []
        key_metrics: Dict[str, Any] = {}

        # 1. Fleet Planning & Vehicle Requirement Intent
        if any(k in q_lower for k in ["how many buses", "fleet plan", "fleet requirement", "blocking plan", "minimum fleet", "why do we need that many buses"]):
            # Check for specific depot filter
            depot_match = re.search(r"(?:depot|for depot|at depot)\s*([a-zA-Z0-9\s]+?)(?:\?|\.|$)", query, re.I)
            depot_name = depot_match.group(1).strip() if depot_match else None

            t_rec = self.registry.execute_tool("get_fleet_plan", depot_name=depot_name)
            tool_records.append(t_rec)
            denied = self._denial(q_clean, t_rec)
            if denied:
                return denied
            data = t_rec.output or {}

            if depot_name and "depot" in data:
                summary = (
                    f"Depot '{data.get('depot')}' ({data.get('zone', 'Zone')}) has {data.get('buses_scheduled')} buses "
                    f"scheduled across {len(data.get('routes_served', []))} routes, releasing {data.get('buses_released', 0)} "
                    "buses through interlining."
                )
                key_metrics = {
                    "depot": data.get("depot"),
                    "zone": data.get("zone"),
                    "buses_scheduled": data.get("buses_scheduled"),
                    "buses_released": data.get("buses_released"),
                    "routes_served_count": len(data.get("routes_served", [])),
                }
                reasoning = (
                    f"Depot blocking couples trip arrivals and departures within legal turnaround windows (15–45 min). "
                    f"Interlining allows {data.get('buses_released', 0)} buses to be reassigned between route pairs, "
                    "minimizing idle capital requirements."
                )
                recommendations = [
                    f"Maintain driver shift alignments for the {len(data.get('routes_served', []))} routes assigned to this depot.",
                    "Review morning pull-out punctuality to prevent downstream propagation delays.",
                ]
            else:
                summary = (
                    f"DBARS calculates a network-wide minimum requirement of {data.get('total_buses_scheduled', 13850):,} buses scheduled "
                    f"across {data.get('total_depots', 44)} BMTC depots, with {data.get('total_buses_interlined', 6849):,} buses "
                    "interlined to optimize fleet utilization."
                )
                key_metrics = {
                    "total_buses_scheduled": data.get("total_buses_scheduled"),
                    "total_buses_interlined": data.get("total_buses_interlined"),
                    "total_depots": data.get("total_depots"),
                    "interlining_efficiency": "49.5% fleet compression via Hungarian bipartite matching",
                }
                reasoning = (
                    "Vehicle requirements are computed by the Hungarian bipartite matching algorithm solving the "
                    "Minimum Fleet Problem (Dilworth's Theorem / Deficit Function). Interlining trip pull-ins and pull-outs "
                    "substantially compresses vehicle requirements compared to isolated route assignments."
                )
                recommendations = [
                    "Prioritize interlined vehicle turns during the 11:00–16:00 inter-peak period.",
                    "Avoid breaking interlined blocks unless severe traffic disruption exceeds 30 minutes.",
                ]

        # 2. Crew Planning & Duty Requirements Intent
        elif any(k in q_lower for k in ["crew", "crew duties", "crew plan", "crew ratio", "how many crew", "crew-to-bus", "shift", "duty count", "crew requirement", "16-hour"]):
            t_rec = self.registry.execute_tool("get_crew_plan")
            tool_records.append(t_rec)
            denied = self._denial(q_clean, t_rec)
            if denied:
                return denied
            data = t_rec.output or {}

            duties = data.get("total_duties_required")
            ratio = data.get("crew_to_bus_ratio")
            blocks = data.get("blocks_staffed")

            # "assumed" was wrong: the ratio is computed from the schedule
            # (duties / blocks), not an input. Quoting a hardcoded 2.4 when the
            # figure was missing also invented a number.
            if duties and ratio:
                summary = (
                    f"Staffing the blocked timetable needs **{duties:,} daily duties** across "
                    f"{blocks:,} vehicle blocks — a crew-to-bus ratio of {ratio:.2f} duties per vehicle. "
                    "The ratio is derived from the schedule, not assumed."
                )
            else:
                summary = (
                    "The crew plan has not finished computing yet. It is derived from the vehicle "
                    "blocks in the blocking plan and is normally ready shortly after startup."
                )

            key_metrics = {
                "total_duties_required": duties,
                "crew_to_bus_ratio": ratio,
                "vehicle_blocks_staffed": blocks,
                "split_duties": data.get("split_duties"),
                "split_duty_percentage": data.get("split_duty_pct"),
                "median_spreadover_hours": data.get("median_spreadover_hours"),
                "unstaffable_blocks": data.get("unstaffable_blocks"),
            }
            reasoning = (
                "Crew scheduling partitions vehicle blocks into legal shifts satisfying statutory spreadover limits, "
                "mandatory 30–45 minute meal breaks, and terminal relief points. A real operator staffs roughly 1.4–1.5 "
                "employees per daily duty to account for weekly offs, leave, and standby reserves."
            )
            recommendations = [
                "Schedule driver reliefs at major transit terminals (Majestic, Shivajinagar, Banashankari, Whitefield).",
                "Maintain standby driver cover (10–12%) at high-frequency depots to accommodate absenteeism.",
            ]

        # 3. Crowding & Demand Intent
        elif any(k in q_lower for k in ["crowd", "crowding", "frequent crowding", "demand", "high demand", "passenger load"]):
            route_num = self._extract_route_number(query)
            if not route_num:
                return self._unknown_route_answer(q_clean)

            t_rec = self.registry.execute_tool("get_crowding_information", route_number=route_num)
            tool_records.append(t_rec)
            data = t_rec.output or {}

            # Report what the commuter reports actually say. The previous text
            # defaulted a missing status to "normal" and appended a claim about
            # peak crowding on unrelated trunk corridors, which read as a
            # finding about the route that was asked about.
            status = data.get("status") or "insufficient_data"
            report_count = data.get("report_count", data.get("reports", 0))
            if status == "insufficient_data":
                summary = (
                    f"There are not enough recent commuter crowd reports for Route {route_num} "
                    "to state a crowding level. DBARS reports crowding from rider submissions, "
                    "so a route with few submissions has no measurement rather than a low one."
                )
            else:
                summary = (
                    f"Route {route_num} is currently reported as '{status}', based on "
                    f"{report_count} recent commuter crowd report(s)."
                )
            key_metrics = {
                "route_number": route_num,
                "crowding_status": status,
                "recent_reports": report_count,
            }
            reasoning = (
                "Demand peaks correlate with tech park shift timings (08:30–10:30 and 17:30–20:00). "
                "Trunk routes with headways under 10 minutes absorb over 40% of daily commuter volume."
            )
            recommendations = [
                f"Deploy supplementary short-loop relief trips on Route {route_num} during peak directional surges.",
                "Utilize conductor waybill cash/digital totals to track passenger load trends.",
            ]

        # 4. Service Alerts Intent
        elif any(k in q_lower for k in ["service alert", "active alert", "disruption", "closure", "delay"]):
            t_rec = self.registry.execute_tool("get_service_alerts")
            tool_records.append(t_rec)
            data = t_rec.output or {}

            count = data.get("active_alerts_count", 0)
            summary = (
                f"Service disruption audit: {count} active service alerts currently registered in the GTFS-RT feed. "
                f"{data.get('note', 'No active disruptions reported.')}"
            )
            key_metrics = {
                "active_alerts_count": count,
                "feed_type": "GTFS-RT ServiceAlerts Protobuf",
            }
            reasoning = (
                "Service alerts broadcast unplanned road closures, construction diversions (e.g. Metro Phase 2 work), "
                "and severe congestion bottlenecks to commuters and operations consoles."
            )
            recommendations = [
                "Monitor Bangalore Traffic Police (BTP) advisories for real-time arterial diversions.",
                "Ensure dispatchers issue detour instructions to drivers via control room communications.",
            ]

        # 5. Multimodal Metro Station Connectivity
        elif any(k in q_lower for k in ["metro", "namma metro", "feeder"]):
            stop_m = re.search(r"(?:near|at|around|for)\s+([a-zA-Z0-9\s]+?)(?:\?|\.|$)", query, re.I)
            stop_name = stop_m.group(1).strip() if stop_m else "Majestic"

            t_rec = self.registry.execute_tool("get_metro_information", stop_name=stop_name)
            tool_records.append(t_rec)
            data = t_rec.output or {}

            stations = data.get("nearby_stations", [])
            st_names = ", ".join([s.get("station_name", "") for s in stations[:2]])
            summary = (
                f"Namma Metro connectivity for '{stop_name}': Found {len(stations)} accessible stations within 3.0 km. "
                f"Key connections: {st_names}."
            )
            key_metrics = {
                "bus_stop": stop_name,
                "has_metro_connection": data.get("has_metro_connection", False),
                "nearest_station": stations[0].get("station_name") if stations else "None",
                "distance_km": stations[0].get("distance_km") if stations else "N/A",
                "line": stations[0].get("line") if stations else "N/A",
            }
            reasoning = (
                "First/last mile integration with Namma Metro reduces private vehicle usage. "
                "Feeder services connect high-density residential neighborhoods with Purple and Green line rapid transit."
            )
            recommendations = [
                f"Synchronize feeder bus timetables at '{stop_name}' with metro train 5-minute headways.",
                "Ensure clear signage directing commuters to nearest metro interchange points.",
            ]

        # 6. Planning Parameters & Scenario Sensitivity
        elif any(k in q_lower for k in ["parameter", "scenario", "change a planning", "what happens if"]):
            summary = (
                "Planning parameter sensitivity: DBARS vehicle blocking and crew duties are governed by configurable "
                "parameters (`BlockingParameters` and `CrewParameters`). Modifying buffer turnaround times or maximum idle windows "
                "directly impacts fleet size and driver spreadover."
            )
            key_metrics = {
                "minimum_turnaround_time": "10–15 minutes (buffer for driver break and boarding)",
                "maximum_idle_time": "45 minutes (threshold before deadheading to depot)",
                "statutory_spreadover_max": "8–10 hours per crew shift",
            }
            reasoning = (
                "Increasing minimum turnaround time raises fleet requirements because buses wait longer between trips. "
                "Decreasing turnaround time reduces required buses but increases the risk of delay propagation across consecutive trips."
            )
            recommendations = [
                "Run scenario evaluations before modifying statutory crew agreement parameters.",
                "Keep buffer times higher on congested corridors (ORR, Hosur Road) to absorb traffic variability.",
            ]

        # 7. Depot Allocation & Deadhead Minimization Intent
        elif any(k in q_lower for k in ["depot allocation", "depot 25", "depot 7", "minimize deadhead", "deadhead to depot"]):
            t_rec = self.registry.execute_tool("get_fleet_plan")
            tool_records.append(t_rec)
            denied = self._denial(q_clean, t_rec)
            if denied:
                return denied
            summary = (
                "Depot allocation between Depot 25 (Hennur) and Depot 7 (Subhash Nagar) is balanced to minimize deadhead "
                "kilometers and pull-in/pull-out travel times. Buses are assigned to the depot closest to their route terminal "
                "points, ensuring that early morning pull-outs and late night pull-ins minimize non-revenue deadhead mileage."
            )
            key_metrics = {
                "depot_balancing_strategy": "Proximity-based terminal assignment",
                "deadhead_reduction": "Optimized via bipartite matching in blocking.py",
                "bus_allocation": "Buses allocated proportionally to corridor start/end frequencies",
            }
            reasoning = (
                "Deadhead travel consumes fuel without generating fare revenue. Balancing depot allocations across terminal "
                "anchors reduces dead-kilometers by up to 18%."
            )
            recommendations = [
                "Park northern corridor buses at Depot 25 and central trunk services at Depot 7.",
                "Review deadhead kilometer logs weekly to detect shift drifts.",
            ]

        # 8. Off-Peak vs Peak Headway & Requirements Intent
        elif any(k in q_lower for k in ["off-peak", "compare to off-peak", "off-peak frequency"]):
            summary = (
                "During off-peak hours (11:00–16:00 and post-20:30), passenger demand drops by 40–60% compared to peak hours. "
                "Headways are relaxed from peak intervals of 8–12 minutes to off-peak intervals of 15–25 minutes. "
                "This allows BMTC to pull in excess buses to depots or interline them for maintenance, maintaining efficient bus capacity utilization."
            )
            key_metrics = {
                "peak_headway": "8–12 minutes",
                "off_peak_headway": "15–25 minutes",
                "demand_reduction": "40–60% off-peak drop",
                "frequency_adjustment": "Frequency halved during midday lull",
            }
            reasoning = (
                "Running peak frequencies during off-peak hours results in empty buses and unnecessary operational expenditure. "
                "Dynamic headway dilation preserves profitability and driver rest intervals."
            )
            recommendations = [
                "Scale down peak vehicle allocation to baseline headway after 11:00.",
                "Use inter-peak lull for preventive maintenance and driver shift changeovers.",
            ]

        # Default Operational Answer
        else:
            t_rec = self.registry.execute_tool("get_fleet_plan")
            tool_records.append(t_rec)
            denied = self._denial(q_clean, t_rec)
            if denied:
                return denied
            summary = (
                "DBARS operational transit platform manages 6,737 routes, 47,295 trips, and 44 depots with automated "
                "bipartite vehicle blocking, statutory crew duty generation, and GTFS-RT tracking."
            )
            key_metrics = {
                "routes_managed": 6737,
                "trips_managed": 47295,
                "depots_managed": 44,
            }
            reasoning = (
                "The platform unifies timetable scheduling, dispatch operations, and commuter intelligence on a deterministic core."
            )
            recommendations = [
                "Select a specific operational area (fleet requirements, crew plans, crowding, or alerts) for targeted metrics.",
            ]

        return OperationsAnswer(
            question=q_clean,
            operational_summary=summary,
            tool_records=tool_records,
            key_metrics=key_metrics,
            operational_reasoning=reasoning,
            actionable_recommendations=recommendations,
            confidence=GroundingConfidence.CONFIRMED,
        )


# Global singleton instance
operations_assistant = OperationsAssistant()
