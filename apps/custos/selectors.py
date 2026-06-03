from decimal import Decimal, ROUND_HALF_UP

from apps.custos.models import ConfiguracaoFinanceira, PrecificacaoModelo


def obter_precificacao_modelo(nome_modelo: str) -> PrecificacaoModelo | None:
    return PrecificacaoModelo.objects.filter(nome_modelo=nome_modelo, ativo=True).first()


def obter_configuracao_financeira() -> ConfiguracaoFinanceira | None:
    return ConfiguracaoFinanceira.objects.order_by("-created_at").first()


def obter_cotacao_dolar() -> Decimal | None:
    config = obter_configuracao_financeira()
    return config.cotacao_dolar if config else None


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


def listar_precificacoes() -> list[PrecificacaoModelo]:
    return list(PrecificacaoModelo.objects.all())
