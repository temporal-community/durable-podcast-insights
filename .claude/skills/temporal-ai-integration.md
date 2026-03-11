# Temporal + AI Integration Patterns - From Production Code

> Source: Bedrock workshop module_3_temporal + AI cookbook agents (6 real patterns)

## Why Temporal for AI?
- **Durability**: LLM calls fail. Kill the worker mid-workflow, restart, it resumes.
- **Observability**: Every LLM call, every tool invocation visible in Temporal UI.
- **Retry**: Automatic retry with backoff for transient LLM failures.
- **Human-in-the-loop**: Workflow waits (hours/days) for approval without consuming compute.
- **Audit trail**: Full event history of every AI decision.

---

## Pattern 1: Bedrock Agentic Loop (REAL code from workshop)

The canonical pattern: LLM decides → tools execute → results feed back.

### workflow.py
```python
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities import ModelRequest

TOOLS = [
    {"toolSpec": {
        "name": "get_time",
        "description": "Get the current date and time.",
        "inputSchema": {"json": {"type": "object", "properties": {}}},
    }},
    {"toolSpec": {
        "name": "http_request",
        "description": "Fetch a URL and return the response body.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
            },
            "required": ["url"],
        }},
    }},
]

RETRY = RetryPolicy(maximum_attempts=3)

@workflow.defn
class AgentWorkflow:
    @workflow.run
    async def run(self, prompt: str) -> str:
        messages = [{"role": "user", "content": [{"text": prompt}]}]

        while True:
            resp = await workflow.execute_activity(
                "call_model",
                arg=ModelRequest(messages=messages, tools=TOOLS),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RETRY,
            )
            msg = resp["message"]
            messages.append(msg)

            if resp["stop_reason"] != "tool_use":
                return "".join(b["text"] for b in msg["content"] if "text" in b)

            tool_results = []
            for block in msg["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    result = await workflow.execute_activity(
                        tu["name"],
                        arg=tu["input"],
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RETRY,
                    )
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tu["toolUseId"],
                            "content": [{"text": result}],
                        }
                    })
            messages.append({"role": "user", "content": tool_results})
```

### activities.py
```python
import boto3
from botocore.config import Config
from dataclasses import dataclass
from collections.abc import Sequence
from temporalio import activity
from temporalio.common import RawValue

bedrock = boto3.client(
    "bedrock-runtime", region_name="us-east-1",
    config=Config(retries={"max_attempts": 0}),
)

@dataclass
class ModelRequest:
    messages: list
    tools: list

@activity.defn
def call_model(request: ModelRequest) -> dict:
    resp = bedrock.converse(
        modelId="us.anthropic.claude-sonnet-4-6",
        messages=request.messages,
        toolConfig={"tools": request.tools},
    )
    return {"message": resp["output"]["message"], "stop_reason": resp["stopReason"]}

TOOL_HANDLERS = {
    "http_request": lambda args: _http_request(args),
    "get_time": lambda args: _get_time(args),
}

@activity.defn(dynamic=True)
def tool_activity(args: Sequence[RawValue]) -> str:
    tool_name = activity.info().activity_type
    tool_args = activity.payload_converter().from_payload(args[0].payload, dict)
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        raise ValueError(f"Unknown tool: {tool_name}")
    return handler(tool_args)
```

### worker.py
```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter

async def main():
    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)
    worker = Worker(
        client,
        task_queue="demo-task-queue",
        workflows=[AgentWorkflow],
        activities=[call_model, tool_activity],
        activity_executor=ThreadPoolExecutor(max_workers=5),
    )
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Pattern 2: Claude Direct Agentic Loop (REAL code from cookbook)

Using Anthropic SDK directly instead of Bedrock.

### activities/claude_responses.py
```python
from temporalio import activity
from anthropic import AsyncAnthropic
from anthropic.types import Message
from dataclasses import dataclass
from typing import Any

@dataclass
class ClaudeResponsesRequest:
    model: str
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    max_tokens: int = 4096

@activity.defn
async def create(request: ClaudeResponsesRequest) -> Message:
    client = AsyncAnthropic(max_retries=0)
    try:
        return await client.messages.create(
            model=request.model, system=request.system,
            messages=request.messages, tools=request.tools,
            max_tokens=request.max_tokens,
        )
    finally:
        await client.close()
```

### activities/tool_invoker.py
```python
from temporalio import activity
from temporalio.common import RawValue
from collections.abc import Sequence
import inspect
from pydantic import BaseModel

@activity.defn(dynamic=True)
async def dynamic_tool_activity(args: Sequence[RawValue]) -> dict:
    from tools import get_handler
    tool_name = activity.info().activity_type
    tool_args = activity.payload_converter().from_payload(args[0].payload, dict)

    handler = get_handler(tool_name)
    sig = inspect.signature(handler)
    params = list(sig.parameters.values())

    if len(params) == 0:
        call_args = []
    else:
        ann = params[0].annotation
        if isinstance(tool_args, dict) and isinstance(ann, type) and issubclass(ann, BaseModel):
            call_args = [ann(**tool_args)]
        else:
            call_args = [tool_args]

    return await handler(*call_args)
```

### tools/__init__.py
```python
from typing import Any, Awaitable, Callable
from .get_weather import get_weather_alerts, WEATHER_TOOL
from .get_location import get_location_info, get_ip_address, LOCATION_TOOL, IP_TOOL

ToolHandler = Callable[..., Awaitable[Any]]

def get_handler(tool_name: str) -> ToolHandler:
    handlers = {
        "get_weather_alerts": get_weather_alerts,
        "get_location_info": get_location_info,
        "get_ip_address": get_ip_address,
    }
    handler = handlers.get(tool_name)
    if not handler:
        raise ValueError(f"Unknown tool: {tool_name}")
    return handler

def get_tools() -> list[dict[str, Any]]:
    return [WEATHER_TOOL, LOCATION_TOOL, IP_TOOL]
```

### tools/get_weather.py (with Pydantic → Claude schema)
```python
import httpx, json
from pydantic import BaseModel, Field
from typing import Any
from helpers.tool_helpers import claude_tool_from_model

class GetWeatherRequest(BaseModel):
    state: str = Field(description="Two-letter US state code (e.g. CA, NY)")

WEATHER_TOOL = claude_tool_from_model(
    "get_weather_alerts", "Get weather alerts for a US state.", GetWeatherRequest
)

async def get_weather_alerts(req: GetWeatherRequest) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.weather.gov/alerts/active/area/{req.state}",
            headers={"User-Agent": "weather-app/1.0"},
            timeout=5.0,
        )
        resp.raise_for_status()
        return json.dumps(resp.json())
```

---

## Pattern 3: Human-in-the-Loop (REAL code from cookbook)

### models.py
```python
from pydantic import BaseModel

class WorkflowInput(BaseModel):
    user_request: str
    approval_timeout_seconds: int = 300

class ProposedAction(BaseModel):
    action_type: str
    description: str
    reasoning: str
    risky_action: bool

class ApprovalRequest(BaseModel):
    request_id: str
    proposed_action: ProposedAction
    context: str
    requested_at: str

class ApprovalDecision(BaseModel):
    request_id: str
    approved: bool
    reviewer_notes: str | None = None
    decided_at: str
```

### workflow.py
```python
from temporalio import workflow
from datetime import timedelta
from typing import Optional
import asyncio

with workflow.unsafe.imports_passed_through():
    from models import WorkflowInput, ProposedAction, ApprovalRequest, ApprovalDecision
    from activities import openai_responses, execute_action, notify_approval_needed

@workflow.defn
class HumanInTheLoopWorkflow:
    def __init__(self):
        self.current_decision: Optional[ApprovalDecision] = None
        self.pending_request_id: Optional[str] = None

    @workflow.run
    async def run(self, input: WorkflowInput) -> str:
        # Step 1: AI analyzes and proposes action
        proposed_action = await self._analyze_and_propose_action(input.user_request)

        # Step 2: If risky, require human approval
        if proposed_action.risky_action:
            self.current_decision = None
            self.pending_request_id = str(workflow.uuid4())

            # Notify human
            await workflow.execute_activity(
                notify_approval_needed.notify,
                ApprovalRequest(
                    request_id=self.pending_request_id,
                    proposed_action=proposed_action,
                    context=input.user_request,
                    requested_at=workflow.now().isoformat(),
                ),
                start_to_close_timeout=timedelta(seconds=10),
            )

            # Wait for signal (can wait hours/days!)
            try:
                await workflow.wait_condition(
                    lambda: self.current_decision is not None,
                    timeout=timedelta(seconds=input.approval_timeout_seconds),
                )
                if self.current_decision.approved:
                    return await self._execute(proposed_action)
                return f"Rejected: {self.current_decision.reviewer_notes}"
            except asyncio.TimeoutError:
                return "Timed out waiting for approval"
        else:
            # Auto-approve safe actions
            return await self._execute(proposed_action)

    @workflow.signal
    async def approval_decision(self, decision: ApprovalDecision):
        if decision.request_id == self.pending_request_id:
            self.current_decision = decision
        else:
            workflow.logger.warning(f"Wrong request_id: {decision.request_id}")

    async def _analyze_and_propose_action(self, request: str) -> ProposedAction:
        result = await workflow.execute_activity(
            openai_responses.create,
            openai_responses.Request(model="gpt-4o-mini", input=request),
            start_to_close_timeout=timedelta(seconds=30),
        )
        return ProposedAction.model_validate_json(result)

    async def _execute(self, action: ProposedAction) -> str:
        return await workflow.execute_activity(
            execute_action.execute,
            action,
            start_to_close_timeout=timedelta(seconds=60),
        )
```

### send_approval.py (external signal sender)
```python
import asyncio, sys
from datetime import datetime, timezone
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

async def main():
    workflow_id = sys.argv[1]
    request_id = sys.argv[2]
    approved = sys.argv[3].lower() == "approve"
    notes = sys.argv[4] if len(sys.argv) > 4 else None

    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("approval_decision", ApprovalDecision(
        request_id=request_id, approved=approved,
        reviewer_notes=notes, decided_at=datetime.now(timezone.utc).isoformat(),
    ))

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Pattern 4: Fan-Out Parallel AI

```python
@workflow.defn
class ParallelAnalysisWorkflow:
    @workflow.run
    async def run(self, text: str, perspectives: list[str]) -> dict:
        import asyncio

        # Launch all analyses in parallel
        tasks = {
            p: workflow.execute_activity(
                "call_model",
                arg=ModelRequest(
                    messages=[{"role": "user", "content": [{"text": f"Analyze from {p} perspective: {text}"}]}],
                    tools=[],
                ),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RETRY,
            )
            for p in perspectives
        }

        results = {}
        for perspective, task in tasks.items():
            resp = await task
            results[perspective] = "".join(
                b["text"] for b in resp["message"]["content"] if "text" in b
            )
        return results
```

---

## Pattern 5: Multi-Step Pipeline

```python
@workflow.defn
class PipelineWorkflow:
    def __init__(self):
        self._status = "started"

    @workflow.run
    async def run(self, text: str) -> dict:
        # Step 1: Classify
        self._status = "classifying"
        classify_resp = await workflow.execute_activity(
            "call_model",
            arg=ModelRequest(
                messages=[{"role": "user", "content": [{"text": f"Classify: {text}"}]}],
                tools=[],
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY,
        )

        # Step 2: Process
        self._status = "processing"
        process_resp = await workflow.execute_activity(
            "call_model",
            arg=ModelRequest(
                messages=[{"role": "user", "content": [{"text": f"Process: {text}"}]}],
                tools=[],
            ),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RETRY,
        )

        self._status = "completed"
        return {"classification": classify_resp, "result": process_resp}

    @workflow.query
    def get_status(self) -> str:
        return self._status
```

---

## Pattern 6: Entity Workflow (Stateful Conversation)

```python
@workflow.defn
class ConversationWorkflow:
    def __init__(self):
        self._messages = []
        self._pending_input: str | None = None
        self._done = False

    @workflow.run
    async def run(self, system_prompt: str) -> list:
        while not self._done:
            await workflow.wait_condition(
                lambda: self._pending_input is not None or self._done
            )
            if self._done:
                break

            user_input = self._pending_input
            self._pending_input = None
            self._messages.append({"role": "user", "content": [{"text": user_input}]})

            resp = await workflow.execute_activity(
                "call_model",
                arg=ModelRequest(messages=self._messages, tools=[]),
                start_to_close_timeout=timedelta(seconds=60),
            )
            self._messages.append(resp["message"])

        return self._messages

    @workflow.signal
    async def send_message(self, message: str):
        self._pending_input = message

    @workflow.signal
    async def end_conversation(self):
        self._done = True

    @workflow.query
    def get_history(self) -> list:
        return self._messages
```

---

## FastAPI + Temporal + Bedrock Integration (run.py)

```python
import asyncio, uvicorn
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter
from concurrent.futures import ThreadPoolExecutor

async def main():
    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)
    app.state.temporal_client = client

    worker = Worker(
        client,
        task_queue="demo-queue",
        workflows=[AgentWorkflow],
        activities=[call_model, tool_activity],
        activity_executor=ThreadPoolExecutor(max_workers=5),
    )

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(worker.run(), server.serve())

if __name__ == "__main__":
    asyncio.run(main())
```

## Architecture (3 processes for demo)
```
Terminal 1: temporal server start-dev     # Temporal server + UI (:8233)
Terminal 2: python worker.py              # Worker polls tasks
Terminal 3: python start.py               # Client sends workflows
```

**Durability demo**: Kill Terminal 2 mid-workflow → restart → workflow resumes!
