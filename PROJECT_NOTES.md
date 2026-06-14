# My Understanding of the AI Agent Orchestration Platform

So basically the idea behind this project is to build a platform where you can create AI agents, set them up the way you want, and then connect them together so they can work as a team to complete tasks. Think of it like hiring a bunch of workers and assigning them different roles — one does research, another one summarizes, another handles customer complaints — and they pass the work between each other automatically.

---

## What the platform actually does

At its core, users can create agents and configure a bunch of things about them — like what their personality is (system prompt), what model they use (GPT-4, Claude, etc.), what tools they have access to (search the web, do math, make HTTP calls), and how much memory they have. There's also guardrails so an agent doesn't go into an infinite loop or burn through too many tokens.

Once you have agents set up, you can connect them into workflows. The workflow builder is visual — you drag nodes onto a canvas, draw lines between them, and those lines represent how the output of one agent feeds into the next. There's even conditions on those connections, so you can say "only pass to the next agent if the output contains a certain keyword" or "only continue if the first agent succeeded."

One of the requirements I found interesting was that at least one agent has to be reachable from an external messaging channel. I went with Telegram for that because it's the easiest to set up — you just message BotFather, get a token, drop it in the .env file, and you're good. No business approval, no waiting, no cost. The agent connected to Telegram just responds to messages in real time.

---

## The tech behind it

For the AI runtime I picked LangGraph. My reasoning was that it's the most transparent of the options available. With something like CrewAI you kind of hand over control and trust the framework to figure out who talks to who. With LangGraph you define the graph yourself — every node, every edge, every condition. That felt like a better fit for a platform where the user is supposed to design the workflow visually, because the visual canvas and the actual execution graph end up being the same thing conceptually.

The backend is FastAPI because it's async-native and works well with everything else that's async here — the database queries, the agent execution, the WebSocket broadcasting. Executions run in background tasks so the HTTP response comes back immediately and the actual agent work happens without blocking anything.

For the database I went with SQLite. I know that's not something you'd use in production at scale but for a challenge like this it felt right — no extra infrastructure to spin up, just a file on disk. You can swap it out for Postgres with a single environment variable change.

The frontend is React with ReactFlow for the workflow canvas. ReactFlow handles all the node rendering, drag behavior, and connection drawing out of the box which saved a lot of time. The rest is just Tailwind for styling and a WebSocket hook that auto-reconnects so the live monitor always stays connected.

---

## How everything fits together

When someone runs a workflow:

1. The frontend sends a POST to `/api/executions/` with the workflow ID and an initial message
2. The backend creates an execution record and kicks off a background task
3. The workflow engine figures out which agent starts first, runs it through LangGraph, takes the output, and passes it to the next agent based on the edges
4. Every time something interesting happens (agent starts, agent finishes, tool gets called) the message bus emits an event over WebSocket
5. The frontend's live monitor picks those up in real time and shows them as they happen

For Telegram it's a bit different — messages come in from the user's phone, get routed to whichever agent is connected to the channel, run through LangGraph the same way, and the response goes back to Telegram.

---

## Things I'm aware of but left as-is for now

The memory implementation is a sliding window — just the last N messages. A proper summary-based memory where the agent compresses old conversations would be better for long-running agents but adds a lot of complexity. The window approach is still configurable per agent.

Also the cost calculation is a rough estimate based on token count. The actual price depends on the model, input vs output tokens, etc. A proper implementation would track that per model but for demo purposes the estimate is close enough to be useful.

---

## Running it

The whole thing runs locally with one command: `./setup.sh`. It detects whether Docker is available and uses that, otherwise it sets up the Python virtual env and runs everything locally. You need at minimum an OpenAI or Anthropic API key in the `.env` file. Everything else is optional — Telegram is optional, the database creates itself.
