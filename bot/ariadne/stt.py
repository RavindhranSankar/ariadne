import os

from pipecat.services.deepgram.stt import DeepgramSTTService


def create_stt_service() -> DeepgramSTTService:
    return DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
