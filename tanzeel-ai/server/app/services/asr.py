"""ASR client for RunPod serverless inference."""

import base64

import httpx

from ..config import settings

RUNPOD_URL = f"https://api.runpod.ai/v2/{settings.runpod_endpoint_id}/runsync"


async def transcribe_audio(audio_bytes: bytes) -> dict:
    """
    Send audio to RunPod serverless endpoint for transcription.

    Args:
        audio_bytes: Raw audio file bytes (WAV/M4A)

    Returns:
        dict with keys: text, segments, words, language, language_probability
    """
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            RUNPOD_URL,
            headers={
                "Authorization": f"Bearer {settings.runpod_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "input": {
                    "audio": audio_base64,
                    "language": "ar",
                    "beam_size": 5,
                }
            },
        )
        response.raise_for_status()
        result = response.json()

        if result.get("status") == "FAILED":
            raise RuntimeError(f"RunPod inference failed: {result.get('error', 'Unknown error')}")

        output = result.get("output", {})

        if "error" in output:
            raise RuntimeError(f"ASR error: {output['error']}")

        return output
