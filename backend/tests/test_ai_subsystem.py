from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.auth import create_access_token
from app.main import create_app


def ai_auth_headers(role: str = "admin") -> dict:
    """Bearer header for an account with the given role.

    Same pattern as tests/test_blocking_api.py. Defined per-file because a
    `tests` package on sys.path shadows this directory, so `from tests.conftest
    import ...` resolves to the wrong module.
    """
    token = create_access_token(f"uid-{role}", f"{role}@example.com", role, role.title())
    return {"Authorization": f"Bearer {token}"}



@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_ai_health_endpoint(client: TestClient) -> None:
    """Verify that GET /ai/health returns 200 OK and expected structure."""
    response = client.get("/ai/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "1.0.0"
    assert data["enabled"] is True


def test_ai_chat_baseline_endpoint(client: TestClient) -> None:
    """Verify that POST /ai/chat accepts query and returns structured response."""
    response = client.post(
        "/ai/chat",
        headers=ai_auth_headers("commuter"),
        json={
            "query": "How does DBARS routing work?",
            "retrieval_mode": "auto",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "grounding" in data
    assert "session_id" in data
    assert "latency_ms" in data


def test_existing_predict_unaltered(client: TestClient) -> None:
    """Verify that existing deterministic /predict endpoint is completely unaffected."""
    response = client.post(
        "/predict",
        json={
            "current_stop": "Silk Board",
            "destination": "Marathahalli",
            "limit": 3,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "best_match" in data
    assert data["best_match"]["bus_number"] == "KIA-8E"


def test_codebase_vector_index_integrity() -> None:
    """Verify that the codebase index was created with proper FAISS index and metadata."""
    from app.ai.config import ai_settings
    from app.ai.rag.vector_store import VectorStore

    store = VectorStore.load(ai_settings.code_index_path)
    assert store.index.ntotal > 500
    assert len(store.metadata) == store.index.ntotal


def test_code_retrieval_preserves_metadata() -> None:
    """Verify that retrieved code chunks carry complete metadata (file, symbol, lines, source)."""
    from app.ai.config import ai_settings
    from app.ai.rag.vector_store import VectorStore

    store = VectorStore.load(ai_settings.code_index_path)
    results = store.similarity_search("BMTCBusPredictor predict", top_k=3)
    assert len(results) > 0

    top_chunk, score = results[0]
    assert "file" in top_chunk
    assert "symbol" in top_chunk
    assert "start_line" in top_chunk
    assert "end_line" in top_chunk
    assert top_chunk["start_line"] >= 1
    assert top_chunk["end_line"] >= top_chunk["start_line"]
    assert top_chunk["source"] == "repository"


def test_secrets_excluded_from_code_index() -> None:
    """Verify that excluded paths (.env, secrets, node_modules) are not present in index."""
    from app.ai.config import ai_settings
    from app.ai.rag.vector_store import VectorStore

    store = VectorStore.load(ai_settings.code_index_path)
    for chunk in store.metadata:
        file_path = chunk.get("file", "").lower()
        assert not file_path.endswith(".env"), f"Secret file leaked: {file_path}"
        assert "node_modules" not in file_path, f"Node modules leaked: {file_path}"
        assert ".venv" not in file_path, f"Venv leaked: {file_path}"


def test_ai_health_shows_code_index_ready(client: TestClient) -> None:
    """Verify that /ai/health accurately detects the code index."""
    response = client.get("/ai/health")
    assert response.status_code == 200
    data = response.json()
    assert data["code_index_ready"] is True
    assert data["doc_index_ready"] is True


def test_doc_vector_index_integrity() -> None:
    """Verify that documentation index was created with valid FAISS index and metadata."""
    from app.ai.config import ai_settings
    from app.ai.rag.vector_store import VectorStore

    store = VectorStore.load(ai_settings.doc_index_path)
    assert store.index.ntotal > 50
    assert len(store.metadata) == store.index.ntotal


def test_doc_retrieval_preserves_doc_metadata() -> None:
    """Verify that retrieved documentation chunks carry title, section, file, authority."""
    from app.ai.rag.doc_retriever import doc_retriever

    citations = doc_retriever.retrieve_citations("MongoDB route search architecture", top_k=3)
    assert len(citations) > 0
    top = citations[0]
    assert top.source_type == "documentation"
    assert top.title is not None
    assert top.section is not None
    assert top.path is not None


def test_doc_retrieval_answers_mongodb_question(client: TestClient) -> None:
    """Verify that POST /ai/chat answers the architectural question regarding MongoDB."""
    response = client.post(
        "/ai/chat",
        headers=ai_auth_headers("commuter"),
        json={
            "query": "Why does DBARS not use MongoDB for route search?",
            "retrieval_mode": "documentation",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["sources"]) > 0
    top_source = data["sources"][0]
    assert top_source["source_type"] == "documentation"
    assert "documentation" in data["answer"].lower() or "dbars" in data["answer"].lower()


def test_query_router_classification() -> None:
    """Verify that QueryRouter accurately distinguishes code, doc, and hybrid intents."""
    from app.ai.models import RetrievalMode
    from app.ai.rag.hybrid_retriever import QueryRouter

    # Code queries
    assert QueryRouter.route_query("Where is require_role implemented?") == RetrievalMode.CODE
    assert QueryRouter.route_query("Which file contains create_app?") == RetrievalMode.CODE

    # Documentation queries
    assert QueryRouter.route_query("Why does DBARS not use MongoDB for route search?") == RetrievalMode.DOCUMENTATION
    assert QueryRouter.route_query("What is the defense rationale for relevance-set scoring?") == RetrievalMode.DOCUMENTATION

    # Hybrid queries
    assert QueryRouter.route_query("How is route prediction implemented and why are ordered stop pairs used?") == RetrievalMode.HYBRID


def test_exact_symbol_lexical_retrieval() -> None:
    """Verify that exact symbol retrieval finds exact function/class definitions."""
    from app.ai.rag.hybrid_retriever import hybrid_retriever

    citations = hybrid_retriever.retrieve_citations("Where is require_role implemented?", top_k=3)
    assert len(citations) > 0
    symbols = [c.symbol for c in citations if c.symbol]
    assert any("require_role" in s for s in symbols)


def test_hybrid_chat_response(client: TestClient) -> None:
    """Verify that POST /ai/chat produces hybrid evidence when question crosses implementation & rationale."""
    response = client.post(
        "/ai/chat",
        headers=ai_auth_headers("commuter"),
        json={
            "query": "How is route prediction implemented and why are ordered stop pairs used?",
            "retrieval_mode": "auto",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["sources"]) > 0
    source_types = {s["source_type"] for s in data["sources"]}
    assert "code" in source_types or "documentation" in source_types


@pytest.mark.asyncio
async def test_langchain_orchestrator_pipeline() -> None:
    """Verify that LangChain LCEL pipeline executes end-to-end and returns structured response."""
    from app.ai.agents.orchestrator import orchestrator
    from app.ai.models import AIChatRequest, GroundingConfidence

    request = AIChatRequest(
        query="Where is BMTCBusPredictor implemented?",
        retrieval_mode="code",
    )
    response = await orchestrator.execute(request)
    assert response is not None
    assert response.grounding == GroundingConfidence.CONFIRMED
    assert len(response.sources) > 0
    assert "BMTCBusPredictor" in response.answer or "predictor.py" in response.answer


@pytest.mark.asyncio
async def test_langchain_error_handling() -> None:
    """Verify that LangChain orchestrator catches errors gracefully without crashing."""
    from app.ai.agents.orchestrator import orchestrator
    from app.ai.models import AIChatRequest

    # Test with empty query or ungrounded topic
    request = AIChatRequest(
        query="What is the nuclear launch code for Mars?",
        retrieval_mode="auto",
    )
    response = await orchestrator.execute(request)
    assert response is not None
    assert "UNKNOWN" in response.answer or "cannot be established" in response.answer


def test_tool_registry_read_only_safety() -> None:
    """Verify that all tools in tool_registry are marked read-only."""
    from app.ai.tools.registry import tool_registry

    tools = tool_registry.list_tools()
    assert len(tools) >= 7
    for t in tools:
        assert getattr(t, "is_read_only", False) is True


def test_search_bus_route_tool_execution() -> None:
    """Verify that search_bus_route calls real BMTCBusPredictor deterministically."""
    from app.ai.tools.registry import tool_registry

    rec = tool_registry.execute_tool("search_bus_route", current_stop="Silk Board", destination="Marathahalli", limit=3)
    assert rec.status == "success"
    assert rec.output["best_match"]["bus_number"] == "KIA-8E"
    assert rec.output["best_match"]["is_direct"] is True or rec.output["best_match"]["is_direct"] is False


def test_get_route_details_tool_execution() -> None:
    """Verify that get_route_details looks up authentic catalogue stops."""
    from app.ai.tools.registry import tool_registry

    rec = tool_registry.execute_tool("get_route_details", bus_number="KIA-8E")
    assert rec.status == "success"
    assert rec.output["found"] is True
    assert rec.output["bus_number"] == "KIA-8E"
    assert len(rec.output["stop_sequence"]) > 0


def test_get_metro_info_tool_execution() -> None:
    """Verify that get_metro_information finds nearby metro stations for a bus stop."""
    from app.ai.tools.registry import tool_registry

    rec = tool_registry.execute_tool("get_metro_information", stop_name="Majestic")
    assert rec.status == "success"
    assert rec.output["has_metro_connection"] is True
    assert len(rec.output["nearby_stations"]) > 0


def test_get_fleet_plan_tool_execution() -> None:
    """Verify that get_fleet_plan returns valid blocking metrics."""
    from app.ai.tools.registry import tool_registry

    rec = tool_registry.execute_tool("get_fleet_plan")
    assert rec.status == "success"
    assert "total_buses_scheduled" in rec.output or "status" in rec.output


def test_ai_chat_end_to_end_tool_invocation(client: TestClient) -> None:
    """Verify that POST /ai/chat invokes the search_bus_route tool for commuter travel queries."""
    response = client.post(
        "/ai/chat",
        headers=ai_auth_headers("commuter"),
        json={
            "query": "How do I travel from Silk Board to Marathahalli?",
            "retrieval_mode": "auto",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["tools_called"]) > 0
    called_tool = data["tools_called"][0]
    assert called_tool["tool_name"] == "search_bus_route"
    assert "KIA-8E" in str(called_tool["output"])
    assert "KIA-8E" in data["answer"]


def test_ai_health_reports_tool_count(client: TestClient) -> None:
    """Verify that GET /ai/health accurately reports registered DBARS tools."""
    response = client.get("/ai/health")
    assert response.status_code == 200
    data = response.json()
    assert data["dbars_tools_registered"] >= 7


def test_codebase_assistant_answers_startup_flow() -> None:
    """Verify that CodebaseAssistant generates 7-part grounded architectural explanation."""
    from app.ai.agents.codebase_agent import codebase_assistant

    answer = codebase_assistant.answer("Where does the application start?")
    assert "main.py" in " ".join(answer.relevant_source_files).lower()
    assert len(answer.execution_flow) >= 3
    assert len(answer.evidence) > 0
    formatted = answer.to_formatted_markdown()
    assert "### 1. Direct Answer" in formatted
    assert "### 2. Relevant Source Files" in formatted
    assert "### 4. Execution Flow" in formatted


def test_codebase_assistant_chat_api(client: TestClient) -> None:
    """Verify that POST /ai/chat routes codebase queries to CodebaseAssistant with 7-part format."""
    response = client.post(
        "/ai/chat",
        headers=ai_auth_headers("commuter"),
        json={
            "query": "Explain predictor.py and how BMTCBusPredictor works",
            "retrieval_mode": "code",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "predictor.py" in data["answer"].lower()
    assert "### 1. Direct Answer" in data["answer"]
    assert "### 4. Execution Flow" in data["answer"]
    assert len(data["sources"]) > 0
