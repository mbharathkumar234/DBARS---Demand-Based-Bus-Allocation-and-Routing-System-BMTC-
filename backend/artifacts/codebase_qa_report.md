# DBARS Codebase Assistant — 26-Question Evaluation Report

**Total Questions Evaluated**: 26

**Passed**: 25 / 26 (96.2%)

| ID | Category | Question | Expected Source | Retrieved Sources | Status | Notes |
|---|---|---|---|---|---|---|
| Q01 | Architecture & Startup | Where does the application start? | `main.py` | `main.py, test_codebase_assistant.py, test_ai_predictor_sharing.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'main.py'. |
| Q02 | Core Routing Engine | Explain predictor.py and its primary role. | `predictor.py` | `predictor.py, test_accuracy_metrics.py, test_confidence_consistency.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'predictor.py'. |
| Q03 | Core Routing Engine | How does BMTCBusPredictor.predict() work? | `predictor.py` | `predictor.py, routes.py, test_source_grounding_verification.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'predictor.py'. |
| Q04 | Stop Matching | How does stop resolution work in predictor.py? | `predictor.py` | `predictor.py, test_stop_resolution.py, text.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'predictor.py'. |
| Q05 | Algorithmic Design | Why are ordered stop pairs used in DBARS route search? | `predictor.py` | `predictor.py, test_ai_subsystem.py, lexical_search.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'predictor.py'. |
| Q06 | Fare Services | Where is fare calculated in DBARS? | `fares.py` | `fares.py, waybill_service.py, test_waybill.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'fares.py'. |
| Q07 | Concession & Passes | Where is Shakti eligibility and pass validation implemented? | `pass_service.py` | `pass_service.py, waybill_service.py, test_shakti.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'pass_service.py'. |
| Q08 | Ticketing & Conductor | How does offline ticket synchronization achieve idempotency? | `waybill_service.py` | `waybill_service.py, implementation-plan.md, resume-entry.md` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'waybill_service.py'. |
| Q09 | Security & RBAC | How does authentication and require_role work? | `auth.py` | `auth.py, auth.py, AI_SECURITY.md` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'auth.py'. |
| Q10 | API Gateway | Which API endpoint calls the route prediction service? | `predict.py` | `predict.py, predictor.py, routes.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'predict.py'. |
| Q11 | Resilience & Fallback | What happens when MongoDB is unavailable during routing? | `predictor.py` | `predictor.py, database.py, blocking_service.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'predictor.py'. |
| Q12 | Dependencies | Which modules depend on predictor.py? | `predict.py` | `predictor.py, test_accuracy_metrics.py, test_confidence_consistency.py` | ❌ Incorrect | Retrieved 5 citations; matched expected source keyword 'predict.py'. |
| Q13 | Test Coverage | What tests cover the route prediction engine? | `test_predictor.py` | `test_predictor.py, test_accuracy_metrics.py, test_api.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'test_predictor.py'. |
| Q14 | End-to-End Flow | Trace the execution path from frontend predict page to route result. | `predict` | `PredictPage.tsx, routes.py, predictor.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'predict'. |
| Q15 | Operations & Fleet | How does the vehicle blocking plan compute minimum fleet? | `blocking.py` | `blocking.py, blocking_service.py, crew_service.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'blocking.py'. |
| Q16 | Crew Scheduling | How are daily crew duties generated from vehicle blocks? | `crew.py` | `crew.py, crew_service.py, test_crew.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'crew.py'. |
| Q17 | Open Transit Data | Where is static GTFS feed generation implemented? | `gtfs` | `gtfs_service.py, builder.py, gtfs.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'gtfs'. |
| Q18 | Realtime AVL | How does live AVL bus tracking simulate vehicle positions? | `tracking` | `tracking_service.py, simulator.py, README.md` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'tracking'. |
| Q19 | Spatial Mathematics | Where is the Haversine distance formula defined? | `metro_service.py` | `metro_service.py, distance.py, predictor.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'metro_service.py'. |
| Q20 | Multimodal Integration | Where is Namma Metro station connectivity defined? | `metro_service.py` | `metro_service.py, metro.py, operations_tools.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'metro_service.py'. |
| Q21 | Services | What is the role of pass_service.py in DBARS? | `pass_service.py` | `pass_service.py, waybill_service.py, conductor.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'pass_service.py'. |
| Q22 | Realtime Alerts | How does the GTFS-RT service alert builder work? | `gtfs` | `gtfs_service.py, builder.py, realtime.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'gtfs'. |
| Q23 | Conductor Operations | Where is conductor waybill management implemented? | `waybill_service.py` | `waybill_service.py, conductor.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'waybill_service.py'. |
| Q24 | GIS & Coordinates | How are bus stop coordinates resolved in DBARS? | `distance` | `distance.py, distance_service.py, test_route_geometry.py` | ✅ Correct | Retrieved 5 citations; matched expected source keyword 'distance'. |
| Q25 | Crowdsourcing | How does the crowd reporting service calculate route crowding? | `crowding` | `crowding_service.py, crowding.py, operations_tools.py` | ✅ Correct | Retrieved 4 citations; matched expected source keyword 'crowding'. |
| Q26 | Adversarial Hallucination Defense | Explain function fake_predictor_999() and its postgres database connection | `UNKNOWN` | `None` | ✅ Correct | Adversarial check correctly identified nonexistent symbol as UNKNOWN. |
