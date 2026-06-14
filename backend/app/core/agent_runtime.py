import operator
import logging
from typing import Annotated, Any, Dict, List, Optional, Sequence
from typing_extensions import TypedDict

from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from .tools import AVAILABLE_TOOLS
from .message_bus import message_bus

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    agent_id: str
    agent_name: str
    execution_id: str
    iteration_count: int


def _get_llm(model: str, max_tokens: int):
    if model.startswith("claude"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, max_tokens=max_tokens)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=model or "gpt-4o-mini", max_tokens=max_tokens)


def create_agent_graph(agent_config: Dict):
    model = agent_config.get("model", "gpt-4o-mini")
    system_prompt = agent_config.get("system_prompt", "You are a helpful AI assistant.")
    tool_names = agent_config.get("tools") or []
    guardrails = agent_config.get("guardrails") or {}
    max_tokens = guardrails.get("max_tokens", 2000)
    max_iterations = guardrails.get("max_iterations", 10)

    tools = [AVAILABLE_TOOLS[t] for t in tool_names if t in AVAILABLE_TOOLS]
    llm = _get_llm(model, max_tokens)
    bound_llm = llm.bind_tools(tools) if tools else llm

    async def agent_node(state: AgentState) -> Dict:
        msgs = list(state["messages"])
        if not any(isinstance(m, SystemMessage) for m in msgs):
            msgs = [SystemMessage(content=system_prompt)] + msgs

        if state.get("iteration_count", 0) >= max_iterations:
            return {
                "messages": [AIMessage(content="Reached maximum iterations.")],
                "iteration_count": state.get("iteration_count", 0),
            }

        response = await bound_llm.ainvoke(msgs)

        tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            tokens = response.usage_metadata.get("total_tokens", 0)

        await message_bus.emit("agent_message", {
            "agent_id": state["agent_id"],
            "agent_name": state["agent_name"],
            "execution_id": state["execution_id"],
            "content": response.content or "[tool call]",
            "tokens": tokens,
        })

        return {
            "messages": [response],
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)

    if tools:
        graph.add_node("tools", ToolNode(tools))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", tools_condition)
        graph.add_edge("tools", "agent")
    else:
        graph.add_edge(START, "agent")
        graph.add_edge("agent", END)

    return graph.compile()


async def run_agent(
    agent_config: Dict,
    messages: List[Dict],
    execution_id: str,
    memory: Optional[List] = None,
) -> Dict[str, Any]:
    lc_messages: List[BaseMessage] = []

    window = (agent_config.get("memory_config") or {}).get("window_size", 10)
    if memory:
        for m in memory[-window:]:
            cls = HumanMessage if m.get("role") == "user" else AIMessage
            lc_messages.append(cls(content=m["content"]))

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))
        elif role == "system":
            lc_messages.append(SystemMessage(content=content))

    if not lc_messages:
        lc_messages = [HumanMessage(content="Hello")]

    graph = create_agent_graph(agent_config)

    initial_state: AgentState = {
        "messages": lc_messages,
        "agent_id": agent_config.get("id", "unknown"),
        "agent_name": agent_config.get("name", "Agent"),
        "execution_id": execution_id,
        "iteration_count": 0,
    }

    try:
        final_state = await graph.ainvoke(initial_state)
        last = final_state["messages"][-1]
        total_tokens = sum(
            (getattr(m, "usage_metadata", None) or {}).get("total_tokens", 0)
            for m in final_state["messages"]
        )
        return {
            "success": True,
            "output": last.content or "[no response]",
            "tokens": total_tokens,
            "iterations": final_state.get("iteration_count", 0),
        }
    except Exception as exc:
        logger.error("Agent execution error: %s", exc)
        return {"success": False, "output": f"Error: {exc}", "tokens": 0, "iterations": 0}
