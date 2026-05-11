"""
SDR — Análise de texto para detectar keywords de conversão/qualificação.
Baseado na lógica do workflow n8n: tag [FIM_ATENDIMENTO] e padrões de reunião.
"""

# Emitidos pelo próprio agente LLM quando detecta qualificação
_AGENT_TAGS = [
    "[fim_atendimento",
    "[fim atendimento",
    "fim_atendimento",
    "lead qualificado",
]

# Padrões de reunião/agendamento confirmado
_MEETING_PATTERNS = [
    "link da reunião",
    "link reunião",
    "meet.google",
    "zoom.us",
    "teams.microsoft",
    "calendly.com",
    "reunião marcada",
    "reunião confirmada",
    "reunião agendada",
    "agendamento confirmado",
    "horário confirmado",
]

# Confirmação geral de interesse avançado
_INTEREST_PATTERNS = [
    "agendado",
    "confirmado",
    "confirmei",
    "marcarmos",
    "vou te passar o link",
    "enviando o link",
]

_ALL_KEYWORDS = _AGENT_TAGS + _MEETING_PATTERNS + _INTEREST_PATTERNS


def detect_conversion(text: str) -> str:
    """
    Retorna a primeira keyword de conversão encontrada, ou '' se nenhuma.
    Prioriza tags do agente, depois padrões de reunião, depois interesse geral.
    """
    t = text.lower()
    for kw in _ALL_KEYWORDS:
        if kw in t:
            return kw
    return ""


def classify_message(text: str, direction: str) -> str:
    """Retorna um label legível para exibição no log."""
    if direction == "out":
        if detect_conversion(text):
            return "QUALIFICADO"
        return "BOT"
    return "LEAD"
