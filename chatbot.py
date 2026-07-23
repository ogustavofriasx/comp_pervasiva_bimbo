"""Chatbot com detecção de intenção de agendamento de reunião."""

import json
import os
from collections import deque

from openai import OpenAI

from google_calendar import create_event, delete_event_by_keyword, list_events, update_event_by_keyword

# Frases para encerrar o chatbot e voltar ao modo de espera
EXIT_PHRASES = ["tchau bimbo", "tchau", "adeus", "sair", "encerrar", "até logo"]

# Contexto: últimas N mensagens (usuário + assistente)
MAX_CONTEXT = 6


class ChatContext:
    """Histórico leve das últimas mensagens para dar contexto ao modelo."""

    def __init__(self, max_messages=MAX_CONTEXT):
        self._messages = deque(maxlen=max_messages)

    def add(self, role, text):
        self._messages.append({"role": role, "content": text})

    def clear(self):
        self._messages.clear()

    def as_text(self):
        """Retorna o histórico formatado para incluir no prompt."""
        if not self._messages:
            return ""
        lines = ["[Conversa anterior:]"]
        for msg in self._messages:
            role = "Você" if msg["role"] == "user" else "Bimbo"
            lines.append(f"{role}: {msg['content']}")
        lines.append("")
        return "\n".join(lines)


# Contexto global da sessão
_context = ChatContext()


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
        dict com type, text, event, keyword, etc.
    """
    if client is None:
        client = _get_client()

    if _should_exit(user_text):
        _context.clear()
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
        "3. Se o usuário quer ALTERAR/MUDAR/EDITAR/REAGENDAR/ADIAR um evento "
        "ou reunião, retorne APENAS o JSON com palavra-chave e NOVOS horários:\n"
        '{"action":"update","keyword":"palavra-chave",'
        '"start":"AAAA-MM-DDTHH:MM:00-03:00","end":"AAAA-MM-DDTHH:MM:00-03:00"}\n\n'
        "4. Se o usuário quer CANCELAR/DESMARCAR/REMOVER/DELETAR um evento "
        "ou reunião, retorne APENAS o JSON com a palavra-chave do evento:\n"
        '{"action":"delete","keyword":"palavra-chave do título"}\n\n'
        f"Data/hora atual: {now_br.isoformat()}\n"
        "Use essa data para interpretar 'hoje', 'amanhã', dias da semana.\n"
        "Duração padrão: 30 minutos se não especificada.\n"
        "Descrição padrão: 'Evento criado pelo Bimbo' se não especificada.\n\n"
        "5. Para QUALQUER outra mensagem (conversa, pergunta, saudação), "
        "responda APENAS com texto natural em português.\n\n"
        "6. Se o usuário disser 'tchau bimbo', 'tchau' ou se despedir, "
        "responda APENAS: {\"action\":\"exit\"}\n\n"
        "Use o contexto da conversa anterior para entender pronomes, "
        "referências e manter coerência nas respostas."
    )

    # Monta input com contexto
    context_text = _context.as_text()
    if context_text:
        full_input = f"{context_text}[Mensagem atual]\n{user_text}"
    else:
        full_input = user_text

    text_model = os.environ.get("OPENAI_TEXT_MODEL", "gpt-5.6-luna")

    response = client.responses.create(
        model=text_model,
        input=full_input,
        instructions=system_prompt,
    )

    raw = response.output_text.strip()

    # Parse JSON
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

        if action == "update":
            keyword = data.get("keyword", "")
            new_start = data.get("start", "")
            new_end = data.get("end", "")
            if not keyword or not new_start or not new_end:
                return {"type": "chat", "text": "Não entendi qual evento ou o novo horário. Pode repetir?"}
            return {"type": "update_event", "keyword": keyword, "start": new_start, "end": new_end}

        if action == "delete":
            keyword = data.get("keyword", "")
            if not keyword:
                return {"type": "chat", "text": "Qual evento você quer cancelar?"}
            return {"type": "delete_event", "keyword": keyword}

        if action == "list":
            return {"type": "list_events"}

        if action == "exit":
            _context.clear()
            return {"type": "exit", "text": "Até mais! Encerrando o assistente."}

        return {"type": "chat", "text": raw}

    except json.JSONDecodeError:
        return {"type": "chat", "text": raw}


def run_chatbot(user_text, client=None):
    """Executa um turno do chatbot: processa mensagem e age conforme intenção.

    Mantém contexto da conversa automaticamente.
    """
    if client is None:
        client = _get_client()

    # Adiciona mensagem do usuário ao contexto
    _context.add("user", user_text)

    result = handle_message(user_text, client)

    if result["type"] == "exit":
        return result.get("text", "Até mais!"), True

    if result["type"] == "schedule_event":
        event = result["event"]
        print("Agendando evento:", event.get("summary"))
        try:
            create_event(event)
            text = (
                f"Prontinho! Reunião '{event.get('summary', 'sem título')}' "
                "agendada com sucesso. Mais alguma coisa?"
            )
        except Exception as e:
            text = f"Erro ao agendar: {e}. Tente novamente."
        _context.add("assistant", text)
        return text, False

    if result["type"] == "update_event":
        keyword = result["keyword"]
        print(f"Reagendando '{keyword}' para {result['start']}...")
        try:
            updated = update_event_by_keyword(keyword, result["start"], result["end"])
            if updated:
                text = f"Evento '{updated}' reagendado com sucesso. Mais alguma coisa?"
            else:
                text = f"Não encontrei nenhum evento com '{keyword}'. Quer tentar com outro nome?"
        except Exception as e:
            text = f"Erro ao reagendar: {e}."
        _context.add("assistant", text)
        return text, False

    if result["type"] == "delete_event":
        keyword = result["keyword"]
        print(f"Cancelando evento com '{keyword}'...")
        try:
            removed = delete_event_by_keyword(keyword)
            if removed:
                text = f"Evento '{removed}' cancelado com sucesso. Mais alguma coisa?"
            else:
                text = f"Não encontrei nenhum evento com '{keyword}'. Quer tentar com outro nome?"
        except Exception as e:
            text = f"Erro ao cancelar: {e}."
        _context.add("assistant", text)
        return text, False

    if result["type"] == "list_events":
        try:
            events = list_events()
            if not events:
                text = "Você não tem eventos próximos na agenda."
            else:
                lines = ["Aqui estão seus próximos eventos:"]
                for ev in events:
                    summary = ev["summary"]
                    start = ev["start"]
                    try:
                        from datetime import datetime as dt
                        dt_start = dt.fromisoformat(start)
                        formatted = dt_start.strftime("%d/%m às %H:%M")
                    except (ValueError, TypeError):
                        formatted = start
                    lines.append(f"  • {summary} — {formatted}")
                text = "\n".join(lines)
        except Exception as e:
            text = f"Erro ao consultar a agenda: {e}."
        _context.add("assistant", text)
        return text, False

    # type == "chat"
    text = result.get("text", "Hmm, não entendi. Pode repetir?")
    _context.add("assistant", text)
    return text, False
