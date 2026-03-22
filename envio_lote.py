"""
envio_lote.py — Etapa 5 (patch v2)

Ponte entre o lote aprovado (Etapa 4) e o envio oficial ao iScholar.

--- Mudanças em relação ao patch v1 ---

A. resultados_etapa3 REMOVIDO de enviar_lote()
   - Antes: enviar_lote(..., resultados_etapa3=...) aceitava qualquer iterable.
   - Agora:  enviar_lote(..., itens_store=...) carrega o conjunto canônico
     persistido no momento da aprovação.
   - Se o lote não tiver itens persistidos → ValueError explícito.
   - Elimina o caminho de injeção arbitrária de itens no fluxo de envio.

B. _compute_item_key() — identidade estável por item
   - Prioridade 1: hash_conteudo do lançamento (calculado pelo transformador).
     Liga diretamente à linha exata da planilha.
   - Prioridade 2: SHA-256(lote_id | linha_origem | componente | subcomponente).
     Fallback estrutural; não depende de strings de nome.
   - Nunca colide por nome de aluno, componente ou disciplina.

C. ResultadoItemEnvio ganha campo item_key : str
   - Propagado para EnvioLoteAuditStore como chave de auditoria estável.

D. _extrair_sendaveis() REMOVIDO deste módulo
   - Essa lógica vive em aprovacao_lote.extrair_itens_sendaveis().

Mantido inalterado:
  - ResolvedorIDsAbstrato / ResolvedorDireto / ResolvedorNaoImplementado
  - Política de falha parcial (um item com erro não aborta o lote)
  - Suporte a dry_run
  - NÃO usa sync_notas_idempotente nem fluxo legado
  - Contratos abertos de IDs documentados em ResolvedorIDsAbstrato
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, TYPE_CHECKING

from aprovacao_lote import EstadoAprovacaoLote

if TYPE_CHECKING:
    from ischolar_client import IScholarClient, ResultadoLancamentoNota
    from lote_itens_store import LoteItensStore
    from envio_lote_audit_store import EnvioLoteAuditStore


def _agora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Identidade estável por item
# ---------------------------------------------------------------------------

def _compute_item_key(lote_id: str, lancamento: Mapping[str, Any]) -> str:
    """
    Computa uma chave estável e resistente a colisão para um lançamento sendável.

    Prioridade:
    1. hash_conteudo — calculado pelo transformador sobre o conteúdo bruto da
       planilha. Liga diretamente à linha exata. Melhor opção quando disponível.

    2. SHA-256(lote_id | linha_origem | componente | subcomponente) — fallback
       estrutural. Não depende de strings de nome. Estável desde que os campos
       de origem não mudem.

    Por que não usar (estudante, componente, disciplina) diretamente:
       Alunos homonômicos existem. Disciplinas têm aliases. Esses campos são
       strings livres e colidem. A identidade deve ser estrutural.
    """
    h = str(lancamento.get("hash_conteudo") or "").strip()
    if h:
        return h

    partes = [
        lote_id,
        str(lancamento.get("linha_origem") or ""),
        str(lancamento.get("componente") or ""),
        str(lancamento.get("subcomponente") or ""),
    ]
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Resultado da resolução de IDs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultadoResolucaoIDs:
    """
    Contém os IDs iScholar resolvidos (ou None + erros se não resolvidos).

    Campos OBRIGATÓRIOS para chamar lancar_nota:
      id_matricula  : int  — resolve via buscar_aluno + listar_matriculas
      id_disciplina : int  — DE-PARA estático ou endpoint não documentado
      id_avaliacao  : int  — ID opaco iScholar; sem endpoint de busca confirmado

    Campo OPCIONAL:
      id_professor  : int | None — pode ser exigido dependendo da escola

    Se qualquer campo obrigatório for None, `resolvido == False` e o item
    é registrado como "erro_resolucao" sem bloquear os demais.
    """

    id_matricula: Optional[int]
    id_disciplina: Optional[int]
    id_avaliacao: Optional[int]
    id_professor: Optional[int]
    erros: list[str]
    rastreabilidade: dict[str, Any] = field(default_factory=dict)

    @property
    def resolvido(self) -> bool:
        return (
            self.id_matricula is not None
            and self.id_disciplina is not None
            and self.id_avaliacao is not None
            and not self.erros
        )


# ---------------------------------------------------------------------------
# Contrato do resolvedor de IDs
# ---------------------------------------------------------------------------

class ResolvedorIDsAbstrato(ABC):
    """
    CONTRATO ABERTO: mapeia um lançamento canônico para IDs iScholar.

    Campos disponíveis no lançamento:
      estudante, turma, disciplina, componente, trimestre,
      nota_ajustada_0a10, linha_origem, hash_conteudo

    IDs que PRECISAM ser resolvidos (contratos ainda abertos):
      1. id_matricula  — buscar_aluno + listar_matriculas; matrícula ambígua sem critério
      2. id_disciplina — sem endpoint confirmado; provavelmente DE-PARA estático
      3. id_avaliacao  — ID opaco; sem endpoint de busca por componente/trimestre
      4. id_professor  — origem e obrigatoriedade variam por escola
    """

    @abstractmethod
    def resolver_ids(self, lancamento: Mapping[str, Any]) -> ResultadoResolucaoIDs:
        """
        Recebe lançamento sendável, retorna ResultadoResolucaoIDs.
        Contrato: NUNCA levanta exceção. Erros vão para .erros.
        Idempotente. Preenche rastreabilidade com contexto auditável.
        """
        ...


# ---------------------------------------------------------------------------
# Implementações incluídas neste módulo
# ---------------------------------------------------------------------------

class ResolvedorNaoImplementado(ResolvedorIDsAbstrato):
    """
    Resolvedor sentinela — levanta NotImplementedError em toda chamada.
    Use como placeholder até um resolvedor real ser implementado.
    """

    def resolver_ids(self, lancamento: Mapping[str, Any]) -> ResultadoResolucaoIDs:
        raise NotImplementedError(
            "Nenhum resolvedor de IDs iScholar foi configurado. "
            "Implemente ResolvedorIDsAbstrato e passe-o para enviar_lote(). "
            "\nContratos abertos: id_disciplina, id_avaliacao, id_professor, "
            "matrícula ambígua — ver docstring de ResolvedorIDsAbstrato."
        )


class ResolvedorDireto(ResolvedorIDsAbstrato):
    """
    Resolvedor de testes — lê IDs de campos privados do lançamento.

    O caller injeta: _id_matricula, _id_disciplina, _id_avaliacao, _id_professor.
    NÃO ADEQUADO PARA PRODUÇÃO.
    """

    def resolver_ids(self, lancamento: Mapping[str, Any]) -> ResultadoResolucaoIDs:
        erros: list[str] = []

        def _get_int(campo: str, obrigatorio: bool = True) -> Optional[int]:
            if campo not in lancamento:
                if obrigatorio:
                    erros.append(f"Campo '{campo}' ausente no lançamento.")
                return None
            val = lancamento[campo]
            if val is None:
                if obrigatorio:
                    erros.append(f"Campo '{campo}' é None.")
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                erros.append(f"Campo '{campo}' não é inteiro válido: {val!r}")
                return None

        return ResultadoResolucaoIDs(
            id_matricula  = _get_int("_id_matricula",  obrigatorio=True),
            id_disciplina = _get_int("_id_disciplina", obrigatorio=True),
            id_avaliacao  = _get_int("_id_avaliacao",  obrigatorio=True),
            id_professor  = _get_int("_id_professor",  obrigatorio=False),
            erros=erros,
            rastreabilidade={"fonte": "ResolvedorDireto"},
        )


# ---------------------------------------------------------------------------
# Tipos de resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoItemEnvio:
    """
    Registro de auditoria por lançamento sendável processado.

    status:
      "enviado"        — POST bem-sucedido
      "dry_run"        — dry_run=True; payload montado, sem HTTP
      "erro_resolucao" — IDs iScholar não resolvidos
      "erro_envio"     — POST falhou (permanente ou transitório)

    item_key:
      Chave estável calculada por _compute_item_key().
      Usada como identidade no EnvioLoteAuditStore.
      Não colide por nome de aluno, componente ou disciplina.
    """

    lote_id: str
    item_key: str              # identidade estável: hash_conteudo ou fallback SHA-256
    estudante: Optional[str]
    componente: Optional[str]
    disciplina: Optional[str]
    trimestre: Optional[str]
    valor_bruta: Optional[float]

    id_matricula: Optional[int]
    id_disciplina: Optional[int]
    id_avaliacao: Optional[int]
    id_professor: Optional[int]

    dry_run: bool
    status: str
    mensagem: str
    transitorio: bool = False

    payload_enviado: Optional[dict[str, Any]] = None
    resposta_api: Optional[Any] = None
    erros_resolucao: list[str] = field(default_factory=list)
    rastreabilidade: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_agora_iso)


@dataclass
class ResultadoEnvioLote:
    """Resumo agregado do envio de um lote aprovado."""

    lote_id: str
    dry_run: bool
    total_sendaveis: int
    total_enviados: int
    total_dry_run: int
    total_erros_resolucao: int
    total_erros_envio: int
    sucesso: bool
    mensagem: str
    itens: list[ResultadoItemEnvio] = field(default_factory=list)
    timestamp: str = field(default_factory=_agora_iso)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def enviar_lote(
    *,
    estado: EstadoAprovacaoLote,
    itens_store: "LoteItensStore",
    cliente: "IScholarClient",
    resolvedor: ResolvedorIDsAbstrato,
    dry_run: bool = False,
    audit_store: "EnvioLoteAuditStore | None" = None,
) -> ResultadoEnvioLote:
    """
    Envia o conjunto canônico aprovado ao iScholar via IScholarClient.lancar_nota().

    Pré-condições (ValueError se violadas):
      1. estado.status == "aprovado_para_envio"
      2. itens_store.carregar_itens(estado.lote_id) retorna lista (não None)
         — se None: lote foi aprovado sem persistir itens (uso incorreto).
           Fluxo correto: extrair_itens_sendaveis() → aprovar_lote(itens_sendaveis,
           itens_store) → enviar_lote(itens_store).

    O conjunto de itens enviados É O MESMO persistido na aprovação.
    Não há caminho para injetar itens externos diferentes.

    Política de falha parcial:
      Erros de resolução e envio NÃO abortam o lote. transitorio=True no item
      sinaliza candidatos a retry seletivo.
    """
    # --- Pré-condição 1: lote aprovado ----------------------------------------
    if estado.status != "aprovado_para_envio":
        raise ValueError(
            f"enviar_lote: lote '{estado.lote_id}' não está aprovado para envio "
            f"(status atual: {estado.status!r}). "
            "Use aprovacao_lote.aprovar_lote() antes de chamar enviar_lote()."
        )

    # --- Pré-condição 2: itens persistidos ------------------------------------
    sendaveis = itens_store.carregar_itens(estado.lote_id)
    if sendaveis is None:
        raise ValueError(
            f"enviar_lote: lote '{estado.lote_id}' está aprovado mas não tem "
            "itens sendáveis persistidos no itens_store. "
            "Fluxo correto: extrair_itens_sendaveis(resultados_etapa3) → "
            "aprovar_lote(..., itens_sendaveis=itens, itens_store=lote_itens_store) → "
            "enviar_lote(..., itens_store=lote_itens_store)."
        )

    n_enviados        = 0
    n_dry_run         = 0
    n_erro_resolucao  = 0
    n_erro_envio      = 0
    itens_resultado: list[ResultadoItemEnvio] = []

    for l in sendaveis:
        estudante  = l.get("estudante")
        componente = l.get("componente")
        disciplina = l.get("disciplina")
        trimestre  = l.get("trimestre")
        valor_bruta: Optional[float] = l.get("nota_ajustada_0a10")

        item_key = _compute_item_key(estado.lote_id, l)

        item_base: dict[str, Any] = dict(
            lote_id       = estado.lote_id,
            item_key      = item_key,
            estudante     = estudante,
            componente    = componente,
            disciplina    = disciplina,
            trimestre     = trimestre,
            valor_bruta   = valor_bruta,
            dry_run       = dry_run,
            id_matricula  = None,
            id_disciplina = None,
            id_avaliacao  = None,
            id_professor  = None,
        )

        # --- Resolução de IDs -------------------------------------------------
        try:
            resolucao = resolvedor.resolver_ids(l)
        except Exception as exc:
            item = ResultadoItemEnvio(
                **item_base,
                status="erro_resolucao",
                mensagem=f"Resolvedor levantou exceção inesperada: {exc!s}",
                erros_resolucao=[str(exc)],
            )
            n_erro_resolucao += 1
            itens_resultado.append(item)
            if audit_store is not None:
                audit_store.salvar_item(item)
            continue

        item_base["id_matricula"]  = resolucao.id_matricula
        item_base["id_disciplina"] = resolucao.id_disciplina
        item_base["id_avaliacao"]  = resolucao.id_avaliacao
        item_base["id_professor"]  = resolucao.id_professor

        if not resolucao.resolvido:
            item = ResultadoItemEnvio(
                **item_base,
                status="erro_resolucao",
                mensagem="IDs iScholar não resolvidos: " + "; ".join(resolucao.erros),
                erros_resolucao=list(resolucao.erros),
                rastreabilidade=dict(resolucao.rastreabilidade),
            )
            n_erro_resolucao += 1
            itens_resultado.append(item)
            if audit_store is not None:
                audit_store.salvar_item(item)
            continue

        # --- Chamada ao client ------------------------------------------------
        resultado_lc: ResultadoLancamentoNota = cliente.lancar_nota(
            id_matricula  = resolucao.id_matricula,
            id_disciplina = resolucao.id_disciplina,   # type: ignore[arg-type]
            id_avaliacao  = resolucao.id_avaliacao,    # type: ignore[arg-type]
            id_professor  = resolucao.id_professor,
            valor_bruta   = valor_bruta,
            dry_run       = dry_run,
        )

        if dry_run:
            status_item = "dry_run"
            n_dry_run += 1
        elif resultado_lc.sucesso:
            status_item = "enviado"
            n_enviados += 1
        else:
            status_item = "erro_envio"
            n_erro_envio += 1

        item = ResultadoItemEnvio(
            **item_base,
            status          = status_item,
            mensagem        = resultado_lc.mensagem,
            transitorio     = getattr(resultado_lc, "transitorio", False),
            payload_enviado = resultado_lc.payload,
            resposta_api    = resultado_lc.dados,
            rastreabilidade = dict(getattr(resultado_lc, "rastreabilidade", {})),
        )
        itens_resultado.append(item)
        if audit_store is not None:
            audit_store.salvar_item(item)

    # --- Resultado agregado ---------------------------------------------------
    total   = len(sendaveis)
    sucesso = (n_erro_resolucao == 0 and n_erro_envio == 0)

    partes: list[str] = []
    if total == 0:
        partes.append("nenhum lançamento sendável no lote aprovado")
    elif dry_run:
        partes.append(f"dry_run: {n_dry_run}/{total} processados")
    else:
        partes.append(f"{n_enviados}/{total} enviados")
    if n_erro_resolucao:
        partes.append(f"{n_erro_resolucao} erro(s) de resolução de IDs")
    if n_erro_envio:
        partes.append(f"{n_erro_envio} erro(s) de envio")

    return ResultadoEnvioLote(
        lote_id               = estado.lote_id,
        dry_run               = dry_run,
        total_sendaveis       = total,
        total_enviados        = n_enviados,
        total_dry_run         = n_dry_run,
        total_erros_resolucao = n_erro_resolucao,
        total_erros_envio     = n_erro_envio,
        sucesso               = sucesso,
        mensagem              = "; ".join(partes),
        itens                 = itens_resultado,
    )


__all__ = [
    "_compute_item_key",
    "ResultadoResolucaoIDs",
    "ResultadoItemEnvio",
    "ResultadoEnvioLote",
    "ResolvedorIDsAbstrato",
    "ResolvedorNaoImplementado",
    "ResolvedorDireto",
    "enviar_lote",
]