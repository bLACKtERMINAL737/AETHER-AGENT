from contextlib import asynccontextmanager
import logging
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .provider import ModelProvider, ModelRouter, ProviderNotConfigured
from .store import TaskStore
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    changed = store.mark_interrupted_as_unknown()
    if changed:
        logger.warning("Marked %s interrupted records as unknown", changed)
    yield


app = FastAPI(title="Project Aether API", version="0.2.0",
              description="Local-first hybrid AI agent MVP. Bind to localhost only.", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    task_type: Literal["general", "coding", "reasoning"] = "general"


class TaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1, max_length=20_000)


class ToolRequest(BaseModel):
    task_id: str | None = None
    input: dict[str, object] = Field(default_factory=dict)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "project": "aether",
        "provider_configured": primary_provider.configured,
        "coding_route_configured": coding_provider.configured,
        "fallback_route_configured": fallback_provider.configured,
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
    try:
        result = await router.chat(request.message, request.task_type)
    except ProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Model provider request failed")
        raise HTTPException(status_code=502, detail="Model provider request failed; see local logs") from exc
    return result
