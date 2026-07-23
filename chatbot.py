"""Chatbot com detecção de intenção de agendamento de reunião."""

import json
import os

from openai import OpenAI

from google_calendar import create_event, delete_event_by_keyword, list_events

# Frases para encerrar o chatbot e voltar ao modo de espera
EXIT_PHRASES = ["tchau bimbo", "tchau", "adeus", "sair", "encerrar", "até logo"]


def _get_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Defina OPENAI_API_KEY no .env")
    return OpenAI(api_key=api_key)


def _should_exit(text):
    text = text.casefold().strip(".!? ")
    return any(phrase in text for phrase in EXIT_PHRASES)


def handle_message(user_text, client=None):
    """Processa uma mensagem do usuário.

    Returns:
        dict com:
          - type: "chat" | "schedule_event" | "exit"
          - text: resposta em português (type=chat)
          - event: dict do evento Google Calendar (type=schedule_event)
    """
    if client is None:
        client = _get_client()

    if _should_exit(user_text):
        return {"type": "exit", "text": "Até mais! Encerrando o assistente."}

    now_br = __import__("datetime").datetime.now(
        __import__("zoneinfo", fromlist=["ZoneInfo"]).ZoneInfo("America/Sao_Paulo")
    )

    system_prompt = (
        "Você é o Bimbo, um assistente de voz brasileiro que roda num Raspberry Pi. "
        "Você conversa de forma natural, amigável e objetiva em português.\n\n"
        "REGRAS IMPORTANTES:\n"
        "1. Se o usuário quer MARCAR/AGENDAR/CRIAR uma reunião, evento, compromisso "
        "ou lembrete no calendário, retorne APENAS:\n"
        '{"action":"schedule","event":{'
        '"summary":"Título","description":"Descrição",'
        '"start":{"dateTime":"AAAA-MM-DDTHH:MM:00-03:00","timeZone":"America/Sao_Paulo"},'
        '"end":{"dateTime":"AAAA-MM-DDTHH:MM:00-03:00","timeZone":"America/Sao_Paulo"}'
        '}}\n\n'
        "2. Se o usuário quer VER/LISTAR/CONSULTAR a agenda, eventos, "
        "compromissos ou perguntar 'o que tenho hoje/amanhã/essa semana', "
        "retorne APENAS:\n"
        '{"action":"list"}\n\n'
        "3. Se o usuário quer CANCELAR/DESMARCAR/REMOVER/DELETAR um evento "
        "ou reunião, retorne APENAS o JSON com a palavra-chave do evento:\n"
        '{"action":"delete","keyword":"palavra-chave do título"}\n\n'
        f"Data/hora atual: {now_br.isoformat()}\n"
        "Use essa data para interpretar 'hoje', 'amanhã', dias da semana.\n"
        "Duração padrão: 30 minutos se não especificada.\n"
        "Descrição padrão: 'Evento criado pelo Bimbo' se não especificada.\n\n"
        "4. Para QUALQUER outra mensagem (conversa, pergunta, saudação), "
        "responda APENAS com texto natural em português.\n\n"
        "5. Se o usuário disser 'tchau bimbo', 'tchau' ou se despedir, "
        "responda APENAS: {\"action\":\"exit\"}"
    )

    text_model = os.environ.get("OPENAI_TEXT_MODEL", "gpt-5.6-luna")

    response = client.responses.create(
        model=text_model,
        input=user_text,
        instructions=system_prompt,
    )

    raw = response.output_text.strip()

    # Tenta parse JSON (action = schedule ou exit)
    try:
        data = json.loads(raw)
        action = data.get("action", "")

        if action == "schedule":
            event = data.get("event", {})
            start = event.get("start", {})
            end = event.get("end", {})
            if not start.get("dateTime") or not end.get("dateTime"):
                return {
                    "type": "chat",
                    "text": "Não consegui entender a data e horário. "
                            "Pode repetir com mais detalhes?",
                }
            return {"type": "schedule_event", "event": event}

        if action == "delete":
            keyword = data.get("keyword", "")
            if not keyword:
                return {"type": "chat", "text": "Qual evento você quer cancelar?"}
            return {"type": "delete_event", "keyword": keyword}

        if action == "list":
            return {"type": "list_events"}

        if action == "exit":
            return {"type": "exit", "text": "Até mais! Encerrando o assistente."}

        # JSON mas ação desconhecida
        return {"type": "chat", "text": raw}

    except json.JSONDecodeError:
        # Resposta em texto natural
        return {"type": "chat", "text": raw}


def run_chatbot(user_text, client=None):
    """Executa um turno do chatbot: processa mensagem e age conforme intenção.

    Returns:
        (response_text, should_exit: bool)
    """
    if client is None:
        client = _get_client()

    result = handle_message(user_text, client)

    if result["type"] == "exit":
        return result.get("text", "Até mais!"), True

    if result["type"] == "schedule_event":
        event = result["event"]
        print("Agendando evento:", event.get("summary"))
        try:
            create_event(event)
            return (
                f"Prontinho! Reunião '{event.get('summary', 'sem título')}' "
                "agendada com sucesso. Mais alguma coisa?",
                False,
            )
        except Exception as e:
            return f"Erro ao agendar: {e}. Tente novamente.", False

    if result["type"] == "delete_event":
        keyword = result["keyword"]
        print(f"Cancelando evento com '{keyword}'...")
        try:
            removed = delete_event_by_keyword(keyword)
            if removed:
                return (
                    f"Evento '{removed}' cancelado com sucesso. "
                    "Mais alguma coisa?",
                    False,
                )
            return (
                f"Não encontrei nenhum evento com '{keyword}' "
                "nos próximos dias. Quer tentar com outro nome?",
                False,
            )
        except Exception as e:
            return f"Erro ao cancelar: {e}.", False

    if result["type"] == "list_events":
        try:
            events = list_events()
            if not events:
                return "Você não tem eventos próximos na agenda.", False

            lines = ["Aqui estão seus próximos eventos:"]
            for ev in events:
                summary = ev["summary"]
                start = ev["start"]
                # Formata a data/hora de forma legível
                try:
                    from datetime import datetime as dt
                    dt_start = dt.fromisoformat(start)
                    formatted = dt_start.strftime("%d/%m às %H:%M")
                except (ValueError, TypeError):
                    formatted = start
                lines.append(f"  • {summary} — {formatted}")
            return "\n".join(lines), False
        except Exception as e:
            return f"Erro ao consultar a agenda: {e}.", False

    # type == "chat"
    return result.get("text", "Hmm, não entendi. Pode repetir?"), False
