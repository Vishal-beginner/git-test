import json
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_message_bus_broadcast():
    from app.core.message_bus import MessageBus

    bus = MessageBus()
    mock_ws = AsyncMock()
    mock_ws.send_text = AsyncMock()

    await bus.connect(mock_ws)
    await bus.broadcast("test_event", {"key": "value"})

    mock_ws.send_text.assert_called_once()
    payload = json.loads(mock_ws.send_text.call_args[0][0])
    assert payload["type"] == "test_event"
    assert payload["data"]["key"] == "value"


@pytest.mark.asyncio
async def test_message_bus_disconnect():
    from app.core.message_bus import MessageBus

    bus = MessageBus()
    mock_ws = AsyncMock()
    await bus.connect(mock_ws)
    assert mock_ws in bus._connections

    bus.disconnect(mock_ws)
    assert mock_ws not in bus._connections


@pytest.mark.asyncio
async def test_create_execution(client):
    agent_r = await client.post("/api/agents/", json={
        "name": "Exec Agent", "role": "assistant",
        "system_prompt": "You are helpful.", "model": "gpt-4o-mini",
    })
    agent_id = agent_r.json()["id"]

    r = await client.post("/api/executions/", json={
        "agent_id": agent_id,
        "input_data": {"message": "Hello"},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["agent_id"] == agent_id
    assert data["status"] in ("pending", "running", "completed", "failed")


@pytest.mark.asyncio
async def test_list_executions(client):
    r = await client.get("/api/executions/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_workflow_execution_created(client):
    a1 = (await client.post("/api/agents/", json={
        "name": "Researcher", "role": "researcher",
        "system_prompt": "Research topics.", "model": "gpt-4o-mini",
    })).json()["id"]

    a2 = (await client.post("/api/agents/", json={
        "name": "Summarizer", "role": "summarizer",
        "system_prompt": "Summarize text.", "model": "gpt-4o-mini",
    })).json()["id"]

    wf = (await client.post("/api/workflows/", json={
        "name": "Research Pipeline",
        "nodes": [
            {"id": "n1", "agent_id": a1, "label": "Researcher",
             "position": {"x": 100, "y": 200}, "config": {}},
            {"id": "n2", "agent_id": a2, "label": "Summarizer",
             "position": {"x": 420, "y": 200}, "config": {}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "condition": "always"}],
    })).json()

    r = await client.post("/api/executions/", json={
        "workflow_id": wf["id"],
        "input_data": {"message": "Tell me about Python"},
    })
    assert r.status_code == 200
    assert r.json()["workflow_id"] == wf["id"]
