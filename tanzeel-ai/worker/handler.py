"""
RunPod Serverless Worker for Quran ASR.
Receives audio (base64-encoded), transcribes using faster-whisper
with the tarteel-ai/whisper-base-ar-quran model (CTranslate2 format).
"""

import base64
import io
import tempfile
import os

import numpy as np
import runpod
from faster_whisper import WhisperModel

# Model is bundled in the Docker image at /model
MODEL_PATH = os.environ.get("MODEL_PATH", "/model/whisper-base-ar-quran-ct2")
DEVICE = os.environ.get("DEVICE", "cuda")
COMPUTE_TYPE = os.environ.get("COMPUTE_TYPE", "float16")

# Load model at startup (runs once per cold start)
print(f"Loading model from {MODEL_PATH} on {DEVICE} ({COMPUTE_TYPE})...")
model = WhisperModel(MODEL_PATH, device=DEVICE, compute_type=COMPUTE_TYPE)
print("Model loaded successfully.")


def decode_audio(audio_base64: str) -> str:
    """Decode base64 audio to a temporary WAV file path."""
    audio_bytes = base64.b64decode(audio_base64)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(audio_bytes)
    tmp.close()
    return tmp.name


def handler(event: dict) -> dict:
    """
    RunPod handler function.

    Input:
        event["input"]["audio"]: base64-encoded audio (WAV/PCM, 16kHz mono)
        event["input"]["language"]: language code (default: "ar")
        event["input"]["beam_size"]: beam size (default: 5)

    Output:
        {
            "text": "transcribed Arabic text",
            "segments": [{"start": 0.0, "end": 1.5, "text": "..."}],
            "words": [{"word": "...", "start": 0.0, "end": 0.5, "probability": 0.95}],
            "language": "ar",
            "language_probability": 0.99
        }
    """
    input_data = event.get("input", {})
    audio_base64 = input_data.get("audio")

    if not audio_base64:
        return {"error": "No audio data provided. Send base64-encoded audio in 'audio' field."}

    language = input_data.get("language", "ar")
    beam_size = input_data.get("beam_size", 5)

    audio_path = None
    try:
        audio_path = decode_audio(audio_base64)

        segments, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=beam_size,
            best_of=5,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 300,
                "threshold": 0.45,
            },
            word_timestamps=True,
            initial_prompt="بسم الله الرحمن الرحيم",
            condition_on_previous_text=True,
        )

        all_text_parts = []
        all_segments = []
        all_words = []

        for segment in segments:
            all_text_parts.append(segment.text.strip())
            all_segments.append({
                "start": round(segment.start, 2),
                "end": round(segment.end, 2),
                "text": segment.text.strip(),
                "avg_logprob": round(segment.avg_logprob, 4),
            })
            if segment.words:
                for word in segment.words:
                    all_words.append({
                        "word": word.word.strip(),
                        "start": round(word.start, 2),
                        "end": round(word.end, 2),
                        "probability": round(word.probability, 4),
                    })

        return {
            "text": " ".join(all_text_parts),
            "segments": all_segments,
            "words": all_words,
            "language": info.language,
            "language_probability": round(info.language_probability, 4),
        }

    except Exception as e:
        return {"error": str(e)}

    finally:
        if audio_path and os.path.exists(audio_path):
            os.unlink(audio_path)


runpod.serverless.start({"handler": handler})
