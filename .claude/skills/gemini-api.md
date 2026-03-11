# Google Gemini API Patterns — For Temporal + AI Demos

> SDK: `google-genai` (NOT the deprecated `google-generativeai`)

## 1. Installation

```bash
pip install "google-genai>=1.0.0"
```

## 2. Client Setup

```python
from google import genai

# Simple API key auth — no cloud project or IAM needed
client = genai.Client(api_key="GEMINI_API_KEY")
```

## 3. Model IDs (as of March 2026)

```python
# GA (stable) — use for production/demos
MODELS_GA = {
    "flash":      "gemini-2.5-flash",       # DEFAULT: fast + cheap + stable
    "flash-lite": "gemini-2.5-flash-lite",   # Cheapest, still fast
    "pro":        "gemini-2.5-pro",          # Highest quality, expensive
}

# Preview (newer, may break) — opt-in via config
MODELS_PREVIEW = {
    "flash":      "gemini-3-flash-preview",         # Better reasoning, dynamic thinking
    "flash-lite": "gemini-3.1-flash-lite-preview",   # Cheapest next-gen
    "pro":        "gemini-3.1-pro-preview",          # Best quality
}

DEFAULT_MODEL = "gemini-2.5-flash"  # Config-switchable via GEMINI_MODEL env var
```

## 4. Pricing (per 1M tokens)

| Model | Input | Output | Status |
|---|---|---|---|
| Gemini 2.5 Flash-Lite | $0.10 | $0.40 | GA |
| **Gemini 2.5 Flash** | **$0.30** | **$2.50** | **GA (default)** |
| Gemini 2.5 Pro | $1.25 | $10.00 | GA |
| Gemini 3 Flash | $0.50 | $3.00 | Preview |
| Gemini 3.1 Flash-Lite | $0.25 | $1.50 | Preview |

Free tier: ~10 RPM, ~500 RPD for Flash. Sufficient for dev/demos.
Gemini 3 Flash also has a free tier.

## 5. Basic Call

```python
from google import genai

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Summarize this text...",
)
print(response.text)
```

## 6. Structured JSON Output (Pydantic — KILLER FEATURE)

```python
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

class VideoRecommendation(BaseModel):
    title: str = Field(description="Video title")
    score: int = Field(description="Relevance score 0-100")
    why: str = Field(description="Why this is relevant")

class AnalysisResult(BaseModel):
    summary: str
    recommendations: list[VideoRecommendation]

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Rank these videos...",
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=AnalysisResult,
        temperature=0.3,
    ),
)

# Already parsed into your Pydantic model!
result: AnalysisResult = response.parsed
```

## 7. With System Instruction

```python
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="User prompt here",
    config=types.GenerateContentConfig(
        system_instruction="You are a video recommendation engine.",
        response_mime_type="application/json",
        response_schema=AnalysisResult,
        temperature=0.3,
        max_output_tokens=4096,
    ),
)
```

## 8. As Temporal Activity (async — no ThreadPoolExecutor needed!)

```python
import os
from temporalio import activity
from google import genai
from google.genai import types

@activity.defn
async def analyze_videos(request: AnalyzeRequest) -> AnalyzeResult:
    """Async activity — google-genai supports async natively."""
    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=55_000),  # Under activity timeout
    )
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=request.prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=AnalyzeResult,
            temperature=0.3,
        ),
    )
    return response.parsed
```

**Key**: Since google-genai is async-compatible, the activity can be `async def`.
No `ThreadPoolExecutor` needed in the Worker — simpler setup than boto3.

## 9. Worker Setup (simpler than Bedrock — no executor needed for async activities)

```python
worker = Worker(
    client,
    task_queue="my-queue",
    workflows=[MyWorkflow],
    activities=[analyze_videos],
    # No activity_executor needed! Activities are async.
)
```

If you also have sync activities, you still need:
```python
activity_executor=ThreadPoolExecutor(max_workers=5)
```

## 10. Disable Client Retries (let Temporal handle)

```python
# google-genai doesn't have built-in retries like boto3.
# But set a timeout to avoid hanging:
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(
        timeout=55_000,  # 55s — under the 60s activity timeout
    ),
)
```

## 11. Error Handling

```python
from google.genai import errors

try:
    response = client.models.generate_content(...)
except errors.ClientError as e:
    # 4xx — bad request, don't retry
    raise
except errors.ServerError as e:
    # 5xx — let Temporal retry via activity retry policy
    raise
```

## Key Rules
1. **SDK**: Use `google-genai`, NOT `google-generativeai` (deprecated Aug 2025)
2. **Structured output**: Use `response_mime_type="application/json"` + `response_schema=PydanticModel`
3. **Parsed result**: Access `response.parsed` for typed Pydantic object
4. **Async activities**: `google-genai` is async-compatible — no ThreadPoolExecutor needed
5. **Timeouts**: Set `HttpOptions(timeout=55_000)` under activity timeout
6. **Temperature**: Use 0.3 or lower for structured/deterministic output
7. **Default model**: `gemini-2.5-flash` (GA) — config-switchable to `gemini-3-flash-preview` via env var
8. **Free tier**: ~10 RPM, 500 RPD — enough for dev and demos
9. **Gemini 3 thinking**: Uses `thinking_level` (minimal/low/medium/high), NOT legacy `thinking_budget`
