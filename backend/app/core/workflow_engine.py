import logging
from typing import Any, Dict, List

from .agent_runtime import run_agent
from .message_bus import message_bus

logger = logging.getLogger(__name__)


class WorkflowEngine:
    async def execute_workflow(
        self,
        workflow: Dict,
        agents: Dict[str, Dict],
        execution_id: str,
        input_data: Dict,
    ) -> Dict[str, Any]:
        nodes: List[Dict] = workflow.get("nodes") or []
        edges: List[Dict] = workflow.get("edges") or []

        if not nodes:
            return {"success": False, "error": "Workflow has no nodes"}

        await message_bus.emit("execution_start", {
            "execution_id": execution_id,
            "workflow_id": workflow.get("id"),
            "workflow_name": workflow.get("name"),
        })

        # Build adjacency map
        graph: Dict[str, Dict] = {}
        for node in nodes:
            graph[node["id"]] = {
                "agent_id": node.get("agent_id"),
                "config": node.get("config") or {},
                "next": [],
            }
        for edge in edges:
            src = edge.get("source", "")
            if src in graph:
                graph[src]["next"].append({
                    "target": edge.get("target"),
                    "condition": edge.get("condition", "always"),
                    "label": edge.get("label", ""),
                })

        # Find entry nodes (no incoming edges)
        targets = {e.get("target") for e in edges}
        entry_nodes = [n["id"] for n in nodes if n["id"] not in targets]
        if not entry_nodes:
            entry_nodes = [nodes[0]["id"]]

        current_input = input_data.get("message", "")
        results: Dict[str, Dict] = {}
        memory_store: Dict[str, List] = {}
        visited: set = set()
        queue: List = [(entry_nodes[0], current_input)]

        while queue:
            node_id, node_input = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            node_data = graph.get(node_id, {})
            agent_id = node_data.get("agent_id")

            if not agent_id or agent_id not in agents:
                logger.warning("Agent %s not found for node %s", agent_id, node_id)
                continue

            agent_cfg = agents[agent_id]

            await message_bus.emit("agent_start", {
                "execution_id": execution_id,
                "agent_id": agent_id,
                "agent_name": agent_cfg.get("name", "Agent"),
                "node_id": node_id,
                "input": node_input[:120],
            })

            memory = memory_store.get(agent_id, [])
            result = await run_agent(
                agent_config={**agent_cfg, "id": agent_id},
                messages=[{"role": "user", "content": node_input}],
                execution_id=execution_id,
                memory=memory,
            )

            memory_store.setdefault(agent_id, [])
            memory_store[agent_id] += [
                {"role": "user", "content": node_input},
                {"role": "assistant", "content": result.get("output", "")},
            ]
            results[node_id] = result

            await message_bus.emit("agent_complete", {
                "execution_id": execution_id,
                "agent_id": agent_id,
                "agent_name": agent_cfg.get("name", "Agent"),
                "node_id": node_id,
                "output": result.get("output", "")[:200],
                "tokens": result.get("tokens", 0),
                "success": result.get("success", False),
            })

            output_text = result.get("output", "")
            for nxt in node_data.get("next", []):
                target_id = nxt["target"]
                condition = (nxt.get("condition") or "always").strip().lower()

                proceed = True
                if condition.startswith("contains:"):
                    kw = condition.removeprefix("contains:").strip()
                    proceed = kw in output_text.lower()
                elif condition == "on_success":
                    proceed = result.get("success", False)
                elif condition == "on_failure":
                    proceed = not result.get("success", True)

                if proceed:
                    queue.append((target_id, output_text))

        final_output = ""
        for nid in reversed(list(visited)):
            if nid in results:
                final_output = results[nid].get("output", "")
                break

        total_tokens = sum(r.get("tokens", 0) for r in results.values())

        await message_bus.emit("execution_complete", {
            "execution_id": execution_id,
            "success": True,
            "output": final_output[:500],
            "total_tokens": total_tokens,
        })

        return {
            "success": True,
            "output": final_output,
            "node_results": results,
            "total_tokens": total_tokens,
            "cost": round(total_tokens * 0.000002, 6),
        }


workflow_engine = WorkflowEngine()
