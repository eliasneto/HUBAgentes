from decimal import Decimal, ROUND_HALF_UP

from apps.custos.models import ConfiguracaoFinanceira, PrecificacaoModelo


def obter_precificacao_modelo(nome_modelo: str) -> PrecificacaoModelo | None:
    return PrecificacaoModelo.objects.filter(nome_modelo=nome_modelo, ativo=True).first()


def obter_configuracao_financeira() -> ConfiguracaoFinanceira | None:
    return ConfiguracaoFinanceira.objects.order_by("-created_at").first()


def obter_cotacao_dolar() -> Decimal | None:
    config = obter_configuracao_financeira()
    return config.cotacao_dolar if config else None


def calcular_custo_com_cache(
    *,
    nome_modelo: str,
    input_tokens: int | None,
    output_tokens: int | None,
    processing_tokens: int | None,
    _cache: dict,
) -> tuple:
    """Versão com cache em dict para evitar N queries num mesmo batch."""
    if "cotacao" not in _cache:
        _cache["cotacao"] = obter_cotacao_dolar()
    if nome_modelo not in _cache:
        _cache[nome_modelo] = obter_precificacao_modelo(nome_modelo)

    prec = _cache[nome_modelo]
    cotacao = _cache["cotacao"]
    if not prec or not cotacao or input_tokens is None or output_tokens is None:
        return None, None

    tokens_saida_total = (output_tokens or 0) + (processing_tokens or 0)
    custo_usd = (
        Decimal(input_tokens) * prec.preco_input_por_milhao
        + Decimal(tokens_saida_total) * prec.preco_output_por_milhao
    ) / Decimal("1000000")
    custo_brl = custo_usd * cotacao
    return (
        custo_usd.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        custo_brl.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
    )


def calcular_custo_processamento(
    *,
    nome_modelo: str,
    input_tokens: int | None,
    output_tokens: int | None,
    processing_tokens: int | None,
) -> tuple[Decimal | None, Decimal | None]:
    if not nome_modelo or input_tokens is None or output_tokens is None:
        return None, None

    precificacao = obter_precificacao_modelo(nome_modelo)
    if not precificacao:
        return None, None

    cotacao = obter_cotacao_dolar()
    if not cotacao:
        return None, None

    tokens_saida_total = (output_tokens or 0) + (processing_tokens or 0)
    custo_usd = (
        Decimal(input_tokens) * precificacao.preco_input_por_milhao
        + Decimal(tokens_saida_total) * precificacao.preco_output_por_milhao
    ) / Decimal("1000000")
    custo_brl = custo_usd * cotacao

    custo_usd = custo_usd.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    custo_brl = custo_brl.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    return custo_usd, custo_brl


def listar_precificacoes(
    *,
    page_number: int | str | None = 1,
    per_page: int = 20,
):
    from django.core.paginator import Paginator

    queryset = PrecificacaoModelo.objects.all()
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page_number)

    return {
        "itens": list(page_obj.object_list),
        "total": paginator.count,
        "pagina_atual": page_obj.number,
        "total_paginas": paginator.num_pages,
        "itens_por_pagina": per_page,
        "primeiro_item": page_obj.start_index() if paginator.count else 0,
        "ultimo_item": page_obj.end_index() if paginator.count else 0,
        "tem_pagina_anterior": page_obj.has_previous(),
        "tem_proxima_pagina": page_obj.has_next(),
        "pagina_anterior": page_obj.previous_page_number() if page_obj.has_previous() else None,
        "proxima_pagina": page_obj.next_page_number() if page_obj.has_next() else None,
        "paginas": [
            "..." if isinstance(p, str) else p
            for p in paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
        ],
    }
