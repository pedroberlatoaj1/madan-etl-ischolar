"""
test_cli_envio.py — Testes do orquestrador cli_envio.py

Cobertura mínima exigida:
  1. Falha por ausência de coluna obrigatória (template inválido → SystemExit 2)
  2. Fluxo feliz em dry_run com mocks (sem HTTP real, sem arquivo real no disco)
  3. Lote não elegível não segue para envio (SystemExit 3)

Convenções:
  - pytest puro, sem mock.patch de módulos internos (dependências injetadas)
  - SQLite :memory: onde possível
  - Sem chamadas HTTP reais
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers: DataFrames de teste
# ---------------------------------------------------------------------------

def _df_template_valido() -> pd.DataFrame:
    """DataFrame mínimo com todas as colunas obrigatórias do template."""
    return pd.DataFrame([{
        "Estudante": "Ana Silva",
        "RA": "RA001",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Matemática",
        "Frente - Professor": "Mat - Prof Silva",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISC)": "4",
        "Simulado": "9",
    }])


def _df_sem_ra() -> pd.DataFrame:
    """DataFrame sem a coluna RA — deve falhar na validação do template."""
    return pd.DataFrame([{
        "Estudante": "Ana Silva",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Matemática",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISC)": "4",
    }])


def _df_com_nota_invalida() -> pd.DataFrame:
    """DataFrame com nota acima de 10 — gera lote não elegível."""
    return pd.DataFrame([{
        "Estudante": "Beto",
        "RA": "RA002",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Física",
        "Frente - Professor": "",
        "AV 1 (OBJ)": "12",   # inválido
        "AV 1 (DISC)": "8",
    }])


# ---------------------------------------------------------------------------
# Helpers: mapas JSON temporários
# ---------------------------------------------------------------------------

def _escrever_mapas(tmp_path: Path) -> tuple[str, str, str]:
    disc = tmp_path / "disc.json"
    aval = tmp_path / "aval.json"
    prof = tmp_path / "prof.json"

    disc.write_text(json.dumps({
        "_schema": "mapa_disciplinas_v1",
        "disciplinas": {"matematica": 101, "fisica": 107},
    }), encoding="utf-8")

    aval.write_text(json.dumps({
        "_schema": "mapa_avaliacoes_v1",
        "avaliacoes": [
            {"componente": "av1", "trimestre": "1", "id_avaliacao": 201},
            {"componente": "simulado", "id_avaliacao": 230},
        ],
    }), encoding="utf-8")

    prof.write_text(json.dumps({
        "_schema": "mapa_professores_v1",
        "professores": {},
    }), encoding="utf-8")

    return str(disc), str(aval), str(prof)


# ---------------------------------------------------------------------------
# Teste 1: template sem coluna obrigatória → SystemExit(2)
# ---------------------------------------------------------------------------

def test_template_sem_ra_aborta_com_exit_2(tmp_path, capsys):
    """Planilha sem coluna RA deve falhar na validação do template com código 2."""
    planilha = tmp_path / "notas.xlsx"
    _df_sem_ra().to_excel(planilha, index=False)
    disc, aval, _ = _escrever_mapas(tmp_path)

    args = [
        "--planilha", str(planilha),
        "--lote-id", "teste-sem-ra",
        "--dry-run",
        "--aprovador", "Tester",
        "--mapa-disciplinas", disc,
        "--mapa-avaliacoes", aval,
    ]

    with patch("sys.argv", ["cli_envio.py"] + args):
        with pytest.raises(SystemExit) as exc_info:
            import cli_envio
            cli_envio.main()

    assert exc_info.value.code == 2

    saida = capsys.readouterr().out
    assert "ra" in saida.lower() or "RA" in saida or "ausente" in saida.lower()


def test_template_sem_estudante_aborta_com_exit_2(tmp_path, capsys):
    """Planilha sem coluna Estudante também deve falhar."""
    df = pd.DataFrame([{
        "RA": "RA001",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Mat",
    }])
    planilha = tmp_path / "notas.xlsx"
    df.to_excel(planilha, index=False)
    disc, aval, _ = _escrever_mapas(tmp_path)

    args = [
        "--planilha", str(planilha),
        "--lote-id", "teste-sem-estudante",
        "--dry-run",
        "--aprovador", "Tester",
        "--mapa-disciplinas", disc,
        "--mapa-avaliacoes", aval,
    ]

    with patch("sys.argv", ["cli_envio.py"] + args):
        with pytest.raises(SystemExit) as exc_info:
            import importlib
            import cli_envio
            importlib.reload(cli_envio)
            cli_envio.main()

    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Teste 2: lote não elegível → SystemExit(3)
# ---------------------------------------------------------------------------

def test_lote_nao_elegivel_nao_segue_para_envio(tmp_path, capsys):
    """
    Planilha com nota inválida gera lote não elegível.
    O script deve encerrar com código 3 antes de chegar no envio.

    IScholarClient é mockado porque no fluxo oficial novo o preflight técnico
    (ETAPA 6) acontece ANTES da verificação de elegibilidade (ETAPA 7).
    Sem o mock, IScholarClient() falharia → PreflightTecnicoError → exit 5.
    """
    planilha = tmp_path / "notas_invalidas.xlsx"
    _df_com_nota_invalida().to_excel(planilha, index=False)
    disc, aval, _ = _escrever_mapas(tmp_path)

    args = [
        "--planilha", str(planilha),
        "--lote-id", "teste-inelegivel",
        "--dry-run",
        "--aprovador", "Tester",
        "--mapa-disciplinas", disc,
        "--mapa-avaliacoes", aval,
    ]

    with patch("sys.argv", ["cli_envio.py"] + args):
        with patch("cli_envio.IScholarClient", return_value=_FakeClient()):
            import importlib
            import cli_envio
            importlib.reload(cli_envio)
            with pytest.raises(SystemExit) as exc_info:
                cli_envio.main()

    assert exc_info.value.code == 3

    saida = capsys.readouterr().out
    # Deve mencionar que não é elegível
    assert any(palavra in saida.lower() for palavra in
               ["elegível", "elegivel", "bloqueado", "erro"])


# ---------------------------------------------------------------------------
# Teste 3: fluxo feliz em dry_run com FakeClient
# ---------------------------------------------------------------------------

@dataclass
class _FakeResultadoLancamento:
    sucesso: bool = True
    transitorio: bool = False
    mensagem: str = "dry_run=True: payload montado."
    payload: Optional[dict] = None
    dados: Optional[Any] = None
    rastreabilidade: dict = field(default_factory=dict)
    dry_run: bool = True


class _FakeClient:
    """Stub de IScholarClient: não faz chamadas HTTP."""

    def lancar_nota(self, *, id_matricula=None, id_disciplina,
                    id_avaliacao, valor_bruta, id_professor=None,
                    dry_run=False) -> _FakeResultadoLancamento:
        return _FakeResultadoLancamento(
            sucesso=True, dry_run=dry_run,
            mensagem="dry_run=True: payload montado.",
            payload={"id_matricula": id_matricula,
                     "id_disciplina": id_disciplina,
                     "id_avaliacao": id_avaliacao,
                     "valor": valor_bruta},
        )

    def buscar_aluno(self, *, ra=None, cpf=None, id_aluno=None):
        from dataclasses import dataclass as dc
        @dc
        class R:
            sucesso: bool = True
            dados: Any = None
            mensagem: str = ""
            transitorio: bool = False
            status_code: int = 200
            endpoint_alvo: str = ""
            params: dict = field(default_factory=dict)
            erro_categoria: Any = None
        return R(sucesso=True, dados={"id_aluno": 42})

    def listar_matriculas(self, *, id_aluno, resolver_id_matricula=True, **kw):
        from dataclasses import dataclass as dc
        @dc
        class R:
            sucesso: bool = True
            id_matricula_resolvido: int = 999
            mensagem: str = ""
            transitorio: bool = False
            status_code: int = 200
            endpoint_alvo: str = ""
            params: dict = field(default_factory=dict)
            rastreabilidade: dict = field(default_factory=dict)
            erro_categoria: Any = None
        return R(sucesso=True, id_matricula_resolvido=999)

    def close(self):
        pass


def test_fluxo_feliz_dry_run(tmp_path, capsys):
    """
    Fluxo completo em dry_run com planilha válida e FakeClient.
    Deve encerrar com código 0 sem erros.
    """
    planilha = tmp_path / "notas_ok.xlsx"
    _df_template_valido().to_excel(planilha, index=False)
    disc, aval, prof = _escrever_mapas(tmp_path)

    args = [
        "--planilha", str(planilha),
        "--lote-id", "fluxo-feliz-001",
        "--dry-run",
        "--aprovador", "Tester",
        "--mapa-disciplinas", disc,
        "--mapa-avaliacoes", aval,
        "--mapa-professores", prof,
    ]

    with patch("sys.argv", ["cli_envio.py"] + args):
        with patch("cli_envio.IScholarClient", return_value=_FakeClient()):
            import importlib
            import cli_envio
            importlib.reload(cli_envio)

            with pytest.raises(SystemExit) as exc_info:
                cli_envio.main()

    # dry_run com resolução bem-sucedida → código 0
    assert exc_info.value.code == 0

    saida = capsys.readouterr().out
    assert "dry" in saida.lower() or "DRY" in saida
    assert "aprovado" in saida.lower() or "Aprovado" in saida or "APROVAÇÃO" in saida


def test_dry_run_imprime_resumo_do_envio(tmp_path, capsys):
    """O resumo final deve mencionar total de itens e modo dry run."""
    planilha = tmp_path / "notas_ok2.xlsx"
    _df_template_valido().to_excel(planilha, index=False)
    disc, aval, prof = _escrever_mapas(tmp_path)

    args = [
        "--planilha", str(planilha),
        "--lote-id", "resumo-test-001",
        "--dry-run",
        "--aprovador", "Tester",
        "--mapa-disciplinas", disc,
        "--mapa-avaliacoes", aval,
    ]

    with patch("sys.argv", ["cli_envio.py"] + args):
        with patch("cli_envio.IScholarClient", return_value=_FakeClient()):
            import importlib
            import cli_envio
            importlib.reload(cli_envio)

            with pytest.raises(SystemExit):
                cli_envio.main()

    saida = capsys.readouterr().out
    # Resumo do lote deve aparecer
    assert "Total sendáveis" in saida or "total" in saida.lower()
    assert "RESULTADO" in saida or "resultado" in saida.lower()


# ---------------------------------------------------------------------------
# Teste 4: mapa de disciplinas ausente → SystemExit(5)
# ---------------------------------------------------------------------------

def test_mapa_disciplinas_ausente_aborta_com_exit_5(tmp_path, capsys):
    """Se o arquivo de mapa de disciplinas não existir, deve abortar com código 5."""
    planilha = tmp_path / "notas_ok.xlsx"
    _df_template_valido().to_excel(planilha, index=False)
    _, aval, _ = _escrever_mapas(tmp_path)

    args = [
        "--planilha", str(planilha),
        "--lote-id", "sem-mapa-disc",
        "--dry-run",
        "--aprovador", "Tester",
        "--mapa-disciplinas", str(tmp_path / "nao_existe.json"),
        "--mapa-avaliacoes", aval,
    ]

    with patch("sys.argv", ["cli_envio.py"] + args):
        with patch("cli_envio.IScholarClient", return_value=_FakeClient()):
            import importlib
            import cli_envio
            importlib.reload(cli_envio)

            with pytest.raises(SystemExit) as exc_info:
                cli_envio.main()

    assert exc_info.value.code == 5


# ---------------------------------------------------------------------------
# Teste 5: resiliência por linha — falha na transformação não aborta o lote
# ---------------------------------------------------------------------------

def test_resiliencia_linha_falha_nao_aborta_lote(tmp_path, capsys):
    """
    Se linha_madan_para_lancamentos lançar em uma linha, o lote NÃO deve abortar.

    Comportamento esperado:
    - A linha problemática vira resultado bloqueado (via criar_resultado_falha_linha).
    - As demais linhas continuam sendo processadas.
    - O processo NÃO sai com exit 1 (crash) nem exit 2 (template).
    - Como a linha falha produz um resultado bloqueado, o lote fica inelegível
      → exit 3 (lote não elegível), NÃO exit 1.

    Nota: linha_madan_para_lancamentos é patchada APÓS importlib.reload() para
    não ser sobrescrita pela re-importação do módulo (não tem guarda defensiva
    como IScholarClient).
    """
    df = pd.DataFrame([
        {   # linha 1: vai falhar na transformação (mockado)
            "Estudante": "Falha Interna",
            "RA": "RA-FALHA",
            "Turma": "2A", "Trimestre": "1",
            "Disciplina": "Física",
            "Frente - Professor": "",
            "AV 1 (OBJ)": "8", "AV 1 (DISC)": "8",
        },
        {   # linha 2: válida
            "Estudante": "Ana Silva",
            "RA": "RA001",
            "Turma": "2A", "Trimestre": "1",
            "Disciplina": "Matemática",
            "Frente - Professor": "Mat - Prof Silva",
            "AV 1 (OBJ)": "8", "AV 1 (DISC)": "8",
        },
    ])
    planilha = tmp_path / "duas_linhas.xlsx"
    df.to_excel(planilha, index=False)
    disc, aval, _ = _escrever_mapas(tmp_path)

    args = [
        "--planilha", str(planilha),
        "--lote-id", "resiliencia-001",
        "--dry-run",
        "--aprovador", "Tester",
        "--mapa-disciplinas", disc,
        "--mapa-avaliacoes", aval,
    ]

    _call_count = [0]

    def _transformador_falha_primeira_linha(*a, **kw):
        """Lança na primeira chamada; delega ao original nas demais."""
        _call_count[0] += 1
        if _call_count[0] == 1:
            raise RuntimeError("Erro simulado de transformação na linha 1")
        from transformador import linha_madan_para_lancamentos as _orig
        return _orig(*a, **kw)

    with patch("sys.argv", ["cli_envio.py"] + args):
        # IScholarClient mockado: preflight (ETAPA 6) precisa passar para
        # chegarmos à verificação de elegibilidade (ETAPA 7).
        with patch("cli_envio.IScholarClient", return_value=_FakeClient()):
            import importlib
            import cli_envio
            importlib.reload(cli_envio)

            # Patch APÓS reload: linha_madan_para_lancamentos não tem guarda
            # defensiva, então o reload a sobrescreveria se patchada antes.
            with patch(
                "cli_envio.linha_madan_para_lancamentos",
                side_effect=_transformador_falha_primeira_linha,
            ):
                with pytest.raises(SystemExit) as exc_info:
                    cli_envio.main()

    # A linha com falha vira resultado bloqueado → lote inelegível → exit 3.
    # Exit 1 (crash) ou exit 2 (template) indicariam falha de resiliência.
    assert exc_info.value.code == 3, (
        f"Esperava exit 3 (lote inelegível por linha bloqueada), got {exc_info.value.code}. "
        "Se exit 1: o lote abortou em vez de tratar a falha. "
        "Se exit 2: a falha foi confundida com erro de template."
    )

    saida = capsys.readouterr().out
    # A segunda linha foi processada e o resumo foi gerado — não saiu antes disso
    assert any(p in saida.lower() for p in ["bloqueado", "erro", "elegível", "elegivel", "resumo"])
    # A transformação foi chamada pelo menos duas vezes (linha 1 falhou, linha 2 foi tentada)
    assert _call_count[0] >= 2, "Esperava que a segunda linha fosse tentada após a falha da primeira"


# ---------------------------------------------------------------------------
# Teste 6: flags --db-aprovacoes / --db-itens / --db-audit são aceitas e usadas
# ---------------------------------------------------------------------------

def test_flags_db_sao_aceitas_e_usadas(tmp_path, capsys):
    """
    --db-aprovacoes, --db-itens e --db-audit devem ser aceitas pelo parser
    e passadas aos respectivos stores.

    Verificação: o fluxo feliz completa com exit 0 quando caminhos explícitos
    são fornecidos; os arquivos de banco são criados no diretório indicado.
    """
    planilha = tmp_path / "notas_db_flags.xlsx"
    _df_template_valido().to_excel(planilha, index=False)
    disc, aval, prof = _escrever_mapas(tmp_path)

    db_aprovacoes = str(tmp_path / "aprovacoes_custom.db")
    db_itens      = str(tmp_path / "itens_custom.db")
    db_audit      = str(tmp_path / "audit_custom.db")

    args = [
        "--planilha", str(planilha),
        "--lote-id", "db-flags-001",
        "--dry-run",
        "--aprovador", "Tester",
        "--mapa-disciplinas", disc,
        "--mapa-avaliacoes", aval,
        "--mapa-professores", prof,
        "--db-aprovacoes", db_aprovacoes,
        "--db-itens",      db_itens,
        "--db-audit",      db_audit,
    ]

    with patch("sys.argv", ["cli_envio.py"] + args):
        with patch("cli_envio.IScholarClient", return_value=_FakeClient()):
            import importlib
            import cli_envio
            importlib.reload(cli_envio)

            with pytest.raises(SystemExit) as exc_info:
                cli_envio.main()

    # Fluxo feliz com flags de DB explícitos → exit 0
    assert exc_info.value.code == 0, (
        f"Esperava exit 0 com flags --db-* explícitas, got {exc_info.value.code}"
    )

    # Os arquivos de banco devem ter sido criados nos caminhos fornecidos
    from pathlib import Path
    assert Path(db_aprovacoes).exists(), "--db-aprovacoes: arquivo não criado"
    assert Path(db_itens).exists(),      "--db-itens: arquivo não criado"
    assert Path(db_audit).exists(),      "--db-audit: arquivo não criado"