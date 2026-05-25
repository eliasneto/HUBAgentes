import re


ERRO_TECNICO_OPERACIONAL = (
    "Ocorreu um erro tecnico ao executar o agente. "
    "Contate o administrador do sistema."
)


_TECHNICAL_ERROR_PATTERNS = (
    "falha http",
    "permission_denied",
    "access denied",
    "denied access",
    "api key",
    "token",
    "traceback",
    "stack trace",
    "exception",
    "credentials",
    "unauthorized",
    "forbidden",
)


def normalizar_erro_processamento(error) -> tuple[str, str]:
    """Retorna mensagem operacional e erro tecnico bruto, quando aplicavel."""
    raw_message = str(error or "").strip()
    if not raw_message:
        return "", ""

    explicit_technical_message = getattr(error, "technical_message", "")
    if explicit_technical_message:
        return raw_message, str(explicit_technical_message).strip()

    if _eh_erro_tecnico(raw_message):
        return ERRO_TECNICO_OPERACIONAL, raw_message

    return raw_message, ""


def _eh_erro_tecnico(message: str) -> bool:
    normalized = message.lower()
    if any(pattern in normalized for pattern in _TECHNICAL_ERROR_PATTERNS):
        return True
    return bool(re.search(r"\b(4\d{2}|5\d{2})\b", normalized))
