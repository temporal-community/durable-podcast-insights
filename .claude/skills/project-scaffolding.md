# Project Scaffolding - From Production Code

> Based on actual patterns from Bedrock workshop + AI cookbook

## pyproject.toml

```toml
[project]
name = "demo-name"
version = "0.1.0"
description = "Temporal + FastAPI + AI Demo"
requires-python = ">=3.11"
dependencies = [
    "temporalio>=1.19.0",
    "protobuf>=5.29.3,<6.0.0",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "boto3>=1.35.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "ruff>=0.6.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

## Project Structure

```
demo-name/
├── pyproject.toml
├── .env.example
├── README.md
├── run.py                  # Single entry: starts API + worker
├── worker.py               # Standalone worker (for 3-terminal demo)
├── start.py                # CLI workflow starter (for 3-terminal demo)
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI app + lifespan
│   ├── config.py           # pydantic-settings config
│   └── api/
│       ├── __init__.py
│       └── routes.py       # API endpoints
├── workflows/
│   ├── __init__.py
│   └── agent.py            # Temporal workflows
├── activities/
│   ├── __init__.py
│   ├── llm.py              # LLM call activity
│   └── tool_invoker.py     # Dynamic tool activity
├── tools/
│   ├── __init__.py          # get_handler() + get_tools()
│   └── weather.py           # Example tool
├── helpers/
│   └── tool_helpers.py      # claude_tool_from_model()
└── models/
    └── schemas.py           # Pydantic models
```

## Key Files

### app/config.py
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

### app/main.py
```python
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.api.routes import router
from workflows.agent import AgentWorkflow
from activities.llm import call_model, tool_activity

@asynccontextmanager
async def lifespan(app: FastAPI):
    client = await Client.connect(
        settings.temporal_host,
        data_converter=pydantic_data_converter,
    )
    app.state.temporal_client = client

    worker = Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[AgentWorkflow],
        activities=[call_model, tool_activity],
        activity_executor=ThreadPoolExecutor(max_workers=5),
    )
    worker_task = asyncio.create_task(worker.run())
    yield
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Demo", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
```

### app/api/routes.py
```python
import uuid
from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/api", tags=["demo"])

@router.post("/start")
async def start_workflow(request: Request, prompt: str):
    client = request.app.state.temporal_client
    wf_id = f"demo-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        AgentWorkflow.run,
        arg=prompt,
        id=wf_id,
        task_queue="demo-queue",
    )
    return {"workflow_id": handle.id}

@router.get("/status/{workflow_id}")
async def get_status(request: Request, workflow_id: str):
    client = request.app.state.temporal_client
    handle = client.get_workflow_handle(workflow_id)
    try:
        status = await handle.query(AgentWorkflow.get_status)
        return {"workflow_id": workflow_id, "status": status}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/result/{workflow_id}")
async def get_result(request: Request, workflow_id: str):
    client = request.app.state.temporal_client
    handle = client.get_workflow_handle(workflow_id)
    result = await handle.result()
    return {"workflow_id": workflow_id, "result": result}

@router.post("/signal/{workflow_id}")
async def signal_workflow(request: Request, workflow_id: str, value: str):
    client = request.app.state.temporal_client
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(AgentWorkflow.receive_input, value)
    return {"status": "signal_sent"}
```

### workflows/agent.py (template)
```python
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.llm import ModelRequest

RETRY = RetryPolicy(maximum_attempts=3)

@workflow.defn
class AgentWorkflow:
    def __init__(self):
        self._status = "started"

    @workflow.run
    async def run(self, prompt: str) -> str:
        self._status = "processing"
        messages = [{"role": "user", "content": [{"text": prompt}]}]

        resp = await workflow.execute_activity(
            "call_model",
            arg=ModelRequest(messages=messages, tools=[]),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RETRY,
        )

        self._status = "completed"
        return "".join(b["text"] for b in resp["message"]["content"] if "text" in b)

    @workflow.query
    def get_status(self) -> str:
        return self._status
```

### activities/llm.py (template)
```python
import boto3
from botocore.config import Config
from dataclasses import dataclass
from collections.abc import Sequence
from temporalio import activity
from temporalio.common import RawValue

from app.config import settings

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=settings.aws_region,
    config=Config(retries={"max_attempts": 0}),
)

@dataclass
class ModelRequest:
    messages: list
    tools: list

@activity.defn
def call_model(request: ModelRequest) -> dict:
    kwargs = {
        "modelId": settings.bedrock_model_id,
        "messages": request.messages,
    }
    if request.tools:
        kwargs["toolConfig"] = {"tools": request.tools}
    resp = bedrock.converse(**kwargs)
    return {"message": resp["output"]["message"], "stop_reason": resp["stopReason"]}

@activity.defn(dynamic=True)
def tool_activity(args: Sequence[RawValue]) -> str:
    tool_name = activity.info().activity_type
    tool_args = activity.payload_converter().from_payload(args[0].payload, dict)
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        raise ValueError(f"Unknown tool: {tool_name}")
    return handler(tool_args)
```

### helpers/tool_helpers.py
```python
from pydantic import BaseModel
from typing import Any

def claude_tool_from_model(
    name: str, description: str, model: type[BaseModel] | None
) -> dict[str, Any]:
    if model is None:
        return {
            "name": name, "description": description,
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
    return {"name": name, "description": description, "input_schema": model.model_json_schema()}

def bedrock_tool_from_model(
    name: str, description: str, model: type[BaseModel] | None
) -> dict[str, Any]:
    if model is None:
        return {"toolSpec": {
            "name": name, "description": description,
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }}
    schema = model.model_json_schema()
    return {"toolSpec": {
        "name": name, "description": description,
        "inputSchema": {"json": schema},
    }}
```

### worker.py (standalone, for 3-terminal demo)
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter

from workflows.agent import AgentWorkflow
from activities.llm import call_model, tool_activity

TASK_QUEUE = "demo-queue"

async def main():
    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AgentWorkflow],
        activities=[call_model, tool_activity],
        activity_executor=ThreadPoolExecutor(max_workers=5),
    )
    print(f"Worker listening on '{TASK_QUEUE}'. Ctrl+C to kill (workflow survives!).")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

### start.py (CLI workflow starter)
```python
import asyncio, uuid
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from workflows.agent import AgentWorkflow

TASK_QUEUE = "demo-queue"

async def main():
    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)

    print("Connected. Type 'quit' to exit.\n")
    while True:
        prompt = input("You: ").strip()
        if not prompt or prompt.lower() in ("quit", "exit"):
            break
        result = await client.execute_workflow(
            AgentWorkflow.run,
            arg=prompt,
            id=f"demo-{uuid.uuid4().hex[:8]}",
            task_queue=TASK_QUEUE,
        )
        print(f"\nAgent: {result}\n")

if __name__ == "__main__":
    asyncio.run(main())
```

### run.py (single entry for API + worker)
```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
```

### .env.example
```env
APP_TEMPORAL_HOST=localhost:7233
APP_TASK_QUEUE=demo-queue
APP_AWS_REGION=us-east-1
APP_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
```

### .gitignore
```
__pycache__/
*.pyc
.env
.venv/
*.egg-info/
dist/
.ruff_cache/
```

## Quick Start
```bash
# 1. Start Temporal dev server
temporal server start-dev

# 2. Install
pip install -e ".[dev]"

# 3. Setup env
cp .env.example .env

# 4a. Run API + embedded worker (single process)
python run.py
# Open: http://localhost:8000/docs (Swagger) + http://localhost:8233 (Temporal UI)

# 4b. OR run 3-terminal demo (shows durability)
# Terminal 2: python worker.py
# Terminal 3: python start.py
```
