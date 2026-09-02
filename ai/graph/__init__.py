"""Week 6 evidence-grounded LangGraph pipeline."""
from langgraph.graph import END,START,StateGraph
from .nodes import classify_node,draft_node,retrieve_node,route_node,validate_citations_node
from .state import TicketState
_builder=StateGraph(TicketState)
for name,node in (("classify",classify_node),("route",route_node),("retrieve",retrieve_node),("draft",draft_node),("validate_citations",validate_citations_node)): _builder.add_node(name,node)
_builder.add_edge(START,"classify"); _builder.add_edge("classify","route"); _builder.add_edge("route","retrieve"); _builder.add_edge("retrieve","draft"); _builder.add_edge("draft","validate_citations"); _builder.add_edge("validate_citations",END)
graph=_builder.compile()
