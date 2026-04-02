"""
cli_envio.py - Interface de terminal do fluxo oficial.

Mantem a UX atual do CLI, mas delega a orquestracao ao pipeline_runner.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd

from aprovacao_lote_store import AprovacaoLoteStore
from envio_lote_audit_store import EnvioLoteAuditStore
from logger import configurar_logger
from lote_itens_store import LoteItensStore
from pipeline_runner import (
    LoteJaAprovadoError,
    LoteNaoElegivelError,
    MapaInvalidoError,
    PreflightTecnicoError,
    SnapshotStaleError,
    TemplateInvalidoError,
    executar_aprovacao_e_envio,
    executar_validacao,
    preparar_dependencias_envio,
)
from validacao_lote_store import ValidacaoLoteStore

if "IScholarClient" not in globals():
    from ischolar_client import IScholarClient


log = configurar_logger("etl.cli_envio")

_MAPA_DISC_DEFAULT = "mapa_disciplinas.json"
_MAPA_AVAL_DEFAULT = "mapa_avaliacoes.json"
_MAPA_PROF_DEFAULT = "mapa_professores.json"
_VALIDACOES_DB_DEFAULT = os.getenv("VALIDACAO_LOTE_DB", "validacoes_lote.db")
_APROVACOES_DB_DEFAULT = os.getenv("APROVACAO_LOTE_DB", "aprovacoes_lote.db")
_ITENS_DB_DEFAULT = os.getenv("LOTE_ITENS_DB", "lote_itens.db")
_AUDIT_DB_DEFAULT = os.getenv("ENVIO_LOTE_AUDIT_DB", "envio_lote_audit.db")


class AprovacaoCanceladaError(InterruptedError):
    """Operador recusou ou cancelou a aprovacao do lote."""


def _sep(char: str = "-", n: int = 60) -> None:
    print(char * n)


def _titulo(texto: str) -> None:
    _sep()
    print(f"  {texto}")
    _sep()


def _ok(msg: str) -> None:
    print(f"  OK  {msg}")


def _aviso(msg: str) -> None:
    print(f"  AVISO  {msg}")


def _erro(msg: str) -> None:
    print(f"  ERRO  {msg}")


def _info(msg: str) -> None:
    print(f"      {msg}")


def _v(obj: Mapping[str, Any] | Any, chave: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(chave)
    return getattr(obj, chave)


def _imprimir_resumo(resumo: Mapping[str, Any], resultados: list[dict[str, Any]]) -> None:
    _titulo("RESUMO DO LOTE")
    print(f"  Linhas lidas          : {_v(resumo, 'total_linhas')}")
    print(f"  Alunos unicos         : {_v(resumo, 'total_alunos')}")
    print(f"  Disciplinas unicas    : {_v(resumo, 'total_disciplinas')}")
    print(f"  Total de lancamentos  : {_v(resumo, 'total_lancamentos')}")
    print(f"  Itens sendaveis       : {_v(resumo, 'total_sendaveis')}")
    print(f"  Itens bloqueados      : {_v(resumo, 'total_bloqueados')}")
    print(f"  Avisos                : {_v(resumo, 'total_avisos')}")
    print(f"  Pendencias            : {_v(resumo, 'total_pendencias')}")
    print(f"  Erros                 : {_v(resumo, 'total_erros')}")
    print(f"  Status sugerido       : {_v(resumo, 'status_sugerido')}")
    _sep("-", 60)

    bloqueadas = [r for r in resultados if r.get("status_geral") == "bloqueado_por_erros"]
    if bloqueadas:
        _aviso(f"{len(bloqueadas)} linha(s) bloqueada(s) por erros:")
        for res in bloqueadas[:10]:
            for lanc in res.get("lancamentos_com_erro", [])[:3]:
                estudante = lanc.get("estudante", "?")
                componente = lanc.get("componente", "?")
                for err in lanc.get("validacao_erros", [])[:2]:
                    _info(f"[{err.get('code')}] {estudante} / {componente}: {err.get('message', '')}")
        if len(bloqueadas) > 10:
            _info(f"... e mais {len(bloqueadas) - 10} linha(s) bloqueada(s).")

    total_avisos = 0
    for res in resultados:
        for aviso in res.get("avisos", []):
            if total_avisos >= 5:
                break
            _aviso(f"Aviso [{aviso.get('code')}]: {aviso.get('message', '')}")
            total_avisos += 1


def _solicitar_aprovacao(
    *,
    apto_para_aprovacao: bool,
    resumo: Mapping[str, Any],
    aprovador_arg: Optional[str],
) -> str:
    if not apto_para_aprovacao:
        raise LoteNaoElegivelError("O lote contem erros e nao pode ser aprovado.")

    if aprovador_arg:
        _ok(f"Aprovacao automatica pelo aprovador: {aprovador_arg!r}")
        return aprovador_arg.strip()

    _titulo("APROVACAO MANUAL NECESSARIA")
    print(f"  Itens sendaveis prontos para envio: {_v(resumo, 'total_sendaveis')}")
    print(f"  Avisos presentes                  : {_v(resumo, 'total_avisos')}")
    print()
    print("  Reveja o resumo acima antes de confirmar.")
    print()

    try:
        nome = input("  Nome do aprovador (ou Enter para cancelar): ").strip()
    except (EOFError, KeyboardInterrupt):
        raise AprovacaoCanceladaError("Aprovacao cancelada pelo operador.")

    if not nome:
        raise AprovacaoCanceladaError("Aprovacao cancelada - nome do aprovador nao informado.")

    try:
        confirma = input(f"  Confirma aprovacao por '{nome}'? [s/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        raise AprovacaoCanceladaError("Aprovacao cancelada pelo operador.")

    if confirma not in ("s", "sim", "y", "yes"):
        raise AprovacaoCanceladaError("Aprovacao cancelada pelo operador.")
    return nome


def _imprimir_resultado_envio(resultado: Mapping[str, Any], dry_run: bool) -> None:
    _titulo("RESULTADO DO ENVIO")
    modo = "DRY RUN" if dry_run else "ENVIO REAL"
    print(f"  Modo                  : {modo}")
    print(f"  Total sendaveis       : {_v(resultado, 'total_sendaveis')}")
    if dry_run:
        print(f"  Processados (dry run) : {_v(resultado, 'total_dry_run')}")
    else:
        print(f"  Enviados com sucesso  : {_v(resultado, 'total_enviados')}")
    print(f"  Erros de resolucao    : {_v(resultado, 'total_erros_resolucao')}")
    print(f"  Erros de envio        : {_v(resultado, 'total_erros_envio')}")
    print(f"  Status geral          : {'OK' if _v(resultado, 'sucesso') else 'COM ERROS'}")
    _sep("-", 60)

    erros_res = [it for it in resultado.get("itens", []) if it.get("status") == "erro_resolucao"]
    if erros_res:
        _aviso(f"{len(erros_res)} item(ns) com erro de resolucao de IDs:")
        for item in erros_res[:10]:
            cats = item.get("rastreabilidade", {}).get("categorias_erro", [])
            cat_str = ", ".join(cats) if cats else "desconhecido"
            _info(f"[{cat_str}] {item.get('estudante') or '?'} / {item.get('componente') or '?'}")
            for err in item.get("erros_resolucao", [])[:2]:
                _info(f"-> {err}")

    erros_env = [it for it in resultado.get("itens", []) if it.get("status") == "erro_envio"]
    if erros_env:
        _aviso(f"{len(erros_env)} item(ns) com erro de envio:")
        for item in erros_env[:10]:
            trans = " [transitorio - candidato a retry]" if item.get("transitorio") else ""
            _info(f"{item.get('estudante') or '?'} / {item.get('componente') or '?'}: {item.get('mensagem')}{trans}")

    if dry_run and _v(resultado, "total_dry_run") > 0:
        _info("")
        _info("Payloads prontos. Remova --dry-run para executar o envio real.")


def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fluxo oficial - Envio de notas Madan para o iScholar",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--planilha", default=None, help="Caminho para o Excel ou CSV de notas.")
    parser.add_argument(
        "--turma-dir",
        default=None,
        dest="turma_dir",
        help="Diretorio com planilhas multi-abas legadas. Mutuamente exclusivo com --planilha.",
    )
    parser.add_argument("--lote-id", required=True, dest="lote_id", help="Identificador unico do lote.")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Monta payloads sem POST real.")
    parser.add_argument("--aprovador", default=None, help="Nome do aprovador.")
    parser.add_argument(
        "--mapa-disciplinas",
        default=_MAPA_DISC_DEFAULT,
        dest="mapa_disciplinas",
        help="Caminho para mapa_disciplinas.json.",
    )
    parser.add_argument(
        "--mapa-avaliacoes",
        default=_MAPA_AVAL_DEFAULT,
        dest="mapa_avaliacoes",
        help="Caminho para mapa_avaliacoes.json.",
    )
    parser.add_argument(
        "--mapa-professores",
        default=None,
        dest="mapa_professores",
        help="Caminho para mapa_professores.json (opcional).",
    )
    parser.add_argument(
        "--professor-obrigatorio",
        action="store_true",
        dest="professor_obrigatorio",
        help="Bloqueia lancamentos sem id_professor.",
    )
    parser.add_argument("--db-validacoes", default=_VALIDACOES_DB_DEFAULT, help="Caminho do DB de validacoes.")
    parser.add_argument("--db-aprovacoes", default=_APROVACOES_DB_DEFAULT, help="Caminho do DB de aprovacoes.")
    parser.add_argument("--db-itens", default=_ITENS_DB_DEFAULT, help="Caminho do DB de itens do lote.")
    parser.add_argument("--db-audit", default=_AUDIT_DB_DEFAULT, help="Caminho do DB de auditoria.")
    return parser.parse_args()


def _preparar_planilha_entrada(args: argparse.Namespace) -> str:
    if args.turma_dir and args.planilha:
        raise TemplateInvalidoError("Use --planilha OU --turma-dir, nao ambos.")
    if not args.turma_dir and not args.planilha:
        raise TemplateInvalidoError("Informe --planilha ou --turma-dir.")

    if not args.turma_dir:
        return str(args.planilha)

    from compilador_turma import compilar_diretorio
    import tempfile

    turma_dir = Path(args.turma_dir)
    if not turma_dir.is_dir():
        raise TemplateInvalidoError(f"Diretorio nao encontrado: {args.turma_dir}")

    tmp_dir = tempfile.mkdtemp()
    compilados = compilar_diretorio(str(turma_dir), tmp_dir)
    if not compilados:
        raise TemplateInvalidoError("Nenhuma planilha compilada com sucesso no diretorio.")

    dfs = [pd.read_excel(str(f), dtype=str) for f in compilados]
    merged = pd.concat(dfs, ignore_index=True)
    merged_path = Path(tmp_dir) / "turmas_compiladas.xlsx"
    merged.to_excel(str(merged_path), index=False)
    _ok(f"Turmas compiladas: {len(compilados)} arquivo(s), {len(merged)} linhas")
    return str(merged_path)


def main() -> None:
    args = _parsear_args()
    cliente = None

    try:
        if args.turma_dir:
            _titulo("PRE-ETAPA - Compilando planilhas de turma")

        planilha_entrada = _preparar_planilha_entrada(args)
        validation_store = ValidacaoLoteStore(args.db_validacoes)
        approval_store = AprovacaoLoteStore(args.db_aprovacoes)
        itens_store = LoteItensStore(args.db_itens)
        audit_store = EnvioLoteAuditStore(args.db_audit)

        _titulo("ETAPA 1-5 - Validacao oficial do lote")
        try:
            resultado_validacao = executar_validacao(
                lote_id=args.lote_id,
                entrada=planilha_entrada,
                validation_store=validation_store,
            )
        except (FileNotFoundError, ValueError, TemplateInvalidoError) as exc:
            _titulo("ERRO - Validacao da planilha")
            _erro(str(exc))
            sys.exit(2)

        _ok(
            f"Planilha validada: {Path(planilha_entrada).name} "
            f"({_v(resultado_validacao['resumo'], 'total_linhas')} linhas processadas)"
        )
        _imprimir_resumo(resultado_validacao["resumo"], resultado_validacao["resultados_validacao"])

        _titulo("ETAPA 6 - Preflight Tecnico (APIs e Mapas)")
        caminho_prof = args.mapa_professores or (
            _MAPA_PROF_DEFAULT if Path(_MAPA_PROF_DEFAULT).exists() else None
        )
        try:
            preflight = preparar_dependencias_envio(
                mapa_disciplinas=args.mapa_disciplinas,
                mapa_avaliacoes=args.mapa_avaliacoes,
                mapa_professores=caminho_prof,
                professor_obrigatorio=args.professor_obrigatorio,
                client_factory=IScholarClient,
            )
            cliente = preflight["cliente"]
            _ok(
                "Resolvedor pronto - "
                f"{preflight['disc_count']} disciplina(s), "
                f"{preflight['aval_count']} avaliacao(oes) mapeada(s)."
            )
        except (PreflightTecnicoError, MapaInvalidoError) as exc:
            _titulo("ERRO - Preflight Tecnico")
            _erro(str(exc))
            _info("Verifique credenciais, mapas e configuracao do iScholar.")
            sys.exit(5)

        _titulo("ETAPA 7 - Aprovacao")
        try:
            nome_aprovador = _solicitar_aprovacao(
                apto_para_aprovacao=bool(resultado_validacao["apto_para_aprovacao"]),
                resumo=resultado_validacao["resumo"],
                aprovador_arg=args.aprovador,
            )
        except LoteNaoElegivelError as exc:
            _titulo("LOTE NAO ELEGIVEL")
            _erro(str(exc))
            _info("Corrija os erros na planilha e reprocesse.")
            sys.exit(3)
        except AprovacaoCanceladaError as exc:
            print()
            _titulo("APROVACAO CANCELADA")
            _erro(str(exc))
            sys.exit(4)

        modo_str = "DRY RUN (sem POST real)" if args.dry_run else "ENVIO REAL"
        _titulo(f"ETAPA 8 - {modo_str}")

        try:
            resultado_execucao = executar_aprovacao_e_envio(
                lote_id=args.lote_id,
                aprovado_por=nome_aprovador,
                approval_identity={
                    "aprovador_nome_informado": nome_aprovador,
                    "aprovador_origem": "cli",
                },
                validation_store=validation_store,
                approval_store=approval_store,
                itens_store=itens_store,
                audit_store=audit_store,
                dry_run=args.dry_run,
                expected_snapshot_hash=resultado_validacao["snapshot_hash"],
                cliente=cliente,
                resolvedor=preflight["resolvedor"],
            )
        except (LoteNaoElegivelError, SnapshotStaleError, LoteJaAprovadoError, ValueError, KeyError) as exc:
            _erro(f"Pre-condicao de envio violada: {exc}")
            sys.exit(3)
        except Exception as exc:
            _erro(f"Erro inesperado no envio: {exc}")
            log.exception("Erro ao executar aprovacao e envio")
            sys.exit(1)

        _ok(
            f"Lote '{args.lote_id}' aprovado por '{nome_aprovador}' "
            f"com status final '{resultado_execucao['status']}'."
        )
        _imprimir_resultado_envio(resultado_execucao["envio"], args.dry_run)

        if not resultado_execucao["envio"]["sucesso"]:
            _aviso("Lote finalizado com erros. Verifique os itens acima.")
            sys.exit(1)

        _ok("Lote finalizado sem erros.")
        sys.exit(0)

    except TemplateInvalidoError as exc:
        _erro(str(exc))
        sys.exit(2)
    finally:
        if cliente is not None:
            try:
                cliente.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
