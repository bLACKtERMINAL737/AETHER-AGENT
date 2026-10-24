from contextlib import asynccontextmanager
import logging
import os
import re
from typing import Literal
from pathlib import Path
from ipaddress import ip_address
from urllib.parse import urlsplit

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
reasoning_provider = ModelProvider(settings.reasoning_model_base_url, settings.reasoning_model_api_key, settings.reasoning_model_name)
router = ModelRouter(primary_provider, coding_provider, fallback_provider, reasoning=reasoning_provider)
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


app = FastAPI(title="AETHER CLAW API", version="0.4.0",
              description="Local-first hybrid AI agent MVP. Bind to localhost only.", lifespan=lifespan)
app.add_middleware(LocalAPIProtection)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    mode: Literal["auto", "manual"] = "auto"
    task_type: Literal["auto", "general", "coding", "reasoning"] = "auto"
    model_route: Literal["primary", "coding", "reasoning", "fallback"] | None = None
    allow_fallback: bool = True
    session_id: str | None = None
    use_saved_memories: bool = False


class ModelConfigurationRequest(BaseModel):
    route: Literal["primary", "coding", "reasoning", "fallback"]
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(min_length=1, max_length=2_000)


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


class SessionSearchRequest(BaseModel):
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
        "reasoning_route_configured": reasoning_provider.configured,
        "coding_test_runner_enabled": coding.enable_test_runner,
        "sandbox_image": coding.sandbox_image,
        "api_token_required": bool(os.getenv("AETHER_API_TOKEN", "").strip()),
    }


@app.get("/health/db")
def health_db():
    """Check that the task database accepts a basic read query."""
    try:
        store.list_tasks(1)
    except Exception as exc:
        logger.error("Database connectivity check failed: %s", exc)
        raise HTTPException(status_code=500, detail="Database is not reachable.") from exc
    return {"status": "ok", "database": "reachable"}


@app.get("/models")
def list_models():
    """Expose configured route names only; never return API keys or full credentials."""
    return {"routes": router.available_routes()}


@app.post("/models/configure")
def configure_model(request: ModelConfigurationRequest):
    """Configure one route in memory for this running process; credentials are never persisted."""
    raw_url = request.base_url.strip()
    model_name = request.model.strip()
    secret = request.api_key.strip()
    if not model_name or not secret:
        raise HTTPException(status_code=422, detail="Model ID and provider key must not be blank.")
    try:
        parsed = urlsplit(raw_url)
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            raise ValueError
        if parsed.query or parsed.fragment:
            raise ValueError
        is_loopback = host.lower() == "localhost"
        if not is_loopback:
            try:
                is_loopback = ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
        if parsed.scheme != "https" and not is_loopback:
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Use an HTTPS provider URL, or HTTP only for localhost/loopback. URL credentials, query strings, and fragments are not allowed.",
        ) from exc

    providers = {
        "primary": primary_provider,
        "coding": coding_provider,
        "reasoning": reasoning_provider,
        "fallback": fallback_provider,
    }
    provider = providers[request.route]
    provider.base_url = raw_url.rstrip("/")
    provider.model = model_name
    provider.api_key = secret
    logger.info("Configured model route %s in memory (credentials not logged)", request.route)
    return {
        "route": request.route,
        "model": provider.model,
        "configured": provider.configured,
        "persistence": "memory-only; configuration resets when the server restarts",
    }


def extract_explicit_memory_request(message: str) -> str | None:
    """Return content only for an unambiguous, user-authored remember request."""
    patterns = (
        r"^(?:please\s+)?remember\s+this(?:\s+[a-z][a-z -]{0,30})?\s*[:：]\s*(.+)$",
        r"^(?:please\s+)?remember\s+(?:that\s+)?(.+)$",
        r"^মনে রাখো\s*[:：-]?\s*(.+)$",
        r"^মনে রেখো\s*[:：-]?\s*(.+)$",
        r"^মনে রাখবে\s*[:：-]?\s*(.+)$",
    )
    text = message.strip()
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            content = match.group(1).strip().strip('"“”‘’')
            content = re.sub(r"\s+", " ", content).strip(" .!。")
            if content and len(content) <= 4_000:
                return content
    return None

def _memory_recall_answer(message: str, memories: list[dict]) -> str | None:
    """Return a saved fact for clear recall questions; never synthesize missing facts."""
    text = message.casefold()
    recall_intent = re.search(
        r"\b(?:what|which|tell me|remind me|do you remember|what's|what is|who|when|where)\b|"
        r"(?:মনে আছে|কি মনে|কী মনে|বলেছিলাম|বলেছিলে|নাম কী|নাম কি)",
        text,
    )
    memory_intent = re.search(
        r"\b(?:remember|remembered|saved|save|told you|asked you|my project|project name|my preference|"
        r"prefer|favorite|favourite|code)\b|(?:মনে|বলেছিলাম|নাম)",
        text,
    )
    if not (recall_intent and memory_intent):
        return None

    # Only recall explicit user-provided facts; rank by meaningful word overlap.
    stop_words = {
        "what", "which", "is", "the", "a", "an", "do", "you", "i", "me", "my",
        "did", "to", "ask", "asked", "tell", "remember", "remembered", "save",
        "saved", "about", "please", "that", "and", "or", "of", "for", "in",
        "বলেছিলাম", "বলেছিলে", "মনে", "আছে", "কি", "কী", "আমার", "নাম",
    }
    terms = {
        term for term in re.findall(r"[a-z0-9_+-]+|[\u0980-\u09ff]+", text)
        if len(term) > 1 and term not in stop_words
    }
    if not terms:
        return None
    candidates = []
    for item in memories:
        if item.get("source") != "explicit_chat_request":
            continue
        content = str(item.get("content", "")).strip()
        words = set(re.findall(r"[a-z0-9_+-]+|[\u0980-\u09ff]+", content.casefold()))
        overlap = terms & words
        if overlap:
            candidates.append((len(overlap), len(words), content))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
    best_score = candidates[0][0]
    best = [item for item in candidates if item[0] == best_score]
    if len(best) != 1:
        return None
    return best[0][2]


def infer_task_type(message: str) -> Literal["general", "coding", "reasoning"]:
    """Conservative, local heuristic; it never sends a second request to classify a task."""
    text = message.lower()
    coding_terms = (
        "code", "coding", "debug", "bug", "function", "class ", "python", "javascript",
        "typescript", "rust", "java ", "c++", "pytest", "test failure", "stack trace",
        "refactor", "implement", "repository", "git ", "api endpoint",
    )
    reasoning_terms = (
        "prove", "derive", "analyze", "analyse", "compare", "trade-off", "tradeoff",
        "step by step", "reasoning", "architecture", "design decision", "complex",
    )
    if any(term in text for term in coding_terms):
        return "coding"
    if any(term in text for term in reasoning_terms):
        return "reasoning"
    return "general"


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
    if session_id and not store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Conversation session not found")

    try:
        # New sessions are created only after the model succeeds, so failed
        # provider requests do not leave empty conversations in the history.
        recent = store.list_session_messages(session_id, limit=12) if session_id else []
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
        effective_task = (
            infer_task_type(request.message)
            if request.mode == "auto" or request.task_type == "auto"
            else request.task_type
        )
        if request.mode == "manual" and request.model_route is None:
            raise HTTPException(
                status_code=422,
                detail="Manual mode requires an explicit model_route selection.",
            )
        tool_task = {"id": None, "count": 0, "attempts": 0, "failed": False, "uncertain": False}

        async def execute_chat_tool(name, arguments):
            if tool_task["id"] is None:
                task = store.create_task("Chat tool use", request.message[:2000])
                tool_task["id"] = task["id"]
                store.set_task_status(task["id"], "running")
            task_id = tool_task["id"]
            tool_task["attempts"] += 1
            execution_id = store.begin_tool(task_id, str(name), arguments)
            try:
                result = tools.execute(name, arguments)
                store.finish_tool(execution_id, "succeeded", result=result)
                tool_task["count"] += 1
                return result
            except ToolError as exc:
                tool_task["failed"] = True
                store.finish_tool(execution_id, "failed", error=str(exc)[:500])
                raise
            except Exception as exc:
                tool_task["failed"] = True
                tool_task["uncertain"] = True
                logger.exception("Unexpected native chat tool failure")
                store.finish_tool(
                    execution_id,
                    "unknown",
                    error="Unexpected execution error; inspect local logs before retrying",
                )
                raise ToolError("Tool execution outcome may be uncertain") from exc

        if callable(getattr(router, "chat_with_tools", None)):
            tool_specs = [
                {
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "description": item["description"],
                        "parameters": item["input_schema"],
                    },
                }
                for item in tools.describe()
            ]
            try:
                result = await router.chat_with_tools(
                    request.message,
                    effective_task,
                    history=history,
                    memories=memories,
                    model_route=request.model_route if request.mode == "manual" else None,
                    allow_fallback=request.allow_fallback,
                    tool_specs=tool_specs,
                    execute_tool=execute_chat_tool,
                    execution_counter=lambda: tool_task["attempts"] > 0,
                    max_tool_calls=5,
                )
            except Exception:
                # The tool journal records each tool's own outcome. If the model
                # fails after a tool ran, mark the parent chat-tool task as failed
                # without rewriting a successful child execution as uncertain.
                if tool_task["id"] is not None:
                    status = "unknown" if tool_task["uncertain"] else "failed"
                    store.set_task_status(
                        tool_task["id"],
                        status,
                        error=(
                            "Tool execution outcome may be uncertain; inspect tool records."
                            if status == "unknown"
                            else "Chat request failed after tool execution; inspect local logs."
                        ),
                    )
                raise
            if tool_task["id"] is not None:
                status = "unknown" if tool_task["uncertain"] else ("failed" if tool_task["failed"] else "succeeded")
                store.set_task_status(
                    tool_task["id"],
                    status,
                    result={"tool_calls": tool_task["count"], "tool_attempts": tool_task["attempts"]},
                    error="One or more tool executions failed" if tool_task["failed"] else None,
                )
                result["task_id"] = tool_task["id"]
                result["tool_calls"] = tool_task["count"]
        else:
            # Compatibility with test adapters and older router implementations.
            result = await router.chat(
                request.message,
                effective_task,
                history=history,
                memories=memories,
                model_route=request.model_route if request.mode == "manual" else None,
                allow_fallback=request.allow_fallback,
            )
        answer = str(result["answer"])
        # Answer knowledge-cutoff questions deterministically: prompt guidance alone
        # cannot prevent a model from repeating a memorized, unsupported date.
        cutoff_question = re.search(
            r"(?:শেষ\s*কবে\s*পর্যন্ত\s*তথ্য|তথ্য\s*দিতে\s*পারো|কত\s*সাল\s*পর্যন্ত|"
            r"last\s*kobe\s*(?:porjonto\s*)?(?:info|information|tothyo)|"
            r"info\s*dite\s*paro|how\s*recent\s*(?:is\s*)?your\s*knowledge|"
            r"knowledge\s*cutoff|what\s*(?:date|year)\s*(?:does\s*)?your\s*(?:knowledge|information))",
            request.message,
            flags=re.IGNORECASE,
        )
        if cutoff_question:
            # Report only configuration/capability facts we can actually observe.
            # A configured model ID is not authoritative metadata for its training cutoff.
            active_model = str(result.get("model") or "নির্দিষ্ট করা যায়নি")
            registered_tools = tools.describe()
            live_search_available = any(
                re.search(r"(?:^|[._-])(web|browser|search)(?:$|[._-])", str(item.get("name", "")), re.I)
                for item in registered_tools
            )
            if live_search_available:
                live_search_note = (
                    "এই অ্যাপে একটি search-সম্পর্কিত tool নিবন্ধিত আছে; সাম্প্রতিক তথ্য "
                    "যাচাই করতে হলে সেটি সত্যিই চালিয়ে ফলাফল পরীক্ষা করতে হবে।"
                )
            else:
                live_search_note = (
                    "এই অ্যাপে বর্তমানে কোনো live web-search tool নিবন্ধিত নেই, তাই এই চ্যাটে "
                    "ওয়েব থেকে সাম্প্রতিক তথ্য যাচাই করতে পারি না।"
                )
            answer = (
                "আমার training data-এর সঠিক শেষ তারিখ provider থেকে যাচাই করা metadata হিসেবে "
                "পাওয়া যায়নি, তাই নির্দিষ্ট মাস বা বছর দাবি করব না। "
                f"এই উত্তরে ব্যবহৃত model ID: {active_model}. "
                "Model ID থেকে একা training cutoff নিশ্চিত করা যায় না। "
                + live_search_note
            )
        # For explicit requests to recall a remembered code, return the saved
        # value directly rather than a verbose model paraphrase. Only use
        # explicitly user-saved memories; never infer a code from unrelated notes.
        code_recall = re.search(
            r"\b(?:what|which)\s+(?:is\s+)?(?:the\s+)?code\b.*\b(?:remember|remembered|save|saved|ask you to remember)\b",
            request.message,
            flags=re.IGNORECASE,
        )
        if request.use_saved_memories and code_recall:
            saved_codes = [
                item for item in memories
                if item.get("source") == "explicit_chat_request"
                and re.search(r"\bcode\b", str(item.get("content", "")), flags=re.IGNORECASE)
            ]
            # A code may be saved as just the value (e.g. CLAW-7391), so also
            # allow concise alphanumeric/hyphen values from explicit remember requests.
            if not saved_codes:
                saved_codes = [
                    item for item in memories
                    if item.get("source") == "explicit_chat_request"
                    and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,80}", str(item.get("content", "")).strip())
                ]
            if saved_codes:
                answer = str(saved_codes[0]["content"]).strip()
        if request.use_saved_memories and not code_recall:
            recalled = _memory_recall_answer(request.message, memories)
            if recalled is not None:
                answer = recalled
        memory_to_save = extract_explicit_memory_request(request.message)
        if memory_to_save:
            saved_memory = store.add_memory(
                "note",
                memory_to_save,
                source="explicit_chat_request",
                tags=["chat", "user-requested"],
            )
            answer = f'I saved this to long-term memory: {saved_memory["content"]}'
        # Create a new session only after a successful model response. Persist
        # the user/assistant pair atomically to avoid empty or partial turns.
        if not session_id:
            session = store.create_session(request.message[:80] or "New conversation")
            session_id = session["id"]
        store.add_session_turn(session_id, request.message, answer)
    except HTTPException:
        raise
    except ProviderNotConfigured as exc:
        if "tool_task" in locals() and tool_task["id"] is not None:
            status = "unknown" if tool_task["uncertain"] else "failed"
            store.set_task_status(
                tool_task["id"], status,
                result={"tool_calls": tool_task["count"], "tool_attempts": tool_task["attempts"]},
                error="Model request failed after tool execution began",
            )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KeyError as exc:
        if "tool_task" in locals() and tool_task["id"] is not None:
            status = "unknown" if tool_task["uncertain"] else "failed"
            store.set_task_status(
                tool_task["id"], status,
                result={"tool_calls": tool_task["count"], "tool_attempts": tool_task["attempts"]},
                error="Chat request failed after tool execution began",
            )
        raise HTTPException(status_code=404, detail="Conversation session not found") from exc
    except Exception as exc:
        if "tool_task" in locals() and tool_task["id"] is not None:
            status = "unknown" if tool_task["uncertain"] else "failed"
            store.set_task_status(
                tool_task["id"], status,
                result={"tool_calls": tool_task["count"], "tool_attempts": tool_task["attempts"]},
                error="Chat request failed after tool execution began",
            )
        logger.exception("Model provider request failed")
        raise HTTPException(status_code=502, detail="Chat request failed; session history may be incomplete; see local logs") from exc
    return {
        **result,
        "answer": answer,
        "session_id": session_id,
        "memory_context_used": bool(request.use_saved_memories and memories),
        "mode": request.mode,
        "task_type": effective_task,
    }


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


@app.get("/sessions/export")
def export_sessions(limit: int = 100):
    """Export local conversation sessions and their messages as versioned JSON."""
    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    sessions = store.list_sessions(limit=limit)
    archive = []
    for session in sessions:
        session_data = store.get_session(session["id"])
        if session_data is None:
            continue
        session_data["messages"] = store.list_session_messages(session["id"], limit=10000)
        archive.append(session_data)
    return {
        "format": "aether-conversation-export",
        "version": 1,
        "sessions": archive,
    }


@app.get("/sessions/{session_id}")
def get_session(session_id: str, limit: int = 100):
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    session["messages"] = store.list_session_messages(session_id, limit=limit)
    return session


@app.post("/sessions/search")
def search_sessions(request: SessionSearchRequest):
    return {"messages": store.search_session_messages(request.query, limit=request.limit)}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    if not store.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return {"deleted": True, "id": session_id}
