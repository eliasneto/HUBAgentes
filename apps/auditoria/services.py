"""ADR-001 Fase 3 (v2.0.0) — log proprio por processamento.

Reaproveita EventoAuditoria (ja existia antes desta fase, com FK opcional
para Processamento) em vez de criar um sistema de log paralelo. Usa
`django_apps.get_model(...)` (em vez de um import direto do model) pelo
mesmo motivo dos pontos de emissao ja existentes em
apps.processamentos.services.agent_execution — evita acoplar quem so
precisa REGISTRAR um evento a um import direto do app de auditoria.
"""

from django.apps import apps as django_apps


def registrar_evento_auditoria(
    *,
    modulo,
    acao,
    actor=None,
    processamento=None,
    objeto_tipo="",
    objeto_id="",
    descricao="",
    payload=None,
):
    """Cria um EventoAuditoria. Silenciosamente vira no-op se o app
    auditoria nao estiver instalado (mesma defesa ja usada nos pontos de
    emissao existentes) — nunca deve derrubar o fluxo principal por conta
    de um log."""
    evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
    if evento_model is None:
        return None
    return evento_model.objects.create(
        modulo=modulo,
        acao=acao,
        actor=actor,
        processamento=processamento,
        objeto_tipo=objeto_tipo,
        objeto_id=str(objeto_id) if objeto_id else "",
        descricao=descricao,
        payload=payload or {},
    )
