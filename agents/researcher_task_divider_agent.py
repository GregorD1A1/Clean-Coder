from langchain_openai.chat_models import ChatOpenAI
from langchain_mistralai.chat_models import ChatMistralAI
from langchain_community.chat_models import ChatOllama
from typing import TypedDict, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.prebuilt.tool_executor import ToolExecutor
from langgraph.graph import StateGraph
from dotenv import load_dotenv, find_dotenv
from langchain.tools.render import render_text_description
from langchain.tools import tool
from tools.tools import list_dir, see_file, see_image
from utilities.util_functions import check_file_contents, find_tool_xml, find_tool_json, print_wrapped, read_project_knowledge
from utilities.langgraph_common_functions import call_model, call_tool, ask_human, after_ask_human_condition
import os


load_dotenv(find_dotenv())
mistral_api_key = os.getenv("MISTRAL_API_KEY")


@tool
def final_response(files_to_work_on, reference_files):
    """That tool outputs list of files executor will need to change and paths to graphical patterns if some.
    Use that tool only when you 100% sure you found all the files Executor will need to modify.
    If not, do additional research.
    tool input:
    :param files_to_work_on: ["List", "of", "files"],
    :param reference_files: ["List", "of", "files"],
    """
    pass


tools = [list_dir, see_file]
rendered_tools = render_text_description(tools)

llm = ChatOpenAI(model="gpt-4-turbo-preview", temperature=0.2)
#llm = ChatOllama(model="openchat") #, temperature=0)
#llm = ChatMistralAI(api_key=mistral_api_key, model="mistral-large-latest")


class AgentState(TypedDict):
    messages: Sequence[BaseMessage]


bad_json_format_msg = ("Bad json format. Json should contain fields 'tool' and 'tool_input' "
                       "and enclosed with '```json', '```' tags.")

project_knowledge = read_project_knowledge()
tool_executor = ToolExecutor(tools)
system_message = SystemMessage(content=f"""
As a scrum master expert, you need is to divide general task in small unit tasks.
To do it you need to get context of the project first, so examine files thoroughly, prioritizing comprehensive checks. 
When you discover significant dependencies from one file to another, ensure to inspect both. 
Avoid recommending unseen or non-existent files in final response. Start from '/' directory.
After file research is done, write a complete list of unit tasks. Unit tasks should be related to code changes -
do not write any tests or documentation or other non-code tasks. For Every task write comprehensive and 
unambiguous description. Number of unit tasks may vary, from 1 in case of simple general task to 10 in case of 
complex one. Never invent things you don't know about the project - continue file research if you lack of some 
information to write a plan. 
If you want to propose some change, think first if it didn't already implemented in some project file.

You have access to following tools:
{rendered_tools}\n
First, provide step by step reasoning about what do you need to find in order to accomplish the task.
Next, generate response using json template: Choose only one tool to use.
```json
{{
    "tool": "$TOOL_NAME",
    "tool_input": "$TOOL_PARAMS",
}}
```
"""
)


# node functions
def call_model_researcher(state):
    state, response = call_model(state, llm)
    # safety mechanism for a bad json
    tool_call = response.tool_call
    if tool_call is None or "tool" not in tool_call:
        state["messages"].append(HumanMessage(content=bad_json_format_msg))
    return state


def call_tool_researcher(state):
    return call_tool(state, tool_executor)


# Logic for conditional edges
def after_agent_condition(state):
    last_message = state["messages"][-1]

    if last_message.content == bad_json_format_msg:
        return "agent"
    elif last_message.tool_call["tool"] == "final_response":
        return "human"
    else:
        return "tool"


# workflow definition
researcher_workflow = StateGraph(AgentState)

researcher_workflow.add_node("agent", call_model_researcher)
researcher_workflow.add_node("tool", call_tool_researcher)
researcher_workflow.add_node("human", ask_human)

researcher_workflow.set_entry_point("agent")

researcher_workflow.add_conditional_edges(
    "agent",
    after_agent_condition,
)
researcher_workflow.add_conditional_edges(
    "human",
    after_ask_human_condition,
)
researcher_workflow.add_edge("tool", "agent")

researcher = researcher_workflow.compile()


def research_task(task):
    print("Researcher starting its work")
    inputs = {"messages": [system_message, HumanMessage(content=f"General task: {task}")]}
    researcher_response = researcher.invoke(inputs, {"recursion_limit": 100})["messages"][-2]

    #tool_json = find_tool_xml(researcher_response.content)
    tool_json = find_tool_json(researcher_response.content)
    text_files = set(tool_json["tool_input"]["files_to_work_on"] + tool_json["tool_input"]["reference_files"])
    file_contents = check_file_contents(text_files)




    return text_files, file_contents

if __name__ == "__main__":
    task = """
    Let's create an additional page with searcher of memorial profiles. Searcher should be able to filter profiles by 
    year of birth, year of death, number of children. talk with appropriate backend endpoint.
    """

    research_task(task)