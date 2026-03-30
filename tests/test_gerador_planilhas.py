"""
Testes para gerador_planilhas.py — geração de planilhas multi-abas por turma.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import openpyxl
import pytest

from gerador_planilhas import (
    Aluno,
    TabConfig,
    _sanitizar_nome_aba,
    agrupar_alunos_por_turma,
    carregar_roster_csv,
    descobrir_tabs_para_turma,
    gerar_planilha_turma,
    gerar_todas_planilhas,
    COLUNAS_IDENTIDADE,
    COLUNAS_NOTA,
    COLUNAS_CONFERENCIA,
    TODAS_COLUNAS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def alunos_1a() -> list[Aluno]:
    return [
        Aluno(nome="Alice Silva", ra="1001", turma="1A"),
        Aluno(nome="Bruno Costa", ra="1002", turma="1A"),
        Aluno(nome="Carla Dias", ra="1003", turma="1A"),
    ]


@pytest.fixture
def alunos_mistos() -> list[Aluno]:
    return [
        Aluno(nome="Alice Silva", ra="1001", turma="1A"),
        Aluno(nome="Bruno Costa", ra="1002", turma="1A"),
        Aluno(nome="Daniel Lima", ra="2001", turma="2B"),
        Aluno(nome="Eva Martins", ra="2002", turma="2B"),
        Aluno(nome="Fernanda Gomes", ra="3001", turma="3A"),  # 3ª série — deve ser ignorada
    ]


@pytest.fixture
def roster_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "roster.csv"
    csv_path.write_text(
        "Nome,RA,Turma\n"
        "Alice Silva,1001,1A\n"
        "Bruno Costa,1002,1A\n"
        "Daniel Lima,2001,2B\n",
        encoding="utf-8",
    )
    return csv_path


# ---------------------------------------------------------------------------
# TestSanitizarNomeAba
# ---------------------------------------------------------------------------

class TestSanitizarNomeAba:
    def test_remove_acentos(self):
        assert _sanitizar_nome_aba("história_F1_José") == "historia_F1_Jose"

    def test_remove_caracteres_proibidos(self):
        assert _sanitizar_nome_aba("mat/F1:prof") == "mat_F1_prof"

    def test_preserva_underscore(self):
        assert _sanitizar_nome_aba("bio_F2_Silva") == "bio_F2_Silva"


# ---------------------------------------------------------------------------
# TestTabConfig
# ---------------------------------------------------------------------------

class TestTabConfig:
    def test_nome_aba_com_frente(self):
        tab = TabConfig("matematica", "F2", "Luan", "Luan Schunck")
        assert tab.nome_aba == "matematica_F2_Luan"

    def test_nome_aba_sem_frente(self):
        tab = TabConfig("arte", "", "Lenice", "Lenice Silva")
        assert tab.nome_aba == "arte_Lenice"

    def test_nome_aba_truncado_31_chars(self):
        tab = TabConfig("interpretacao de texto", "F1", "ProfessorNomeMuitoLongo", "Full Name")
        assert len(tab.nome_aba) <= 31

    def test_nome_aba_sem_acentos(self):
        tab = TabConfig("história", "F1", "José", "José da Silva")
        assert "ó" not in tab.nome_aba
        assert "é" not in tab.nome_aba


# ---------------------------------------------------------------------------
# TestDescobrirTabs
# ---------------------------------------------------------------------------

class TestDescobrirTabs:
    def test_turma_1a_tem_tabs(self):
        tabs = descobrir_tabs_para_turma(1, "A")
        assert len(tabs) > 0

    def test_turma_1a_tem_matematica(self):
        tabs = descobrir_tabs_para_turma(1, "A")
        disciplinas = {t.disciplina for t in tabs}
        assert "matematica" in disciplinas

    def test_tabs_deduplicadas(self):
        tabs = descobrir_tabs_para_turma(1, "A")
        nomes = [t.nome_aba for t in tabs]
        assert len(nomes) == len(set(nomes)), "Abas duplicadas encontradas"

    def test_turma_2b_tem_tabs(self):
        tabs = descobrir_tabs_para_turma(2, "B")
        assert len(tabs) > 0

    def test_tabs_ordenadas(self):
        tabs = descobrir_tabs_para_turma(1, "A")
        disciplinas = [t.disciplina for t in tabs]
        assert disciplinas == sorted(disciplinas)


# ---------------------------------------------------------------------------
# TestCarregarRoster
# ---------------------------------------------------------------------------

class TestCarregarRoster:
    def test_carrega_csv_basico(self, roster_csv: Path):
        alunos = carregar_roster_csv(roster_csv)
        assert len(alunos) == 3
        assert alunos[0].nome == "Alice Silva"
        assert alunos[0].ra == "1001"
        assert alunos[0].turma == "1A"

    def test_csv_com_headers_alternativos(self, tmp_path: Path):
        csv_path = tmp_path / "alt.csv"
        csv_path.write_text(
            "Estudante,Registro_Aluno,Sala\n"
            "Maria,5001,2A\n",
            encoding="utf-8",
        )
        alunos = carregar_roster_csv(csv_path)
        assert len(alunos) == 1
        assert alunos[0].nome == "Maria"
        assert alunos[0].ra == "5001"

    def test_csv_sem_coluna_obrigatoria_levanta_erro(self, tmp_path: Path):
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text("Nome,Turma\nAlice,1A\n", encoding="utf-8")
        with pytest.raises(ValueError, match="ra"):
            carregar_roster_csv(csv_path)

    def test_csv_pula_linhas_sem_nome_ou_ra(self, tmp_path: Path):
        csv_path = tmp_path / "sparse.csv"
        csv_path.write_text(
            "Nome,RA,Turma\nAlice,1001,1A\n,,1A\nBruno,,1A\n",
            encoding="utf-8",
        )
        alunos = carregar_roster_csv(csv_path)
        assert len(alunos) == 1


# ---------------------------------------------------------------------------
# TestAgruparPorTurma
# ---------------------------------------------------------------------------

class TestAgruparPorTurma:
    def test_agrupa_corretamente(self, alunos_mistos: list[Aluno]):
        grupos = agrupar_alunos_por_turma(alunos_mistos)
        assert "1A" in grupos
        assert "2B" in grupos
        assert "3A" in grupos
        assert len(grupos["1A"]) == 2
        assert len(grupos["2B"]) == 2

    def test_alunos_ordenados_por_nome(self, alunos_1a: list[Aluno]):
        # Insere em ordem inversa
        desordenados = list(reversed(alunos_1a))
        grupos = agrupar_alunos_por_turma(desordenados)
        nomes = [a.nome for a in grupos["1A"]]
        assert nomes == sorted(nomes)


# ---------------------------------------------------------------------------
# TestGerarPlanilha
# ---------------------------------------------------------------------------

class TestGerarPlanilha:
    def test_gera_arquivo_xlsx(self, alunos_1a: list[Aluno], tmp_path: Path):
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)
        assert filepath.exists()
        assert filepath.suffix == ".xlsx"
        assert "1A" in filepath.name

    def test_contem_abas_de_disciplina(self, alunos_1a: list[Aluno], tmp_path: Path):
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)
        wb = openpyxl.load_workbook(str(filepath))
        # Deve ter mais de 1 aba (disciplinas + _metadata)
        assert len(wb.sheetnames) > 1
        assert "_metadata" in wb.sheetnames
        wb.close()

    def test_colunas_corretas_em_aba(self, alunos_1a: list[Aluno], tmp_path: Path):
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)
        wb = openpyxl.load_workbook(str(filepath))
        # Pega primeira aba de disciplina (não _metadata)
        aba_disc = [s for s in wb.sheetnames if s != "_metadata"][0]
        ws = wb[aba_disc]
        headers = [ws.cell(row=1, column=i).value for i in range(1, len(TODAS_COLUNAS) + 1)]
        assert headers == TODAS_COLUNAS
        wb.close()

    def test_dados_pre_preenchidos(self, alunos_1a: list[Aluno], tmp_path: Path):
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)
        wb = openpyxl.load_workbook(str(filepath))
        aba_disc = [s for s in wb.sheetnames if s != "_metadata"][0]
        ws = wb[aba_disc]

        # Verifica dados dos alunos na linha 2 (primeira linha de dados)
        assert ws.cell(row=2, column=1).value == "Alice Silva"
        assert ws.cell(row=2, column=2).value == "1001"
        assert ws.cell(row=2, column=3).value == "1A"
        wb.close()

    def test_alunos_iguais_em_todas_abas(self, alunos_1a: list[Aluno], tmp_path: Path):
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)
        wb = openpyxl.load_workbook(str(filepath))
        abas_disc = [s for s in wb.sheetnames if s != "_metadata"]

        # Coleta nomes da primeira aba
        ws0 = wb[abas_disc[0]]
        nomes_ref = [ws0.cell(row=r, column=1).value for r in range(2, len(alunos_1a) + 2)]

        # Verifica que todas as abas têm os mesmos alunos
        for aba in abas_disc[1:]:
            ws = wb[aba]
            nomes = [ws.cell(row=r, column=1).value for r in range(2, len(alunos_1a) + 2)]
            assert nomes == nomes_ref, f"Aba {aba} tem alunos diferentes"
        wb.close()

    def test_metadata_presente(self, alunos_1a: list[Aluno], tmp_path: Path):
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)
        wb = openpyxl.load_workbook(str(filepath))
        ws = wb["_metadata"]

        # Verifica metadados gerais
        meta = {}
        for row in ws.iter_rows(min_row=2, max_row=8, max_col=2, values_only=True):
            if row[0] and row[1]:
                meta[str(row[0])] = str(row[1])

        assert meta["trimestre"] == "T1"
        assert meta["turma"] == "1A"
        assert meta["ano"] == "2026"
        wb.close()

    def test_metadata_mapa_abas(self, alunos_1a: list[Aluno], tmp_path: Path):
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)
        wb = openpyxl.load_workbook(str(filepath))
        ws = wb["_metadata"]

        # Mapa de abas começa na linha 11
        abas_meta = []
        for row in ws.iter_rows(min_row=11, max_col=5, values_only=True):
            if row[0] is None:
                break
            abas_meta.append(row[0])

        abas_disc = [s for s in wb.sheetnames if s != "_metadata"]
        assert set(abas_meta) == set(abas_disc)
        wb.close()

    def test_serie_3_levanta_erro(self, tmp_path: Path):
        alunos = [Aluno(nome="Test", ra="9999", turma="3A")]
        with pytest.raises(ValueError, match="não é suportada"):
            gerar_planilha_turma("3A", "T1", 2026, alunos, tmp_path)

    def test_turma_invalida_levanta_erro(self, tmp_path: Path):
        alunos = [Aluno(nome="Test", ra="9999", turma="XZ")]
        with pytest.raises(ValueError):
            gerar_planilha_turma("XZ", "T1", 2026, alunos, tmp_path)


# ---------------------------------------------------------------------------
# TestGerarTodas
# ---------------------------------------------------------------------------

class TestGerarTodas:
    def test_gera_apenas_series_suportadas(self, alunos_mistos: list[Aluno], tmp_path: Path):
        arquivos = gerar_todas_planilhas("T1", 2026, alunos_mistos, tmp_path)
        nomes = {f.name for f in arquivos}
        assert "1A_T1_2026.xlsx" in nomes
        assert "2B_T1_2026.xlsx" in nomes
        # 3ª série deve ser ignorada
        assert not any("3A" in n for n in nomes)

    def test_gera_numero_correto_de_arquivos(self, alunos_mistos: list[Aluno], tmp_path: Path):
        arquivos = gerar_todas_planilhas("T1", 2026, alunos_mistos, tmp_path)
        assert len(arquivos) == 2  # 1A e 2B (3A ignorada)
