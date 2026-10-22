"""Synchronous port of LangChain Open Deep Research's researcher subgraph.

Derived from deep_researcher.py at the revision in provenance.json (MIT).
The researcher -> researcher_tools -> researcher/compress_research topology,
iteration limit, tool observations and completion handling are retained.
Model/tool dependencies are injected; compression is a lossless handoff here.
See README.md for the explicit differences from upstream.
"""
from typing import Annotated, TypedDict
import operator

from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command


class ResearcherState(TypedDict, total=False):
    researcher_messages: Annotated[list, operator.add]
    research_topic: dict
    tool_call_iterations: int
    research_output: dict


def build_researcher_subgraph(decide, tools, compress, *, max_iterations=3,
                              checkpoint=None, progress=None):
    """Inject project policies without importing upstream report/supervisor code."""
    def researcher(state):
        if progress: progress('researcher')
        response = decide(state)
        return Command(goto='researcher_tools', update={
            'researcher_messages': [response],
            'tool_call_iterations': state.get('tool_call_iterations', 0) + 1})

    def researcher_tools(state):
        if progress: progress('researcher_tools')
        response = state['researcher_messages'][-1]
        if not response.tool_calls:
            return Command(goto='compress_research')
        observations = []
        complete = False
        # One batch action per decision. A batch can perform independent I/O
        # concurrently inside the project tool, with ordered checkpoints.
        for call in response.tool_calls:
            name = call['name']
            if name == 'ResearchComplete':
                complete = True
                result = {'status': 'handoff'}
            else:
                result = tools[name](**call['args'])
            import json
            observations.append(ToolMessage(content=json.dumps(result, ensure_ascii=False),
                                            name=name, tool_call_id=call['id']))
            if checkpoint: checkpoint()
        return Command(goto='compress_research' if complete or
                       state['tool_call_iterations'] >= max_iterations else 'researcher',
                       update={'researcher_messages': observations})

    def compress_research(state):
        if progress: progress('compress_research')
        return {'research_output': compress(state)}

    builder = StateGraph(ResearcherState)
    builder.add_node('researcher', researcher, destinations=('researcher_tools',))
    builder.add_node('researcher_tools', researcher_tools,
                     destinations=('researcher', 'compress_research'))
    builder.add_node('compress_research', compress_research)
    builder.add_edge(START, 'researcher')
    builder.add_edge('compress_research', END)
    return builder.compile()
