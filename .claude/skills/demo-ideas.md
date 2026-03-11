# Demo Ideas - 5-Minute Showcase Projects

## Tier 1: Quick Wins (< 30 min to build)

### 1. AI Content Pipeline
**Pitch**: "Watch Temporal orchestrate a multi-step AI content pipeline with automatic retries"
- Input: Topic/prompt
- Workflow: Research → Draft → Review → Polish
- Each step is a Bedrock activity with different system prompts
- Query shows real-time progress through steps
- **Wow factor**: Kill the worker mid-workflow, restart it, watch it resume

### 2. Document Analyzer with Human Review
**Pitch**: "AI analyzes documents, humans approve - Temporal handles the wait"
- Upload text/paste content
- AI generates analysis (classification, summary, key entities)
- Workflow pauses waiting for human signal
- Human approves/rejects via API call
- If rejected, AI revises based on feedback
- **Wow factor**: Show workflow waiting in Temporal UI, send signal, watch it continue

### 3. AI Chatbot with Persistent Memory
**Pitch**: "A conversation that survives server crashes - powered by Temporal"
- Entity workflow per conversation
- Signals send user messages
- Queries retrieve conversation history
- Full conversation history maintained in workflow state
- **Wow factor**: Restart everything, conversation continues from where it left off

---

## Tier 2: Impressive Demos (1-2 hours to build)

### 4. Multi-Perspective AI Analyst
**Pitch**: "Get legal, financial, and technical analysis in parallel - reliably"
- Input: Business proposal/document
- Fan-out: 3+ parallel AI activities (legal, financial, technical, risk)
- Fan-in: Synthesis activity combines all perspectives
- Real-time SSE streaming of each perspective as it completes
- **Wow factor**: Parallel execution visible in Temporal UI, synthesis step

### 5. AI-Powered Code Review Pipeline
**Pitch**: "Automated code review with human escalation for critical issues"
- Input: Code snippet or PR diff
- Step 1: AI scans for bugs, security issues, style
- Step 2: AI rates severity (auto-approve if low)
- Step 3: If critical → human-in-the-loop signal for approval
- Step 4: Generate review summary
- **Wow factor**: Automatic vs. human review path, visible in workflow history

### 6. Intelligent Data Processing Pipeline
**Pitch**: "ETL meets AI - Transform, enrich, and validate data with LLMs"
- Input: CSV/JSON data
- Step 1: AI classifies/categorizes each record
- Step 2: AI enriches with missing information
- Step 3: AI validates for consistency
- Step 4: Output structured results
- Child workflows for each batch (fan-out)
- **Wow factor**: Progress tracking, batch processing, error handling

### 7. AI Agent with Tool Use
**Pitch**: "Watch an AI agent think, plan, and execute - with full observability"
- Input: Complex task (e.g., "Research company X and write a brief")
- Agent loop: Think → Decide tool → Execute → Observe → Repeat
- Tools: web search, calculator, text analysis
- Each iteration is an activity (full Temporal history)
- Max iterations safety net
- **Wow factor**: Step-by-step agent reasoning visible in Temporal UI

---

## Tier 3: Show-Stoppers (2-4 hours)

### 8. Multi-Agent Collaboration System
**Pitch**: "Multiple AI agents working together on complex tasks"
- Parent workflow assigns sub-tasks to child workflows
- Each child is a specialized "agent" (researcher, writer, critic)
- Agents pass results between each other via workflow
- Final synthesis workflow combines all work
- **Wow factor**: Visual flow of agents collaborating in Temporal UI

### 9. AI-Powered Approval Workflow
**Pitch**: "Enterprise-ready AI with governance - every decision auditable"
- AI generates proposal/recommendation
- Multi-level approval chain (manager → director → VP)
- Each level can approve, reject, or request changes
- AI revises on rejection with specific feedback
- Full audit trail in Temporal history
- Timer-based escalation if no response in X hours
- **Wow factor**: Enterprise governance + AI in one workflow

### 10. Real-Time AI Translation Pipeline
**Pitch**: "Translate content to 5 languages in parallel with quality checks"
- Input: Text content
- Fan-out: Parallel translation to N languages
- Each translation gets a quality score
- Low-quality translations get auto-retried with different prompts
- Final output: All translations with confidence scores
- **Wow factor**: Parallel execution, quality-based retry logic

---

## Demo Presentation Tips

### Structure (5 minutes)
1. **Problem** (30s): "Today, AI pipelines are fragile..."
2. **Solution** (30s): "Temporal makes AI workflows durable and observable"
3. **Architecture** (30s): Quick diagram - FastAPI → Temporal → Bedrock
4. **Live Demo** (2.5min): Show Swagger, trigger workflow, show Temporal UI
5. **Failure Demo** (30s): Kill worker, show resume (THE wow moment)
6. **Wrap-up** (30s): "This is just the beginning..."

### Key Demo Moments to Highlight
- **Swagger UI**: "Instant interactive API documentation"
- **Temporal UI**: "Full visibility into every workflow execution"
- **Retry in action**: "The LLM call failed, watch Temporal retry automatically"
- **Human-in-the-loop**: "The workflow is waiting for approval... let me signal it"
- **Durability**: "I just killed the process. Watch what happens when I restart..."

### Environment Setup Checklist
- [ ] `temporal server start-dev` running
- [ ] App running (`python run.py`)
- [ ] Browser tabs: Swagger (:8000/docs), Temporal UI (:8233)
- [ ] AWS credentials configured
- [ ] Sample data/prompts ready to paste
