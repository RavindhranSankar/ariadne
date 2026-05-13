import os

from loguru import logger
from pipecat.runner.types import (
    DailyDialinRequest,
    DailyRunnerArguments,
    RunnerArguments,
    SmallWebRTCRunnerArguments,
)
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.daily.transport import DailyDialinSettings, DailyParams, DailyTransport
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport


def create_transport(runner_args: RunnerArguments) -> BaseTransport | None:
    match runner_args:
        case DailyRunnerArguments():
            daily_api_key = os.getenv("DAILY_API_KEY", "")
            daily_api_url = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")
            dialin_settings = None

            if runner_args.body and runner_args.body.get("dialin_settings"):
                request = DailyDialinRequest.model_validate(runner_args.body)
                daily_api_key = request.daily_api_key
                daily_api_url = request.daily_api_url
                dialin_settings = DailyDialinSettings(
                    call_id=request.dialin_settings.call_id,
                    call_domain=request.dialin_settings.call_domain,
                )

            return DailyTransport(
                runner_args.room_url,
                runner_args.token,
                "Pipecat Bot",
                params=DailyParams(
                    api_key=daily_api_key,
                    api_url=daily_api_url,
                    dialin_settings=dialin_settings,
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                ),
            )

        case SmallWebRTCRunnerArguments():
            webrtc_connection: SmallWebRTCConnection = runner_args.webrtc_connection
            return SmallWebRTCTransport(
                webrtc_connection=webrtc_connection,
                params=TransportParams(
                    audio_in_enabled=True,
                    audio_out_enabled=True,
                ),
            )

        case _:
            logger.error(f"Unsupported runner arguments type: {type(runner_args)}")
            return None
