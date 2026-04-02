"""
pipeline_runner.py - Orquestracao reutilizavel do pipeline oficial.

Este modulo concentra a orquestracao sem depender de CLI:
- validacao oficial do lote;
- persistencia do resultado de validacao antes da aprovacao;
- aprovacao explicita e envio oficial.
"""

from __future__ import annotations

import os
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd

from aprovacao_lote import (
    ResumoLote,
    avaliar_lote_para_aprovacao,
    aprovar_lote,
    criar_estado_lote,
    extrair_itens_sendaveis,
    gerar_resumo_lote,
)
from aprovacao_lote_store import AprovacaoLoteStore
from envio_lote import ResultadoEnvioLote, ResolvedorIDsAbstrato, enviar_lote
from envio_lote_audit_store import EnvioLoteAuditStore
from logger import configurar_logger
from lote_itens_store import LoteItensStore
from madan_planilha_mapper import (
    COLUNAS_OBRIGATORIAS_TEMPLATE,
    validar_colunas_obrigatorias_template,
)
from resolvedor_ids_ischolar import (
    ResolvedorIDsHibrido,
    carregar_mapa_avaliacoes,
    carregar_mapa_disciplinas,
    carregar_mapa_professores,
    validar_mapa_avaliacoes,
    validar_mapa_disciplinas,
)
from transformador import linha_madan_para_lancamentos
from utils.hash_utils import sha256_bytes, sha256_dataframe_normalizado
from validacao_lote_store import ResultadoValidacaoPersistido, ValidacaoLoteStore
from resultado_envio_lote_store import ResultadoEnvioLoteStore, ResultadoEnvioPersistido
from validacao_pre_envio import (
    STATUS_BLOQUEADO_ERROS,
    validar_pre_envio_linha,
    criar_resultado_falha_linha,
)
from wide_format_adapter import (
    FORMATO_WIDE_NOVO,
    despivotar_dataframe,
    detectar_formato,
    validar_colunas_wide_novo,
)

if "IScholarClient" not in globals():
    from ischolar_client import IScholarClient


log = configurar_logger("etl.pipeline_runner")

STATUS_VALIDATION_JOB_QUEUED = "validation_job_queued"
STATUS_VALIDATION_PENDING_APPROVAL = "validation_pending_approval"
STATUS_VALIDATION_FAILED = "validation_failed"
STATUS_APPROVAL_JOB_QUEUED = "approval_job_queued"
STATUS_SEND_PROCESSING = "send_processing"
STATUS_SEND_RETRY_SCHEDULED = "send_retry_scheduled"
STATUS_DRY_RUN_COMPLETED = "dry_run_completed"
STATUS_SENT = "sent"
STATUS_SEND_FAILED = "send_failed"

DEFAULT_MAPA_DISC = "mapa_disciplinas.json"
DEFAULT_MAPA_AVAL = "mapa_avaliacoes.json"
DEFAULT_MAPA_PROF = "mapa_professores.json"


class TemplateInvalidoError(ValueError):
    """Planilha com colunas obrigatorias ausentes ou formato incompatível."""


class PreflightTecnicoError(RuntimeError):
    """Falha ao inicializar o client do iScholar."""


class MapaInvalidoError(ValueError):
    """Arquivo de mapa ausente, ilegivel ou com schema invalido."""


class LoteNaoElegivelError(ValueError):
    """Lote bloqueado por erros; nao pode ser aprovado."""


class SnapshotStaleError(ValueError):
    """O snapshot aprovado nao corresponde mais ao snapshot validado."""


class LoteJaAprovadoError(ValueError):
    """Tentativa de aprovar/enviar novamente um lote ja aprovado."""


def _normalizar_email(email: Optional[str]) -> Optional[str]:
    valor = str(email or "").strip().lower()
    if not valor:
        return None
    if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", valor):
        return valor
    return None


def _agora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _valor(obj: Any, chave: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(chave)
    return getattr(obj, chave)


def _normalizar_nome_coluna(nome: str) -> str:
    s = str(nome).strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = (
        s.replace("á", "a")
        .replace("à", "a")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ì", "i")
        .replace("ó", "o")
        .replace("ò", "o")
        .replace("õ", "o")
        .replace("ô", "o")
        .replace("ú", "u")
        .replace("ù", "u")
        .replace("ç", "c")
    )
    s = re.sub(r"[^a-z0-9_]", "_", s)
    return s or "_"


def _calcular_snapshot_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return sha256_bytes(b"__EMPTY_VALIDATION_SNAPSHOT__")
    df_norm = df.copy()
    df_norm.columns = [_normalizar_nome_coluna(c) for c in df_norm.columns]
    sort_by = [
        c
        for c in ("estudante", "ra", "turma", "trimestre", "disciplina")
        if c in df_norm.columns
    ]
    return sha256_dataframe_normalizado(df_norm.fillna(""), sort_by_columns=sort_by)


def carregar_entrada(entrada: str | os.PathLike[str] | pd.DataFrame) -> pd.DataFrame:
    if isinstance(entrada, pd.DataFrame):
        df = entrada.copy()
        return df.dropna(how="all").reset_index(drop=True)

    caminho = Path(entrada)
    if not caminho.exists():
        raise FileNotFoundError(f"Planilha nao encontrada: {caminho}")

    ext = caminho.suffix.lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(caminho, dtype=str, header=0)
        colunas_esperadas = {"estudante", "ra", "turma", "trimestre", "disciplina"}
        colunas_norm = {str(c).strip().lower() for c in df.columns if isinstance(c, str)}
        if not colunas_esperadas.intersection(colunas_norm):
            log.info("Header da linha 1 sem colunas esperadas; tentando header=1.")
            df = pd.read_excel(caminho, dtype=str, header=1)
    elif ext == ".csv":
        df = pd.read_csv(caminho, dtype=str, sep=None, engine="python")
    else:
        raise ValueError(f"Extensao nao suportada: {ext}. Use .xlsx, .xls ou .csv.")

    return df.dropna(how="all").reset_index(drop=True)


def preparar_dataframe_pipeline(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    formato = detectar_formato(list(df.columns))
    if formato == FORMATO_WIDE_NOVO:
        problemas = validar_colunas_wide_novo(list(df.columns))
        if problemas:
            raise TemplateInvalidoError(f"Template wide novo invalido: {problemas}")
        return despivotar_dataframe(df), formato

    ausentes = validar_colunas_obrigatorias_template(list(df.columns))
    if ausentes:
        raise TemplateInvalidoError(
            f"Colunas obrigatorias ausentes na planilha: {ausentes}. "
            f"Esperadas: {COLUNAS_OBRIGATORIAS_TEMPLATE}"
        )
    return df, formato


def processar_validacao(df: pd.DataFrame) -> list[dict[str, Any]]:
    resultados: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        linha_num = int(idx) + 2
        try:
            lancs = linha_madan_para_lancamentos(row_dict, linha_origem=linha_num)
            resultado = validar_pre_envio_linha(row_wide=row_dict, lancamentos=lancs)
            resultados.append(resultado)
        except Exception as exc:
            log.exception("Erro interno inesperado ao processar linha %s", linha_num)
            estudante = row_dict.get("Estudante") or row_dict.get("estudante") or "Desconhecido"
            disciplina = row_dict.get("Disciplina") or row_dict.get("disciplina") or "Desconhecido"
            resultados.append(
                criar_resultado_falha_linha(
                    linha_origem=linha_num,
                    estudante=estudante,
                    componente=disciplina,
                    mensagem_erro=(
                        f"Falha na transformacao ou validacao: "
                        f"{type(exc).__name__} - {exc}"
                    ),
                )
            )
    return resultados


def _agregar_issues(resultados_validacao: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    avisos: list[dict[str, Any]] = []
    erros: list[dict[str, Any]] = []
    pendencias: list[dict[str, Any]] = []

    for res in resultados_validacao:
        for aviso in res.get("avisos", []) or []:
            avisos.append(dict(aviso))
        for erro in res.get("erros", []) or []:
            erros.append(dict(erro))
        for pendencia in res.get("pendencias", []) or []:
            pendencias.append(dict(pendencia))

        for lanc in res.get("lancamentos_com_erro", []) or []:
            for erro in lanc.get("validacao_erros", []) or []:
                item = dict(erro)
                item.setdefault("linha_origem", lanc.get("linha_origem"))
                item.setdefault("componente", lanc.get("componente"))
                item.setdefault("estudante", lanc.get("estudante"))
                erros.append(item)
            for aviso in lanc.get("validacao_avisos", []) or []:
                item = dict(aviso)
                item.setdefault("linha_origem", lanc.get("linha_origem"))
                item.setdefault("componente", lanc.get("componente"))
                item.setdefault("estudante", lanc.get("estudante"))
                avisos.append(item)
            for pendencia in lanc.get("validacao_pendencias", []) or []:
                item = dict(pendencia)
                item.setdefault("linha_origem", lanc.get("linha_origem"))
                item.setdefault("componente", lanc.get("componente"))
                item.setdefault("estudante", lanc.get("estudante"))
                pendencias.append(item)

    return avisos, erros, pendencias


def _resumo_to_dict(resumo: ResumoLote) -> dict[str, Any]:
    return asdict(resumo)


def _resumo_from_dict(dados: Mapping[str, Any]) -> ResumoLote:
    return ResumoLote(
        total_linhas=int(dados["total_linhas"]),
        total_alunos=int(dados["total_alunos"]),
        total_disciplinas=int(dados["total_disciplinas"]),
        total_lancamentos=int(dados["total_lancamentos"]),
        total_sendaveis=int(dados["total_sendaveis"]),
        total_bloqueados=int(dados["total_bloqueados"]),
        total_avisos=int(dados["total_avisos"]),
        total_pendencias=int(dados["total_pendencias"]),
        total_duplicidades=int(dados["total_duplicidades"]),
        total_erros=int(dados["total_erros"]),
        status_geral_por_linha=dict(dados["status_geral_por_linha"]),
        status_sugerido=str(dados["status_sugerido"]),
        motivos_status=list(dados["motivos_status"]),
    )


def _serializar_validacao(resultado: ResultadoValidacaoPersistido, *, formato_detectado: Optional[str] = None) -> dict[str, Any]:
    payload = {
        "lote_id": resultado.lote_id,
        "job_id": resultado.job_id,
        "snapshot_hash": resultado.snapshot_hash,
        "status": resultado.status,
        "resumo": resultado.resumo,
        "avisos": resultado.avisos,
        "erros": resultado.erros,
        "pendencias": resultado.pendencias,
        "apto_para_aprovacao": resultado.apto_para_aprovacao,
        "resultados_validacao": resultado.resultados_validacao,
        "itens_sendaveis": resultado.itens_sendaveis,
        "versao": resultado.versao,
        "expires_at": resultado.expires_at,
        "created_at": resultado.created_at,
        "updated_at": resultado.updated_at,
    }
    if formato_detectado is not None:
        payload["formato_detectado"] = formato_detectado
    return payload


def _normalizar_identidade_aprovador(
    *,
    aprovado_por: Optional[str],
    approval_identity: Optional[Mapping[str, Any]] = None,
    origem_padrao: str = "api_manual",
) -> dict[str, Optional[str]]:
    dados = dict(approval_identity or {})
    email = _normalizar_email(dados.get("aprovador_email"))
    nome_informado = str(dados.get("aprovador_nome_informado") or "").strip() or None
    origem = str(dados.get("aprovador_origem") or origem_padrao).strip() or origem_padrao
    display = (
        str(dados.get("aprovado_por") or aprovado_por or "").strip()
        or email
        or nome_informado
    )
    strength = "medium" if (email and origem == "google_apps_script_session") else "weak"
    return {
        "aprovado_por": display or None,
        "aprovador_nome_informado": nome_informado,
        "aprovador_email": email,
        "aprovador_origem": origem,
        "aprovador_identity_strength": strength,
    }


def _serializar_identidade_aprovador(obj: Mapping[str, Any] | Any) -> dict[str, Any]:
    return {
        "nome_informado": _valor(obj, "aprovador_nome_informado"),
        "email": _valor(obj, "aprovador_email"),
        "origem": _valor(obj, "aprovador_origem"),
        "identity_strength": _valor(obj, "aprovador_identity_strength"),
    }


def _serializar_estado_aprovacao(estado: Any) -> dict[str, Any]:
    return {
        "lote_id": estado.lote_id,
        "status": estado.status,
        "elegivel_para_aprovacao": estado.elegivel_para_aprovacao,
        "resumo_atual": estado.resumo_atual,
        "aprovado_por": estado.aprovado_por,
        "aprovador": _serializar_identidade_aprovador(estado),
        "aprovado_em": estado.aprovado_em,
        "rejeitado_por": estado.rejeitado_por,
        "rejeitado_em": estado.rejeitado_em,
        "motivo_rejeicao": estado.motivo_rejeicao,
        "snapshot_resumo_aprovado": estado.snapshot_resumo_aprovado,
        "hash_resumo_aprovado": estado.hash_resumo_aprovado,
    }


def _serializar_resultado_envio(resultado: ResultadoEnvioLote) -> dict[str, Any]:
    return asdict(resultado)


def _serializar_resultado_envio_persistido(resultado: ResultadoEnvioPersistido) -> dict[str, Any]:
    return {
        "lote_id": resultado.lote_id,
        "job_id": resultado.job_id,
        "snapshot_hash": resultado.snapshot_hash,
        "status": resultado.status,
        "aprovado_por": resultado.aprovado_por,
        "aprovador": _serializar_identidade_aprovador(resultado),
        "sucesso": resultado.sucesso,
        "quantidade_enviada": resultado.quantidade_enviada,
        "quantidade_com_erro": resultado.quantidade_com_erro,
        "total_sendaveis": resultado.total_sendaveis,
        "total_dry_run": resultado.total_dry_run,
        "total_erros_resolucao": resultado.total_erros_resolucao,
        "total_erros_envio": resultado.total_erros_envio,
        "mensagem": resultado.mensagem,
        "resumo": resultado.resumo,
        "auditoria_resumo": resultado.auditoria_resumo,
        "finished_at": resultado.finished_at,
        "created_at": resultado.created_at,
        "updated_at": resultado.updated_at,
    }


def _hash_resumo(resumo: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(resumo), sort_keys=True, ensure_ascii=False, default=str)
    return sha256_bytes(canonical.encode("utf-8"))


def _approval_state_matches_current_snapshot(estado: Any, resumo_atual: Mapping[str, Any]) -> bool:
    if getattr(estado, "status", None) == "aguardando_aprovacao":
        return True
    if getattr(estado, "snapshot_resumo_aprovado", None) is None or getattr(estado, "hash_resumo_aprovado", None) is None:
        return False
    return str(estado.hash_resumo_aprovado) == _hash_resumo(resumo_atual)


def registrar_validacao_em_fila(
    *,
    lote_id: str,
    job_id: int,
    snapshot_hash: str,
    validation_store: ValidacaoLoteStore,
) -> dict[str, Any]:
    anterior = validation_store.carregar(lote_id)
    persistido = validation_store.salvar(
        ResultadoValidacaoPersistido(
            lote_id=lote_id,
            job_id=job_id,
            snapshot_hash=snapshot_hash,
            status=STATUS_VALIDATION_JOB_QUEUED,
            resumo={},
            avisos=[],
            erros=[],
            pendencias=[],
            apto_para_aprovacao=False,
            resultados_validacao=[],
            itens_sendaveis=[],
            versao=(anterior.versao + 1) if anterior is not None else 1,
            expires_at=anterior.expires_at if anterior is not None else None,
        )
    )
    return _serializar_validacao(persistido)


def registrar_resultado_envio(
    *,
    lote_id: str,
    job_id: Optional[int],
    snapshot_hash: str,
    status: str,
    result_store: ResultadoEnvioLoteStore,
    aprovado_por: Optional[str] = None,
    approval_identity: Optional[Mapping[str, Any]] = None,
    sucesso: bool = False,
    mensagem: Optional[str] = None,
    envio: Optional[Mapping[str, Any]] = None,
    auditoria_resumo: Optional[dict[str, int]] = None,
    finished_at: Optional[str] = None,
) -> dict[str, Any]:
    envio_dict = dict(envio or {})
    identidade = _normalizar_identidade_aprovador(
        aprovado_por=aprovado_por,
        approval_identity=approval_identity,
    )
    total_erros_resolucao = int(envio_dict.get("total_erros_resolucao", 0) or 0)
    total_erros_envio = int(envio_dict.get("total_erros_envio", 0) or 0)
    persistido = result_store.salvar(
        ResultadoEnvioPersistido(
            lote_id=lote_id,
            job_id=job_id,
            snapshot_hash=snapshot_hash,
            status=status,
            aprovado_por=identidade["aprovado_por"],
            aprovador_nome_informado=identidade["aprovador_nome_informado"],
            aprovador_email=identidade["aprovador_email"],
            aprovador_origem=identidade["aprovador_origem"],
            aprovador_identity_strength=identidade["aprovador_identity_strength"],
            sucesso=bool(envio_dict.get("sucesso", sucesso)),
            quantidade_enviada=int(envio_dict.get("total_enviados", 0) or 0),
            quantidade_com_erro=total_erros_resolucao + total_erros_envio,
            total_sendaveis=int(envio_dict.get("total_sendaveis", 0) or 0),
            total_dry_run=int(envio_dict.get("total_dry_run", 0) or 0),
            total_erros_resolucao=total_erros_resolucao,
            total_erros_envio=total_erros_envio,
            mensagem=mensagem or envio_dict.get("mensagem"),
            resumo=envio_dict,
            auditoria_resumo=dict(auditoria_resumo or {}),
            finished_at=finished_at,
        )
    )
    return _serializar_resultado_envio_persistido(persistido)


def atualizar_status_lote_envio(
    *,
    lote_id: str,
    status: str,
    validation_store: ValidacaoLoteStore,
    result_store: Optional[ResultadoEnvioLoteStore] = None,
    job_id: Optional[int] = None,
    snapshot_hash: Optional[str] = None,
    aprovado_por: Optional[str] = None,
    approval_identity: Optional[Mapping[str, Any]] = None,
    sucesso: bool = False,
    mensagem: Optional[str] = None,
    envio: Optional[Mapping[str, Any]] = None,
    auditoria_resumo: Optional[dict[str, int]] = None,
    finished_at: Optional[str] = None,
) -> tuple[Optional[ResultadoValidacaoPersistido], Optional[dict[str, Any]]]:
    persistido = validation_store.carregar(lote_id)
    snapshot_hash_final = snapshot_hash
    if persistido is not None:
        persistido.status = status
        persistido = validation_store.salvar(persistido)
        snapshot_hash_final = persistido.snapshot_hash
    resultado_envio = None
    if result_store is not None and snapshot_hash_final is not None:
        resultado_envio = registrar_resultado_envio(
            lote_id=lote_id,
            job_id=job_id,
            snapshot_hash=snapshot_hash_final,
            status=status,
            result_store=result_store,
            aprovado_por=aprovado_por,
            approval_identity=approval_identity,
            sucesso=sucesso,
            mensagem=mensagem,
            envio=envio,
            auditoria_resumo=auditoria_resumo,
            finished_at=finished_at,
        )
    return persistido, resultado_envio


def consultar_resultado_envio_atual(
    *,
    lote_id: str,
    validation_store: ValidacaoLoteStore,
    result_store: ResultadoEnvioLoteStore,
) -> Optional[dict[str, Any]]:
    validacao = validation_store.carregar(lote_id)
    persistido = result_store.carregar(lote_id)
    if validacao is None or persistido is None:
        return None
    if persistido.snapshot_hash != validacao.snapshot_hash:
        return None
    return _serializar_resultado_envio_persistido(persistido)


def validar_solicitacao_aprovacao(
    *,
    lote_id: str,
    aprovado_por: str,
    approval_identity: Optional[Mapping[str, Any]] = None,
    validation_store: ValidacaoLoteStore,
    approval_store: AprovacaoLoteStore,
    expected_snapshot_hash: Optional[str] = None,
    result_store: Optional[ResultadoEnvioLoteStore] = None,
) -> dict[str, Any]:
    identidade = _normalizar_identidade_aprovador(
        aprovado_por=aprovado_por,
        approval_identity=approval_identity,
    )
    if not str(identidade["aprovado_por"] or "").strip():
        raise ValueError("aprovado_por e obrigatorio para aprovar o lote.")

    persistido = validation_store.carregar(lote_id)
    if persistido is None:
        raise KeyError(f"Resultado de validacao do lote '{lote_id}' nao encontrado.")

    if expected_snapshot_hash and persistido.snapshot_hash != expected_snapshot_hash:
        raise SnapshotStaleError(
            f"Snapshot stale para o lote '{lote_id}': "
            f"esperado={expected_snapshot_hash} atual={persistido.snapshot_hash}"
        )

    if persistido.status != STATUS_VALIDATION_PENDING_APPROVAL:
        raise ValueError(
            f"Lote '{lote_id}' nao esta aguardando aprovacao para o snapshot atual "
            f"(status atual: {persistido.status})."
        )

    if not persistido.apto_para_aprovacao:
        raise LoteNaoElegivelError("O lote contem erros e nao pode ser aprovado.")

    resultado_envio_atual = result_store.carregar(lote_id) if result_store is not None else None
    if (
        resultado_envio_atual is not None
        and resultado_envio_atual.snapshot_hash == persistido.snapshot_hash
    ):
        raise LoteJaAprovadoError(
            f"Lote '{lote_id}' ja possui solicitacao de aprovacao/envio "
            f"para este snapshot (status atual: {resultado_envio_atual.status})."
        )

    resumo = _resumo_from_dict(persistido.resumo)
    estado = approval_store.carregar(lote_id)
    if (
        estado is not None
        and estado.status != "aguardando_aprovacao"
        and resultado_envio_atual is not None
        and resultado_envio_atual.snapshot_hash == persistido.snapshot_hash
    ):
        raise LoteJaAprovadoError(f"Lote '{lote_id}' ja foi aprovado anteriormente.")

    return {
        "lote_id": lote_id,
        "snapshot_hash": persistido.snapshot_hash,
        "aprovado_por": str(identidade["aprovado_por"]).strip(),
        "approval_identity": identidade,
        "status": persistido.status,
        "validation_result": _serializar_validacao(persistido),
        "resumo": _resumo_to_dict(resumo),
    }


def registrar_solicitacao_aprovacao_envio(
    *,
    lote_id: str,
    job_id: int,
    aprovado_por: str,
    approval_identity: Optional[Mapping[str, Any]] = None,
    validation_store: ValidacaoLoteStore,
    approval_store: AprovacaoLoteStore,
    result_store: ResultadoEnvioLoteStore,
    expected_snapshot_hash: Optional[str] = None,
) -> dict[str, Any]:
    validado = validar_solicitacao_aprovacao(
        lote_id=lote_id,
        aprovado_por=aprovado_por,
        approval_identity=approval_identity,
        validation_store=validation_store,
        approval_store=approval_store,
        expected_snapshot_hash=expected_snapshot_hash,
        result_store=result_store,
    )
    persistido = validation_store.carregar(lote_id)
    if persistido is None:
        raise KeyError(f"Resultado de validacao do lote '{lote_id}' nao encontrado.")

    resumo = _resumo_from_dict(persistido.resumo)
    criar_estado_lote(lote_id=lote_id, resumo=resumo, store=approval_store)
    persistido, resultado_envio = atualizar_status_lote_envio(
        lote_id=lote_id,
        status=STATUS_APPROVAL_JOB_QUEUED,
        validation_store=validation_store,
        result_store=result_store,
        job_id=job_id,
        snapshot_hash=persistido.snapshot_hash,
        aprovado_por=validado["aprovado_por"],
        approval_identity=validado["approval_identity"],
        sucesso=False,
        mensagem="Job de aprovacao/envio criado e aguardando worker.",
    )
    if persistido is None:
        raise KeyError(f"Resultado de validacao do lote '{lote_id}' nao encontrado.")
    validado["status"] = persistido.status
    validado["validation_result"] = _serializar_validacao(persistido)
    validado["send_result"] = resultado_envio
    return validado


def preparar_dependencias_envio(
    *,
    mapa_disciplinas: str,
    mapa_avaliacoes: str,
    mapa_professores: Optional[str] = None,
    professor_obrigatorio: bool = False,
    cliente: Any = None,
    client_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    cliente_local = cliente
    cliente_criado = False

    if cliente_local is None:
        factory = client_factory or IScholarClient
        try:
            cliente_local = factory()
            cliente_criado = True
        except Exception as exc:
            raise PreflightTecnicoError(
                f"Falha ao inicializar IScholarClient: {exc}"
            ) from exc

    try:
        resolvedor, total_disc, total_aval = _carregar_resolvedor(
            cliente=cliente_local,
            caminho_disc=mapa_disciplinas,
            caminho_aval=mapa_avaliacoes,
            caminho_prof=mapa_professores,
            professor_obrigatorio=professor_obrigatorio,
        )
    except Exception:
        if cliente_criado:
            try:
                cliente_local.close()
            except Exception:
                pass
        raise

    return {
        "cliente": cliente_local,
        "resolvedor": resolvedor,
        "disc_count": total_disc,
        "aval_count": total_aval,
        "cliente_criado": cliente_criado,
    }


def executar_validacao(
    *,
    lote_id: str,
    entrada: str | os.PathLike[str] | pd.DataFrame,
    validation_store: ValidacaoLoteStore,
    job_id: Optional[int] = None,
    snapshot_hash: Optional[str] = None,
    versao: int = 1,
    expires_at: Optional[str] = None,
) -> dict[str, Any]:
    df_original = carregar_entrada(entrada)
    snapshot_hash_final = snapshot_hash or _calcular_snapshot_hash(df_original)
    df_pipeline, formato = preparar_dataframe_pipeline(df_original)
    resultados_validacao = processar_validacao(df_pipeline)
    resumo = gerar_resumo_lote(resultados_validacao)
    apto_para_aprovacao = bool(
        avaliar_lote_para_aprovacao(resumo)["elegivel_para_aprovacao"]
    )
    avisos, erros, pendencias = _agregar_issues(resultados_validacao)
    itens_sendaveis = extrair_itens_sendaveis(resultados_validacao)
    status = (
        STATUS_VALIDATION_PENDING_APPROVAL
        if apto_para_aprovacao
        else STATUS_VALIDATION_FAILED
    )

    persistido = validation_store.salvar(
        ResultadoValidacaoPersistido(
            lote_id=lote_id,
            job_id=job_id,
            snapshot_hash=snapshot_hash_final,
            status=status,
            resumo=_resumo_to_dict(resumo),
            avisos=avisos,
            erros=erros,
            pendencias=pendencias,
            apto_para_aprovacao=apto_para_aprovacao,
            resultados_validacao=resultados_validacao,
            itens_sendaveis=itens_sendaveis,
            versao=versao,
            expires_at=expires_at,
        )
    )
    return _serializar_validacao(persistido, formato_detectado=formato)


def executar_aprovacao_e_envio(
    *,
    lote_id: str,
    aprovado_por: str,
    approval_identity: Optional[Mapping[str, Any]] = None,
    validation_store: ValidacaoLoteStore,
    approval_store: AprovacaoLoteStore,
    itens_store: LoteItensStore,
    result_store: Optional[ResultadoEnvioLoteStore] = None,
    audit_store: Optional[EnvioLoteAuditStore] = None,
    dry_run: bool = False,
    expected_snapshot_hash: Optional[str] = None,
    job_id: Optional[int] = None,
    cliente: Any = None,
    resolvedor: Optional[ResolvedorIDsAbstrato] = None,
    mapa_disciplinas: Optional[str] = None,
    mapa_avaliacoes: Optional[str] = None,
    mapa_professores: Optional[str] = None,
    professor_obrigatorio: bool = False,
    client_factory: Optional[Callable[[], Any]] = None,
) -> dict[str, Any]:
    persistido = validation_store.carregar(lote_id)
    if persistido is None:
        raise KeyError(f"Resultado de validacao do lote '{lote_id}' nao encontrado.")
    identidade = _normalizar_identidade_aprovador(
        aprovado_por=aprovado_por,
        approval_identity=approval_identity,
    )

    if expected_snapshot_hash and persistido.snapshot_hash != expected_snapshot_hash:
        raise SnapshotStaleError(
            f"Snapshot stale para o lote '{lote_id}': "
            f"esperado={expected_snapshot_hash} atual={persistido.snapshot_hash}"
        )

    dependencias: dict[str, Any] = {}
    cliente_local = cliente
    cliente_criado = False
    resolvedor_local = resolvedor

    if resolvedor_local is None:
        caminho_disc = mapa_disciplinas or DEFAULT_MAPA_DISC
        caminho_aval = mapa_avaliacoes or DEFAULT_MAPA_AVAL
        caminho_prof = mapa_professores
        if caminho_prof is None and Path(DEFAULT_MAPA_PROF).exists():
            caminho_prof = DEFAULT_MAPA_PROF

        dependencias = preparar_dependencias_envio(
            mapa_disciplinas=caminho_disc,
            mapa_avaliacoes=caminho_aval,
            mapa_professores=caminho_prof,
            professor_obrigatorio=professor_obrigatorio,
            cliente=cliente_local,
            client_factory=client_factory,
        )
        cliente_local = dependencias["cliente"]
        resolvedor_local = dependencias["resolvedor"]
        cliente_criado = bool(dependencias["cliente_criado"])

    try:
        if not persistido.apto_para_aprovacao:
            raise LoteNaoElegivelError("O lote contem erros e nao pode ser aprovado.")

        resumo = _resumo_from_dict(persistido.resumo)
        resumo_hash_atual = _hash_resumo(persistido.resumo)
        estado = approval_store.carregar(lote_id)
        if estado is None:
            estado = criar_estado_lote(lote_id=lote_id, resumo=resumo, store=approval_store)
        elif estado.status == "aprovado_para_envio":
            resultado_envio_atual = result_store.carregar(lote_id) if result_store is not None else None
            if (
                resultado_envio_atual is not None
                and resultado_envio_atual.snapshot_hash == persistido.snapshot_hash
                and job_id is not None
                and resultado_envio_atual.job_id == job_id
                and resultado_envio_atual.status in {
                    STATUS_APPROVAL_JOB_QUEUED,
                    STATUS_SEND_PROCESSING,
                    STATUS_SEND_RETRY_SCHEDULED,
                    STATUS_SEND_FAILED,
                }
                and str(estado.hash_resumo_aprovado or "") == resumo_hash_atual
            ):
                log.info(
                    "Retomando lote aprovado no mesmo job | lote_id=%s | job_id=%s | status_resultado=%s",
                    lote_id,
                    job_id,
                    resultado_envio_atual.status,
                )
            elif str(estado.hash_resumo_aprovado or "") != resumo_hash_atual:
                estado = criar_estado_lote(lote_id=lote_id, resumo=resumo, store=approval_store)
            else:
                raise LoteJaAprovadoError(f"Lote '{lote_id}' ja foi aprovado anteriormente.")
        elif estado.status != "aguardando_aprovacao":
            if _approval_state_matches_current_snapshot(estado, persistido.resumo):
                raise ValueError(
                    f"Lote '{lote_id}' nao esta aguardando aprovacao "
                    f"(status atual: {estado.status})."
                )
            estado = criar_estado_lote(lote_id=lote_id, resumo=resumo, store=approval_store)
        else:
            estado.resumo_atual = dict(persistido.resumo)
            estado.elegivel_para_aprovacao = persistido.apto_para_aprovacao
            approval_store.salvar(estado)

        persistido, _ = atualizar_status_lote_envio(
            lote_id=lote_id,
            status=STATUS_SEND_PROCESSING,
            validation_store=validation_store,
            result_store=result_store,
            job_id=job_id,
            snapshot_hash=persistido.snapshot_hash,
            aprovado_por=identidade["aprovado_por"],
            approval_identity=identidade,
            sucesso=False,
            mensagem="Worker processando aprovacao/envio.",
        )
        if persistido is None:
            raise KeyError(f"Resultado de validacao do lote '{lote_id}' nao encontrado.")

        if estado.status != "aprovado_para_envio":
            estado = aprovar_lote(
                estado,
                aprovado_por=str(identidade["aprovado_por"]),
                aprovador_nome_informado=identidade["aprovador_nome_informado"],
                aprovador_email=identidade["aprovador_email"],
                aprovador_origem=identidade["aprovador_origem"],
                aprovador_identity_strength=identidade["aprovador_identity_strength"],
                store=approval_store,
                itens_sendaveis=persistido.itens_sendaveis,
                itens_store=itens_store,
            )

        resultado_envio = enviar_lote(
            estado=estado,
            itens_store=itens_store,
            cliente=cliente_local,
            resolvedor=resolvedor_local,
            dry_run=dry_run,
            audit_store=audit_store,
        )

        if dry_run and resultado_envio.sucesso:
            persistido.status = STATUS_DRY_RUN_COMPLETED
        elif resultado_envio.sucesso:
            persistido.status = STATUS_SENT
        else:
            persistido.status = STATUS_SEND_FAILED
        persistido, resultado_envio_persistido = atualizar_status_lote_envio(
            lote_id=lote_id,
            status=persistido.status,
            validation_store=validation_store,
            result_store=result_store,
            job_id=job_id,
            snapshot_hash=persistido.snapshot_hash,
            aprovado_por=identidade["aprovado_por"],
            approval_identity=identidade,
            sucesso=bool(resultado_envio.sucesso),
            mensagem=str(resultado_envio.mensagem),
            envio=_serializar_resultado_envio(resultado_envio),
            auditoria_resumo=(audit_store.resumo_lote(lote_id) if audit_store is not None else {}),
            finished_at=getattr(resultado_envio, "timestamp", None) or _agora_iso(),
        )
        if persistido is None:
            raise KeyError(f"Resultado de validacao do lote '{lote_id}' nao encontrado.")

        return {
            "lote_id": lote_id,
            "job_id": job_id or persistido.job_id,
            "snapshot_hash": persistido.snapshot_hash,
            "status": persistido.status,
            "aprovacao": _serializar_estado_aprovacao(estado),
            "envio": _serializar_resultado_envio(resultado_envio),
            "validation_result": _serializar_validacao(persistido),
            "send_result": resultado_envio_persistido,
            "preflight": {
                "disc_count": dependencias.get("disc_count"),
                "aval_count": dependencias.get("aval_count"),
            },
        }
    finally:
        if cliente_criado and cliente_local is not None:
            try:
                cliente_local.close()
            except Exception:
                pass


def _carregar_resolvedor(
    *,
    cliente: Any,
    caminho_disc: str,
    caminho_aval: str,
    caminho_prof: Optional[str],
    professor_obrigatorio: bool,
) -> tuple[ResolvedorIDsHibrido, int, int]:
    if not Path(caminho_disc).exists():
        raise MapaInvalidoError(f"Mapa de disciplinas nao encontrado: {caminho_disc}")

    try:
        mapa_disc = carregar_mapa_disciplinas(caminho_disc)
    except Exception as exc:
        raise MapaInvalidoError(f"Mapa de disciplinas invalido: {exc}") from exc

    problemas_disc = validar_mapa_disciplinas(mapa_disc)
    if problemas_disc:
        log.warning("Mapa de disciplinas com problemas: %s", problemas_disc)

    if not Path(caminho_aval).exists():
        raise MapaInvalidoError(f"Mapa de avaliacoes nao encontrado: {caminho_aval}")

    try:
        mapa_aval = carregar_mapa_avaliacoes(caminho_aval)
    except Exception as exc:
        raise MapaInvalidoError(f"Mapa de avaliacoes invalido: {exc}") from exc

    problemas_aval = validar_mapa_avaliacoes(mapa_aval)
    if problemas_aval:
        log.warning("Mapa de avaliacoes com problemas: %s", problemas_aval)

    mapa_prof: Optional[dict[str, int]] = None
    if caminho_prof and Path(caminho_prof).exists():
        try:
            mapa_prof = carregar_mapa_professores(caminho_prof)
        except Exception as exc:
            log.warning("Mapa de professores invalido (ignorado): %s", exc)
            mapa_prof = None

    resolvedor = ResolvedorIDsHibrido(
        cliente=cliente,
        mapa_disciplinas=mapa_disc,
        mapa_avaliacoes=mapa_aval,
        mapa_professores=mapa_prof,
        professor_obrigatorio=professor_obrigatorio,
    )
    return resolvedor, len(mapa_disc), len(mapa_aval)


__all__ = [
    "STATUS_VALIDATION_JOB_QUEUED",
    "STATUS_VALIDATION_PENDING_APPROVAL",
    "STATUS_VALIDATION_FAILED",
    "STATUS_APPROVAL_JOB_QUEUED",
    "STATUS_SEND_PROCESSING",
    "STATUS_SEND_RETRY_SCHEDULED",
    "STATUS_DRY_RUN_COMPLETED",
    "STATUS_SENT",
    "STATUS_SEND_FAILED",
    "TemplateInvalidoError",
    "PreflightTecnicoError",
    "MapaInvalidoError",
    "LoteNaoElegivelError",
    "SnapshotStaleError",
    "LoteJaAprovadoError",
    "carregar_entrada",
    "preparar_dataframe_pipeline",
    "processar_validacao",
    "preparar_dependencias_envio",
    "registrar_validacao_em_fila",
    "registrar_resultado_envio",
    "atualizar_status_lote_envio",
    "consultar_resultado_envio_atual",
    "validar_solicitacao_aprovacao",
    "registrar_solicitacao_aprovacao_envio",
    "executar_validacao",
    "executar_aprovacao_e_envio",
]
