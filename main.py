import io
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo


# ─── Filtro de ruído ALSA/JACK/PortAudio ──────────────────────────
# Bibliotecas C (libasound, PortAudio, JACK) escrevem warnings direto
# no file descriptor 2, bypassando sys.stderr. Redirecionamos o fd 2
# via pipe e filtramos em thread.
_NOISE_PATTERN = re.compile(
    r"(ALSA lib|Cannot connect to server|jack server|JackShmReadWrite|"
    r"capture slave|unable to open slave|Unknown PCM|"
    r"Unable to find definition|Evaluate error|"
    r"snd_func_refer|snd_config_expand|snd_pcm_open_noupdate|"
    r"snd_pcm_asym_open|snd_pcm_dmix_open|snd_ctl_open_noupdate|"
    r"Invalid CTL)"
)

_original_stderr_fd = os.dup(2)
_pipe_read, _pipe_write = os.pipe()
os.dup2(_pipe_write, 2)  # redireciona fd 2 para o pipe
os.close(_pipe_write)


def _filter_stderr():
    """Lê do pipe e escreve no stderr original apenas linhas não-ruidosas."""
    buf = b""
    while True:
        try:
            data = os.read(_pipe_read, 4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace")
                if not _NOISE_PATTERN.search(text):
                    os.write(_original_stderr_fd, (text + "\n").encode())
        except (OSError, ValueError):
            break


_stderr_thread = threading.Thread(target=_filter_stderr, daemon=True)
_stderr_thread.start()

# ─── Imports de áudio (emitem ruído C na inicialização) ───────────
import speech_recognition as sr
from openai import OpenAI

from google_calendar import create_event


def openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Defina a variável de ambiente OPENAI_API_KEY.")
    return OpenAI(api_key=api_key)


def listen_mic():
    mic = sr.Recognizer()

    with sr.Microphone() as source:
        print("Estou ouvindo...")
        mic.adjust_for_ambient_noise(source)
        audio = mic.listen(source)

    try:
        return mic.recognize_google(audio, language="pt-BR")
    except sr.UnknownValueError:
        print("Não entendi o que você disse.")
        return None
    except sr.RequestError as error:
        print("Falha no serviço de reconhecimento:", error)
        return None


def building_command():
    client = openai_client()
    mic = sr.Recognizer()

    # Pequena pausa para o usuário começar a falar o comando
    time.sleep(0.5)

    with sr.Microphone() as source:
        print("Pode falar o comando...")
        mic.adjust_for_ambient_noise(source)
        audio = mic.listen(source)

    audio_file = io.BytesIO(audio.get_wav_data())
    audio_file.name = "comando.wav"

    transcription = client.audio.transcriptions.create(
        model="gpt-4o-mini-transcribe",
        file=audio_file,
        language="pt",
    )

    texto = transcription.text
    print("Comando:", texto)
    execute_command(texto)


def execute_command(command):
    client = openai_client()
    now = datetime.now(ZoneInfo("America/Sao_Paulo"))

    input_text = f"""
    Analise o comando abaixo e retorne somente um JSON válido.

    Data e hora atuais:
    {now.isoformat()}

    Comando:
    {command}

    Regras:
    - Não invente informações que não estejam no comando.
    - Interprete palavras como "hoje", "amanhã" e dias da semana
    usando a data atual informada.
    - Caso a duração não seja informada, use 30 minutos.
    - Caso a descrição não seja informada, use
    "Evento criado pelo assistente de voz".
    - Caso a data não seja informada, adicione "data" em "missingFields".
    - Caso o horário não seja informado, adicione "horário" em "missingFields".
    - Para informações ausentes, use null.
    - Use o fuso horário "America/Sao_Paulo".
    - Retorne somente JSON, sem Markdown ou explicações.
    - IMPORTANTE: Se o comando não estiver em português ou for ininteligível,
      retorne um JSON com "summary": "ininteligível" e "missingFields": ["comando"].

    Formato esperado:

    {{
        "summary": "Título do evento",
        "description": "Descrição do evento",
        "start": {{
            "dateTime": "2026-07-21T15:00:00-03:00",
            "timeZone": "America/Sao_Paulo"
        }},
        "end": {{
            "dateTime": "2026-07-21T15:30:00-03:00",
            "timeZone": "America/Sao_Paulo"
        }},
        "missingFields": []
    }}
    """

    response = client.responses.create(
        model=os.environ.get("OPENAI_TEXT_MODEL", "gpt-5.6-luna"),
        input=input_text,
    )

    print("Resposta bruta:", response.output_text)

    try:
        event_data = json.loads(response.output_text)
    except json.JSONDecodeError as error:
        print("O modelo não retornou um JSON válido.")
        print("Erro:", error)
        return

    # Valida se o evento tem os campos obrigatórios
    missing = event_data.get("missingFields", [])
    if missing:
        print(f"Comando incompleto — campos ausentes: {missing}")
        print("Diga o comando novamente com data e horário.")
        return

    start = event_data.get("start", {})
    if not start.get("dateTime"):
        print("Evento sem data/hora — ignorado. Fale novamente.")
        return

    try:
        create_event(event_data)
    except Exception as error:
        print("Erro ao criar evento no Google Calendar:", error)


def main():
    while True:
        activate_command = listen_mic()
        if activate_command and activate_command.casefold().rstrip(".!?") == "oi bimbo":
            break

    print("Comando de ativação detectado")
    building_command()


if __name__ == "__main__":
    main()
