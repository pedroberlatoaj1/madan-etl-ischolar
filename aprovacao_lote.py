"""
aprovacao_lote.py — Etapa 4  (patch cirúrgico v2)

Camada de aprovação manual do lote (NÃO envia nada).

--- Mudanças em relação ao patch anterior ---

5. extrair_itens_sendaveis(resultados_etapa3) — nova função pública
   - Extrai os lançamentos sendáveis do resultado da Etapa 3.
   - Deve ser chamada pelo operador ANTES de aprovar_lote quando se quer
     persistir o conjunto canônico junto à aprovação.

6. aprovar_lote ganha dois parâmetros opcionais (keyword-only):
     itens_sendaveis : list[Mapping[str, Any]] | None = None
     itens_store     : LoteItensStore | None = None
   - Ambos devem ser informados juntos ou ambos omitidos (ValueError se apenas um).
   - Quando ambos presentes, persiste o conjunto canônico via
     itens_store.salvar_itens() APÓS a transição de estado do lote.
   - Código existente que não passa esses parâmetros não é afetado.

   Rationale: a aprovação é o único momento com autoridade para definir
   "o que foi aprovado". Persistir os itens junto à aprovação elimina o
   risco de enviar um conjunto diferente do aprovado.

--- Mudanças anteriores (patch v1, não repetidas aqui) ---

1. Elegibilidade endurecida (avaliar_lote_para_aprovacao)
2. Hash estável do snapshot aprovado
3. Parâmetro `store` opcional nas funções de mutação
4. Função de conveniência `carregar_estado_lote(lote_id, store)`
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Optional

from avaliacao_rules import is_blank

if TYPE_CHECKING:
    from aprovacao_lote_store import AprovacaoLoteStore
    from lote_itens_store import LoteItensStore


def _agora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hash_resumo(d: dict[str, Any]) -> str:
    """
    SHA-256 do JSON canônico (sort_keys=True) do dicionário.
    Estável entre processos; usado para verificar integridade do snapshot.
    """
    canonical = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Tipos de dados
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResumoLote:
    total_linhas: int
    total_alunos: int
    total_disciplinas: int
    total_lancamentos: int
    total_sendaveis: int
    total_bloqueados: int
    total_avisos: int
    total_pendencias: int
    total_duplicidades: int
    total_erros: int
    status_geral_por_linha: dict[str, int]
    status_sugerido: str   # "bloqueado_por_erros" | "aguardando_aprovacao"
    motivos_status: list[str]


@dataclass
class EstadoAprovacaoLote:
    """
    Estado operacional do lote.

    Invariantes:
      - elegivel_para_aprovacao  !=  aprovado
      - aprovado                 !=  enviado
      - snapshot_resumo_aprovado é congelado no momento da aprovação e nunca
        deve ser sobrescrito após aprovação; hash_resumo_aprovado permite
        detectar adulteração posterior.
    """

    lote_id: str
    status: str  # "aguardando_aprovacao" | "aprovado_para_envio" | "rejeitado"
    elegivel_para_aprovacao: bool
    resumo_atual: dict[str, Any]
    aprovado_por: Optional[str] = None
    aprovado_em: Optional[str] = None
    rejeitado_por: Optional[str] = None
    rejeitado_em: Optional[str] = None
    motivo_rejeicao: Optional[str] = None
    snapshot_resumo_aprovado: Optional[dict[str, Any]] = None
    # SHA-256(JSON canônico de snapshot_resumo_aprovado).
    # None enquanto o lote não for aprovado.
    hash_resumo_aprovado: Optional[str] = None


# ---------------------------------------------------------------------------
# Lógica de negócio
# ---------------------------------------------------------------------------

def gerar_resumo_lote(
    resultados_validacao: Iterable[Mapping[str, Any]],
) -> ResumoLote:
    """
    Consolida um lote (lista de resultados da Etapa 3) em um resumo executivo.
    """
    resultados = list(resultados_validacao)

    alunos: set[str] = set()
    disciplinas: set[str] = set()

    total_lanc = 0
    total_sendaveis = 0
    total_bloqueados = 0
    total_avisos = 0
    total_pendencias = 0
    total_duplicidades = 0
    total_erros = 0

    status_por_linha: dict[str, int] = {}

    for res in resultados:
        status_linha = str(res.get("status_geral") or "desconhecido")
        status_por_linha[status_linha] = status_por_linha.get(status_linha, 0) + 1

        avisos = res.get("avisos") or []
        pend   = res.get("pendencias") or []
        dups   = res.get("duplicidades") or []
        l_validos = res.get("lancamentos_validos") or []
        l_erros   = res.get("lancamentos_com_erro") or []

        total_avisos      += len(avisos)
        total_pendencias  += len(pend)
        total_duplicidades+= len(dups)
        total_lanc        += len(l_validos) + len(l_erros)
        total_erros       += len(l_erros)

        for l in list(l_validos) + list(l_erros):
            estudante  = l.get("estudante")
            disciplina = l.get("disciplina")
            if not is_blank(estudante):
                alunos.add(str(estudante).strip())
            if not is_blank(disciplina):
                disciplinas.add(str(disciplina).strip())

            if l.get("sendavel"):
                total_sendaveis += 1
                if l.get("validacao_erros"):
                    total_bloqueados += 1

    motivos: list[str] = []

    # Política: qualquer linha com bloqueio por erros => lote sugerido bloqueado.
    if status_por_linha.get("bloqueado_por_erros", 0) > 0:
        status_sugerido = "bloqueado_por_erros"
        motivos.append("Existe ao menos uma linha com bloqueio por erros.")
    else:
        status_sugerido = "aguardando_aprovacao"
        motivos.append("Sem bloqueios: elegível para aprovação manual (não aprova automaticamente).")

    if total_avisos:
        motivos.append(f"Avisos encontrados: {total_avisos}.")
    if total_pendencias:
        motivos.append(f"Pendências encontradas: {total_pendencias}.")
    if total_duplicidades:
        motivos.append(f"Duplicidades encontradas: {total_duplicidades}.")

    return ResumoLote(
        total_linhas=len(resultados),
        total_alunos=len({a for a in alunos if a}),
        total_disciplinas=len({d for d in disciplinas if d}),
        total_lancamentos=total_lanc,
        total_sendaveis=total_sendaveis,
        total_bloqueados=total_bloqueados,
        total_avisos=total_avisos,
        total_pendencias=total_pendencias,
        total_duplicidades=total_duplicidades,
        total_erros=total_erros,
        status_geral_por_linha=status_por_linha,
        status_sugerido=status_sugerido,
        motivos_status=motivos,
    )


def avaliar_lote_para_aprovacao(resumo: ResumoLote) -> dict[str, Any]:
    """
    Decide elegibilidade para aprovação manual.

    Política (explícita e tripla — belt-and-suspenders):
      1. status_sugerido != "bloqueado_por_erros"
      2. total_erros == 0
      3. total_bloqueados == 0

    Importante: elegível != aprovado.
    A aprovação é sempre uma ação humana explícita (aprovar_lote).
    """
    motivos_bloqueio: list[str] = []

    if resumo.status_sugerido == "bloqueado_por_erros":
        motivos_bloqueio.append(
            f"status_sugerido=bloqueado_por_erros "
            f"({resumo.status_geral_por_linha.get('bloqueado_por_erros', 0)} linha(s) bloqueada(s))."
        )
    if resumo.total_erros > 0:
        motivos_bloqueio.append(
            f"total_erros={resumo.total_erros} (lançamentos com erro de validação)."
        )
    if resumo.total_bloqueados > 0:
        motivos_bloqueio.append(
            f"total_bloqueados={resumo.total_bloqueados} (lançamentos sendáveis bloqueados)."
        )

    elegivel = len(motivos_bloqueio) == 0
    motivos = list(resumo.motivos_status)
    if motivos_bloqueio:
        motivos.extend(motivos_bloqueio)

    return {
        "elegivel_para_aprovacao": elegivel,
        "status_inicial": "aguardando_aprovacao",
        "motivos": motivos,
        "motivos_bloqueio": motivos_bloqueio,
    }


def extrair_itens_sendaveis(
    resultados_etapa3: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Extrai os lançamentos sendáveis de uma sequência de resultados da Etapa 3.

    Critério: lançamento em lancamentos_validos com sendavel=True.

    Deve ser chamada pelo operador ANTES de aprovar_lote, para que o conjunto
    canônico seja persistido junto à aprovação:

        itens = extrair_itens_sendaveis(resultados_etapa3)
        aprovar_lote(
            estado,
            aprovado_por="gestor",
            itens_sendaveis=itens,
            itens_store=lote_itens_store,
        )

    Após isso, enviar_lote() carregará esses itens do store — sem depender
    de um iterable externo arbitrário.
    """
    sendaveis: list[dict[str, Any]] = []
    for res in resultados_etapa3:
        for l in (res.get("lancamentos_validos") or []):
            if l.get("sendavel"):
                sendaveis.append(dict(l))
    return sendaveis


def criar_estado_lote(
    *,
    lote_id: str,
    resumo: ResumoLote,
    store: "AprovacaoLoteStore | None" = None,
) -> EstadoAprovacaoLote:
    """
    Cria o estado inicial do lote a partir do resumo da Etapa 3.
    Se `store` for informado, persiste imediatamente.
    """
    avaliacao = avaliar_lote_para_aprovacao(resumo)
    estado = EstadoAprovacaoLote(
        lote_id=lote_id,
        status="aguardando_aprovacao",
        elegivel_para_aprovacao=bool(avaliacao["elegivel_para_aprovacao"]),
        resumo_atual=deepcopy(resumo.__dict__),
    )
    if store is not None:
        store.salvar(estado)
    return estado


def aprovar_lote(
    estado: EstadoAprovacaoLote,
    *,
    aprovado_por: str,
    store: "AprovacaoLoteStore | None" = None,
    itens_sendaveis: list[Mapping[str, Any]] | None = None,
    itens_store: "LoteItensStore | None" = None,
) -> EstadoAprovacaoLote:
    """
    Aprovação explícita obrigatória.

    Parâmetros novos (opcionais, mas devem ser fornecidos JUNTOS):
      itens_sendaveis : lista produzida por extrair_itens_sendaveis(resultados_etapa3)
      itens_store     : LoteItensStore onde o conjunto será persistido

    Quando ambos são fornecidos, o conjunto canônico é persistido APÓS a
    transição de estado do lote — garantindo que enviar_lote() use exatamente
    esses itens, sem aceitar um iterable externo diferente.

    Quando ambos são omitidos, o comportamento é idêntico ao patch v1
    (compatibilidade retroativa).

    Regras:
      - aprovado_por obrigatório (não vazio)
      - lote deve estar em aguardando_aprovacao
      - lote deve ser elegível (não bloqueado)
      - apenas um dos (itens_sendaveis, itens_store) é ValueError
      - congela snapshot do resumo aprovado com hash SHA-256
      - se `store` informado, persiste o EstadoAprovacaoLote aprovado
    """
    # --- Validações pré-condição -----------------------------------------------
    if is_blank(aprovado_por):
        raise ValueError("aprovado_por é obrigatório para aprovar o lote.")
    if estado.status != "aguardando_aprovacao":
        raise ValueError(
            f"Lote não está aguardando aprovação (status atual: {estado.status})."
        )
    if not estado.elegivel_para_aprovacao:
        raise ValueError("Lote não é elegível para aprovação (bloqueado por erros).")

    # Guard: ambos ou nenhum (fornece mensagem clara para o operador)
    _tem_itens = itens_sendaveis is not None
    _tem_store = itens_store is not None
    if _tem_itens != _tem_store:
        raise ValueError(
            "aprovar_lote: informe ambos 'itens_sendaveis' e 'itens_store' "
            "ou nenhum dos dois. "
            "Para persistir o conjunto aprovado: use extrair_itens_sendaveis() "
            "antes de chamar aprovar_lote()."
        )

    # --- Transição de estado ---------------------------------------------------
    snapshot = deepcopy(estado.resumo_atual)
    estado.status                   = "aprovado_para_envio"
    estado.aprovado_por             = str(aprovado_por).strip()
    estado.aprovado_em              = _agora_iso()
    estado.snapshot_resumo_aprovado = snapshot
    estado.hash_resumo_aprovado     = _hash_resumo(snapshot)

    # --- Persistência do EstadoAprovacaoLote -----------------------------------
    if store is not None:
        store.salvar(estado)

    # --- Persistência do conjunto canônico de itens sendáveis -----------------
    # Executado APÓS a persistência do estado (estado coerente antes dos itens).
    if _tem_itens and _tem_store:
        itens_store.salvar_itens(  # type: ignore[union-attr]
            estado.lote_id,
            [dict(i) for i in itens_sendaveis],  # type: ignore[union-attr]
        )

    return estado


def rejeitar_lote(
    estado: EstadoAprovacaoLote,
    *,
    rejeitado_por: str,
    motivo: str | None = None,
    store: "AprovacaoLoteStore | None" = None,
) -> EstadoAprovacaoLote:
    """
    Rejeição explícita:
      - exige rejeitador não vazio
      - lote deve estar em aguardando_aprovacao
      - se `store` informado, persiste o estado rejeitado
    """
    if is_blank(rejeitado_por):
        raise ValueError("rejeitado_por é obrigatório para rejeitar o lote.")
    if estado.status != "aguardando_aprovacao":
        raise ValueError(
            f"Lote não está aguardando aprovação (status atual: {estado.status})."
        )

    estado.status          = "rejeitado"
    estado.rejeitado_por   = str(rejeitado_por).strip()
    estado.rejeitado_em    = _agora_iso()
    estado.motivo_rejeicao = None if is_blank(motivo) else str(motivo)

    if store is not None:
        store.salvar(estado)
    return estado


def carregar_estado_lote(
    lote_id: str,
    store: "AprovacaoLoteStore",
) -> EstadoAprovacaoLote:
    """
    Carrega o estado de um lote do store.
    Lança KeyError se o lote_id não existir.
    """
    estado = store.carregar(lote_id)
    if estado is None:
        raise KeyError(f"Lote '{lote_id}' não encontrado no store.")
    return estado


def verificar_integridade_snapshot(estado: EstadoAprovacaoLote) -> bool:
    """
    Verifica se o snapshot_resumo_aprovado não foi adulterado após a aprovação.
    Retorna True se íntegro, False se hash divergir ou snapshot/hash ausentes.
    """
    if estado.snapshot_resumo_aprovado is None or estado.hash_resumo_aprovado is None:
        return False
    return _hash_resumo(estado.snapshot_resumo_aprovado) == estado.hash_resumo_aprovado


__all__ = [
    "ResumoLote",
    "EstadoAprovacaoLote",
    "gerar_resumo_lote",
    "avaliar_lote_para_aprovacao",
    "extrair_itens_sendaveis",   # NOVO — v2
    "criar_estado_lote",
    "aprovar_lote",
    "rejeitar_lote",
    "carregar_estado_lote",
    "verificar_integridade_snapshot",
]