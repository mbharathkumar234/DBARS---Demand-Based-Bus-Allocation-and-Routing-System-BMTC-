# -*- coding: utf-8 -*-
"""Sections 40-42: the AI Intelligence Layer, the defects it exposed, and what
was measured versus what was only claimed."""
from style import bullets, callout, code, evidence, h, numbered, page_break, para, table


def section_40(doc):
    page_break(doc)
    h(doc, 1, "40. The AI Intelligence Layer")
    para(doc, "An assistant sits over the deterministic engine: it answers questions about the "
              "codebase, the documentation, and live transit state. The single most important "
              "property is that it is additive. The routing engine does not import it, does not "
              "call it, and does not depend on it. Being able to say that precisely - and to show "
              "the test that proves it - is the point of this section.")

    h(doc, 2, "40.1 Where it sits")
    code(doc,
         "HTTP  ->  app/ai/api/routes.py        authentication + role checks\n"
         "      ->  app/ai/agents/orchestrator  LCEL chain, intent routing\n"
         "          |-- RAG retrieval           code index + documentation index\n"
         "          |-- domain agents           codebase / operations / travel\n"
         "          '-- tool registry           8 read-only tools, authorisation chokepoint\n"
         "                     |\n"
         "                     v  read-only calls\n"
         "          DETERMINISTIC CORE (app/ml, app/gtfs, app/tracking, app/services)",
         caption="The arrow into the core points one way. Nothing in app/ai writes to it.")

    h(doc, 2, "40.2 The dependency rule, and why it is load-bearing")
    para(doc, "app/main.py imports the AI router inside a try/except. This is not defensive "
              "decoration. The AI layer pulls in langchain, faiss-cpu and sentence-transformers; "
              "before the guard existed, a missing optional package raised at module scope and took "
              "the ENTIRE backend down with it - route prediction, ticketing and GTFS included. A "
              "fresh 'pip install -r requirements.txt' produced a server that could not start at all.")
    code(doc,
         "try:\n"
         "    from app.ai.api.routes import router as ai_router\n"
         "except Exception as _ai_import_error:\n"
         "    ai_router = None",
         caption="Same principle as init_db(): an optional subsystem may fail, but it may never "
                 "prevent DBARS from starting.")
    evidence(doc, "Verified by blocking the AI packages at import time: the app started with 82 "
                  "routes instead of 93, logged a warning, and every deterministic feature behaved "
                  "identically.")

    h(doc, 2, "40.3 Retrieval-Augmented Generation")
    para(doc, "RAG is the part of this layer most worth being able to defend, because it is where the "
              "interesting design decisions are. The shape is standard - retrieve, then ground an "
              "answer in what was retrieved - but three choices here are worth explaining.")

    h(doc, 3, "40.3.1 The pipeline")
    code(doc,
         "question\n"
         "   |\n"
         "   +-> QueryRouter          code / documentation / operations / travel / hybrid\n"
         "   +-> expand_query()       plain words -> the identifiers the code uses\n"
         "   |\n"
         "   +-> VECTOR  search       FAISS IndexFlatIP, 384-d, cosine on normalised vectors\n"
         "   +-> LEXICAL search       BM25, k1=1.5, b=0.75\n"
         "   |\n"
         "   +-> Reciprocal Rank Fusion   score(d) = SUM 1 / (60 + rank_i(d))\n"
         "   |\n"
         "   +-> Citations            file, symbol, start_line, end_line, snippet\n"
         "   +-> grounding_verifier   labels CONFIRMED / INFERRED / UNKNOWN",
         caption="Two indices are built: code (1,560 chunks over 235 files) and documentation "
                 "(262 chunks over 20 files).")

    h(doc, 3, "40.3.2 Chunking is symbol-aware, not fixed-width")
    para(doc, "Python is parsed with the ast module and emits one chunk per meaningful unit - a "
              "module chunk carrying the docstring and imports, a class-overview chunk, and one chunk "
              "per method and top-level function. Each carries file, symbol, type, start_line and "
              "end_line.")
    para(doc, "This is why a citation reads predictor.py:412-455 with a function name rather than "
              "'chunk 87', and why a question about a function retrieves that function instead of a "
              "600-character window straddling two unrelated definitions. TypeScript is chunked by "
              "declaration with a regex parser, because no TS AST is available in-process.")

    h(doc, 3, "40.3.3 Why the retrieval is hybrid")
    table(doc, ["Half", "What it contributes", "Where it fails alone"], [
        ["Vector (FAISS)", "Tolerates paraphrase and word order",
         "Cannot match an exact\nsymbol it has not seen"],
        ["BM25 lexical", "Exact identifiers: require_role,\nBMTCBusPredictor, route_distance",
         "Blind to a question that\nshares no token with the\ncode"],
    ], widths=[1.3, 2.6, 2.1])
    para(doc, "Reciprocal Rank Fusion combines them on RANK rather than score, so the two "
              "incomparable scales never need calibrating and a document ranked highly by either "
              "half surfaces. k = 60 is the standard constant from the original RRF paper.")

    h(doc, 3, "40.3.4 The embedding decision, and the vocabulary gap")
    para(doc, "The default embedding provider is deterministic hashed n-grams, not a neural model. "
              "That is a deliberate choice backed by measurement, and section 42.3 gives the numbers - "
              "swapping in all-MiniLM-L6-v2 produced no improvement at 80x the load time.")
    callout(doc, "State this limitation before an examiner finds it",
            "Hashed n-grams are a LEXICAL signal. 'How is the fare computed' and 'where is pricing "
            "calculated' do not land near each other the way true sentence embeddings would, so the "
            "dense half behaves like a fuzzy keyword index. Calling it semantic search would be an "
            "overstatement.", warn=True)
    para(doc, "The gap is bridged by query expansion: about twenty mappings from plain language to "
              "the identifiers this codebase actually uses - 'travelling time' adds duration_minutes "
              "and route_distance, 'fare' adds price_ticket. It was added after a concrete failure: "
              "the question 'how is travelling time calculated' returned README.md, a translations "
              "JSON and a planning document, while distance.py - which computes it, 23 chunks of it - "
              "sat unranked in the same index. That is a hand-written vocabulary, not a learned one, "
              "and a question phrased outside it can still under-retrieve.")

    h(doc, 3, "40.3.5 Grounding")
    para(doc, "Retrieval alone does not stop a wrong answer. The same question above was originally "
              "answered 'Execution enters through README.md' with a line range presented as a "
              "function, and reported as CONFIRMED. The answer template took the top citation, "
              "whatever it was, and asserted a call path through it.")
    bullets(doc, [
        ("Source files are preferred over prose and configuration,", "and implementation files over "
         "tests - a test exercising a feature is not an answer to where it is implemented."),
        ("Line-range pseudo-symbols are never presented as functions.", "README.md:L1-L60 is a chunk "
         "address produced by the generic chunker, not a definition."),
        ("An execution flow is described only from a named symbol.", "When only documentation "
         "matches, the answer says so and carries a limitation instead of narrating a call path."),
        ("verify_function_exists() checks a symbol against the indexed AST", "before the assistant "
         "will discuss it, so a question about a function that does not exist returns UNKNOWN.")
    ])
    evidence(doc, "23 regression tests in tests/test_codebase_answer_grounding.py, including a "
                  "reconstruction of the documentation-only case that asserts the answer admits it.")

    h(doc, 2, "40.4 Security: what was wrong, and what it is now")
    callout(doc, "The layer shipped as a working authentication bypass",
            "No /ai/* endpoint had any authentication. Every 'require_role' occurrence in app/ai "
            "was a string inside a prompt or a regex, not an enforced check. Confirmed against a "
            "running server: GET /depot/blocking-plan returned 401 to an anonymous caller, while "
            "POST /ai/chat answered the same question with the full depot fleet figures and a 200.",
            warn=True)
    para(doc, "An assistant that reaches the same services the REST API reaches must apply the same "
              "role checks, or it is simply a side door around them. The fix:")
    bullets(doc, [
        ("Identity comes from the token, never the body.", "A client-supplied user_id could "
         "otherwise claim to be anyone - which is exactly how session history leaked."),
        ("Tools are gated at one chokepoint.", "ToolRegistry.execute_tool() is the single path every "
         "agent and the orchestrator go through, so a new call site cannot forget the check. It "
         "fails closed: with no principal bound, a restricted tool is denied."),
        ("Session memory is keyed user_id::session_id.", "Both identifiers used to come from the "
         "client, so anyone supplying a matching pair read that user's conversation and journey "
         "context - origin and destination included."),
        ("Observability and evaluation are admin-only.", "Traces carry other users' question text, "
         "the buffer reset is destructive, and a benchmark run is a denial-of-service lever."),
    ])
    table(doc, ["Anonymous request", "Before", "After"], [
        ["POST /ai/chat", "200 + depot data", "401"],
        ["GET /ai/session/{id}/history", "200 + victim's journey", "401"],
        ["DELETE /ai/observability/traces", "200 (destructive)", "401"],
        ["POST /ai/evaluation/run", "200 (expensive)", "401"],
        ["GET /ai/health", "200", "200 (public by design)"],
        ["POST /predict", "200", "200 (unchanged)"],
    ], widths=[2.4, 1.9, 1.7])
    evidence(doc, "tests/test_ai_authorization.py holds 19 regression tests, including the "
                  "401-versus-200 pair above and the session IDOR.")

    h(doc, 2, "40.5 The read-only contract")
    para(doc, "Eight tools, all reads. None writes, deletes or mutates a record, ticket, waybill, "
              "fleet plan, user role or configuration value. The model cannot execute shell "
              "commands, evaluate Python, write files, issue SQL or make outbound HTTP requests - no "
              "such tool is registered, and the model reaches DBARS only through the registry.")
    table(doc, ["Tool", "Returns", "Required role"], [
        ["search_bus_route", "Journey options between two stops", "any authenticated"],
        ["get_route_details", "Stop list, terminals, frequencies", "any authenticated"],
        ["get_fleet_plan", "Minimum fleet, interlining, depots", "depot_manager / admin"],
        ["get_crew_plan", "Daily duties, crew-to-bus ratio", "depot_manager / admin"],
        ["get_crowding_information", "Recent commuter crowd reports", "any authenticated"],
        ["get_service_alerts", "Active disruptions", "any authenticated"],
        ["get_metro_information", "Nearby Metro stations", "any authenticated"],
        ["get_bus_eta", "Vehicle positions, schedule status", "any authenticated"],
    ], widths=[1.8, 2.6, 1.6])
    callout(doc, "Say this precisely in a viva",
            "is_read_only is a declared attribute, not an enforced sandbox. No registered tool "
            "writes - that was verified by reading every tool's call path - but nothing mechanically "
            "prevents a future one from doing so. The role restrictions ARE enforced, at the "
            "registry chokepoint. Claiming more than that is the kind of overstatement an examiner "
            "will find.")


def section_41(doc):
    page_break(doc)
    h(doc, 1, "41. Defects the AI Layer Exposed in the Routing Engine")
    para(doc, "Building an assistant that answers the same questions as the search page surfaced "
              "several defects in the deterministic engine itself. These are worth rehearsing "
              "because each one is a good story about measurement: a user-visible symptom, a root "
              "cause in a specific line, and a number that moved.")

    h(doc, 2, "41.1 Stop resolution compared spelling, not place")
    para(doc, "Two separate failures shared one cause - the matcher treated a NAME difference as a "
              "PLACE difference.")
    table(doc, ["Query", "Returned", "Why"], [
        ["dasarahalli metro station", "Vajarahalli Metro Station,\nthe opposite end of the\nGreen Line",
         "Shared generic token\n'metro' plus a similar\nending outscored an\nexact match on the\ndistinctive word"],
        ["White Field Post Office\n-> Kengeri", "86 stops, 85.9 km\ninstead of 33 stops,\n41.4 km",
         "Alighting at 'Kengeri\nBus Station' counted as\ninexact - it is 0.22 km\nfrom 'Kengeri'"],
    ], widths=[1.7, 2.1, 2.2])
    para(doc, "The first was fixed by keying on whether the network actually uses a word, and how "
              "often: no character-similarity threshold separates 'dasarahalli' from 'vajarahalli' "
              "(0.82) from a genuine typo like 'majestc'/'majestic' (0.93). The second by measuring "
              "physical distance - if a commuter could walk it, it is the stop they asked for.")
    evidence(doc, "23 regression tests in tests/test_stop_resolution.py; rank_quality unchanged "
                  "because the benchmark uses canonical stop names while the fix governs free text.")

    h(doc, 2, "41.2 Trunk preference outranked journey length")
    para(doc, "route_rank_score ordered trunk_tier ABOVE total_stops, and route 253 matches the "
              "trunk prefix list. The existing length penalty could not counter it, because "
              "_min_span_for_pair is derived from DIRECT segments only - on a transfer-only pair it "
              "stays None and the penalty is always zero, leaving trunk status to decide unopposed.")
    code(doc,
         "(stop_exactness, transfers, special, span_band, trunk_tier, total_stops, ...)\n"
         "                                     ^^^^^^^^^  ^^^^^^^^^^\n"
         "        length band inserted ABOVE trunk status, banded against the\n"
         "        shortest WALKABLE candidate - a plain min() picks up\n"
         "        name-collision chains and makes every band one stop wide",
         caption="Trunk routes still win among journeys of comparable length; they no longer win by "
                 "riding materially further.")

    h(doc, 2, "41.3 Stop count is not distance")
    para(doc, "Ranking runs before any leg is built, so it uses total_stops as the length signal. "
              "The proxy fails when stop spacing differs: Shivanapura -> Avalahalli BDA Layout was "
              "answered with a 78-stop, 146.3 km journey over an 85-stop, 62.5 km one, because "
              "78 < 85 while 146 km is more than twice as far. A post-build pass now demotes a "
              "candidate more than 1.6x the shortest of its transfer tier, using real distances the "
              "ranker could not see.")

    h(doc, 2, "41.4 The search could not see past one interchange")
    para(doc, "Sapthagiri College -> Reva College are both in north Bengaluru, but no single "
              "interchange links them along the northern arc, so a direct + one-transfer search "
              "could only reach Reva by coming into the city and back out. Google Maps answers the "
              "same pair with three buses. Every one of those routes is in this dataset - 248-BA "
              "serves Sapthagiri, 289-S serves Reva, and 401-A serves NEITHER. It is purely a "
              "middle leg, which no amount of one-transfer searching can find.")
    para(doc, "A bounded meet-in-the-middle search adds the third leg: collect where the first bus "
              "can drop you, where the last can collect you, and examine only routes touching both. "
              "Measured over 60 random pairs, it made 16 pairs routable that previously had no "
              "answer at all, and offered a materially shorter option on 15 more.")

    h(doc, 2, "41.5 Confidence contradicted the ranking")
    callout(doc, "29.8% of results recommended the option they scored lower",
            "Ranking and confidence were two unrelated formulas. Ranking used exactness, transfers, "
            "frequency tier, span and trunk status; confidence used transfers, stop count and "
            "frequency alone. _enrich_transfer_distances was the only code that would have "
            "reconciled them, and nothing called it.", warn=True)
    para(doc, "The score now includes the ranker's signals, weighted in its order of priority, and "
              "the sequence is then forced non-increasing. Be precise about which half does the "
              "work: the formula orders correctly on its own in 76% of multi-option results; the "
              "clamp guarantees the remaining 24% cannot display a contradiction either. A "
              "lexicographic tuple cannot be collapsed into one scalar without loss.")

    h(doc, 2, "41.6 Performance")
    table(doc, ["Measurement", "Before", "After"], [
        ["_detect_metro_interchange share of a route search", "65%", "cached"],
        ["Route search, median", "212 ms", "39 ms"],
        ["Route search, p90", "901 ms", "406 ms"],
        ["First depot question on a cold process", "10-15 s", "77 ms"],
        ["Copilot journey request", "1,932 ms", "~550 ms"],
    ], widths=[3.0, 1.5, 1.5])
    para(doc, "The metro scan re-tokenised all 85 stations for every stop of every leg built - 621k "
              "token lookups per query. The depot figure was a missing warm-up: the lifespan warmed "
              "the blocking plan and the GTFS feed but not the crew plan, so the first question paid "
              "5.6 s rebuilding a cached context plus 7.6 s scheduling crew.")


def section_42(doc):
    page_break(doc)
    h(doc, 1, "42. What Was Measured, and What Was Not")
    para(doc, "This section exists so that nothing in this document is defended further than the "
              "evidence supports. An examiner who finds an overstatement will discount everything "
              "else; leading with the limits is safer and more honest.")

    h(doc, 2, "42.1 The benchmark, read correctly")
    table(doc, ["Metric", "Value"], [
        ["Questions", "57 across 12 categories"],
        ["Pass rate", "100% (57/57)"],
        ["Mean answer correctness (headline)", "81.5%"],
        ["Hallucination rate", "0.00%"],
        ["Mean latency", "635 ms"],
    ], widths=[3.4, 2.6])
    callout(doc, "A pass needs only 40% keyword coverage",
            "'100% pass rate' means every answer cleared a floor, not that every answer was "
            "complete - eight questions passed sitting exactly on it. Mean answer correctness is the "
            "number that can actually move, which is why it is the headline. Weakest categories: "
            "debugging (0.500) and documentation (0.662).", warn=True)
    para(doc, "An earlier version of this report claimed 'Overall Accuracy 100.0%', 'all targets "
              "PASSED' and 'zero metrics are fabricated' - over 2 questions in 1 category, while 57 "
              "across 12 were defined in the repository. It had been generated with limit=2. That is "
              "the kind of number that collapses under one question in a viva.")

    h(doc, 2, "42.2 The 0% hallucination rate is architectural")
    para(doc, "Without GEMINI_API_KEY the layer uses a grounded deterministic model that assembles "
              "answers from retrieved evidence and tool output. It structurally cannot invent a fact "
              "absent from the evidence. That is why the rate is zero - not because a generative "
              "model was tested and found truthful.")
    para(doc, "More pointedly: with a real key configured and Gemini reachable, only 1 of 57 "
              "benchmark questions actually invoked the model - 1.8%. The orchestrator is an intent "
              "router into hand-written agents; the LCEL chain is the fallback branch for queries no "
              "agent claims. Swapping the deterministic model for live Gemini moved mean answer "
              "correctness from 0.8150 to 0.8146. Describing the system as 'LLM-powered' would "
              "substantially overstate the model's role.")

    h(doc, 2, "42.3 Semantic embeddings were tried and did not help")
    para(doc, "The obvious upgrade to a lexical index is real sentence embeddings. It was measured, "
              "not assumed, on identical content:")
    table(doc, ["Provider", "Alone", "With query expansion", "Cost"], [
        ["Hashed n-grams", "5/10", "8/10", "0.15 s, 18 MB"],
        ["all-MiniLM-L6-v2", "4/10", "8/10", "12.07 s, 450 MB"],
    ], widths=[1.8, 1.1, 1.7, 1.4])
    para(doc, "Identical with expansion and slightly worse without it, for 80x the load time and 25x "
              "the memory. all-MiniLM-L6-v2 is trained on natural-language sentences, not source "
              "code; chunks of identifiers and type annotations are out of distribution for it, "
              "while the BM25 half of the hybrid already caught the literal tokens these questions "
              "carry. The deterministic provider is the default. A code-trained embedding model is "
              "the thing worth trying next.")

    h(doc, 2, "42.4 Remaining limits")
    bullets(doc, [
        ("Prompt-injection defence is signature-based.", "It stops the phrasings it enumerates; it "
         "is not a proof against a novel paraphrase. The controls that actually bound the blast "
         "radius are the read-only tool contract and the role checks."),
        ("Query expansion is a hand-written vocabulary.", "About 20 mappings bridging plain language "
         "to identifiers. A question phrased outside them can still under-retrieve."),
        ("Journey times are estimates.", "Route distance plus a flat waiting allowance per change. "
         "The dataset has trip counts but no published per-band frequency, so the allowance is an "
         "assumption - and the UI says so rather than presenting it as live data."),
        ("The two-transfer search is a heuristic.", "Meet-in-the-middle with pruning, not exhaustive. "
         "It finds good three-bus options, not provably optimal ones."),
        ("Detour ratios reflect the network, not only the ranker.", "Across 244 routed pairs the "
         "median journey is 1.80x the straight-line distance and 34 exceed 2.5x. Of those, ZERO had "
         "a materially shorter option already in the candidate set - the rest are the bus network as "
         "it is."),
    ])

    h(doc, 2, "42.5 Verification summary")
    table(doc, ["Check", "Result"], [
        ["Backend test suite", "430 passing"],
        ["rank_quality.best_option_rate", "0.7167 (unchanged through every fix)"],
        ["rank_quality.ndcg@5", "0.9810 -> 0.9820"],
        ["/predict with the AI layer vs blocked", "byte-identical output"],
        ["Protected engine files modified", "one, on explicit instruction (41.1)"],
        ["Secrets in the code index", "none (1,592 chunks scanned)"],
    ], widths=[3.0, 3.0])
