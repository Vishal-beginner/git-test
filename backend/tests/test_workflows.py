import pytest


@pytest.mark.asyncio
async def test_list_templates(client):
    r = await client.get("/api/workflows/templates")
    assert r.status_code == 200
    templates = r.json()
    assert len(templates) >= 2
    ids = [t["id"] for t in templates]
    assert "customer_support" in ids
    assert "research_summarizer" in ids


@pytest.mark.asyncio
async def test_create_workflow(client):
    r = await client.post("/api/workflows/", json={
        "name": "Test Workflow",
        "description": "A test workflow",
        "nodes": [],
        "edges": [],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Test Workflow"
    assert data["status"] == "draft"


@pytest.mark.asyncio
async def test_workflow_with_nodes(client):
    agent_r = await client.post("/api/agents/", json={
        "name": "WF Agent", "role": "assistant",
        "system_prompt": "Process tasks.", "model": "gpt-4o-mini",
    })
    agent_id = agent_r.json()["id"]

    r = await client.post("/api/workflows/", json={
        "name": "Workflow With Nodes",
        "nodes": [{"id": "n1", "agent_id": agent_id, "label": "Node 1",
                   "position": {"x": 100, "y": 100}, "config": {}}],
        "edges": [],
    })
    assert r.status_code == 200
    assert len(r.json()["nodes"]) == 1


@pytest.mark.asyncio
async def test_update_workflow_status(client):
    create = await client.post("/api/workflows/", json={"name": "Status Test"})
    wf_id = create.json()["id"]

    r = await client.put(f"/api/workflows/{wf_id}", json={"status": "active"})
    assert r.status_code == 200
    assert r.json()["status"] == "active"


@pytest.mark.asyncio
async def test_delete_workflow(client):
    create = await client.post("/api/workflows/", json={"name": "To Delete"})
    wf_id = create.json()["id"]

    r = await client.delete(f"/api/workflows/{wf_id}")
    assert r.status_code == 200

    r2 = await client.get(f"/api/workflows/{wf_id}")
    assert r2.status_code == 404
