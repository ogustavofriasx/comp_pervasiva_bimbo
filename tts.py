"""Síntese de voz com OpenAI TTS."""

import os
import subprocess
import sys
import tempfile
import threading

from openai import OpenAI

# Modelo e voz
TTS_MODEL = os.environ.get("TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("TTS_VOICE", "onyx")

# Evento que indica se o TTS está tocando áudio
_busy = threading.Event()


def is_speaking():
    """Retorna True se o TTS ainda está tocando áudio."""
    return _busy.is_set()


def wait_silence(timeout=None):
    """Bloqueia até o TTS terminar de falar."""
    _busy.wait(timeout=timeout)


def _get_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Defina OPENAI_API_KEY no .env")
    return OpenAI(api_key=api_key)


def _get_player():
    if sys.platform == "darwin":
        return ["afplay"]
    return ["aplay", "-q"]


def _play_audio(audio_bytes):
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
    """Converte texto em fala e toca o áudio (bloqueante)."""
    if not text:
        _busy.clear()
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
        print(f"[TTS] Erro: {e}")
    finally:
        _busy.clear()


def speak_async(text, client=None):
    """Dispara TTS em background. Enquanto gera/toca áudio, is_speaking()=True.

    O caller deve esperar is_speaking()==False antes de abrir o microfone.
    """
    if not text:
        _busy.clear()
        return
    _busy.set()
    thread = threading.Thread(target=speak, args=(text, client), daemon=True)
    thread.start()
