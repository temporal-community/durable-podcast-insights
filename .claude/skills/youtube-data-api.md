# YouTube Data API v3 — Patterns for Temporal Activities

## 1. Setup

### API Key
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable **YouTube Data API v3** in APIs & Services
3. Create credentials → API Key
4. (Optional) Restrict key to YouTube Data API v3 only
5. Set env var: `YOUTUBE_API_KEY=AIza...`

### Python SDK Choice
Use **raw httpx** (async, zero extra deps, already in stack). Do NOT use:
- `google-api-python-client` — sync only, no async support
- `youtubeaio` — sparse docs, unclear coverage
- `python-youtube` — sync only

## 2. Quota System (CRITICAL)

| Fact | Value |
|------|-------|
| Daily free quota | **10,000 units/day** per GCP project |
| Quota reset | Midnight Pacific Time |
| `search.list` cost | **100 units** (expensive!) |
| `videos.list` cost | **1 unit** (up to 50 IDs per call) |
| `channels.list` cost | **1 unit** |
| `playlistItems.list` cost | **1 unit** |

### Quota Math
- `search.list`: 10,000 / 100 = **100 searches/day**
- `videos.list`: 10,000 / 1 = **10,000 calls/day** (500K video lookups with batching)

### Optimization: Uploads Playlist (33x cheaper)
When you have a channel ID, skip `search.list` entirely:
```
channels.list (get uploads playlist)  = 1 unit
playlistItems.list (get video IDs)    = 1 unit
videos.list (get details, 50 IDs)     = 1 unit
                              Total   = 3 units (vs 101 for search)
```
Channel upload playlist ID: replace `UC` prefix with `UU` (e.g., `UCabc123` → `UUabc123`).

## 3. Endpoint Reference

### search.list — Search videos by keyword
```
GET https://www.googleapis.com/youtube/v3/search
```
| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `part` | string | required | `snippet` only |
| `q` | string | — | Search query |
| `type` | string | `video,channel,playlist` | Use `video` for video search |
| `maxResults` | int | 5 | 1-50 |
| `order` | string | `relevance` | `date`, `rating`, `relevance`, `viewCount` |
| `channelId` | string | — | Restrict to specific channel |
| `publishedAfter` | datetime | — | RFC 3339: `2025-01-01T00:00:00Z` |
| `relevanceLanguage` | string | — | ISO 639-1: `en` |
| `videoDuration` | string | `any` | `short`, `medium`, `long` |
| `pageToken` | string | — | From `nextPageToken` in response |
| `key` | string | required | API key |

### videos.list — Get video details (views, likes, duration)
```
GET https://www.googleapis.com/youtube/v3/videos
```
| Param | Type | Notes |
|-------|------|-------|
| `part` | string | `snippet,statistics,contentDetails` |
| `id` | string | Comma-separated video IDs (max 50) |
| `key` | string | API key |

**Response fields:**
- `snippet`: title, channelTitle, description, publishedAt, thumbnails
- `statistics`: viewCount, likeCount, commentCount
- `contentDetails`: duration (ISO 8601: `PT1H2M3S`)

### channels.list — Get channel info
```
GET https://www.googleapis.com/youtube/v3/channels
```
| Param | Type | Notes |
|-------|------|-------|
| `part` | string | `snippet,contentDetails,statistics` |
| `id` or `forHandle` | string | Channel ID or `@handle` |
| `key` | string | API key |

### playlistItems.list — Get videos from a playlist
```
GET https://www.googleapis.com/youtube/v3/playlistItems
```
| Param | Type | Notes |
|-------|------|-------|
| `part` | string | `snippet` |
| `playlistId` | string | Uploads playlist (UU...) |
| `maxResults` | int | 1-50 |
| `key` | string | API key |

## 4. Async Activity Pattern (httpx)

```python
import httpx
from temporalio import activity

YT_BASE = "https://www.googleapis.com/youtube/v3"

@activity.defn
async def search_videos(request: SearchRequest) -> SearchResult:
    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: Search
        resp = await client.get(f"{YT_BASE}/search", params={
            "part": "snippet",
            "q": request.query,
            "type": "video",
            "maxResults": request.max_results,
            "key": api_key,
        })
        resp.raise_for_status()
        items = resp.json()["items"]
        video_ids = [item["id"]["videoId"] for item in items]

        # Step 2: Get details (1 unit for up to 50 videos)
        resp = await client.get(f"{YT_BASE}/videos", params={
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
            "key": api_key,
        })
        resp.raise_for_status()
        return parse_videos(resp.json())
```

### Key points:
- **Async native** — no ThreadPoolExecutor needed
- **Batch video IDs** — up to 50 per `videos.list` call (1 unit)
- **Timeout**: 30s is plenty (API responds in <1s)
- **Activity timeout**: 30s (not 120s like Apify)
- **Let Temporal retry** — raise on HTTP errors, Temporal handles retries

## 5. Error Handling

| HTTP Code | Meaning | Temporal Action |
|-----------|---------|-----------------|
| 400 | Bad request (invalid params) | Non-retryable — fix code |
| 401 | Invalid API key | Non-retryable — fix key |
| 403 `quotaExceeded` | Daily quota exhausted | Retryable with long backoff (wait for midnight PT) |
| 403 `forbidden` | API not enabled / restricted key | Non-retryable — fix GCP config |
| 404 | Resource not found | Non-retryable |
| 429 | Rate limited | Retryable with backoff |
| 5xx | Server error | Retryable (Temporal default) |

## 6. ISO 8601 Duration Parsing

YouTube returns duration as ISO 8601 (`PT1H2M30S`). Parse with:
```python
import re

def parse_duration(iso: str) -> str:
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return iso
    h, mins, s = (int(x) if x else 0 for x in m.groups())
    if h:
        return f"{h}:{mins:02d}:{s:02d}"
    return f"{mins}:{s:02d}"
```

## 7. Pagination

```python
all_items = []
page_token = None
while True:
    params = {"part": "snippet", "playlistId": pid, "maxResults": 50, "key": key}
    if page_token:
        params["pageToken"] = page_token
    resp = await client.get(url, params=params)
    data = resp.json()
    all_items.extend(data["items"])
    page_token = data.get("nextPageToken")
    if not page_token:
        break
```

## Key Rules
1. **Prefer `videos.list` over `search.list`** — 100x cheaper quota
2. **Use uploads playlist** when you have a channel ID — avoids search entirely
3. **Batch video IDs** — up to 50 per call, costs only 1 unit
4. **Use `fields` param** to reduce payload: `fields=items(id,snippet(title),statistics(viewCount))`
5. **Activity timeout**: 30s (API is fast, unlike Apify)
6. **httpx async** — no ThreadPoolExecutor needed in Worker
7. **Let Temporal retry** — raise on errors, set `RetryPolicy(maximum_attempts=3)`
