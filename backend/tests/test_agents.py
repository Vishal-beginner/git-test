import pytest


@pytest.mark.asyncio
async def test_list_tools(client):
    r = await client.get("/api/agents/tools")
    assert r.status_code == 200
    tools = r.json()
    assert "calculator" in tools
    assert "web_search" in tools


@pytest.mark.asyncio
async def test_create_agent(client):
    r = await client.post("/api/agents/", json={
        "name": "Test Agent",
        "role": "assistant",
        "system_prompt": "You are a test agent.",
        "model": "gpt-4o-mini",
        "tools": ["calculator"],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Test Agent"
    assert data["role"] == "assistant"
    assert "calculator" in data["tools"]
    assert "id" in data


@pytest.mark.asyncio
async def test_list_agents(client):
    r = await client.get("/api/agents/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_get_agent(client):
    create = await client.post("/api/agents/", json={
        "name": "Get Test", "role": "assistant",
        "system_prompt": "Test", "model": "gpt-4o-mini",
    })
    agent_id = create.json()["id"]

    r = await client.get(f"/api/agents/{agent_id}")
    assert r.status_code == 200
    assert r.json()["id"] == agent_id


@pytest.mark.asyncio
async def test_update_agent(client):
    create = await client.post("/api/agents/", json={
        "name": "Original Name", "role": "assistant",
        "system_prompt": "Test", "model": "gpt-4o-mini",
    })
    agent_id = create.json()["id"]

    r = await client.put(f"/api/agents/{agent_id}", json={"name": "Updated Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_delete_agent(client):
    create = await client.post("/api/agents/", json={
        "name": "To Delete", "role": "assistant",
        "system_prompt": "Test", "model": "gpt-4o-mini",
    })
    agent_id = create.json()["id"]

    r = await client.delete(f"/api/agents/{agent_id}")
    assert r.status_code == 200

    r2 = await client.get(f"/api/agents/{agent_id}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_get_nonexistent_agent(client):
    r = await client.get("/api/agents/nonexistent-id")
    assert r.status_code == 404
