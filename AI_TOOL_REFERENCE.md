# DBARS AI — Tool Reference

Eight read-only tools, registered in `app/ai/tools/registry.py`. Every tool
subclasses `BaseDBARSTool` (a LangChain `BaseTool`) and declares
`is_read_only = True`.

All tool calls pass through `ToolRegistry.execute_tool()`, which applies the
role check described in `AI_SECURITY.md` and returns a `ToolExecutionRecord`
carrying the tool name, arguments, output, duration and status.

## Routing tools — `app/ai/tools/routing_tools.py`

### `search_bus_route`
Finds bus options between two stops, including transfers.

| Parameter | Type | Required |
|---|---|---|
| `current_stop` | string | yes |
| `destination` | string | yes |

Delegates to the shared `BMTCBusPredictor`. Returns the same route data
`POST /predict` returns — bus number or chain, transfer stops, confidence,
matched stop names and route path. **The predictor is called, never
reimplemented**; the AI layer holds no routing logic of its own.

Access: any authenticated user.

### `get_route_details`
Stop list, terminal points and trip frequencies for a known bus number.

| Parameter | Type | Required |
|---|---|---|
| `route_number` | string | yes |

Access: any authenticated user.

## Operations tools — `app/ai/tools/operations_tools.py`

### `get_fleet_plan` — **restricted**
Minimum fleet requirement, buses scheduled, buses interlined and depot
statistics, from `blocking_service`.

| Parameter | Type | Required |
|---|---|---|
| `depot_name` | string | no — filters to one depot |

**Access: `depot_manager` or `admin`.** Mirrors `GET /depot/blocking-plan`.

### `get_crew_plan` — **restricted**
Total daily duties, crew-to-bus ratio and shift parameters, from
`crew_service`.

| Parameter | Type | Required |
|---|---|---|
| `depot_name` | string | no |

**Access: `depot_manager` or `admin`.** Mirrors `GET /depot/crew-plan`.

### `get_crowding_information`
Recent commuter crowd reports and crowding level for a route.
Alias: `get_crowding_info`.

| Parameter | Type | Required |
|---|---|---|
| `route_number` | string | yes |

Access: any authenticated user.

### `get_service_alerts`
Active disruptions, road closures and passenger notices.

| Parameter | Type | Required |
|---|---|---|
| `route_number` | string | no |
| `stop_name` | string | no |

Access: any authenticated user.

### `get_metro_information`
Nearby Namma Metro stations, line colours and interchange options.
Alias: `get_metro_info`.

| Parameter | Type | Required |
|---|---|---|
| `stop_name` | string | yes |

Access: any authenticated user.

### `get_bus_eta`
Active vehicle positions and schedule adherence for a route, from
`vehicle_service`. Returns whatever the configured AVL feed provides and
preserves the `is_live` flag, so simulated positions are never presented as
real.

| Parameter | Type | Required |
|---|---|---|
| `route_number` | string | yes |

Access: any authenticated user.

## What is deliberately absent

No tool writes. There is no tool to issue or void a ticket, open or close a
waybill, deploy a bus, alter a fleet plan, change a user role, edit
configuration, adjust routing parameters, trigger training or index rebuilds,
run shell commands, evaluate code, read arbitrary files, query the database
directly, or make outbound HTTP requests. The model can only reach DBARS
through the eight tools above.

## Adding a tool

1. Subclass `BaseDBARSTool` in `routing_tools.py` or `operations_tools.py`.
2. Implement `_run_tool()` calling an existing **read** service path.
3. Register it in `ToolRegistry._register_default_tools()`.
4. If it exposes role-restricted data, add it to `RESTRICTED_TOOLS` in
   `app/ai/security/authorization.py` with the same roles the equivalent REST
   endpoint requires, and add a denial test to
   `tests/test_ai_authorization.py`.

Step 4 is not optional. A tool absent from `RESTRICTED_TOOLS` is readable by
any authenticated user.
