"""
cli_envio.py — Orquestrador do fluxo oficial novo: planilha → aprovação → envio.

Uso:
  # Dry run (monta payloads sem POST real; ainda pode exigir credenciais e
  # resolução de IDs via API):
  python cli_envio.py --planilha notas.xlsx --lote-id t1-2A-2026 --dry-run

  # Envio real com aprovação automática:
  python cli_envio.py --planilha notas.xlsx --lote-id t1-2A-2026 --aprovador "Pedro"

  # Envio real com confirmação interativa no terminal:
  python cli_envio.py --planilha notas.xlsx --lote-id t1-2A-2026

  # Batch de turmas (compila planilhas multi-abas automaticamente):
  python cli_envio.py --turma-dir planilhas/ --lote-id t1-2026 --dry-run

  # Mapas em caminhos não padrão; DBs em paths explícitos:
  python cli_envio.py --planilha notas.xlsx --lote-id t1-2A-2026 --dry-run \
      --mapa-disciplinas mapas/disciplinas.json \
      --mapa-avaliacoes  mapas/avaliacoes.json  \
      --mapa-professores mapas/professores.json \
      --db-aprovacoes    aprovacoes.db          \
      --db-itens         itens.db               \
      --db-audit         audit.db

Caminhos padrão dos mapas (sobrescrevíveis via argumento):
  mapa_disciplinas.json
  mapa_avaliacoes.json
  mapa_professores.json  (opcional — se não existir, professor é tratado como ausente)

Fluxo interno (fluxo oficial novo):
  1. Carregar planilha
  2. Validar template fixo (colunas obrigatórias)
  3. Gerar lançamentos canônicos + validação pré-envio por linha
  4. Gerar resumo do lote
  5. Preflight técnico — inicializar IScholarClient, carregar mapas, instanciar
     ResolvedorIDsHibrido (falha aqui não cria estado em banco)
  6. Criar stores + estado do lote (persistência inicial)
  7. Aprovação explícita (automática via --aprovador ou interativa)
  8. Enviar (dry_run ou real) + auditoria por item
  9. Imprimir resumo final

Exit codes:
  0 — sucesso
  1 — erro operacional inesperado
  2 — problema de entrada / planilha / template
  3 — lote não elegível / pré-condição de envio violada
  4 — cancelamento do operador
  5 — configuração / mapas / credenciais / preflight técnico
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pandas as pd

from aprovacao_lote import (
    aprovar_lote,
    criar_estado_lote,
    extrair_itens_sendaveis,
    gerar_resumo_lote,
)
from aprovacao_lote_store import AprovacaoLoteStore
from envio_lote import enviar_lote
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
from wide_format_adapter import (
    detectar_formato,
    despivotar_dataframe,
    validar_colunas_wide_novo,
    FORMATO_WIDE_NOVO,
)
from validacao_pre_envio import (
    validar_pre_envio_linha,
    criar_resultado_falha_linha,
    STATUS_APROVADO,
    STATUS_BLOQUEADO_ERROS,
)

# Importação defensiva: preserva os mocks de teste durante importlib.reload()
if "IScholarClient" not in globals():
    from ischolar_client import IScholarClient


class TemplateInvalidoError(ValueError):
    """Planilha com colunas obrigatórias ausentes ou formato incompatível."""


class PreflightTecnicoError(RuntimeError):
    """Falha ao inicializar o IScholarClient (credenciais, rede, configuração)."""


class MapaInvalidoError(ValueError):
    """Arquivo de mapa ausente, ilegível ou com schema inválido."""


class LoteNaoElegivelError(ValueError):
    """Lote bloqueado por erros — não pode ser aprovado."""


class AprovacaoCanceladaError(InterruptedError):
    """Operador recusou ou cancelou a aprovação do lote."""


log = configurar_logger("etl.cli_envio")

# ---------------------------------------------------------------------------
# Caminhos padrão
# ---------------------------------------------------------------------------

_MAPA_DISC_DEFAULT     = "mapa_disciplinas.json"
_MAPA_AVAL_DEFAULT     = "mapa_avaliacoes.json"
_MAPA_PROF_DEFAULT     = "mapa_professores.json"
_APROVACOES_DB_DEFAULT = os.getenv("APROVACAO_LOTE_DB", "aprovacoes_lote.db")
_ITENS_DB_DEFAULT      = os.getenv("LOTE_ITENS_DB",     "lote_itens.db")
_AUDIT_DB_DEFAULT      = os.getenv("ENVIO_LOTE_AUDIT_DB","envio_lote_audit.db")


# ---------------------------------------------------------------------------
# Helpers de saída no terminal
# ---------------------------------------------------------------------------

def _sep(char: str = "─", n: int = 60) -> None:
    print(char * n)


def _titulo(texto: str) -> None:
    _sep()
    print(f"  {texto}")
    _sep()


def _ok(msg: str) -> None:
    print(f"  ✅  {msg}")


def _aviso(msg: str) -> None:
    print(f"  ⚠️   {msg}")


def _erro(msg: str) -> None:
    print(f"  ❌  {msg}")


def _info(msg: str) -> None:
    print(f"      {msg}")


# ---------------------------------------------------------------------------
# 1. Carregamento da planilha
# ---------------------------------------------------------------------------

def _carregar_planilha(caminho: str) -> pd.DataFrame:
    p = Path(caminho)
    if not p.exists():
        raise FileNotFoundError(f"Planilha não encontrada: {caminho}")

    ext = p.suffix.lower()
    if ext in (".xlsx", ".xls"):
        # Tenta header=0 primeiro; se as colunas obrigatórias não forem
        # encontradas, tenta header=1 (planilha Madan tem linha de
        # cabeçalho agrupado antes dos nomes reais das colunas).
        df = pd.read_excel(caminho, dtype=str, header=0)
        _colunas_obrig = {"estudante", "ra", "turma", "trimestre", "disciplina"}
        colunas_norm = {c.strip().lower() for c in df.columns if isinstance(c, str)}
        if not _colunas_obrig.intersection(colunas_norm):
            log.info("Header na linha 1 não contém colunas esperadas; tentando header=1")
            df = pd.read_excel(caminho, dtype=str, header=1)
    elif ext == ".csv":
        # Tenta separador padrão; fallback para ponto-e-vírgula
        df = pd.read_csv(caminho, dtype=str, sep=None, engine="python")
    else:
        raise ValueError(f"Extensão não suportada: {ext}. Use .xlsx, .xls ou .csv.")

    # Remove linhas completamente vazias (linhas de separação visual no Excel)
    df = df.dropna(how="all").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 2. Validação do template fixo
# ---------------------------------------------------------------------------

def _validar_template(df: pd.DataFrame) -> None:
    """
    Verifica colunas obrigatórias. Levanta TemplateInvalidoError se alguma faltar.
    """
    ausentes = validar_colunas_obrigatorias_template(list(df.columns))
    if ausentes:
        raise TemplateInvalidoError(f"Colunas obrigatórias ausentes na planilha: {ausentes}")


# ---------------------------------------------------------------------------
# 3 + 4. Lançamentos canônicos + validação pré-envio
# ---------------------------------------------------------------------------

def _processar_linhas(
    df: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Itera o DataFrame linha a linha.
    Retorna (todos_lancamentos, resultados_etapa3).
    """
    todos_lancamentos: list[dict[str, Any]] = []
    resultados_etapa3: list[dict[str, Any]] = []

    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        linha_num = int(idx) + 2  # +1 header, +1 base-0

        try:
            lancs = linha_madan_para_lancamentos(row_dict, linha_origem=linha_num)
            todos_lancamentos.extend(lancs)

            resultado = validar_pre_envio_linha(
                row_wide=row_dict,
                lancamentos=lancs,
            )
            resultados_etapa3.append(resultado)
        except Exception as exc:
            log.exception(f"Erro interno inesperado a processar linha {linha_num}")
            
            # Preserva a auditabilidade no relatório do lote
            estudante = row_dict.get("Estudante") or row_dict.get("estudante") or "Desconhecido"
            disciplina = row_dict.get("Disciplina") or row_dict.get("disciplina") or "Desconhecido"
            
            resultado_falha = criar_resultado_falha_linha(
                linha_origem=linha_num,
                estudante=estudante,
                componente=disciplina,
                mensagem_erro=f"Falha na transformação ou validação: {type(exc).__name__} - {str(exc)}"
            )
            resultados_etapa3.append(resultado_falha)

    return todos_lancamentos, resultados_etapa3


# ---------------------------------------------------------------------------
# 5. Resumo legível do lote para o operador
# ---------------------------------------------------------------------------

def _imprimir_resumo(resumo: Any, resultados: list[dict[str, Any]]) -> None:
    _titulo("RESUMO DO LOTE")
    print(f"  Linhas lidas          : {resumo.total_linhas}")
    print(f"  Alunos únicos         : {resumo.total_alunos}")
    print(f"  Disciplinas únicas    : {resumo.total_disciplinas}")
    print(f"  Total de lançamentos  : {resumo.total_lancamentos}")
    print(f"  Itens sendáveis       : {resumo.total_sendaveis}")
    print(f"  Itens bloqueados      : {resumo.total_bloqueados}")
    print(f"  Avisos                : {resumo.total_avisos}")
    print(f"  Pendências            : {resumo.total_pendencias}")
    print(f"  Erros                 : {resumo.total_erros}")
    print(f"  Status sugerido       : {resumo.status_sugerido}")
    _sep("─", 60)

    # Detalha linhas bloqueadas (até 10)
    bloqueadas = [r for r in resultados if r.get("status_geral") == STATUS_BLOQUEADO_ERROS]
    if bloqueadas:
        _aviso(f"{len(bloqueadas)} linha(s) bloqueada(s) por erros:")
        for res in bloqueadas[:10]:
            for lanc in res.get("lancamentos_com_erro", [])[:3]:
                estudante = lanc.get("estudante", "?")
                componente = lanc.get("componente", "?")
                for err in lanc.get("validacao_erros", [])[:2]:
                    _info(f"  [{err.get('code')}] {estudante} / {componente}: {err.get('message','')}")
        if len(bloqueadas) > 10:
            _info(f"  ... e mais {len(bloqueadas) - 10} linha(s) bloqueada(s).")

    # Detalha avisos (até 5)
    total_avisos_detalhados = 0
    for res in resultados:
        for av in res.get("avisos", []):
            if total_avisos_detalhados >= 5:
                break
            _aviso(f"Aviso [{av.get('code')}]: {av.get('message','')}")
            total_avisos_detalhados += 1


# ---------------------------------------------------------------------------
# 6. Aprovação
# ---------------------------------------------------------------------------

def _solicitar_aprovacao(
    estado: Any,
    resumo: Any,
    aprovador_arg: Optional[str],
) -> str:
    """
    Retorna o nome do aprovador confirmado, ou levanta exceções se
    o operador recusar ou o lote não for elegível.
    """
    if not estado.elegivel_para_aprovacao:
        raise LoteNaoElegivelError("O lote contém erros e não pode ser aprovado.")

    # Aprovação automática via --aprovador
    if aprovador_arg:
        _ok(f"Aprovação automática pelo aprovador: {aprovador_arg!r}")
        return aprovador_arg.strip()

    # Aprovação interativa
    _titulo("APROVAÇÃO MANUAL NECESSÁRIA")
    print(f"  Itens sendáveis prontos para envio: {resumo.total_sendaveis}")
    print(f"  Avisos presentes                  : {resumo.total_avisos}")
    print()
    print("  Reveja o resumo acima antes de confirmar.")
    print()

    try:
        nome = input("  Nome do aprovador (ou Enter para cancelar): ").strip()
    except (EOFError, KeyboardInterrupt):
        raise AprovacaoCanceladaError("Aprovação cancelada pelo operador.")

    if not nome:
        raise AprovacaoCanceladaError("Aprovação cancelada — nome do aprovador não informado.")

    try:
        confirma = input(f"  Confirma aprovação por '{nome}'? [s/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        raise AprovacaoCanceladaError("Aprovação cancelada pelo operador.")

    if confirma not in ("s", "sim", "y", "yes"):
        raise AprovacaoCanceladaError("Aprovação cancelada pelo operador.")

    return nome


# ---------------------------------------------------------------------------
# 7. Carregamento dos mapas + resolvedor
# ---------------------------------------------------------------------------

def _carregar_resolvedor(
    cliente: IScholarClient,
    caminho_disc: str,
    caminho_aval: str,
    caminho_prof: Optional[str],
    professor_obrigatorio: bool,
) -> tuple[ResolvedorIDsHibrido, int, int]:
    """
    Carrega os mapas JSON e instancia o ResolvedorIDsHibrido.
    Levanta MapaInvalidoError se mapas ausentes ou inválidos.
    Retorna a instância e as contagens de disciplinas e avaliações.
    """
    # --- Disciplinas ---
    if not Path(caminho_disc).exists():
        raise MapaInvalidoError(f"Mapa de disciplinas não encontrado: {caminho_disc}")

    try:
        mapa_disc = carregar_mapa_disciplinas(caminho_disc)
    except Exception as exc:
        raise MapaInvalidoError(f"Mapa de disciplinas inválido: {exc}") from exc

    problemas_disc = validar_mapa_disciplinas(mapa_disc)
    if problemas_disc:
        _titulo("AVISO — Mapa de disciplinas com problemas")
        for p in problemas_disc:
            _aviso(p)
        # Não aborta — disciplinas ausentes vão gerar erro de resolução por item

    # --- Avaliações ---
    if not Path(caminho_aval).exists():
        raise MapaInvalidoError(f"Mapa de avaliações não encontrado: {caminho_aval}")

    try:
        mapa_aval = carregar_mapa_avaliacoes(caminho_aval)
    except Exception as exc:
        raise MapaInvalidoError(f"Mapa de avaliações inválido: {exc}") from exc

    problemas_aval = validar_mapa_avaliacoes(mapa_aval)
    if problemas_aval:
        for p in problemas_aval:
            _aviso(p)

    # --- Professores (opcional) ---
    mapa_prof: Optional[dict[str, int]] = None
    if caminho_prof and Path(caminho_prof).exists():
        try:
            mapa_prof = carregar_mapa_professores(caminho_prof)
            _ok(f"Mapa de professores carregado: {len(mapa_prof)} entrada(s)")
        except Exception as exc:
            _aviso(f"Mapa de professores inválido (ignorado): {exc}")
            mapa_prof = None
    else:
        _info("Mapa de professores não encontrado — id_professor=None (opcional).")

    resolvedor = ResolvedorIDsHibrido(
        cliente=cliente,
        mapa_disciplinas=mapa_disc,
        mapa_avaliacoes=mapa_aval,
        mapa_professores=mapa_prof,
        professor_obrigatorio=professor_obrigatorio,
    )
    return resolvedor, len(mapa_disc), len(mapa_aval)


# ---------------------------------------------------------------------------
# 9. Resumo final do envio
# ---------------------------------------------------------------------------

def _imprimir_resultado_envio(resultado: Any, dry_run: bool) -> None:
    _titulo("RESULTADO DO ENVIO")

    modo = "DRY RUN" if dry_run else "ENVIO REAL"
    print(f"  Modo                  : {modo}")
    print(f"  Total sendáveis       : {resultado.total_sendaveis}")

    if dry_run:
        print(f"  Processados (dry run) : {resultado.total_dry_run}")
    else:
        print(f"  Enviados com sucesso  : {resultado.total_enviados}")

    print(f"  Erros de resolução    : {resultado.total_erros_resolucao}")
    print(f"  Erros de envio        : {resultado.total_erros_envio}")
    print(f"  Status geral          : {'✅ OK' if resultado.sucesso else '❌ COM ERROS'}")
    _sep("─", 60)

    # Detalha erros de resolução (até 10)
    erros_res = [it for it in resultado.itens if it.status == "erro_resolucao"]
    if erros_res:
        _aviso(f"{len(erros_res)} item(ns) com erro de resolução de IDs:")
        for item in erros_res[:10]:
            cats = item.rastreabilidade.get("categorias_erro", [])
            cat_str = ", ".join(cats) if cats else "desconhecido"
            _info(f"  [{cat_str}] {item.estudante or '?'} / {item.componente or '?'}")
            for err in item.erros_resolucao[:2]:
                _info(f"    → {err}")
        if len(erros_res) > 10:
            _info(f"  ... e mais {len(erros_res) - 10} item(ns).")

    # Detalha erros de envio (até 10)
    erros_env = [it for it in resultado.itens if it.status == "erro_envio"]
    if erros_env:
        _aviso(f"{len(erros_env)} item(ns) com erro de envio:")
        for item in erros_env[:10]:
            trans = " [transitório — candidato a retry]" if item.transitorio else ""
            _info(f"  {item.estudante or '?'} / {item.componente or '?'}: {item.mensagem}{trans}")
        if len(erros_env) > 10:
            _info(f"  ... e mais {len(erros_env) - 10} item(ns).")

    if dry_run and resultado.total_dry_run > 0:
        _info("")
        _info("Payloads prontos. Remova --dry-run para executar o envio real.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fluxo B — Envio de notas Madan → iScholar",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--planilha",
        default=None,
        help="Caminho para o arquivo Excel ou CSV de notas (template fixo).",
    )
    parser.add_argument(
        "--turma-dir",
        default=None,
        dest="turma_dir",
        help="Diretório com planilhas multi-abas (geradas por gerador_planilhas.py). "
             "Compila automaticamente e usa como planilha de entrada. "
             "Mutuamente exclusivo com --planilha.",
    )
    parser.add_argument(
        "--lote-id",
        required=True,
        dest="lote_id",
        help="Identificador único do lote (ex.: t1-2A-2026). Usado para rastreabilidade.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Monta e valida payloads sem POST real. Ainda exige credenciais e resolução de IDs na API.",
    )
    parser.add_argument(
        "--aprovador",
        default=None,
        help="Nome do aprovador. Se omitido, a aprovação será solicitada interativamente.",
    )
    parser.add_argument(
        "--mapa-disciplinas",
        default=_MAPA_DISC_DEFAULT,
        dest="mapa_disciplinas",
        help=f"Caminho para mapa_disciplinas.json (padrão: {_MAPA_DISC_DEFAULT}).",
    )
    parser.add_argument(
        "--mapa-avaliacoes",
        default=_MAPA_AVAL_DEFAULT,
        dest="mapa_avaliacoes",
        help=f"Caminho para mapa_avaliacoes.json (padrão: {_MAPA_AVAL_DEFAULT}).",
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
        help="Se definido, lançamentos sem id_professor são bloqueados.",
    )
    parser.add_argument(
        "--db-aprovacoes",
        default=_APROVACOES_DB_DEFAULT,
        help="Caminho para o DB de aprovações.",
    )
    parser.add_argument(
        "--db-itens",
        default=_ITENS_DB_DEFAULT,
        help="Caminho para o DB de itens do lote.",
    )
    parser.add_argument(
        "--db-audit",
        default=_AUDIT_DB_DEFAULT,
        help="Caminho para o DB de auditoria.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parsear_args()
    cliente = None

    # Validação: --planilha ou --turma-dir (um dos dois, não ambos)
    if args.turma_dir and args.planilha:
        _erro("Use --planilha OU --turma-dir, não ambos.")
        sys.exit(2)
    if not args.turma_dir and not args.planilha:
        _erro("Informe --planilha ou --turma-dir.")
        sys.exit(2)

    # Se --turma-dir: compila planilhas multi-abas num XLSX temporário
    if args.turma_dir:
        _titulo("PRÉ-ETAPA — Compilando planilhas de turma")
        try:
            from compilador_turma import compilar_diretorio
            import tempfile

            turma_dir = Path(args.turma_dir)
            if not turma_dir.is_dir():
                _erro(f"Diretório não encontrado: {args.turma_dir}")
                sys.exit(2)

            tmp_dir = tempfile.mkdtemp()
            compilados = compilar_diretorio(str(turma_dir), tmp_dir)
            if not compilados:
                _erro("Nenhuma planilha compilada com sucesso no diretório.")
                sys.exit(2)

            dfs = [pd.read_excel(str(f), dtype=str) for f in compilados]
            merged = pd.concat(dfs, ignore_index=True)
            merged_path = Path(tmp_dir) / "turmas_compiladas.xlsx"
            merged.to_excel(str(merged_path), index=False)
            args.planilha = str(merged_path)
            _ok(f"Turmas compiladas: {len(compilados)} arquivo(s), {len(merged)} linhas")
        except ImportError:
            _erro("compilador_turma.py não encontrado. Instale o módulo para usar --turma-dir.")
            sys.exit(5)
        except Exception as exc:
            _erro(f"Erro ao compilar turmas: {exc}")
            log.exception("Erro em compilar_diretorio")
            sys.exit(2)

    try:
        # ------------------------------------------------------------------
        # ETAPA 1: Carregamento da planilha
        # ------------------------------------------------------------------
        _titulo("ETAPA 1 — Carregando planilha")
        try:
            df = _carregar_planilha(args.planilha)
        except (FileNotFoundError, ValueError) as exc:
            _erro(str(exc))
            sys.exit(2)

        _ok(f"Planilha carregada: {Path(args.planilha).name} ({len(df)} linhas)")

        # ------------------------------------------------------------------
        # ETAPA 2: Validação do template + auto-detecção de formato
        # ------------------------------------------------------------------
        _titulo("ETAPA 2 — Validando template")

        formato = detectar_formato(list(df.columns))

        if formato == FORMATO_WIDE_NOVO:
            _info("Formato wide novo detectado (1 linha por aluno, colunas dinâmicas)")
            problemas = validar_colunas_wide_novo(list(df.columns))
            if problemas:
                _titulo("ERRO — Template wide novo inválido")
                for p in problemas:
                    _erro(p)
                sys.exit(2)
            _ok("Template wide novo válido.")

            _info("Despivotando para formato pipeline (1 linha por aluno × disciplina × frente)...")
            linhas_antes = len(df)
            df = despivotar_dataframe(df)
            _ok(f"Despivotamento concluído: {linhas_antes} linhas → {len(df)} linhas virtuais")
        else:
            try:
                _validar_template(df)
                _ok("Template válido — todas as colunas obrigatórias presentes.")
            except TemplateInvalidoError as exc:
                _titulo("ERRO — Template inválido")
                _erro(str(exc))
                _info("Colunas obrigatórias do template fixo:")
                for c in COLUNAS_OBRIGATORIAS_TEMPLATE:
                    _info(f"  • {c}")
                _info("\nCorrija a planilha e tente novamente.")
                sys.exit(2)

        ra_col = next((c for c in df.columns if c.strip().upper() == "RA"), None)
        if ra_col is not None:
            ra_vazios = df[ra_col].isna().sum() + (df[ra_col].astype(str).str.strip() == "").sum()
            if ra_vazios > 0:
                _aviso(
                    f"{ra_vazios} linha(s) com RA vazio. "
                    "Esses alunos terão erro de resolução de matrícula no envio."
                )

        # ------------------------------------------------------------------
        # ETAPA 3 + 4: Lançamentos canônicos + validação pré-envio
        # ------------------------------------------------------------------
        _titulo("ETAPA 3/4 — Gerando lançamentos e validando")
        try:
            _, resultados_etapa3 = _processar_linhas(df)
        except Exception as exc:
            _erro(f"Erro inesperado ao processar linhas: {exc}")
            log.exception("Erro em _processar_linhas")
            sys.exit(2)

        # ------------------------------------------------------------------
        # ETAPA 5: Resumo do lote
        # ------------------------------------------------------------------
        resumo = gerar_resumo_lote(resultados_etapa3)
        _imprimir_resumo(resumo, resultados_etapa3)

        # ------------------------------------------------------------------
        # ETAPA 6: Preflight Técnico (Cliente e Resolvedor)
        # ------------------------------------------------------------------
        _titulo("ETAPA 6 — Preflight Técnico (APIs e Mapas)")
        try:
            cliente = IScholarClient()
        except Exception as exc:
            raise PreflightTecnicoError(
                f"Falha ao inicializar IScholarClient: {exc}"
            ) from exc

        caminho_prof = args.mapa_professores or (
            _MAPA_PROF_DEFAULT if Path(_MAPA_PROF_DEFAULT).exists() else None
        )

        try:
            resolvedor, disc_count, aval_count = _carregar_resolvedor(
                cliente=cliente,
                caminho_disc=args.mapa_disciplinas,
                caminho_aval=args.mapa_avaliacoes,
                caminho_prof=caminho_prof,
                professor_obrigatorio=args.professor_obrigatorio,
            )
            _ok(f"Resolvedor pronto — {disc_count} disciplina(s), {aval_count} avaliação(ões) mapeada(s).")
        except MapaInvalidoError as exc:
            _titulo("ERRO — Falha no Preflight de Mapas")
            _erro(str(exc))
            sys.exit(5)

        # ------------------------------------------------------------------
        # ETAPA 6b: Persistência do Estado do Lote
        # ------------------------------------------------------------------
        aprov_store = AprovacaoLoteStore(args.db_aprovacoes)
        itens_store = LoteItensStore(args.db_itens)
        audit_store = EnvioLoteAuditStore(args.db_audit)

        estado = criar_estado_lote(
            lote_id=args.lote_id,
            resumo=resumo,
            store=aprov_store,
        )

        # ------------------------------------------------------------------
        # ETAPA 7: Aprovação explícita
        # ------------------------------------------------------------------
        _titulo("ETAPA 7 — Aprovação")
        try:
            nome_aprovador = _solicitar_aprovacao(estado, resumo, args.aprovador)
        except LoteNaoElegivelError as exc:
            _titulo("LOTE NÃO ELEGÍVEL")
            _erro(str(exc))
            _info("Corrija os erros na planilha e reprocesse.")
            sys.exit(3)
        except AprovacaoCanceladaError as exc:
            print()
            _titulo("APROVAÇÃO CANCELADA")
            _erro(str(exc))
            sys.exit(4)

        itens_sendaveis = extrair_itens_sendaveis(resultados_etapa3)

        try:
            aprovar_lote(
                estado,
                aprovado_por=nome_aprovador,
                store=aprov_store,
                itens_sendaveis=itens_sendaveis,
                itens_store=itens_store,
            )
        except ValueError as exc:
            _erro(f"Falha na aprovação: {exc}")
            sys.exit(3)

        _ok(
            f"Lote '{args.lote_id}' aprovado por '{nome_aprovador}' — "
            f"{len(itens_sendaveis)} item(ns) sendável(is) persistido(s)."
        )

        # ------------------------------------------------------------------
        # ETAPA 8: Envio
        # ------------------------------------------------------------------
        modo_str = "DRY RUN (sem POST real)" if args.dry_run else "ENVIO REAL"
        _titulo(f"ETAPA 8 — {modo_str}")

        try:
            resultado = enviar_lote(
                estado=estado,
                itens_store=itens_store,
                cliente=cliente,
                resolvedor=resolvedor,
                dry_run=args.dry_run,
                audit_store=audit_store,
            )
        except ValueError as exc:
            _erro(f"Pré-condição de envio violada: {exc}")
            sys.exit(3)
        except Exception as exc:
            _erro(f"Erro inesperado no envio: {exc}")
            log.exception("Erro em enviar_lote")
            sys.exit(1)

        # ------------------------------------------------------------------
        # ETAPA 9: Resultado final
        # ------------------------------------------------------------------
        _imprimir_resultado_envio(resultado, args.dry_run)

        if not resultado.sucesso:
            _aviso("Lote finalizado com erros. Verifique os itens acima.")
            sys.exit(1)

        _ok("Lote finalizado sem erros.")
        sys.exit(0)

    except PreflightTecnicoError as exc:
        _titulo("ERRO — Preflight Técnico")
        _erro(str(exc))
        _info("Verifique ISCHOLAR_API_TOKEN e ISCHOLAR_CODIGO_ESCOLA no .env.")
        sys.exit(5)

    finally:
        if cliente:
            try:
                cliente.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()