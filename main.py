import io
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

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

    with sr.Microphone() as source:
        print("Estou ouvindo...")
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
        create_event(event_data)
    except json.JSONDecodeError as error:
        print("O modelo não retornou um JSON válido.")
        print("Erro:", error)


def main():
    while True:
        activate_command = listen_mic()
        if activate_command and activate_command.casefold().rstrip(".!?") == "oi bimbo":
            break

    print("Comando de ativação detectado")
    building_command()


if __name__ == "__main__":
    main()
