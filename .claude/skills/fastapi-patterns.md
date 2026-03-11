# FastAPI Patterns - For Temporal + AI Demos

## 1. App Setup with Lifespan + Embedded Worker

```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter
from concurrent.futures import ThreadPoolExecutor

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect to Temporal + start worker
    client = await Client.connect(
        "localhost:7233",
        data_converter=pydantic_data_converter,
    )
    app.state.temporal_client = client

    worker = Worker(
        client,
        task_queue="demo-queue",
        workflows=[AgentWorkflow],
        activities=[call_model, tool_activity],
        activity_executor=ThreadPoolExecutor(max_workers=5),
    )
    worker_task = asyncio.create_task(worker.run())
    yield
    # Shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Demo", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

## 2. Router with Temporal Integration

```python
import uuid
from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/api", tags=["demo"])

@router.post("/start")
async def start_workflow(request: Request, prompt: str):
    """Start a new agent workflow."""
    client = request.app.state.temporal_client
    wf_id = f"demo-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        AgentWorkflow.run,
        arg=prompt,
        id=wf_id,
        task_queue="demo-queue",
    )
    return {"workflow_id": handle.id, "run_id": handle.result_run_id}

@router.get("/result/{workflow_id}")
async def get_result(request: Request, workflow_id: str):
    """Wait for and return workflow result (blocking)."""
    client = request.app.state.temporal_client
    handle = client.get_workflow_handle(workflow_id)
    try:
        result = await handle.result()
        return {"workflow_id": workflow_id, "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/status/{workflow_id}")
async def get_status(request: Request, workflow_id: str):
    """Query workflow status without blocking."""
    client = request.app.state.temporal_client
    handle = client.get_workflow_handle(workflow_id)
    try:
        status = await handle.query(AgentWorkflow.get_status)
        return {"workflow_id": workflow_id, "status": status}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/signal/{workflow_id}")
async def signal_workflow(request: Request, workflow_id: str, value: str):
    """Send a signal to a running workflow (e.g., human approval)."""
    client = request.app.state.temporal_client
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("approval_decision", value)
    return {"status": "signal_sent"}
```

## 3. Pydantic v2 Models

```python
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting_for_input"
    COMPLETED = "completed"
    FAILED = "failed"

class StartRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}
    prompt: str = Field(..., min_length=1, max_length=4000)

class StartResponse(BaseModel):
    workflow_id: str
    status: str = "started"

class StatusResponse(BaseModel):
    workflow_id: str
    status: str
    result: Optional[str] = None
```

## 4. SSE for Real-time Workflow Updates

```python
import asyncio, json
from fastapi.responses import StreamingResponse

@router.get("/stream/{workflow_id}")
async def stream_status(request: Request, workflow_id: str):
    client = request.app.state.temporal_client

    async def event_generator():
        handle = client.get_workflow_handle(workflow_id)
        last_status = None
        while True:
            try:
                status = await handle.query(AgentWorkflow.get_status)
                if status != last_status:
                    yield f"data: {json.dumps({'status': status})}\n\n"
                    last_status = status
                    if status in ("completed", "failed"):
                        result = await handle.result()
                        yield f"data: {json.dumps({'status': status, 'result': result})}\n\n"
                        break
                await asyncio.sleep(1)
            except Exception:
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

## 5. WebSocket for Real-time

```python
from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/ws/{workflow_id}")
async def ws_endpoint(websocket: WebSocket, workflow_id: str):
    await websocket.accept()
    client = websocket.app.state.temporal_client
    handle = client.get_workflow_handle(workflow_id)

    try:
        while True:
            status = await handle.query(AgentWorkflow.get_status)
            await websocket.send_json({"status": status})
            if status in ("completed", "failed"):
                result = await handle.result()
                await websocket.send_json({"result": result})
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
```

## 6. Config with pydantic-settings

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_prefix": "APP_"}

    temporal_host: str = "localhost:7233"
    task_queue: str = "demo-queue"
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-6"

settings = Settings()
```

## 7. Simple HTML UI (for demo)

```python
from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html><head><title>Demo</title></head>
    <body>
        <h1>Temporal AI Demo</h1>
        <p>API: <a href="/docs">/docs</a></p>
        <p>Temporal UI: <a href="http://localhost:8233">localhost:8233</a></p>
    </body></html>
    """
```

## Key Patterns
- Use `lifespan` (not deprecated `@app.on_event`)
- Access Temporal client via `request.app.state.temporal_client`
- Use Pydantic v2 (`model_config` dict, NOT `class Config`)
- SSE for real-time demo updates (simpler than WebSocket for demos)
- Run with: `uvicorn app.main:app --reload --port 8000`
- Always use `pydantic_data_converter` when connecting to Temporal
