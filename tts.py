"""Síntese de voz com OpenAI TTS."""

import os
import subprocess
import sys
import tempfile
import threading

from openai import OpenAI

# Modelo e voz
TTS_MODEL = os.environ.get("TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("TTS_VOICE", "nova")


def _get_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Defina OPENAI_API_KEY no .env")
    return OpenAI(api_key=api_key)


def _get_player():
    """Retorna o comando do player de áudio nativo do sistema."""
    if sys.platform == "darwin":
        return ["afplay"]
    # Linux / Raspberry Pi (ALSA)
    return ["aplay", "-q"]


def _play_audio(audio_bytes):
    """Toca os bytes de áudio usando o player nativo do sistema."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        subprocess.run(
            _get_player() + [tmp_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    finally:
        os.unlink(tmp_path)


def speak(text, client=None):
    """Converte texto em fala e toca o áudio (bloqueante).

    Roda em thread separada pra não travar o loop principal.
    """
    if not text:
        return

    if client is None:
        client = _get_client()

    try:
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice=TTS_VOICE,
            input=text,
            response_format="wav",
        )
        _play_audio(response.content)
    except Exception as e:
        print(f"[TTS] Erro ao gerar fala: {e}")


def speak_async(text, client=None):
    """Versão não-bloqueante: toca o áudio em thread separada."""
    if not text:
        return
    thread = threading.Thread(target=speak, args=(text, client), daemon=True)
    thread.start()
