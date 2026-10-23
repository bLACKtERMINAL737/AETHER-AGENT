from contextlib import asynccontextmanager
import logging
import os
from typing import Literal
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .coding import CodingEngine, CodingError
from .config import Settings
from .provider import ModelProvider, ModelRouter, ProviderNotConfigured
from .store import TaskStore
from .security import LocalAPIProtection
from .tools import ToolRegistry, ToolError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aether")
settings = Settings.from_env()
settings.workspace.mkdir(parents=True, exist_ok=True)
store = TaskStore(settings.db_path)
tools = ToolRegistry(settings.workspace)
primary_provider = ModelProvider(settings.model_base_url, settings.model_api_key, settings.model_name)
coding_provider = ModelProvider(settings.coding_model_base_url, settings.coding_model_api_key, settings.coding_model_name)
fallback_provider = ModelProvider(settings.fallback_model_base_url, settings.fallback_model_api_key, settings.fallback_model_name)
router = ModelRouter(primary_provider, coding_provider, fallback_provider)
coding = CodingEngine(
    settings.workspace, store, router,
    enable_test_runner=os.getenv("AETHER_ENABLE_TEST_RUNNER", "").lower() == "true",
    test_timeout_seconds=int(os.getenv("AETHER_TEST_TIMEOUT_SECONDS", "60")),
    sandbox_image=os.getenv("AETHER_SANDBOX_IMAGE", "aether-sandbox:latest"),
    test_project=Path(os.environ["AETHER_TEST_PROJECT"]).expanduser()
    if os.getenv("AETHER_TEST_PROJECT") else None,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    changed = store.mark_interrupted_as_unknown()
    if changed:
        logger.warning("Marked %s interrupted records as unknown", changed)
    # Do not mislabel another local server process's live apply operation as
    # interrupted. If the lock is busy, that process owns the apply lifecycle.
    with store.coding_apply_lock(blocking=False) as acquired:
        if acquired:
            proposals = store.mark_interrupted_proposals_for_review()
            if proposals:
                logger.warning(
                    "Found %s coding proposals interrupted during apply; manual workspace reconciliation is required",
                    proposals,
                )
        else:
            logger.info(
                "Skipped coding proposal startup recovery because another process holds the apply lock"
            )
    yield


app = FastAPI(title="Project Aether API", version="0.4.0",
              description="Local-first hybrid AI agent MVP. Bind to localhost only.", lifespan=lifespan)
app.add_middleware(LocalAPIProtection)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    task_type: Literal["general", "coding", "reasoning"] = "general"
    session_id: str | None = None
    use_saved_memories: bool = False


class TaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1, max_length=20_000)


class ToolRequest(BaseModel):
    task_id: str | None = None
    input: dict[str, object] = Field(default_factory=dict)


class CodingProposalRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=8_000)
    paths: list[str] = Field(min_length=1, max_length=8)


class CodingIterationRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=8_000)
    paths: list[str] = Field(min_length=1, max_length=8)
    max_rounds: int = Field(default=3, ge=1, le=3)


class MemoryCreateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=4_000)
    source: str = Field(default="user", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=20, ge=1, le=100)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "project": "aether",
        "provider_configured": primary_provider.configured,
        "coding_route_configured": coding_provider.configured,
        "fallback_route_configured": fallback_provider.configured,
        "coding_test_runner_enabled": coding.enable_test_runner,
        "sandbox_image": coding.sandbox_image,
        "api_token_required": bool(os.getenv("AETHER_API_TOKEN", "").strip()),
    }


@app.get("/tools")
def list_tools():
    return {"tools": tools.describe()}


@app.post("/tools/{tool_name}")
def execute_tool(tool_name: str, request: ToolRequest):
    task_id = request.task_id
    if task_id and not store.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    if not task_id:
        task_id = store.create_task(f"Tool: {tool_name}", f"Execute {tool_name}")["id"]
    store.set_task_status(task_id, "running")
    execution_id = None
    try:
        execution_id = store.begin_tool(task_id, tool_name, request.input)
        result = tools.execute(tool_name, request.input)
        store.finish_tool(execution_id, "succeeded", result=result)
        store.set_task_status(task_id, "succeeded", result=result)
        return {"task_id": task_id, "execution_id": execution_id, "status": "succeeded", "result": result}
    except ToolError as exc:
        if execution_id:
            store.finish_tool(execution_id, "failed", error=str(exc))
        store.set_task_status(task_id, "failed", error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected tool failure")
        if execution_id:
            store.finish_tool(execution_id, "unknown", error="Unexpected execution error; inspect logs before retrying")
        store.set_task_status(task_id, "unknown", error="Execution outcome may be uncertain")
        raise HTTPException(status_code=500, detail="Tool execution outcome may be uncertain") from exc


@app.post("/tasks")
def create_task(request: TaskRequest):
    return store.create_task(request.title, request.input)


@app.get("/tasks")
def list_tasks(limit: int = 50):
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    return {"tasks": store.list_tasks(limit)}


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task["tool_executions"] = store.list_tool_executions(task_id)
    return task


@app.post("/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id
    if session_id:
        if not store.get_session(session_id):
            raise HTTPException(status_code=404, detail="Conversation session not found")
    else:
        session = store.create_session(request.message[:80] or "New conversation")
        session_id = session["id"]

    try:
        recent = store.list_session_messages(session_id, limit=12)
        history = [
            {"role": item["role"], "content": item["content"]}
            for item in recent
            if item["role"] in {"user", "assistant"}
        ][-12:]
        memories = []
        if request.use_saved_memories:
            # Retrieve direct lexical matches first, then include user preferences
            # because they can guide response style even when the prompt shares
            # no literal words with the stored preference.
            memories = store.search_memories(request.message, limit=5)
            seen_memory_ids = {item["id"] for item in memories}
            for item in store.list_memories(limit=100, category="preference"):
                if item["id"] not in seen_memory_ids:
                    memories.append(item)
                    seen_memory_ids.add(item["id"])
                if len(memories) >= 5:
                    break
        result = await router.chat(
            request.message,
            request.task_type,
            history=history,
            memories=memories,
        )
        answer = str(result["answer"])
        # Persist only successful turns so failed provider calls do not create orphan user messages.
        store.add_session_message(session_id, "user", request.message)
        store.add_session_message(session_id, "assistant", answer)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation session not found") from exc
    except Exception as exc:
        logger.exception("Model provider request failed")
        raise HTTPException(status_code=502, detail="Chat request failed; session history may be incomplete; see local logs") from exc
    return {**result, "session_id": session_id, "memory_context_used": bool(request.use_saved_memories and memories)}


@app.post("/coding/proposals")
async def create_coding_proposal(request: CodingProposalRequest):
    try:
        return await coding.propose(request.instruction, request.paths)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CodingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not create coding proposal")
        raise HTTPException(status_code=502, detail="Coding proposal failed; see local logs") from exc


@app.post("/coding/iterate")
async def iterate_coding_task(request: CodingIterationRequest):
    try:
        return await coding.iterate_with_tests(
            request.instruction, request.paths, max_rounds=request.max_rounds
        )
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CodingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Iterative coding task failed")
        raise HTTPException(status_code=502, detail="Iterative coding task failed; inspect local logs") from exc


@app.get("/coding/proposals/{proposal_id}")
def get_coding_proposal(proposal_id: str):
    proposal = store.get_proposal(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


@app.post("/coding/proposals/{proposal_id}/approve")
def approve_coding_proposal(proposal_id: str):
    try:
        return coding.approve(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CodingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/coding/proposals/{proposal_id}/reject")
def reject_coding_proposal(proposal_id: str):
    try:
        return coding.reject(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CodingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/coding/proposals/{proposal_id}/apply")
def apply_coding_proposal(proposal_id: str):
    try:
        return coding.apply(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CodingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/coding/run-tests")
def run_coding_tests():
    try:
        return coding.run_tests()
    except CodingError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/coding/files")
def list_coding_files(path: str = "."):
    try:
        result = tools.execute("workspace.list_files", {"path": path})
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    base = "" if result["path"] == "." else str(result["path"]).rstrip("/") + "/"
    return {
        "path": result["path"],
        "entries": [
            {"name": entry["name"], "type": entry["type"], "path": base + entry["name"]}
            for entry in result["entries"]
        ],
    }


app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")


@app.post("/memory")
def create_memory(request: MemoryCreateRequest):
    return store.add_memory(request.category, request.content, request.source, request.tags)


@app.get("/memory")
def list_memory(limit: int = 100, category: str | None = None):
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    return {"memories": store.list_memories(limit=limit, category=category)}


@app.post("/memory/search")
def search_memory(request: MemorySearchRequest):
    return {"memories": store.search_memories(request.query, limit=request.limit)}


@app.delete("/memory/{memory_id}")
def delete_memory(memory_id: str):
    if not store.delete_memory(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": True, "id": memory_id}


@app.post("/sessions")
def create_session(title: str = "New conversation"):
    return store.create_session(title)


@app.get("/sessions")
def list_sessions(limit: int = 50):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    return {"sessions": store.list_sessions(limit=limit)}


@app.get("/sessions/{session_id}")
def get_session(session_id: str, limit: int = 100):
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    session["messages"] = store.list_session_messages(session_id, limit=limit)
    return session


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    if not store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return {"deleted": True, "id": session_id}
