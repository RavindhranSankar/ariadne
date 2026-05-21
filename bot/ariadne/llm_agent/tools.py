from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from ariadne.ariadne_session import AriadneSession
from ariadne.ariadne_task_queue import AriadneTaskQueue
from ariadne.orchestrator import Orchestrator


def build_tools_schema() -> ToolsSchema:
    return ToolsSchema(standard_tools=[
        FunctionSchema(
            name="enqueue_task",
            description=(
                "Submit a background task. Always confirm with the caller what you're about "
                "to do before calling this. "
                "Use kind='investigation' for a read-only repo inspection. "
                "Use kind='write-doc' to generate a written document. "
                "Returns immediately with a task_id — you can continue conversing while the task runs."
            ),
            properties={
                "kind": {
                    "type": "string",
                    "enum": ["investigation", "write-doc"],
                    "description": "Type of task.",
                },
                "description": {
                    "type": "string",
                    "description": "Short human-readable label used in status updates.",
                },
                "problem_context": {
                    "type": "string",
                    "description": (
                        "Full context for the worker: problem framing, goal, constraints, "
                        "and the specific request. For write-doc, include all findings and "
                        "content the writer needs. Be specific."
                    ),
                },
            },
            required=["kind", "description", "problem_context"],
        ),
        FunctionSchema(
            name="dequeue_task",
            description=(
                "Remove a task that is still queued (not yet running). "
                "Use cancel_task instead if the task is already running."
            ),
            properties={
                "task_id": {"type": "string", "description": "The task_id to remove."},
            },
            required=["task_id"],
        ),
        FunctionSchema(
            name="get_task_status",
            description="Check the current status of a specific task.",
            properties={
                "task_id": {"type": "string", "description": "The task_id to check."},
            },
            required=["task_id"],
        ),
        FunctionSchema(
            name="get_active_tasks",
            description="List all currently queued or running tasks.",
            properties={
                "kind": {
                    "type": "string",
                    "enum": ["investigation", "write-doc"],
                    "description": "Optional filter by task kind.",
                },
            },
            required=[],
        ),
        FunctionSchema(
            name="get_task_results",
            description=(
                "Retrieve results for a completed task. "
                "Call this after receiving a task completion notice. "
                "Returns voice_summary (speak this first) and context "
                "(use for deeper follow-up or as input to a write-doc task)."
            ),
            properties={
                "task_id": {"type": "string", "description": "The task_id to retrieve results for."},
            },
            required=["task_id"],
        ),
        FunctionSchema(
            name="cancel_task",
            description=(
                "Cancel a running task. "
                "Use dequeue_task instead if the task is still queued."
            ),
            properties={
                "task_id": {"type": "string", "description": "The task_id to cancel."},
            },
            required=["task_id"],
        ),
    ])


def register_tools(
    llm,
    task_queue: AriadneTaskQueue,
    orchestrator: Orchestrator,
    session: AriadneSession,
):
    def _log(event: str, data: dict):
        session.logger.log(
            "conversation-agent",
            event,
            data,
            turn_id=session.current_turn_id,
        )

    async def handle_enqueue_task(params: FunctionCallParams):
        args = params.arguments
        kind = args.get("kind", "")
        description = args.get("description", "")
        problem_context = args.get("problem_context", "")
        result = task_queue.enqueue(kind, description, problem_context)
        _log("conversation-agent.tool_call", {
            "tool": "enqueue_task",
            "args": {"kind": kind, "description": description, "problem_context": problem_context},
            "result": result,
        })
        await params.result_callback(result)

    async def handle_dequeue_task(params: FunctionCallParams):
        task_id = params.arguments.get("task_id", "")
        result = task_queue.dequeue(task_id)
        _log("conversation-agent.tool_call", {
            "tool": "dequeue_task",
            "args": {"task_id": task_id},
            "result": result,
        })
        await params.result_callback(result)

    async def handle_get_task_status(params: FunctionCallParams):
        result = task_queue.get_task_status(params.arguments.get("task_id", ""))
        await params.result_callback(result)

    async def handle_get_active_tasks(params: FunctionCallParams):
        kind = params.arguments.get("kind")
        result = task_queue.get_active_tasks(kind)
        await params.result_callback(result)

    async def handle_get_task_results(params: FunctionCallParams):
        task_id = params.arguments.get("task_id", "")
        result = task_queue.get_task_results(task_id)
        _log("conversation-agent.tool_call", {
            "tool": "get_task_results",
            "args": {"task_id": task_id},
            "result": {k: v for k, v in result.items() if k != "context"},  # skip large payload
        })
        await params.result_callback(result)

    async def handle_cancel_task(params: FunctionCallParams):
        task_id = params.arguments.get("task_id", "")
        result = task_queue.cancel(task_id)
        await orchestrator.cancel_worker(task_id)
        _log("conversation-agent.tool_call", {
            "tool": "cancel_task",
            "args": {"task_id": task_id},
            "result": result,
        })
        await params.result_callback(result)

    # enqueue_task is fire-and-forget: LLM continues immediately after the tool resolves.
    llm.register_function("enqueue_task", handle_enqueue_task, cancel_on_interruption=False)
    llm.register_function("dequeue_task", handle_dequeue_task)
    llm.register_function("get_task_status", handle_get_task_status)
    llm.register_function("get_active_tasks", handle_get_active_tasks)
    llm.register_function("get_task_results", handle_get_task_results)
    llm.register_function("cancel_task", handle_cancel_task)
