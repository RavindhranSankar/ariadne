import asyncio

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMMessagesAppendFrame, LLMRunFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transports.base_transport import BaseTransport

from ariadne.ariadne_session import AriadneSession
from ariadne.ariadne_task_queue import AriadneTaskQueue
from ariadne.coding_agent.doc_writer import DocWriter
from ariadne.coding_agent.handlers import InvestigationTaskHandler, WriteDocTaskHandler
from ariadne.coding_agent.investigator import Investigator
from ariadne.config import AriadneConfig
from ariadne.debug_server import (
    register_session,
    start_debug_server,
    stop_debug_server,
    unregister_session,
)
from ariadne.idle_timeout import IdleTimeout
from ariadne.llm_agent.agent import LLMAgent
from ariadne.llm_agent.tools import register_tools
from ariadne.orchestrator import Orchestrator
from ariadne.stt import create_stt_service
from ariadne.task_executor import TaskExecutor
from ariadne.tts import create_tts_service

GOODBYE_MESSAGE = "Thank you for using Ariadne. Wishing you well for the rest of the day."


def _build_greeting_label(config: AriadneConfig) -> str:
    label = f"Ariadne, {config.user_name}'s coding assistant" if config.user_name else "Ariadne"
    if config.project_name:
        label += f", working on {config.project_name}"
    return label


async def run_bot(transport: BaseTransport):
    logger.info("Starting bot")

    config = AriadneConfig.from_env()
    session = AriadneSession()
    task_ref: dict = {"task": None}

    llm_agent = LLMAgent(config)
    stt = create_stt_service()
    tts = create_tts_service()

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        llm_agent.context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    task_queue = AriadneTaskQueue(max_active=config.task_queue_max)
    investigator = Investigator(repo_path=config.repo_path, session=session, codex_timeout_seconds=config.codex_timeout_seconds)
    doc_writer = DocWriter(session=session, repo_path=config.repo_path)
    task_executor = TaskExecutor([
        InvestigationTaskHandler(investigator=investigator, session=session),
        WriteDocTaskHandler(doc_writer=doc_writer),
    ])

    # ------------------------------------------------------------------
    # Task event handler: inject completion/failure notice into LLM context.
    # Pipecat's frame queue ensures this is processed after the current
    # LLM response completes — no custom safe-boundary detection needed.
    # ------------------------------------------------------------------

    async def on_task_event(event: dict):
        pipeline_task = task_ref["task"]
        if pipeline_task is None:
            return

        task_id = event["task_id"]

        if event["status"] == "done":
            notification = (
                f"[ARIADNE RUNTIME] Task {task_id} completed. "
                f"Results are available via get_task_results('{task_id}'). "
                "Mention this briefly at a natural transition point. "
                "Do not derail the current answer unless the caller is clearly waiting."
            )
        else:
            failure_reason = event.get("failure_reason", "unknown")
            message = event.get("message", "")
            notification = (
                f"[ARIADNE RUNTIME] Task {task_id} failed (reason: {failure_reason}). "
                f"{message} Inform the caller briefly and offer to retry if appropriate."
            )

        await pipeline_task.queue_frames([
            LLMMessagesAppendFrame(
                messages=[{"role": "user", "content": notification}],
                run_llm=True,
            )
        ])

    orchestrator = Orchestrator(
        task_queue=task_queue,
        task_executor=task_executor,
        session=session,
        on_task_event=on_task_event,
        task_timeout_seconds=config.task_timeout_seconds,
    )

    register_tools(llm_agent.service, task_queue, orchestrator, session)

    # ------------------------------------------------------------------
    # STT: fires once per complete VAD-bounded user turn.
    # ------------------------------------------------------------------

    @user_aggregator.event_handler("on_user_turn_stopped")
    async def on_user_turn_stopped(aggregator, strategy, message):
        text = message.content.strip()
        if not text:
            return
        turn_id = session.next_turn_id()
        session.mark_human_activity()
        idle_timeout.reset()
        session.logger.log(
            "stt",
            "stt.transcript.final",
            {"text": text, "finalized": True},
            turn_id=turn_id,
        )
        session.logger.append_transcript_user(turn_id, text)

    # ------------------------------------------------------------------
    # LLM response logging: fires when the assistant finishes a turn.
    # ------------------------------------------------------------------

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(aggregator, message):
        text = message.content.strip()
        if not text:
            return
        session.logger.log(
            "conversation-agent",
            "conversation-agent.response",
            {"text": text, "interrupted": message.interrupted},
            turn_id=session.current_turn_id,
        )
        session.logger.log(
            "tts",
            "tts.request",
            {"text": text},
            turn_id=session.current_turn_id,
        )
        session.logger.append_transcript_assistant(session.current_turn_id, text)

    # ------------------------------------------------------------------
    # Idle timeout
    # ------------------------------------------------------------------

    async def on_idle_timeout():
        task = task_ref["task"]
        if task is None or session.status == "closed":
            return
        logger.info("Idle timeout: speaking goodbye and closing session")
        session.logger.log("daily", "daily.session_closing", {"reason": "idle_timeout"})
        await task.queue_frames([TTSSpeakFrame(text=GOODBYE_MESSAGE)])
        await asyncio.sleep(5)
        session.close("idle_timeout")
        await task.cancel()

    idle_timeout = IdleTimeout(
        on_timeout=on_idle_timeout,
        timeout_seconds=config.idle_timeout_seconds,
    )

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    pipeline = Pipeline([
        transport.input(),
        stt,
        user_aggregator,
        llm_agent.service,
        tts,
        transport.output(),
        assistant_aggregator,
    ])

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[],
    )
    task_ref["task"] = task

    @task.rtvi.event_handler("on_client_ready")
    async def on_client_ready(rtvi):
        llm_agent.context.add_message({"role": "user", "content": "Please introduce yourself."})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")
        session.logger.log("daily", "daily.session_started", {"session_id": session.session_id})
        session.logger.log("daily", "daily.client_connected", {"client": str(client)})
        session.logger.write_session_json(session)
        idle_timeout.start()
        await asyncio.sleep(1.0)
        llm_agent.context.add_message(
            {
                "role": "user",
                "content": (
                    "The caller has just joined the phone call. "
                    f"Greet them briefly as {_build_greeting_label(config)} and ask what they "
                    "want to think through. Keep it to one short sentence."
                ),
            }
        )
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        idle_timeout.cancel()
        session.logger.log(
            "daily",
            "daily.client_disconnected",
            {"client": str(client), "reason": "participant_left"},
        )
        session.close("participant_left")
        await task.cancel()

    # ------------------------------------------------------------------
    # Debug server + orchestrator
    # ------------------------------------------------------------------

    register_session(session)
    debug_runner = None
    try:
        debug_runner = await start_debug_server()
    except Exception as exc:
        logger.warning(f"Debug server failed to start: {exc}")

    orchestrator_task = asyncio.create_task(orchestrator.run())

    try:
        runner = PipelineRunner(handle_sigint=False)
        await runner.run(task)
    finally:
        orchestrator_task.cancel()
        try:
            await orchestrator_task
        except asyncio.CancelledError:
            pass
        unregister_session(session)
        await stop_debug_server(debug_runner)
