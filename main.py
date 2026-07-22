import io
import json
import os
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo


# ─── Filtro de ruído ALSA/JACK/PortAudio ──────────────────────────
# As bibliotecas de áudio emitem warnings no stderr via C (libasound,
# PortAudio, JACK). Esse filtro remove essas linhas sem afetar
# mensagens reais de erro do Python.
_NOISE_PATTERN = re.compile(
    r"(ALSA lib|Cannot connect to server|jack server|JackShmReadWrite|"
    r"capture slave|unable to open slave|Unknown PCM|"
    r"Unable to find definition|Evaluate error|"
    r"snd_func_refer|snd_config_expand|snd_pcm_open_noupdate|"
    r"snd_pcm_asym_open|snd_pcm_dmix_open)"
)


class _NoiseFilter:
    """Wrapper que filtra ruído de áudio do stderr."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        if not _NOISE_PATTERN.search(text):
            return self._stream.write(text)
        return len(text)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


sys.stderr = _NoiseFilter(sys.stderr)

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
