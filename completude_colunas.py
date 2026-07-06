"""
completude_colunas.py — Gate de completude de colunas do formato wide novo.

Motivação (incidente 2026-06/07): um cabeçalho fora do padrão não parseava,
a coluna era tratada como "fixa" e as notas eram descartadas em silêncio —
sem erro, sem linha na auditoria e com o lote aparentando sucesso. Este módulo
dá um veredito explícito para CADA coluna da planilha na fase de validação,
antes da aprovação do lote:

  - fixa_reconhecida                → coluna de contexto conhecida (Estudante, RA...)
  - dinamica_ok                     → parseia e o professor resolve no mapa
  - dinamica_sem_professor          → parseia mas o professor não tem mapeamento
                                      (viraria erro_resolucao no envio)
  - dinamica_tipo_nao_reconhecido   → parseia mas o tipo de avaliação é desconhecido
  - nao_reconhecida                 → não parseia e não é fixa: as notas seriam
                                      DESCARTADAS em silêncio (detector de perda)

A montagem da chave de professor replica exatamente o comportamento do envio
(despivotar_linha_wide + _resolver_professor): chave por turma primeiro, com
fallback para a chave global. Funções puras, sem I/O — o chamador fornece o
mapa de professores já carregado (ou None, caso em que a verificação de
professor é pulada sem gerar falso bloqueio).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

import pandas as pd

from avaliacao_rules import is_blank
from madan_planilha_mapper import mapear_colunas_madan
from resolvedor_ids_ischolar import (
    _chave_professor_por_turma,
    _normalizar_chave,
    _normalizar_codigo_turma,
)
from validacao_pre_envio import Issue
from wide_format_adapter import (
    FORMATO_WIDE_NOVO,
    _extrair_serie_letra,
    _normalizar_texto,
    _qualificar_chave_com_professor,
    construir_frente_professor,
    mapear_tipo_avaliacao,
    parsear_coluna_dinamica,
)


# ---------------------------------------------------------------------------
# Categorias de veredito
# ---------------------------------------------------------------------------

CATEGORIA_FIXA_RECONHECIDA = "fixa_reconhecida"
CATEGORIA_DINAMICA_OK = "dinamica_ok"
CATEGORIA_DINAMICA_SEM_PROFESSOR = "dinamica_sem_professor"
CATEGORIA_DINAMICA_TIPO_NAO_RECONHECIDO = "dinamica_tipo_nao_reconhecido"
CATEGORIA_NAO_RECONHECIDA = "nao_reconhecida"


# ---------------------------------------------------------------------------
# Códigos de Issue do gate
# ---------------------------------------------------------------------------

COD_COLUNA_NAO_RECONHECIDA_COM_NOTAS = "COLUNA_NAO_RECONHECIDA_COM_NOTAS"
COD_COLUNA_NAO_RECONHECIDA_VAZIA = "COLUNA_NAO_RECONHECIDA_VAZIA"
COD_COLUNA_PROFESSOR_SEM_MAPEAMENTO = "COLUNA_PROFESSOR_SEM_MAPEAMENTO"
COD_TIPO_AVALIACAO_NAO_RECONHECIDO = "TIPO_AVALIACAO_NAO_RECONHECIDO_COLUNA"
COD_MAPA_PROFESSORES_INDISPONIVEL = "MAPA_PROFESSORES_INDISPONIVEL"

ORIGEM_GATE = "gate_colunas"


# ---------------------------------------------------------------------------
# Tipos de dados
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VereditoColuna:
    """Destino de uma coluna da planilha wide no pipeline."""
    coluna: str                 # cabeçalho CRU (preserva \n para auditoria)
    categoria: str
    celulas_com_valor: int
    disciplina: str | None = None
    frente: str | None = None
    tipo_avaliacao: str | None = None
    professor: str | None = None
    chave_professor: str | None = None        # chave global normalizada do lookup
    chaves_turma: list[str] = field(default_factory=list)
    id_professor: int | None = None
    motivo: str | None = None                 # texto curto para a operadora


@dataclass(frozen=True)
class RelatorioColunas:
    """Veredito de todas as colunas de um DataFrame wide + agregados."""
    formato: str
    turmas: list[str]
    professor_verificado: bool
    colunas: list[VereditoColuna]
    total_colunas: int
    total_fixas: int
    total_dinamicas_ok: int
    total_dinamicas_sem_professor: int
    total_nao_reconhecidas: int
    total_nao_reconhecidas_com_valor: int
    celulas_com_valor_reconhecidas: int       # células com nota em dinâmicas reconhecidas
    celulas_com_valor_descartaveis: int       # células com nota em colunas nao_reconhecidas

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _texto_cabecalho(coluna: str) -> str:
    """Versão de exibição do cabeçalho (colapsa \n/espaços múltiplos)."""
    return " ".join(str(coluna).split())


def _extrair_turmas(df: pd.DataFrame) -> list[str]:
    """Valores distintos e não-vazios da coluna Turma (case-insensitive)."""
    for col in df.columns:
        if str(col).strip().lower() == "turma":
            vistos: list[str] = []
            for v in df[col].tolist():
                if is_blank(v):
                    continue
                t = str(v).strip()
                if t not in vistos:
                    vistos.append(t)
            return vistos
    return []


def _contar_celulas_com_valor(serie: pd.Series) -> int:
    return sum(1 for v in serie.tolist() if not is_blank(v))


def _resolver_professor_coluna(
    parsed_professor: str | None,
    disciplina: str,
    frente: str,
    turmas: list[str],
    mapa: Mapping[str, int],
) -> tuple[str, list[str], int | None, list[str]]:
    """
    Replica a montagem de chave do envio (despivotar_linha_wide) e o lookup do
    resolvedor (_resolver_professor: chave por turma → fallback global).

    Retorna (chave_global, chaves_turma_testadas, id_professor, turmas_sem_mapeamento).
    id_professor é o primeiro id resolvido; turmas_sem_mapeamento lista as turmas
    em que o lookup falhou (vazia = coluna resolve em todas).
    """
    base = construir_frente_professor(disciplina, frente)
    contextos = turmas if turmas else [None]

    chave_global = ""
    chaves_turma: list[str] = []
    id_encontrado: int | None = None
    turmas_sem_mapeamento: list[str] = []

    for turma in contextos:
        if parsed_professor:
            sintetico = f"{base} - {_normalizar_texto(parsed_professor.strip())}"
        else:
            serie_letra = _extrair_serie_letra(turma) if turma is not None else None
            if serie_letra is not None:
                serie, letra = serie_letra
                sintetico = _qualificar_chave_com_professor(base, disciplina, serie, letra)
            else:
                sintetico = base

        chave = _normalizar_chave(sintetico)
        chave_global = chave
        codigo_turma = _normalizar_codigo_turma(turma) if turma is not None else None

        id_p: int | None = None
        if codigo_turma:
            chave_turma = _chave_professor_por_turma(codigo_turma, chave)
            chaves_turma.append(chave_turma)
            id_p = mapa.get(chave_turma)
        if id_p is None:
            id_p = mapa.get(chave)

        if id_p is None:
            turmas_sem_mapeamento.append(str(turma) if turma is not None else "?")
        elif id_encontrado is None:
            id_encontrado = id_p

    return chave_global, chaves_turma, id_encontrado, turmas_sem_mapeamento


# ---------------------------------------------------------------------------
# Relatório por coluna
# ---------------------------------------------------------------------------

def gerar_relatorio_colunas(
    df: pd.DataFrame,
    *,
    mapa_professores: Mapping[str, int] | None,
) -> RelatorioColunas:
    """
    Gera o veredito de cada coluna de um DataFrame no formato wide novo.

    ``mapa_professores`` é o dict achatado de carregar_mapa_professores()
    (chaves globais + chaves por turma "1a quimica a"). Se None, a verificação
    de professor é pulada (professor_verificado=False) — nunca gera falso
    bloqueio por indisponibilidade do mapa.
    """
    colunas = list(df.columns)
    fixas_conhecidas = set(mapear_colunas_madan(colunas))
    turmas = _extrair_turmas(df)
    professor_verificado = mapa_professores is not None

    vereditos: list[VereditoColuna] = []

    for i, col in enumerate(colunas):
        serie = df.iloc[:, i]
        celulas = _contar_celulas_com_valor(serie)
        parsed = parsear_coluna_dinamica(str(col))

        if parsed is None:
            if col in fixas_conhecidas:
                vereditos.append(VereditoColuna(
                    coluna=str(col),
                    categoria=CATEGORIA_FIXA_RECONHECIDA,
                    celulas_com_valor=celulas,
                ))
            else:
                vereditos.append(VereditoColuna(
                    coluna=str(col),
                    categoria=CATEGORIA_NAO_RECONHECIDA,
                    celulas_com_valor=celulas,
                    motivo=(
                        "cabecalho fora do padrao "
                        "'Disciplina - Professor (Frente X) - Tipo'"
                    ),
                ))
            continue

        if mapear_tipo_avaliacao(parsed.tipo_avaliacao) is None:
            vereditos.append(VereditoColuna(
                coluna=str(col),
                categoria=CATEGORIA_DINAMICA_TIPO_NAO_RECONHECIDO,
                celulas_com_valor=celulas,
                disciplina=parsed.disciplina,
                frente=parsed.frente,
                tipo_avaliacao=parsed.tipo_avaliacao,
                professor=parsed.professor,
                motivo=f"tipo de avaliacao nao reconhecido: '{parsed.tipo_avaliacao}'",
            ))
            continue

        if not professor_verificado:
            vereditos.append(VereditoColuna(
                coluna=str(col),
                categoria=CATEGORIA_DINAMICA_OK,
                celulas_com_valor=celulas,
                disciplina=parsed.disciplina,
                frente=parsed.frente,
                tipo_avaliacao=parsed.tipo_avaliacao,
                professor=parsed.professor,
            ))
            continue

        chave, chaves_turma, id_p, turmas_falha = _resolver_professor_coluna(
            parsed.professor, parsed.disciplina, parsed.frente, turmas, mapa_professores,
        )
        if turmas_falha:
            vereditos.append(VereditoColuna(
                coluna=str(col),
                categoria=CATEGORIA_DINAMICA_SEM_PROFESSOR,
                celulas_com_valor=celulas,
                disciplina=parsed.disciplina,
                frente=parsed.frente,
                tipo_avaliacao=parsed.tipo_avaliacao,
                professor=parsed.professor,
                chave_professor=chave,
                chaves_turma=chaves_turma,
                id_professor=id_p,
                motivo=f"professor sem mapeamento (turmas: {', '.join(turmas_falha)})",
            ))
        else:
            vereditos.append(VereditoColuna(
                coluna=str(col),
                categoria=CATEGORIA_DINAMICA_OK,
                celulas_com_valor=celulas,
                disciplina=parsed.disciplina,
                frente=parsed.frente,
                tipo_avaliacao=parsed.tipo_avaliacao,
                professor=parsed.professor,
                chave_professor=chave,
                chaves_turma=chaves_turma,
                id_professor=id_p,
            ))

    nao_reconhecidas = [v for v in vereditos if v.categoria == CATEGORIA_NAO_RECONHECIDA]
    dinamicas_reconhecidas = [
        v for v in vereditos
        if v.categoria in (CATEGORIA_DINAMICA_OK, CATEGORIA_DINAMICA_SEM_PROFESSOR)
    ]

    return RelatorioColunas(
        formato=FORMATO_WIDE_NOVO,
        turmas=turmas,
        professor_verificado=professor_verificado,
        colunas=vereditos,
        total_colunas=len(vereditos),
        total_fixas=sum(1 for v in vereditos if v.categoria == CATEGORIA_FIXA_RECONHECIDA),
        total_dinamicas_ok=sum(1 for v in vereditos if v.categoria == CATEGORIA_DINAMICA_OK),
        total_dinamicas_sem_professor=sum(
            1 for v in vereditos if v.categoria == CATEGORIA_DINAMICA_SEM_PROFESSOR
        ),
        total_nao_reconhecidas=len(nao_reconhecidas),
        total_nao_reconhecidas_com_valor=sum(
            1 for v in nao_reconhecidas if v.celulas_com_valor > 0
        ),
        celulas_com_valor_reconhecidas=sum(v.celulas_com_valor for v in dinamicas_reconhecidas),
        celulas_com_valor_descartaveis=sum(v.celulas_com_valor for v in nao_reconhecidas),
    )


# ---------------------------------------------------------------------------
# Gate → Issues
# ---------------------------------------------------------------------------

def avaliar_gate_completude(
    relatorio: RelatorioColunas,
    *,
    coluna_nao_reconhecida_bloqueante: bool = False,
    professor_sem_mapeamento_bloqueante: bool = False,
) -> list[Issue]:
    """
    Converte o relatório de colunas em Issues para o resultado da validação.

    Severidades default (decisão operacional 2026-07-02): avisos/pendências
    NÃO bloqueantes — o lote continua aprovável, mas a operadora vê em destaque
    o que seria descartado ou cairia em erro de professor. Os flags permitem
    endurecer para fail-closed sem mudar código.
    """
    issues: list[Issue] = []

    for v in relatorio.colunas:
        detalhes = {
            "coluna": v.coluna,
            "celulas_com_valor": v.celulas_com_valor,
            "chave_professor": v.chave_professor,
            "chaves_turma": list(v.chaves_turma),
            "turmas": list(relatorio.turmas),
            "origem": ORIGEM_GATE,
        }
        cabecalho = _texto_cabecalho(v.coluna)

        if v.categoria == CATEGORIA_NAO_RECONHECIDA:
            if v.celulas_com_valor > 0:
                issues.append(Issue(
                    severity="erro" if coluna_nao_reconhecida_bloqueante else "aviso",
                    code=COD_COLUNA_NAO_RECONHECIDA_COM_NOTAS,
                    message=(
                        f"Coluna '{cabecalho}' nao reconhecida pelo parser: "
                        f"{v.celulas_com_valor} nota(s) seriam DESCARTADAS em silencio. "
                        "Corrija o cabecalho para o padrao "
                        "'Disciplina - Professor (Frente X) - Tipo'."
                    ),
                    details=detalhes,
                    bloqueante=coluna_nao_reconhecida_bloqueante,
                ))
            else:
                issues.append(Issue(
                    severity="aviso",
                    code=COD_COLUNA_NAO_RECONHECIDA_VAZIA,
                    message=(
                        f"Coluna '{cabecalho}' nao reconhecida pelo parser (sem notas "
                        "preenchidas). Sera ignorada no envio."
                    ),
                    details=detalhes,
                ))
        elif v.categoria == CATEGORIA_DINAMICA_SEM_PROFESSOR:
            issues.append(Issue(
                severity="pendencia",
                code=COD_COLUNA_PROFESSOR_SEM_MAPEAMENTO,
                message=(
                    f"Coluna '{cabecalho}': professor sem mapeamento "
                    f"(chave: '{v.chave_professor}'). No envio, "
                    f"{v.celulas_com_valor} nota(s) desta coluna cairao em "
                    "erro_resolucao (professor_sem_mapeamento); as demais colunas "
                    "seguem normalmente."
                ),
                details=detalhes,
                bloqueante=professor_sem_mapeamento_bloqueante,
            ))
        elif v.categoria == CATEGORIA_DINAMICA_TIPO_NAO_RECONHECIDO:
            issues.append(Issue(
                severity="erro",
                code=COD_TIPO_AVALIACAO_NAO_RECONHECIDO,
                message=(
                    f"Coluna '{cabecalho}': tipo de avaliacao "
                    f"'{v.tipo_avaliacao}' nao reconhecido."
                ),
                details=detalhes,
                bloqueante=True,
            ))

    tem_dinamicas = any(
        v.categoria != CATEGORIA_FIXA_RECONHECIDA and v.categoria != CATEGORIA_NAO_RECONHECIDA
        for v in relatorio.colunas
    )
    if not relatorio.professor_verificado and tem_dinamicas:
        issues.append(Issue(
            severity="aviso",
            code=COD_MAPA_PROFESSORES_INDISPONIVEL,
            message=(
                "Mapa de professores indisponivel na validacao: a verificacao de "
                "professor por coluna nao foi executada (o envio ainda valida por item)."
            ),
            details={"origem": ORIGEM_GATE},
        ))

    return issues


__all__ = [
    "VereditoColuna",
    "RelatorioColunas",
    "gerar_relatorio_colunas",
    "avaliar_gate_completude",
    "CATEGORIA_FIXA_RECONHECIDA",
    "CATEGORIA_DINAMICA_OK",
    "CATEGORIA_DINAMICA_SEM_PROFESSOR",
    "CATEGORIA_DINAMICA_TIPO_NAO_RECONHECIDO",
    "CATEGORIA_NAO_RECONHECIDA",
    "COD_COLUNA_NAO_RECONHECIDA_COM_NOTAS",
    "COD_COLUNA_NAO_RECONHECIDA_VAZIA",
    "COD_COLUNA_PROFESSOR_SEM_MAPEAMENTO",
    "COD_TIPO_AVALIACAO_NAO_RECONHECIDO",
    "COD_MAPA_PROFESSORES_INDISPONIVEL",
    "ORIGEM_GATE",
]
