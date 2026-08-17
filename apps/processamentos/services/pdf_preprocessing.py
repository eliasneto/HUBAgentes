"""Pre-processamento deterministico de PDF antes do envio a IA.

Camada 100% Python (sem IA) para reduzir o documento e, com isso, o custo da
chamada ao provedor: extrai o texto de cada pagina com PyMuPDF, identifica
linhas de cabecalho/rodape institucional que se repetem na maioria das
paginas (numero de pagina, nome do orgao, CNPJ etc.) e usa RapidFuzz para
detectar paginas duplicadas ou quase-duplicadas comparando o texto de cada
pagina (ja sem as linhas de cabecalho/rodape, que senao mascarariam
duplicidade real ou gerariam falso positivo so por repetirem em todas as
paginas). Paginas identificadas como duplicata sao removidas do PDF antes de
envia-lo ao adapter de IA.

Este modulo e agnostico de Django/Processamento: recebe bytes, devolve bytes
+ estatisticas, e aceita um callback opcional de progresso. Quem decide
quando chamar (por agente, so para PDF) e liga isso ao modelo de dados fica
em apps.processamentos.services.agent_execution.
"""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

try:
    import pymupdf as fitz  # `import fitz` direto esta deprecado no PyMuPDF
except ImportError:  # pragma: no cover - dependencia opcional ausente
    fitz = None

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - dependencia opcional ausente
    fuzz = None


class PdfPreprocessingError(Exception):
    """Falha ao pre-processar o PDF. O chamador deve capturar e seguir com
    o documento original — este e um passo de otimizacao, nunca deve
    impedir a analise pela IA."""


# Quantas linhas do topo/rodape de cada pagina sao candidatas a
# cabecalho/rodape institucional repetido.
HEADER_FOOTER_LINE_COUNT = 3

# Fracao minima das paginas em que uma linha precisa se repetir (no topo/
# rodape) para ser tratada como cabecalho/rodape institucional.
HEADER_FOOTER_MIN_OCCURRENCE_RATIO = 0.6

# Similaridade minima (rapidfuzz.fuzz.ratio, 0-100) para duas paginas serem
# tratadas como duplicata. Alto de proposito: o objetivo e so remover
# duplicacao real (mesma pagina/anexo inserido mais de uma vez), nunca
# paginas so tematicamente parecidas (comum em editais, que reusam frases
# padrao entre clausulas diferentes).
DUPLICATE_SIMILARITY_THRESHOLD = 97

# Acima desse numero de paginas, a comparacao par-a-par fica cara demais
# para valer a pena (custo de CPU local vs. economia de tokens); pula a
# deducao de duplicatas e segue so com a extracao/remocao de cabecalho.
MAX_PAGINAS_PARA_DEDUP = 1500


@dataclass(frozen=True)
class ResultadoPreprocessamentoPdf:
    pdf_bytes: bytes
    paginas_originais: int
    paginas_removidas: int
    indices_paginas_removidas: list = field(default_factory=list)
    linhas_cabecalho_rodape_detectadas: list = field(default_factory=list)

    @property
    def reduziu_documento(self) -> bool:
        return self.paginas_removidas > 0


def eh_pdf(mime_type: str | None, nome_arquivo: str) -> bool:
    """True quando o documento e um PDF, pelas mesmas regras de fallback
    ja usadas na execucao (mime_type vazio -> assume PDF, ver
    agent_execution._execute_document)."""
    if mime_type:
        return mime_type == "application/pdf"
    return (nome_arquivo or "").lower().endswith(".pdf")


def _normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto).strip().lower()
    return texto


def _extrair_linhas(pagina_texto: str) -> list:
    return [linha.strip() for linha in pagina_texto.splitlines() if linha.strip()]


def _detectar_linhas_repetidas(paginas_linhas: list) -> set:
    """Linhas normalizadas que aparecem entre as N primeiras/ultimas linhas
    de uma pagina, repetidas na maioria das paginas — candidatas a
    cabecalho/rodape institucional (numero de pagina, nome do orgao,
    CNPJ...). Ignora linhas puramente numericas (numeracao de pagina, que
    varia a cada pagina e nao deve entrar como "linha repetida" fixa)."""
    total_paginas = len(paginas_linhas)
    if total_paginas < 3:
        return set()

    candidatos = Counter()
    for linhas in paginas_linhas:
        amostra = linhas[:HEADER_FOOTER_LINE_COUNT] + linhas[-HEADER_FOOTER_LINE_COUNT:]
        vistos_na_pagina = set()
        for linha in amostra:
            norm = _normalizar_texto(linha)
            if not norm or norm.isdigit():
                continue
            if norm in vistos_na_pagina:
                continue
            vistos_na_pagina.add(norm)
            candidatos[norm] += 1

    limite = max(2, round(total_paginas * HEADER_FOOTER_MIN_OCCURRENCE_RATIO))
    return {linha for linha, qtd in candidatos.items() if qtd >= limite}


def _texto_para_comparacao(linhas: list, linhas_repetidas: set) -> str:
    filtradas = [linha for linha in linhas if _normalizar_texto(linha) not in linhas_repetidas]
    return _normalizar_texto(" ".join(filtradas))


def _detectar_paginas_duplicadas(textos_comparaveis: list, *, on_progress=None, offset=0, amplitude=0):
    """Retorna os indices das paginas duplicadas/quase-duplicadas, comparando
    cada pagina com as paginas ja mantidas (nao removidas) anteriores a ela.
    Paginas cujo texto comparavel ficou vazio (ex.: pagina so com
    cabecalho/rodape, sem conteudo proprio) nunca sao removidas: na duvida,
    mantem — o objetivo e so eliminar duplicacao inequivoca."""
    total = len(textos_comparaveis)
    indices_removidos = []
    textos_mantidos = []
    for indice, texto_atual in enumerate(textos_comparaveis):
        duplicada = False
        if texto_atual:
            for texto_mantido in textos_mantidos:
                if fuzz.ratio(texto_atual, texto_mantido) >= DUPLICATE_SIMILARITY_THRESHOLD:
                    duplicada = True
                    break
        if duplicada:
            indices_removidos.append(indice)
        else:
            textos_mantidos.append(texto_atual)
        if on_progress and total:
            percentual = offset + round((indice + 1) / total * amplitude)
            on_progress(percentual, "Comparando paginas para detectar duplicidade")
    return indices_removidos


def pre_processar_pdf(
    document_bytes: bytes,
    *,
    on_progress: "Callable[[int, str], None] | None" = None,
) -> ResultadoPreprocessamentoPdf:
    """Remove paginas duplicadas/quase-duplicadas de um PDF antes de envia-lo
    a IA. Nao interpreta o conteudo (isso continua com o modelo) — so reduz
    o documento com regras deterministicas de texto.

    `on_progress(percentual, etapa)` e chamado incrementalmente (0-48) para
    alimentar o indicador de progresso do processamento; o restante (48-100)
    fica para a chamada de IA em si e a finalizacao, que o chamador cuida.

    Levanta PdfPreprocessingError em qualquer falha — o chamador deve
    capturar e seguir com o documento original, nunca deixar isso bloquear
    a analise.
    """
    if fitz is None or fuzz is None:
        raise PdfPreprocessingError(
            "Dependencias de pre-processamento de PDF (pymupdf/rapidfuzz) "
            "nao estao instaladas."
        )

    def _progresso(percentual, etapa):
        if on_progress:
            on_progress(percentual, etapa)

    try:
        doc = fitz.open(stream=document_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfPreprocessingError(f"Falha ao abrir o PDF: {exc}") from exc

    try:
        total_paginas = doc.page_count
        if not total_paginas:
            raise PdfPreprocessingError("PDF sem paginas.")

        _progresso(8, "Extraindo texto do documento")
        paginas_linhas = []
        for indice in range(total_paginas):
            try:
                texto_pagina = doc[indice].get_text()
            except Exception as exc:
                raise PdfPreprocessingError(
                    f"Falha ao extrair texto da pagina {indice + 1}: {exc}"
                ) from exc
            paginas_linhas.append(_extrair_linhas(texto_pagina))
            percentual = 8 + round((indice + 1) / total_paginas * 17)
            _progresso(percentual, "Extraindo texto do documento")

        _progresso(27, "Identificando cabecalhos e rodapes repetidos")
        linhas_repetidas = _detectar_linhas_repetidas(paginas_linhas)

        indices_removidos = []
        if total_paginas <= MAX_PAGINAS_PARA_DEDUP:
            textos_comparaveis = [
                _texto_para_comparacao(linhas, linhas_repetidas) for linhas in paginas_linhas
            ]
            indices_removidos = _detectar_paginas_duplicadas(
                textos_comparaveis, on_progress=_progresso, offset=30, amplitude=15
            )
            if indices_removidos:
                doc.delete_pages(indices_removidos)

        _progresso(46, "Documento reduzido; preparando envio para a IA")
        pdf_final = doc.tobytes(garbage=4, deflate=True) if indices_removidos else document_bytes
    except PdfPreprocessingError:
        raise
    except Exception as exc:
        raise PdfPreprocessingError(f"Falha inesperada no pre-processamento: {exc}") from exc
    finally:
        doc.close()

    return ResultadoPreprocessamentoPdf(
        pdf_bytes=pdf_final,
        paginas_originais=total_paginas,
        paginas_removidas=len(indices_removidos),
        indices_paginas_removidas=indices_removidos,
        linhas_cabecalho_rodape_detectadas=sorted(linhas_repetidas),
    )
