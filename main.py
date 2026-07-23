import io
import os
import re
import sys
import threading
import time


# ─── Carrega .env (necessário fora do Docker) ─────────────────────
def _load_dotenv(path=".env"):
    """Carrega variáveis de um arquivo .env sem dependências externas."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


# ─── Filtro de ruído ALSA/JACK/PortAudio ──────────────────────────
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
os.dup2(_pipe_write, 2)
os.close(_pipe_write)


def _filter_stderr():
    buf = b""
    while True:
        try:
            data = os.read(_pipe_read, 4096)
            if not data:
                # EOF — escreve o que sobrou no buffer
                if buf:
                    text = buf.decode(errors="replace")
                    if not _NOISE_PATTERN.search(text):
                        os.write(_original_stderr_fd, (text + "\n").encode())
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace")
                if not _NOISE_PATTERN.search(text):
                    os.write(_original_stderr_fd, (text + "\n").encode())
        except (OSError, ValueError):
            if buf:
                text = buf.decode(errors="replace")
                if not _NOISE_PATTERN.search(text):
                    os.write(_original_stderr_fd, text.encode())
            break


_stderr_thread = threading.Thread(target=_filter_stderr, daemon=True)
_stderr_thread.start()

# ─── Imports de áudio ─────────────────────────────────────────────
import speech_recognition as sr
from openai import OpenAI

from chatbot import run_chatbot
from tts import speak_async

# ─── Constantes ───────────────────────────────────────────────────
WAKE_WORD = "oi bimbo"
WAKE_KEYWORDS = ["bimbo", "bimbu", "bimba"]  # variantes aceitas
AMBIENT_DURATION = 0.5
PHRASE_TIMEOUT = 5
WAKE_PAUSE = 0.3

# Thresholds para o chatbot (frases longas descrevendo reuniões)
CHAT_TIMEOUT = 10           # espera até 10s pelo início da fala
CHAT_PAUSE_THRESHOLD = 1.2  # pausa maior = não corta no meio da fala
CHAT_PHRASE_TIME_LIMIT = 15 # até 15s de fala contínua


def _contains_wake_word(transcripts):
    """Verifica se alguma transcrição contém a wake word ou variantes."""
    for text in transcripts:
        text = text.casefold().strip(".!? ")
        if WAKE_WORD in text:
            return True
        for kw in WAKE_KEYWORDS:
            if kw in text:
                return True
    return False


def _get_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Defina a variável de ambiente OPENAI_API_KEY.")
    return OpenAI(api_key=api_key)


def main():
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.5

    with sr.Microphone() as source:
        print("Calibrando ruído ambiente...")
        recognizer.adjust_for_ambient_noise(source, duration=AMBIENT_DURATION)
        print(f"Pronto. Energia base: {recognizer.energy_threshold:.0f}")

        # ── Loop principal: wake word → chatbot → repete ──
        while True:
            # ── Aguarda wake word ──
            while True:
                print("Estou ouvindo...")
                try:
                    audio = recognizer.listen(
                        source,
                        timeout=PHRASE_TIMEOUT,
                        phrase_time_limit=3,
                    )
                    result = recognizer.recognize_google(
                        audio, language="pt-BR", show_all=True,
                    )
                    transcripts = []
                    if isinstance(result, dict):
                        for alt in result.get("alternative", []):
                            t = alt.get("transcript", "")
                            if t:
                                transcripts.append(t)
                    elif isinstance(result, str):
                        transcripts.append(result)

                    if transcripts:
                        print(f"  Ouvido: {transcripts[0]}")
                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    continue
                except sr.RequestError as e:
                    print("Falha no serviço de reconhecimento:", e)
                    continue

                if _contains_wake_word(transcripts):
                    break

            # ── Wake word detectada ──
            print("Comando de ativação detectado")
            client = _get_openai_client()
            greeting = "Olá! Em que posso ajudar?"
            print("Bimbo:", greeting)
            speak_async(greeting, client)
            time.sleep(WAKE_PAUSE)

            # ── Loop do chatbot ──
            # Aumenta a pausa pra não cortar frases longas
            recognizer.pause_threshold = CHAT_PAUSE_THRESHOLD

            while True:
                print("Estou ouvindo...")
                try:
                    audio = recognizer.listen(
                        source,
                        timeout=CHAT_TIMEOUT,
                        phrase_time_limit=CHAT_PHRASE_TIME_LIMIT,
                    )
                except sr.WaitTimeoutError:
                    prompt = "Não ouvi nada. Ainda está aí?"
                    print("Bimbo:", prompt)
                    speak_async(prompt, client)
                    time.sleep(2)
                    continue

                audio_file = io.BytesIO(audio.get_wav_data())
                audio_file.name = "comando.wav"

                transcription = client.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe",
                    file=audio_file,
                    language="pt",
                )
                user_text = transcription.text.strip()
                if not user_text:
                    continue

                print("Você:", user_text)

                response_text, should_exit = run_chatbot(user_text, client)
                print("Bimbo:", response_text)
                speak_async(response_text, client)

                if should_exit:
                    break

            # Restaura threshold curto pra detecção da wake word
            recognizer.pause_threshold = 0.5

            print("Chatbot encerrado. Diga 'oi bimbo' para ativar novamente.")


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        if "No Default Input Device" in str(error):
            print("Nenhum microfone encontrado.")
            print("No macOS, rode fora do Docker: python main.py")
            print("No Raspberry Pi, conecte o microfone USB e tente novamente.")
            sys.exit(0)
        raise
