# AI Agent Orchestration Platform

A full-stack platform for creating, configuring, and orchestrating AI agents into collaborative multi-agent workflows — with real-time monitoring, a visual workflow builder, and Telegram channel integration.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│               React Frontend (Port 3000)                 │
│  Dashboard · Agent Manager · Workflow Builder · Monitor  │
└─────────────────────┬───────────────────────────────────┘
                      │ REST + WebSocket
┌─────────────────────▼───────────────────────────────────┐
│               FastAPI Backend (Port 8000)                │
│  /api/agents · /api/workflows · /api/executions · /ws   │
├──────────────┬───────────────────┬──────────────────────┤
│  LangGraph   │  SQLite (async)   │   Telegram Bot       │
│  Agent       │  Agent/Workflow/  │   python-telegram-   │
│  Runtime     │  Execution/Msg    │   bot v21            │
└──────────────┴───────────────────┴──────────────────────┘
```

### Layer separation

| Layer | Location | Responsibility |
|---|---|---|
| **UI** | `frontend/src/` | React + ReactFlow visual builder, agent forms, live monitor |
| **API** | `backend/app/api/` | FastAPI routers, request validation, HTTP responses |
| **Agent Runtime** | `backend/app/core/agent_runtime.py` | LangGraph graph construction and execution |
| **Workflow Engine** | `backend/app/core/workflow_engine.py` | Multi-agent orchestration, conditional routing |
| **Message Bus** | `backend/app/core/message_bus.py` | Async WebSocket broadcast, event queue |
| **Persistence** | `backend/app/models.py` | SQLAlchemy ORM, async SQLite |
| **Channels** | `backend/app/channels/telegram_bot.py` | Telegram bot integration |

---

## Technology Choices & Justifications

### AI Runtime: LangGraph
- **Why LangGraph over CrewAI/AutoGen:** LangGraph gives explicit control over graph topology — nodes, edges, and conditional routing are first-class primitives that map directly to the visual workflow builder. Each agent is a compiled `StateGraph` that supports tool-call loops natively via `ToolNode` + `tools_condition`.
- **State management:** `AgentState` (TypedDict with `Annotated[list, operator.add]`) ensures messages accumulate correctly across graph traversals.
- **Memory:** Configurable buffer window — last N messages are prepended to every agent invocation.

### Backend: Python FastAPI
- Async-native, matches SQLAlchemy's async engine and LangGraph's async `ainvoke`.
- Background tasks for long-running executions without blocking the HTTP response.
- WebSocket endpoint feeds real-time events to the frontend.

### Frontend: React + Vite + ReactFlow
- `@xyflow/react` provides the visual workflow canvas with drag-and-drop nodes and connections.
- Tailwind CSS for rapid, consistent styling.
- WebSocket hook auto-reconnects and streams events to the Live Monitor.

### Database: SQLite (async via aiosqlite)
- Zero-setup for local development — no PostgreSQL/Redis required.
- Can be replaced with PostgreSQL by changing `DATABASE_URL` in `.env`.

### Messaging Channel: Telegram
- No approval process or business account required.
- `python-telegram-bot` v21 is fully async and integrates cleanly with FastAPI's asyncio event loop.

---

## Features

- **Agent CRUD** — name, role, system prompt, model, tools, channels, schedule (cron), memory (buffer/summary), guardrails (max_tokens, max_iterations, timeout), skills, interaction rules
- **Visual Workflow Builder** — ReactFlow canvas; drag nodes, draw edges, assign agents, set conditions, run workflows directly
- **3 Pre-built Templates** — Customer Support Pipeline, Research & Summarizer, Code Review Pipeline
- **LangGraph Runtime** — real tool execution, multi-step reasoning, configurable iteration limits
- **6 Built-in Tools** — `web_search`, `calculator`, `get_datetime`, `http_request`, `summarize_text`, `weather_info`
- **Telegram Integration** — one-command setup; any agent can be the Telegram-facing bot
- **Live Monitor** — WebSocket-based real-time event stream; execution history with per-message token tracking
- **Async multi-agent execution** — agents communicate through workflow edges with conditional routing

---

## Quick Start

### Option 1: Docker Compose (recommended)

```bash
cp .env.example .env
# Edit .env — add OPENAI_API_KEY or ANTHROPIC_API_KEY
docker-compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs

### Option 2: Single setup script

```bash
cp .env.example .env
# Edit .env — add your API key
./setup.sh
```

### Option 3: Manual

**Backend:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # add your API key
uvicorn app.main:app --reload --port 8000
```

**Frontend (new terminal):**
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

---

## Telegram Setup

1. Message `@BotFather` on Telegram, create a bot, copy the token.
2. Add `TELEGRAM_BOT_TOKEN=<your-token>` to `.env`.
3. Restart the backend.
4. In the platform UI → **Agents** page → hover any agent card → click **Telegram**.
5. Message your bot — responses come from the connected agent in real time.

---

## Running Tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

Tests cover:
- Agent CRUD (create, read, update, delete, tools list)
- Workflow CRUD (create, templates, nodes, status update, delete)
- Message delivery (bus broadcast, disconnect, execution creation, workflow execution)

---

## Adding New Tools

In `backend/app/core/tools.py`:

```python
from langchain_core.tools import tool

@tool
def my_new_tool(param: str) -> str:
    """Description shown to the LLM."""
    return result

AVAILABLE_TOOLS["my_new_tool"] = my_new_tool
TOOL_DESCRIPTIONS["my_new_tool"] = "Short UI description"
```

## Adding New Workflow Templates

In `backend/app/api/workflows.py`, append to `TEMPLATES`:

```python
{
    "id": "my_template",
    "name": "My Template",
    "description": "What it does.",
    "nodes": [
        {"id": "n1", "label": "Agent A", "agent_id": None,
         "position": {"x": 100, "y": 200}, "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2", "condition": "always"},
    ],
}
```

## Adding New Messaging Channels

1. Create `backend/app/channels/<name>.py` with `start()`, `stop()`, `send_message()`, `set_agent_handler()`.
2. Import and start it in the `lifespan` context in `backend/app/main.py`.
3. Add a connect endpoint in `backend/app/api/channels.py`.

---

## Edge Conditions

| Condition | Behavior |
|---|---|
| `always` | Always routes to next node (default) |
| `on_success` | Only if agent ran without error |
| `on_failure` | Only on agent error |
| `contains:<keyword>` | Only if agent output contains keyword |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/agents/` | List all agents |
| POST | `/api/agents/` | Create agent |
| PUT | `/api/agents/{id}` | Update agent |
| DELETE | `/api/agents/{id}` | Delete agent |
| GET | `/api/agents/tools` | Available tools |
| GET | `/api/workflows/templates` | Pre-built templates |
| POST | `/api/workflows/` | Create workflow |
| POST | `/api/executions/` | Run agent or workflow |
| GET | `/api/executions/{id}/messages` | Execution messages |
| GET | `/api/channels/status` | Channel status |
| POST | `/api/channels/telegram/connect-agent` | Connect agent to Telegram |
| WS | `/ws` | Real-time event stream |

Full interactive docs: http://localhost:8000/docs
