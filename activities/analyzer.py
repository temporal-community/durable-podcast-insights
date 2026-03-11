from google import genai
from google.genai import types
from temporalio import activity

from app.config import settings
from models.schemas import (
    ExtractedInterests,
    ExtractInterestsRequest,
    RankRequest,
    RankResult,
    SummaryRequest,
    SummaryResult,
)

EXTRACT_PROMPT = """You are an interest parser. Given a raw user interests string,
extract specific keywords and broader topic categories.
Keywords: specific terms the user mentioned (e.g. "kubernetes", "RAG", "temporal").
Topics: broader categories (e.g. "cloud infrastructure", "AI/ML", "devops")."""

RANK_PROMPT = """You are a podcast episode recommendation engine that scores long-form YouTube videos for a specific listener.

You receive rich metadata per episode: title, description, tags, chapters (section titles), view/like/comment counts, and duration. Use ALL of these signals:
- Chapters are the strongest signal — they reveal the depth and breadth of topics discussed
- Tags reveal exact topics and guest names
- Longer episodes with many chapters indicate deep-dive discussions
- High like-to-view ratio and comment count indicate engaging conversations
- Description often lists guests, topics covered, and timestamps

Scoring guide (evaluate as podcast episodes for this listener):
- 85-100: Episode directly covers a user keyword — confirmed by chapters, tags, or title
- 70-84: Strong topical overlap via description or tags, likely valuable discussion
- 50-69: Adjacent topic that a curious listener would enjoy
- 30-49: Weak connection, mostly different subject matter
- 0-29: Completely unrelated to user interests

Rules:
- ONLY use videos from the provided list — never invent episodes
- Copy the EXACT title, URL, duration, and views from the input
- Every video in the list MUST appear in your output — rank ALL of them
- Sort by score descending
- In the "why" field, mention what topic/guest makes this episode valuable and which signal (chapter, tag, description) confirmed it"""

SUMMARY_PROMPT = """You are a podcast channel analyst specializing in YouTube long-form content.
Given a channel name and its episode catalog, produce:
1. A brief summary of the podcast's focus and format (2-3 sentences — mention if it's interview-based, solo, panel, etc.)
2. 3-5 key insights (recurring guests/themes, episode cadence, discussion depth, standout series, content gaps)
3. The content tone: educational, entertainment, news, tutorial, or mixed"""


def _make_client() -> genai.Client:
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=45_000),
    )


@activity.defn
async def extract_interests(request: ExtractInterestsRequest) -> ExtractedInterests:
    """Parse raw interests string into structured keywords + topics."""
    client = _make_client()
    model = settings.gemini_model
    activity.logger.info(f"Extracting interests from: {request.interests[:80]}")

    response = await client.aio.models.generate_content(
        model=model,
        contents=f"User interests: {request.interests}",
        config=types.GenerateContentConfig(
            system_instruction=EXTRACT_PROMPT,
            response_mime_type="application/json",
            response_schema=ExtractedInterests,
            temperature=0.2,
        ),
    )
    result = response.parsed
    activity.logger.info(f"Extracted {len(result.keywords)} keywords, {len(result.topics)} topics")
    return result


@activity.defn
async def rank_videos(request: RankRequest) -> RankResult:
    """Rank videos by relevance to structured interests."""
    client = _make_client()

    video_lines = []
    for i, v in enumerate(request.videos, 1):
        parts = [
            f"[{i}] {v.title}",
            f"    URL: {v.url} | Duration: {v.duration} | Views: {v.views} | Likes: {v.likes} | Comments: {v.comments} | Date: {v.date}",
            f"    Description: {v.description[:500]}",
        ]
        if v.tags:
            parts.append(f"    Tags: {', '.join(v.tags[:12])}")
        if v.chapters:
            parts.append(f"    Chapters: {', '.join(v.chapters[:10])}")
        video_lines.append("\n".join(parts))
    videos_text = "\n\n".join(video_lines)

    prompt = f"""Listener keywords: {', '.join(request.keywords)}
Listener topics: {', '.join(request.topics)}

{len(request.videos)} podcast episodes from the channel:

{videos_text}

Score and rank ALL {len(request.videos)} episodes for this listener. Return every episode with a score."""

    model = settings.gemini_model
    activity.logger.info(f"Ranking {len(request.videos)} videos with {model}")
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=RANK_PROMPT,
            response_mime_type="application/json",
            response_schema=RankResult,
            temperature=0.3,
        ),
    )
    return response.parsed


@activity.defn
async def generate_summary(request: SummaryRequest) -> SummaryResult:
    """Generate channel overview, insights, and tone analysis."""
    client = _make_client()

    titles = [v.title for v in request.videos]
    titles_text = "\n".join(f"- {t}" for t in titles)

    prompt = f"""Channel: {request.channel_name}
User interest keywords: {', '.join(request.keywords)}

Recent video titles:
{titles_text}

Analyze this channel."""

    model = settings.gemini_model
    activity.logger.info(f"Generating summary for {request.channel_name}")
    response = await client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SUMMARY_PROMPT,
            response_mime_type="application/json",
            response_schema=SummaryResult,
            temperature=0.3,
        ),
    )
    return response.parsed
