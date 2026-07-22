FROM python:3.13-slim-bookworm AS builder

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim-bookworm

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo \
    GOOGLE_TOKEN_PATH=/data/token.json \
    ALSA_CONFIG_PATH=/etc/asound.conf \
    JACK_NO_AUDIO_RESERVATION=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates flac libasound2 libportaudio2 tzdata \
    && rm -rf /var/lib/apt/lists/*

# Configuração ALSA mínima (suprime Unknown PCM warnings)
COPY asound.conf /etc/asound.conf

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY main.py google_calendar.py ./

# Filtra warnings inofensivos de ALSA/JACK/PortAudio
CMD ["sh", "-c", "python -u main.py 2>&1 | grep -v -e 'ALSA lib' -e 'Cannot connect to server' -e 'jack server' -e 'JackShmReadWrite' -e 'capture slave' -e 'unable to open slave'"]
