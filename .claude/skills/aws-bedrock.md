# AWS Bedrock Patterns - From Production Code

> Source: Bedrock workshop module_3_temporal + AI cookbook agents

## 1. Client Setup (CRITICAL: disable retries)

```python
import boto3
from botocore.config import Config

# CRITICAL: Disable boto3 retries — Temporal handles retries durably
bedrock = boto3.client(
    "bedrock-runtime",
    region_name="us-east-1",
    config=Config(retries={"max_attempts": 0}),
)
```

## 2. Model IDs

```python
# Cross-region inference (preferred - higher availability)
MODELS_CROSS_REGION = {
    "claude-sonnet-4":   "us.anthropic.claude-sonnet-4-6",
    "claude-3.5-sonnet": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    "claude-3.5-haiku":  "us.anthropic.claude-3-5-haiku-20241022-v1:0",
}

# Direct model IDs
MODELS_DIRECT = {
    "claude-3.5-sonnet-v2": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "claude-3.5-haiku":     "anthropic.claude-3-5-haiku-20241022-v1:0",
    "claude-3-opus":        "anthropic.claude-3-opus-20240229-v1:0",
    "claude-3-haiku":       "anthropic.claude-3-haiku-20240307-v1:0",
}

# Default for demos
DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"
```

## 3. Converse API - Basic Call

```python
def chat(prompt: str, system: str = "") -> dict:
    kwargs = {
        "modelId": DEFAULT_MODEL,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
    }
    if system:
        kwargs["system"] = [{"text": system}]

    resp = bedrock.converse(**kwargs)
    return {
        "message": resp["output"]["message"],
        "stop_reason": resp["stopReason"],
    }
```

## 4. Converse API with Tools (REAL pattern from workshop)

```python
from dataclasses import dataclass

@dataclass
class ModelRequest:
    messages: list
    tools: list

def call_model(request: ModelRequest) -> dict:
    """Call Bedrock converse API with tool definitions."""
    resp = bedrock.converse(
        modelId=DEFAULT_MODEL,
        messages=request.messages,
        toolConfig={"tools": request.tools},
    )
    return {"message": resp["output"]["message"], "stop_reason": resp["stopReason"]}
```

## 5. Tool Definition Format (Bedrock)

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

## 6. Tool Use Response Handling (Bedrock)

```python
# Response flow:
# 1. Bedrock returns stop_reason="tool_use" when it wants to call tools
# 2. Parse toolUse blocks from message content
# 3. Execute tools, return toolResult blocks
# 4. Loop back with updated messages

# Parsing tool calls from Bedrock response
for block in msg["content"]:
    if "toolUse" in block:
        tu = block["toolUse"]
        tool_name = tu["name"]
        tool_input = tu["input"]
        tool_use_id = tu["toolUseId"]

# Sending tool results back
tool_results = [{
    "toolResult": {
        "toolUseId": tu["toolUseId"],
        "content": [{"text": result_string}],
    }
}]
messages.append({"role": "user", "content": tool_results})
```

## 7. Anthropic Direct (Alternative to Bedrock)

```python
from anthropic import AsyncAnthropic
from anthropic.types import Message

# CRITICAL: Disable retries - let Temporal handle
client = AsyncAnthropic(max_retries=0)

try:
    resp = await client.messages.create(
        model="claude-sonnet-4-20250514",
        system="You are a helpful agent.",
        messages=[{"role": "user", "content": "Hello"}],
        tools=tools_list,  # Claude format, not Bedrock format
        max_tokens=4096,
    )
    # Response: resp.content = list of TextBlock / ToolUseBlock
    # resp.content[i].type == "text" or "tool_use"
    # resp.content[i].text (for text)
    # resp.content[i].name, .id, .input (for tool_use)
finally:
    await client.close()
```

## 8. Claude Tool Format (different from Bedrock!)

```python
# Claude (Anthropic direct) uses this format:
claude_tools = [
    {
        "name": "get_weather_alerts",
        "description": "Get weather alerts for a US state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "Two-letter US state code"}
            },
            "required": ["state"],
        },
    }
]

# Bedrock uses this format (wrapped in toolSpec):
bedrock_tools = [
    {"toolSpec": {
        "name": "get_weather_alerts",
        "description": "Get weather alerts for a US state.",
        "inputSchema": {"json": {  # Note: inputSchema.json (not input_schema)
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "Two-letter US state code"}
            },
            "required": ["state"],
        }},
    }}
]
```

## 9. Pydantic → Claude Tool Schema Helper

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

# Define tool input with Pydantic
class GetWeatherRequest(BaseModel):
    state: str = Field(description="Two-letter US state code (e.g. CA, NY)")

WEATHER_TOOL = claude_tool_from_model(
    "get_weather_alerts", "Get weather alerts for a US state.", GetWeatherRequest
)
```

## 10. Streaming (ConverseStream)

```python
def chat_stream(prompt: str, system: str = ""):
    kwargs = {
        "modelId": DEFAULT_MODEL,
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"temperature": 0.7, "maxTokens": 1024},
    }
    if system:
        kwargs["system"] = [{"text": system}]

    response = bedrock.converse_stream(**kwargs)

    for event in response["stream"]:
        if "contentBlockDelta" in event:
            yield event["contentBlockDelta"]["delta"]["text"]
        if "messageStop" in event:
            break
```

## 11. As Temporal Activity (sync, for Bedrock)

```python
from temporalio import activity

@activity.defn
def call_model(request: ModelRequest) -> dict:
    """Sync activity — Worker must have ThreadPoolExecutor."""
    resp = bedrock.converse(
        modelId=DEFAULT_MODEL,
        messages=request.messages,
        toolConfig={"tools": request.tools},
    )
    return {"message": resp["output"]["message"], "stop_reason": resp["stopReason"]}
```

## 12. As Temporal Activity (async, for Anthropic direct)

```python
from temporalio import activity
from anthropic import AsyncAnthropic

@activity.defn
async def create(request: ClaudeResponsesRequest) -> Message:
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

## IAM Policy Required
```json
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        "Resource": "arn:aws:bedrock:*::foundation-model/*"
    }]
}
```

## Key Rules (from REAL code)
1. **ALWAYS disable client retries** - `Config(retries={"max_attempts": 0})` — Temporal handles retries
2. **Bedrock vs Claude format** - `toolSpec.inputSchema.json` vs `input_schema` — different!
3. **Cross-region model IDs** - Prefix with `us.` for higher availability
4. **Sync activities** for boto3, **async activities** for Anthropic SDK
5. **Tool loop**: check `stop_reason == "tool_use"`, execute tools, append results, loop
6. **Message format**: `{"role": "user", "content": [{"text": "..."}]}` for Bedrock
7. **Tool results**: `{"toolResult": {"toolUseId": "...", "content": [{"text": "..."}]}}` for Bedrock
8. **Haiku for fast tasks**, Sonnet for quality — route based on task complexity
