from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes.advance import advance_node
from app.graph.nodes.discovery import discovery_node
from app.graph.nodes.finalize import finalize_node
from app.graph.nodes.generator import dispatch_generation_pages, generate_page_node
from app.graph.nodes.scenario_pipeline import run_scenario_node
from app.graph.nodes.select_scenario import dispatch_scenarios, select_scenario_node
from app.graph.nodes.vision import after_vision_node, dispatch_vision_pages, vision_page_node
from app.graph.state import QAState


def build_graph(checkpointer: BaseCheckpointSaver):
    builder = StateGraph(QAState)

    builder.add_node("discovery", discovery_node)
    builder.add_node("vision_page", vision_page_node)
    builder.add_node("after_vision", after_vision_node)
    builder.add_node("generate_page", generate_page_node)
    builder.add_node("select_scenario", select_scenario_node)
    builder.add_node("run_scenario", run_scenario_node)
    builder.add_node("advance", advance_node)
    builder.add_node("finalize", finalize_node)

    builder.add_edge(START, "discovery")
    builder.add_conditional_edges(
        "discovery", dispatch_vision_pages, ["vision_page", "finalize"]
    )
    builder.add_edge("vision_page", "after_vision")
    builder.add_conditional_edges(
        "after_vision", dispatch_generation_pages, ["generate_page", "finalize"]
    )
    builder.add_edge("generate_page", "select_scenario")
    builder.add_conditional_edges(
        "select_scenario", dispatch_scenarios, ["run_scenario", "finalize"]
    )
    builder.add_edge("run_scenario", "advance")
    builder.add_edge("advance", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile(checkpointer=checkpointer)
