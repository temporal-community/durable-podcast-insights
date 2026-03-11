# Temporal Python SDK - Patterns from Production Code

> Source: Bedrock workshop module_3_temporal + AI cookbook agents

## Installation
```bash
pip install "temporalio>=1.19.0" "protobuf>=5.29.3,<6.0.0"
```

## 1. Client Connection (Self-Hosted)

```python
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

# Always use pydantic_data_converter for proper serialization
client = await Client.connect(
    "localhost:7233",
    data_converter=pydantic_data_converter,
)
```

## 2. Workflow Definition (Agentic Loop - REAL pattern)

```python
"""Workflow file - agentic loop with LLM + tool calls as separate activities."""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

# CRITICAL: Use unsafe.imports_passed_through for non-Temporal imports
with workflow.unsafe.imports_passed_through():
    from activities import ModelRequest

RETRY = RetryPolicy(maximum_attempts=3)

@workflow.defn
class AgentWorkflow:
    @workflow.run
    async def run(self, prompt: str) -> str:
        messages = [{"role": "user", "content": [{"text": prompt}]}]

        while True:
            # 1. Call LLM (named activity)
            resp = await workflow.execute_activity(
                "call_model",
                arg=ModelRequest(messages=messages, tools=TOOLS),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RETRY,
            )
            msg = resp["message"]
            messages.append(msg)

            # 2. If no tool use, return text
            if resp["stop_reason"] != "tool_use":
                return "".join(b["text"] for b in msg["content"] if "text" in b)

            # 3. Execute each tool as dynamic activity (visible in Temporal UI!)
            tool_results = []
            for block in msg["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    result = await workflow.execute_activity(
                        tu["name"],  # Dynamic: activity type = tool name
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

## 3. Workflow with Claude (Anthropic Direct)

```python
from temporalio import workflow
from datetime import timedelta

with workflow.unsafe.imports_passed_through():
    from tools import get_tools
    from activities import claude_responses

@workflow.defn
class AgentWorkflow:
    @workflow.run
    async def run(self, input: str) -> str:
        messages = [{"role": "user", "content": input}]

        while True:
            result = await workflow.execute_activity(
                claude_responses.create,
                claude_responses.ClaudeResponsesRequest(
                    model="claude-sonnet-4-20250514",
                    system="You are a helpful agent.",
                    messages=messages,
                    tools=get_tools(),
                    max_tokens=4096,
                ),
                start_to_close_timeout=timedelta(seconds=30),
            )

            tool_use_blocks = [b for b in result.content if b.type == "tool_use"]

            if tool_use_blocks:
                # Serialize assistant response for message history
                assistant_content = []
                for block in result.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use", "id": block.id,
                            "name": block.name, "input": block.input,
                        })
                messages.append({"role": "assistant", "content": assistant_content})

                # Execute tools via dynamic activities
                tool_results = []
                for block in tool_use_blocks:
                    tool_result = await workflow.execute_activity(
                        block.name, block.input,
                        start_to_close_timeout=timedelta(seconds=30),
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(tool_result),
                    })
                messages.append({"role": "user", "content": tool_results})
            else:
                text_blocks = [b for b in result.content if b.type == "text"]
                return text_blocks[0].text if text_blocks else "No response"
```

## 4. Activity Definition - Bedrock (Sync)

```python
import boto3
from botocore.config import Config
from dataclasses import dataclass
from temporalio import activity

# Disable boto3 retries — Temporal handles retries
bedrock = boto3.client(
    "bedrock-runtime",
    region_name="us-east-1",
    config=Config(retries={"max_attempts": 0}),
)

@dataclass
class ModelRequest:
    messages: list
    tools: list

@activity.defn
def call_model(request: ModelRequest) -> dict:
    """Sync activity - boto3 is synchronous. Worker needs ThreadPoolExecutor."""
    resp = bedrock.converse(
        modelId="us.anthropic.claude-sonnet-4-6",
        messages=request.messages,
        toolConfig={"tools": request.tools},
    )
    return {"message": resp["output"]["message"], "stop_reason": resp["stopReason"]}
```

## 5. Activity Definition - Anthropic Direct (Async)

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
    # Disable retries - let Temporal handle
    client = AsyncAnthropic(max_retries=0)
    try:
        return await client.messages.create(
            model=request.model,
            system=request.system,
            messages=request.messages,
            tools=request.tools,
            max_tokens=request.max_tokens,
        )
    finally:
        await client.close()
```

## 6. Dynamic Tool Activity (each tool = separate activity type in UI)

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
    activity.logger.info(f"Running dynamic tool '{tool_name}' with args: {tool_args}")

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

    result = await handler(*call_args)
    return result
```

## 7. Sync Dynamic Activity (simpler, for Bedrock)

```python
from temporalio import activity
from temporalio.common import RawValue
from collections.abc import Sequence

TOOL_HANDLERS = {
    "http_request": lambda args: _http_request(args),
    "get_time":     lambda args: _mcp_tool("get_time", args),
}

@activity.defn(dynamic=True)
def tool_activity(args: Sequence[RawValue]) -> str:
    """Dynamic activity — tool name is the activity type, visible in Temporal UI."""
    tool_name = activity.info().activity_type
    tool_args = activity.payload_converter().from_payload(args[0].payload, dict)
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        raise ValueError(f"Unknown tool: {tool_name}")
    return handler(tool_args)
```

## 8. Worker Setup

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter

TASK_QUEUE = "demo-task-queue"

async def main():
    client = await Client.connect(
        "localhost:7233",
        data_converter=pydantic_data_converter,
    )
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[AgentWorkflow],
        activities=[call_model, tool_activity],
        activity_executor=ThreadPoolExecutor(max_workers=5),  # For sync activities
    )
    print(f"Worker listening on '{TASK_QUEUE}'. Ctrl+C to kill (workflow survives!).")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
```

## 9. Workflow Starter (CLI)

```python
import asyncio, uuid
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

TASK_QUEUE = "demo-task-queue"

async def main():
    client = await Client.connect("localhost:7233", data_converter=pydantic_data_converter)

    result = await client.execute_workflow(
        AgentWorkflow.run,
        arg="What is the weather in CA?",
        id=f"agent-{uuid.uuid4().hex[:8]}",
        task_queue=TASK_QUEUE,
    )
    print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

## 10. Signals (Human-in-the-Loop)

```python
from temporalio import workflow
from typing import Optional
import asyncio

with workflow.unsafe.imports_passed_through():
    from models import ApprovalDecision

@workflow.defn
class HumanInTheLoopWorkflow:
    def __init__(self):
        self.current_decision: Optional[ApprovalDecision] = None
        self.pending_request_id: Optional[str] = None

    @workflow.run
    async def run(self, input: WorkflowInput) -> str:
        # ... AI proposes action ...

        # Wait for human approval
        self.pending_request_id = str(workflow.uuid4())
        try:
            await workflow.wait_condition(
                lambda: self.current_decision is not None,
                timeout=timedelta(seconds=input.approval_timeout_seconds),
            )
            return "approved" if self.current_decision.approved else "rejected"
        except asyncio.TimeoutError:
            return "timeout"

    @workflow.signal
    async def approval_decision(self, decision: ApprovalDecision):
        """Validate request_id to prevent race conditions."""
        if decision.request_id == self.pending_request_id:
            self.current_decision = decision
        else:
            workflow.logger.warning(f"Wrong request ID: {decision.request_id}")
```

### Sending Signal from External Process

```python
handle = client.get_workflow_handle(workflow_id)
await handle.signal("approval_decision", approval_decision_obj)
```

## 11. Queries

```python
@workflow.defn
class MyWorkflow:
    def __init__(self):
        self._status = "started"

    @workflow.query
    def get_status(self) -> str:
        return self._status

# Client-side
handle = client.get_workflow_handle("wf-id")
status = await handle.query(MyWorkflow.get_status)
```

## 12. Tool Definition Helpers (Pydantic → Claude schema)

```python
from pydantic import BaseModel, Field
from typing import Any

def claude_tool_from_model(
    name: str, description: str, model: type[BaseModel] | None
) -> dict[str, Any]:
    """Convert Pydantic model to Claude's tool format."""
    if model is None:
        return {
            "name": name, "description": description,
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
    return {
        "name": name, "description": description,
        "input_schema": model.model_json_schema(),
    }

# Usage
class GetWeatherRequest(BaseModel):
    state: str = Field(description="Two-letter US state code (e.g. CA, NY)")

WEATHER_TOOL = claude_tool_from_model(
    "get_weather_alerts", "Get weather alerts for a US state.", GetWeatherRequest
)
```

## 13. Tool Definition (Bedrock format)

```python
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
                "method": {"type": "string", "description": "HTTP method (default GET)"},
            },
            "required": ["url"],
        }},
    }},
]
```

## Key Rules (from REAL code)
1. **`pydantic_data_converter`** - ALWAYS use on Client.connect for Pydantic/dataclass serialization
2. **`workflow.unsafe.imports_passed_through()`** - ALWAYS wrap non-Temporal imports in workflow files
3. **`ThreadPoolExecutor`** - REQUIRED in Worker when using sync `@activity.defn` (like boto3)
4. **Disable client retries** - `Config(retries={"max_attempts": 0})` for boto3, `max_retries=0` for Anthropic
5. **`workflow.uuid4()`** - Use for deterministic UUIDs inside workflows, NOT `uuid.uuid4()`
6. **`workflow.now()`** - Use for current time inside workflows, NOT `datetime.now()`
7. **`activity.info().activity_type`** - Gets dynamic activity name inside `@activity.defn(dynamic=True)`
8. **`activity.payload_converter().from_payload()`** - Deserialize dynamic activity args
9. **Task queue names must match** between worker and starter
10. **Activity timeouts**: 60s for LLM calls, 30s for tool calls, 10s for notifications
