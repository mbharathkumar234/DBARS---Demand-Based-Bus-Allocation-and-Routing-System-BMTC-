# -*- coding: utf-8 -*-
"""Front matter + Sections 1-5."""
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from style import (ACCENT, GREY, NAVY, add_toc, bullets, callout, code,
                   evidence, h, numbered, page_break, para, table)


def front_matter(doc):
    for _ in range(5):
        doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("DBARS")
    r.font.size = Pt(46); r.bold = True; r.font.color.rgb = NAVY
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Demand Based Bus Allocation & Routing System")
    r.font.size = Pt(17); r.font.color.rgb = ACCENT
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("A transit planning, operations and open-data platform for BMTC, Bengaluru")
    r.font.size = Pt(11); r.italic = True; r.font.color.rgb = GREY
    doc.add_paragraph()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("PROJECT DEFENSE & CODEBASE MASTERY DOCUMENT")
    r.font.size = Pt(14); r.bold = True; r.font.color.rgb = NAVY
    for _ in range(2):
        doc.add_paragraph()
    table(doc, ["Attribute", "Detail"], [
        ["Project name", "DBARS - Demand Based Bus Allocation & Routing System"],
        ["Repository", "github.com/mbharathkumar234/\nDBARS---Demand-Based-Bus-Allocation-and-Routing-System-BMTC-"],
        ["Backend", "Python 3.12, FastAPI 0.115.6, Uvicorn, Pydantic 2.10.4, Motor 3.6 (MongoDB)"],
        ["Frontend", "React 19, TypeScript 5.7, Vite 6, Tailwind 3.4, Leaflet 1.9, Recharts 3"],
        ["Database", "MongoDB (17 collections) - optional; core routing runs without it"],
        ["Mobile", "Capacitor 8 (Android shell around the built web app)"],
        ["Open data", "GTFS static + GTFS-Realtime (protobuf) export"],
        ["Deployment", "Docker Compose (backend / frontend / mongo), Render, Vercel, Nginx"],
        ["CI", "GitHub Actions - pytest + compileall + frontend build on every push"],
        ["Scale of code", "~13,562 lines backend Python (65 files); ~8,459 lines frontend\nTS/TSX (45 files); 2,440 lines of tests (15 files); 82 REST endpoints"],
        ["Test suite", "161 backend tests, all passing"],
        ["Document date", "1 September 2026"],
    ], widths=[1.5, 5.3])
    page_break(doc)

    h(doc, 1, "How to Use This Document")
    para(doc, "This document is written for a reader who knows basic programming but has not "
              "memorised this codebase. Read it once end to end to understand the system, then "
              "use it as a reference when defending, debugging or extending the project.")
    bullets(doc, [
        ("Sections 1-6:", "the system as a whole - what it does and how the parts fit together. Read these first."),
        ("Sections 7-12:", "the code itself - files, entry point, execution traces, functions, classes, line by line."),
        ("Sections 13-25:", "subsystem deep dives - API, database, auth, ML, errors, config, security, testing, deployment, patterns, algorithms."),
        ("Sections 26-33:", "explanation and defense - the full story, professor questions, recruiter answers, diagrams to draw."),
        ("Sections 34-39:", "practical mastery - debugging, modification, weaknesses, technical debt, code quality, master map."),
    ])
    callout(doc, "Confidence labels used throughout",
            "CONFIRMED - directly supported by a file in the repository, cited in an Evidence line.   "
            "INFERRED - strongly implied by the implementation but not stated outright.   "
            "UNCERTAIN - insufficient evidence; stated as such rather than guessed.   "
            "Where something cannot be established from the code at all, this document says "
            "\"Not determinable from the supplied code/project files.\"")
    callout(doc, "An important honesty note about this project",
            "DBARS is an academic / portfolio project, not a deployed BMTC system. Three things "
            "inside it are deliberately simulated, and are labelled as such in the code itself: "
            "live vehicle positions (a physics simulator, unless a real feed is configured), ticket "
            "payment (a transaction record is written; there is no payment gateway), and Shakti "
            "scheme eligibility (taken from the gender on the account; no government ID check). "
            "Claiming otherwise in a viva would be false. The code contains explicit guards that "
            "prevent simulated data being published as real - that is a strength to explain, not a "
            "weakness to hide.", warn=True)
    page_break(doc)

    h(doc, 1, "Table of Contents")
    para(doc, "In Microsoft Word, click the field below and press F9 (or right-click > Update Field) "
              "to generate the contents with page numbers.", italic=True, size=9)
    add_toc(doc)
    page_break(doc)


def section_1(doc):
    h(doc, 1, "1. Executive Project Overview")

    h(doc, 2, "1.1 Project Name")
    para(doc, "DBARS - Demand Based Bus Allocation & Routing System.")
    evidence(doc, "README.md; backend/app/core/config.py -> Settings.app_name")

    h(doc, 2, "1.2 One-Sentence Description")
    para(doc, "DBARS is a full-stack platform that turns BMTC's published bus timetable into three "
              "things at once: a journey planner for commuters, an operations planning tool for depot "
              "managers (how many buses and how much crew a timetable actually needs), and an open "
              "GTFS data feed that any external journey planner can consume.", bold=True)

    h(doc, 2, "1.3 Problem Being Solved")
    para(doc, "Bengaluru's bus network is large and hard to navigate, and the software around it "
              "addresses only one side of the problem. The project targets three gaps:")
    bullets(doc, [
        ("Commuters", "cannot easily find which bus goes from stop A to stop B, especially when a "
                      "transfer is needed. The dataset holds 3,940 distinct bus numbers across 4,883 stops."),
        ("The operator", "gets nothing from a commuter app that answers operational questions: how "
                         "few buses can run this timetable, how many kilometres are run empty, and how "
                         "many crew duties are needed to staff it."),
        ("External journey planners", "(Google Maps and similar) can only be as good as the data they "
                                      "are given; BMTC data published as GTFS improves all of them at once."),
    ])
    para(doc, "A fourth, narrower gap is addressed by the conductor module: the daily paperwork of a "
              "bus conductor - the waybill, cash reconciliation, and counting free travel under the "
              "Karnataka Shakti scheme for state reimbursement - is not modelled by any consumer app, "
              "because it is not a consumer problem. It is where the money is.")

    h(doc, 2, "1.4 Proposed Solution")
    para(doc, "One system built on one shared dataset, serving four user roles from a single backend. "
              "The same 6,737 route-direction records power the commuter's journey search, the depot "
              "manager's fleet and crew plans, and the GTFS export - so the answers cannot disagree "
              "with one another.")
    code(doc,
         "            dataset/routes_cleaned.csv   (BMTC published timetable)\n"
         "                              |\n"
         "        +---------------------+---------------------+\n"
         "        |                     |                     |\n"
         "   COMMUTER              OPERATIONS             OPEN DATA\n"
         "   journey search        fleet blocking         GTFS static\n"
         "   e-ticket              crew duties            GTFS-Realtime\n"
         "   live map              waybill / revenue      (alerts, vehicles)\n"
         "   SMS channel           demand voting",
         caption="Figure 1.1 - One dataset, three products.")

    h(doc, 2, "1.5 Target Users")
    table(doc, ["Role", "Who they are", "What they do in DBARS", "Evidence"], [
        ["commuter", "Ordinary bus passenger",
         "Search journeys, vote for unserved routes, buy\ne-tickets, report crowding, share trips",
         "auth/auth.py\nUserRole"],
        ["conductor", "Onboard staff who sell tickets",
         "Sign on to a waybill, issue tickets offline,\nverify passes, sign off with cash",
         "api/conductor.py"],
        ["depot_manager", "Runs one bus depot",
         "Fleet blocking plan, crew duty plan, scenario\nconsoles, waybill oversight",
         "api/routes.py\ndepot endpoints"],
        ["admin", "BMTC corporate / office user",
         "Network dashboards, user management, Shakti\nclaims, revenue reconciliation, audit log",
         "api/admin.py"],
        ["driver", "Bus driver",
         "Role exists and can be named on a waybill;\nno driver-facing screens yet",
         "auth/auth.py\nUserRole.DRIVER"],
    ], widths=[1.0, 1.4, 2.8, 1.6])
    callout(doc, "Finding - an incomplete role",
            "UserRole.DRIVER was added so a waybill can record which driver was on the bus, but there "
            "is no driver-facing page, no driver sign-up flow and no driver endpoints. This is a "
            "declared gap, not something to hide - say so if asked. CONFIRMED: no route in "
            "frontend/src/App.tsx is gated to the driver role.", warn=True)

    h(doc, 2, "1.6 Core Features")
    table(doc, ["#", "Feature", "What it does", "Where it lives"], [
        ["1", "Journey search", "Direct and one-transfer routes between two stops,\nranked, with distance, fare and metro interchange", "ml/predictor.py"],
        ["2", "Demand voting", "Commuters vote for origin-destination pairs; votes\nbecome depot dispatch recommendations", "api/votes.py\nservices/vote_service.py"],
        ["3", "Fleet blocking", "Minimum buses and dead kilometres per depot,\nderived from the timetable alone", "ml/blocking.py"],
        ["4", "Crew duty scheduling", "Cuts vehicle blocks into legal crew duties; reports\nthe crew-to-bus ratio", "ml/crew.py"],
        ["5", "GTFS export", "Full static feed plus realtime service alerts", "app/gtfs/"],
        ["6", "Vehicle location (AVL)", "Pluggable feed adapters, schedule adherence,\nroute-following ETAs", "app/tracking/"],
        ["7", "E-ticketing", "Signed QR tokens, 6-character short codes, and\nShakti free travel", "api/tickets.py"],
        ["8", "Conductor waybill", "Sign-on, offline ticket sync, cash reconciliation,\nShakti claim reporting", "api/conductor.py"],
        ["9", "Travel passes", "Issued as signed tokens, verified offline against a\nrevocation list", "services/pass_service.py"],
        ["10", "Crowding reports", "Commuter-reported occupancy with freshness and\ncooldown rules", "services/crowding_service.py"],
        ["11", "Service alerts", "Depot-published disruptions, also exported as\nGTFS-Realtime", "api/alerts.py"],
        ["12", "SMS channel", "Free-text journey queries by SMS, for feature phones", "api/sms.py"],
        ["13", "Personal safety", "Trusted contacts and expiring shared-trip links", "services/safety_service.py"],
        ["14", "Metro integration", "Nearest metro stations; interchange detection inside\na bus route", "services/metro_service.py"],
        ["15", "Multilingual UI", "English, Kannada, Hindi, Telugu", "frontend/src/i18n/"],
    ], widths=[0.3, 1.35, 3.05, 2.1])

    h(doc, 2, "1.7 Project Goals")
    numbered(doc, [
        "Answer a commuter's \"which bus do I take?\" question from real BMTC data, including transfers.",
        "Produce operational figures - fleet size, dead kilometres, crew duties - that no consumer app produces.",
        "Close the loop between commuter demand (votes) and operator action (dispatch recommendations).",
        "Publish the data in a standard format so the wider ecosystem benefits.",
        "Model the money: fares, cash reconciliation and state reimbursement, correctly separated.",
        "Never present simulated or modelled data as measured fact.",
    ])

    h(doc, 2, "1.8 Real-World Use Case")
    para(doc, "A commuter at Majestic wants to reach Marathahalli. She opens DBARS, types both stops, "
              "and receives bus 335-G with the stop sequence, distance, estimated fare and a map of the "
              "route. Because her account records her gender as female, her e-ticket is issued free "
              "under the Karnataka Shakti scheme - with the fare value still recorded, so BMTC can claim "
              "it back from the state. If no bus served her pair, she could vote for it; enough votes "
              "surface that pair on the depot manager's dispatch screen. Meanwhile the depot manager, "
              "working from the same data, sees that the network timetable can be held by 6,849 "
              "interlined buses needing 15,636 daily crew duties.")

    h(doc, 2, "1.9 What Makes the Project Technically Interesting")
    bullets(doc, [
        ("Two products from one dataset.", "The same CSV answers a consumer question and an "
         "operations-research question. The fleet-blocking and crew-scheduling engines are genuinely "
         "uncommon in a student project."),
        ("A graph search, not a classifier.", "Route prediction is an indexed search over 655,438 "
         "ordered stop pairs, not a trained model. The project benchmarks it against three alternative "
         "rankers and reports all four honestly."),
        ("Honesty enforced in code.", "Simulated vehicle positions carry an is_live=False flag that "
         "gates the GTFS-Realtime endpoint with a hard 503. The system is built so that it cannot "
         "accidentally lie about the provenance of its data."),
        ("Offline-first money handling.", "Conductor ticket sales use client-generated UUIDs and a "
         "unique database index, so a replayed offline batch cannot double-count revenue."),
        ("Degradation by design.", "Route prediction, blocking, crew planning and GTFS export all work "
         "with MongoDB switched off; only the features that genuinely need a database report themselves "
         "unavailable."),
    ])

    h(doc, 2, "1.10 Current Project Maturity")
    para(doc, "Classification: MVP / production-oriented prototype.", bold=True)
    table(doc, ["Signal", "Evidence", "Points toward"], [
        ["161 automated tests running in CI", "backend/tests/, .github/workflows/ci.yml", "Production-oriented"],
        ["Containerised, three deploy targets", "docker-compose.yml, render.yaml, vercel.json", "Production-oriented"],
        ["Role-based access control on writes", "auth/auth.py -> require_role", "Production-oriented"],
        ["Graceful degradation without a database", "db/database.py -> init_db docstring", "Production-oriented"],
        ["No payment gateway", "api/tickets.py writes a transaction record only", "Prototype"],
        ["Vehicle tracking simulated by default", "TRACKING_FEED defaults to \"simulated\"", "Prototype"],
        ["No frontend tests at all", "frontend/package.json has no test script", "Prototype"],
        ["Shakti eligibility unverified", "core/shakti.py -> DISCLOSURE", "Prototype"],
        ["In-memory, single-process rate limiter", "core/rate_limit.py", "Not production-ready"],
    ], widths=[2.2, 3.0, 1.6])
    para(doc, "Reasoning: the engineering discipline is production-oriented - tests, CI, RBAC, "
              "containerisation and explicit failure modes. What keeps it short of production-ready is "
              "that three subsystems are deliberately simulated, there is no real payment or identity "
              "verification, and some infrastructure (rate limiting, in-memory state) assumes a single "
              "process. INFERRED from the combination of signals above.")
    page_break(doc)
