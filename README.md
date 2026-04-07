# Agentic Data Analyst

Agentic Data Analyst is a backend-first multi-agent system for tabular analytics workflows. It demonstrates how to build a configurable AI agent architecture that can inspect datasets, route work to specialist subagents, execute typed tools, stream intermediate events, pause for human approval, and return decision-ready artifacts such as reports, cleaned datasets, and charts.

**What this demonstrates**

- Multi-agent orchestration with a main agent and specialist subagents
- Tool-grounded execution instead of relying on free-form prompting alone
- Thread-level memory and checkpointing for stateful workflows
- Human-in-the-loop approval gates for sensitive actions
- Per-user isolated workspaces and secure artifact delivery
- Streaming token, tool-call, artifact, and interrupt events over SSE
- Config-driven agent composition using YAML plus prompt templates

Tech stack: FastAPI, LangGraph, LangChain, Deep Agents, Pandas, scikit-learn, Matplotlib, OpenRouter or Azure OpenAI, and Groq for voice transcription.

## System design

The system is organized around one orchestrator and three specialist subagents.

- The main agent receives the user goal, decides which workflow is needed, and synthesizes the final answer.
- The `Data_Quality_Subagent` handles profiling, schema checks, cleaning plans, and dataset comparison.
- The `Visualization_Subagent` handles plot generation and chart interpretation.
- The `Segmentation_Subagent` handles clustering, segment summaries, and exportable outputs.

This split exists for a practical reason: a single large prompt can answer simple questions, but it performs worse when every workflow, tool contract, and edge case must share the same context window. Specialist subagents keep each task smaller, more focused, and easier to reason about.

The agent runtime is also intentionally structured around tools rather than pure text generation.

- Dataset inspection goes through typed tools such as `preview_dataset`, `validate_dataset`, and `profile_dataset`.
- Stateful outputs such as cleaned datasets, reports, and segmentation summaries are produced by explicit tool calls.
- Generated artifacts are returned through a secure file delivery path instead of being described abstractly in chat.

Thread state is persisted with a checkpointer, so the same conversation can continue across multiple user turns. Each registered user also gets an isolated workspace, which keeps uploads, generated artifacts, and prompt memory scoped to that user session.

## Agentic patterns and tradeoffs

### Main agent plus specialist subagents

- Implemented as one orchestrator with role-specific subagents defined in YAML.
- This reduces context bloat and lets each specialist carry tighter behavioral instructions.
- Tradeoff: more moving parts and more prompt/config surfaces to maintain.

### Tool-grounded execution

- Implemented with typed tools for profiling, cleaning, comparison, segmentation, plotting, reporting, and file delivery.
- This makes workflows more reliable than asking the model to describe transformations without executing them.
- Tradeoff: every tool becomes an interface that must be validated and maintained carefully.

### Human in the loop

- Cleaning and report export can interrupt for approval before producing user-visible outputs.
- This is useful for workflows that change data or create an “official” artifact.
- Tradeoff: approvals improve control but add latency and require a front end or client that can resume interrupted flows cleanly.

### Context control and token discipline

- The orchestrator delegates deeper tasks instead of carrying every detail in the main thread.
- Prompt content, tool access, and subagent behavior are separated into configuration files and templates.
- Tradeoff: better token discipline comes at the cost of more architectural complexity than a single-agent prototype.

### Streaming and runtime observability

- The API streams tokens, tool calls, artifact notifications, and interrupt events over SSE.
- This makes the agent easier to demo and easier to inspect while it is working.
- Tradeoff: SSE gives useful runtime visibility, but it is not a full tracing or evaluation system yet.

### Config-driven extensibility

- The default agent is assembled from YAML config plus prompt files rather than being hardcoded in one module.
- This makes it easier to swap tools, change specialist roles, or repurpose the backend for a new vertical.
- Tradeoff: configuration drift becomes a real concern if templates and code contracts are not kept aligned.

## Demo scenarios

### 1. Profile and cleaning recommendation

- Dataset: `examples/retail_sales.csv`
- Goal: identify missingness, duplicates, suspicious columns, and a safe cleaning plan
- Expected workflow: main agent -> `Data_Quality_Subagent` -> profiling and validation tools
- Visible outcome: concise risk summary and a recommended cleaning action

### 2. Raw vs cleaned comparison and report export

- Dataset: `examples/retail_sales.csv` plus a cleaned derivative in the workspace
- Goal: compare schema and numeric drift between raw and cleaned data
- Expected workflow: main agent -> `Data_Quality_Subagent` -> compare tool -> report export
- Visible outcome: markdown report plus approval-aware artifact generation

### 3. Segmentation plus visualization

- Dataset: `examples/marketing_leads.csv`
- Goal: cluster leads into interpretable segments and visualize them
- Expected workflow: main agent -> `Segmentation_Subagent` -> segmentation tool -> `Visualization_Subagent`
- Visible outcome: labeled segments, a supporting chart, and an optional report artifact

These scenarios are intentionally simple so they can be run quickly during an interview or recorded as short demos.

## Production considerations

This repository is designed to demonstrate agent engineering patterns, not to claim full production hardening.

- `generate_plot` executes Python in-process. In production, this should be moved behind a stronger sandbox boundary.
- The workspace-per-user model is practical for demos and internal tools, but larger systems would likely want object storage, job isolation, and stricter retention policies.
- Human approval checkpoints are control points, not full governance. Production systems usually need richer audit trails and resume semantics.
- Streaming SSE events provide lightweight runtime visibility, but a production deployment would benefit from structured traces, metrics, and replayable evaluation scenarios.
- The architecture is intentionally generic and based on synthetic datasets so the public repository can showcase agentic system design without relying on proprietary domain logic.

## Architecture at a glance

```text
User request
  -> FastAPI endpoint
  -> Main agent
  -> Specialist subagent (quality / visualization / segmentation)
  -> Typed tool execution
  -> Optional approval interrupt
  -> Artifact generation
  -> Secure file delivery + streamed events
```

Key implementation points:

- `app/services/agent_factory.py` builds cached Deep Agents with per-thread checkpointing and workspace-backed tools.
- `templates/data_analyst_agent/` defines the default public agent, prompt pack, and specialist composition.
- `app/services/streaming.py` streams tokens, tool calls, artifact sends, and interrupt events.
- `app/services/user_provisioning.py` creates per-user workspaces and seeds workspace memory via `AGENTS.md`.

## Available tools

- `preview_dataset`
- `validate_dataset`
- `profile_dataset`
- `clean_dataset`
- `compare_datasets`
- `segment_dataset`
- `export_report`
- `generate_plot`
- `send_files_to_user`

## API surface

- `POST /users/register`
- `POST /upload/{user_id}`
- `POST /chat/{user_id}/{agent_id}`
- `POST /voice-chat/{user_id}/{agent_id}`
- `GET /files/{user_id}/{file_path}`
- `GET /health`

## Example datasets

The repository includes small synthetic datasets under `examples/`:

- `retail_sales.csv` for profiling, cleaning, and comparison workflows
- `support_tickets.csv` for service analytics and operational triage demos
- `marketing_leads.csv` for segmentation and chart generation workflows

They are deliberately lightweight so the repo can be demoed quickly without needing large infrastructure or private data.

## Local run

1. Create a `.env` file from `.env.example`.
2. Set `ROOT_DIR` to the repository root.
3. Configure either OpenRouter or Azure OpenAI.
4. Optionally configure Groq if you want to use the voice endpoint.
5. Start the API:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Why this project matters for AI engineering roles

This project is meant to show more than API construction. It is evidence of how I think about agent systems as software systems:

- when to use specialists instead of a single agent
- when to require tools instead of trusting text-only reasoning
- where to place human approval boundaries
- how to manage context, state, and artifacts across multi-step workflows
- how to design a backend that is easy to repurpose for a new vertical without rewriting the orchestration model

That makes it a useful portfolio project for discussions about agent architecture, workflow reliability, context management, and production-oriented design tradeoffs.
