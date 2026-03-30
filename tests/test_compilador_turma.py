"""
Testes para compilador_turma.py — compilação de planilha multi-abas para formato pipeline.

Inclui teste de round-trip: gerar → preencher notas → compilar → validar formato.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from compilador_turma import (
    _formatar_frente_professor,
    _ler_metadata,
    compilar_planilha_turma,
    compilar_planilha_para_arquivo,
    compilar_diretorio,
)
from gerador_planilhas import (
    Aluno,
    gerar_planilha_turma,
    COLUNAS_NOTA,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def alunos_1a() -> list[Aluno]:
    return [
        Aluno(nome="Alice Silva", ra="1001", turma="1A"),
        Aluno(nome="Bruno Costa", ra="1002", turma="1A"),
    ]


@pytest.fixture
def planilha_1a(alunos_1a: list[Aluno], tmp_path: Path) -> Path:
    """Gera planilha da turma 1A e retorna o caminho."""
    return gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)


@pytest.fixture
def planilha_1a_com_notas(planilha_1a: Path) -> Path:
    """Planilha 1A com notas preenchidas em uma aba."""
    wb = openpyxl.load_workbook(str(planilha_1a))

    # Preenche notas na primeira aba de disciplina
    abas_disc = [s for s in wb.sheetnames if s != "_metadata"]
    ws = wb[abas_disc[0]]

    # Desprotege para editar notas de teste
    ws.protection.sheet = False

    # Alice (row 2): AV1(OBJ)=4, AV1(DISC)=3
    ws.cell(row=2, column=4, value=4)   # AV 1 (OBJ)
    ws.cell(row=2, column=5, value=3)   # AV 1 (DISC)

    # Bruno (row 3): AV1(OBJ)=5, AV1(DISC)=4, Simulado=7
    ws.cell(row=3, column=4, value=5)
    ws.cell(row=3, column=5, value=4)
    ws.cell(row=3, column=10, value=7)  # Simulado

    wb.save(str(planilha_1a))
    wb.close()
    return planilha_1a


# ---------------------------------------------------------------------------
# TestFormatarFrenteProfessor
# ---------------------------------------------------------------------------

class TestFormatarFrenteProfessor:
    def test_com_frente(self):
        assert _formatar_frente_professor("F2", "Luan") == "F2 - Luan"

    def test_sem_frente(self):
        assert _formatar_frente_professor("", "Nery") == "Nery"

    def test_frente_complexa(self):
        assert _formatar_frente_professor("F1", "Cavaco") == "F1 - Cavaco"


# ---------------------------------------------------------------------------
# TestLerMetadata
# ---------------------------------------------------------------------------

class TestLerMetadata:
    def test_le_metadata_corretamente(self, planilha_1a: Path):
        wb = openpyxl.load_workbook(str(planilha_1a))
        meta = _ler_metadata(wb)
        wb.close()

        assert meta["trimestre"] == "T1"
        assert meta["turma"] == "1A"
        assert meta["ano"] == "2026"
        assert len(meta["mapa_abas"]) > 0

    def test_mapa_abas_tem_disciplina(self, planilha_1a: Path):
        wb = openpyxl.load_workbook(str(planilha_1a))
        meta = _ler_metadata(wb)
        wb.close()

        for aba in meta["mapa_abas"]:
            assert aba["disciplina"], f"Aba {aba['nome_aba']} sem disciplina"
            assert aba["professor"], f"Aba {aba['nome_aba']} sem professor"

    def test_sem_metadata_levanta_erro(self, tmp_path: Path):
        # Cria um xlsx sem aba _metadata
        wb = openpyxl.Workbook()
        wb.active.title = "dados"
        path = tmp_path / "sem_meta.xlsx"
        wb.save(str(path))
        wb.close()

        wb2 = openpyxl.load_workbook(str(path))
        with pytest.raises(ValueError, match="_metadata"):
            _ler_metadata(wb2)
        wb2.close()


# ---------------------------------------------------------------------------
# TestCompilarPlanilha
# ---------------------------------------------------------------------------

class TestCompilarPlanilha:
    def test_planilha_sem_notas_retorna_vazio(self, planilha_1a: Path):
        df = compilar_planilha_turma(planilha_1a)
        assert df.empty

    def test_planilha_com_notas_retorna_linhas(self, planilha_1a_com_notas: Path):
        df = compilar_planilha_turma(planilha_1a_com_notas)
        assert not df.empty
        assert len(df) == 2  # Alice e Bruno

    def test_colunas_pipeline_presentes(self, planilha_1a_com_notas: Path):
        df = compilar_planilha_turma(planilha_1a_com_notas)
        colunas_obrigatorias = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Disciplina", "Frente - Professor",
        ]
        for col in colunas_obrigatorias:
            assert col in df.columns, f"Coluna '{col}' ausente no output"

    def test_trimestre_preenchido(self, planilha_1a_com_notas: Path):
        df = compilar_planilha_turma(planilha_1a_com_notas)
        assert all(df["Trimestre"] == "T1")

    def test_disciplina_preenchida(self, planilha_1a_com_notas: Path):
        df = compilar_planilha_turma(planilha_1a_com_notas)
        assert all(df["Disciplina"].notna())
        assert all(df["Disciplina"] != "")

    def test_frente_professor_preenchida(self, planilha_1a_com_notas: Path):
        df = compilar_planilha_turma(planilha_1a_com_notas)
        assert all(df["Frente - Professor"].notna())

    def test_notas_preservadas(self, planilha_1a_com_notas: Path):
        df = compilar_planilha_turma(planilha_1a_com_notas)
        alice = df[df["Estudante"] == "Alice Silva"].iloc[0]
        assert alice["AV 1 (OBJ)"] == 4
        assert alice["AV 1 (DISC)"] == 3

    def test_ordenado_por_aluno_disciplina(self, planilha_1a_com_notas: Path):
        df = compilar_planilha_turma(planilha_1a_com_notas)
        estudantes = list(df["Estudante"])
        assert estudantes == sorted(estudantes)


# ---------------------------------------------------------------------------
# TestCompilarParaArquivo
# ---------------------------------------------------------------------------

class TestCompilarParaArquivo:
    def test_gera_arquivo_xlsx(self, planilha_1a_com_notas: Path, tmp_path: Path):
        output = tmp_path / "output" / "pipeline.xlsx"
        result = compilar_planilha_para_arquivo(planilha_1a_com_notas, output)
        assert result.exists()
        assert result.suffix == ".xlsx"

    def test_arquivo_legivel_por_pandas(self, planilha_1a_com_notas: Path, tmp_path: Path):
        output = tmp_path / "pipeline.xlsx"
        compilar_planilha_para_arquivo(planilha_1a_com_notas, output)
        df = pd.read_excel(str(output), dtype=str)
        assert len(df) == 2
        assert "Estudante" in df.columns


# ---------------------------------------------------------------------------
# TestCompilarDiretorio
# ---------------------------------------------------------------------------

class TestCompilarDiretorio:
    def test_compila_todos_xlsx(self, alunos_1a: list[Aluno], tmp_path: Path):
        input_dir = tmp_path / "planilhas"
        output_dir = tmp_path / "pipeline"

        # Gera planilha
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, input_dir)

        # Preenche uma nota para que o compilador produza output
        wb = openpyxl.load_workbook(str(filepath))
        abas_disc = [s for s in wb.sheetnames if s != "_metadata"]
        ws = wb[abas_disc[0]]
        ws.protection.sheet = False
        ws.cell(row=2, column=4, value=8)  # AV1 OBJ para Alice
        wb.save(str(filepath))
        wb.close()

        # Compila
        arquivos = compilar_diretorio(input_dir, output_dir)
        assert len(arquivos) == 1
        assert "pipeline" in arquivos[0].name


# ---------------------------------------------------------------------------
# TestRoundTrip — teste de integração completo
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """
    Teste round-trip: gera planilha → preenche notas → compila → verifica
    que o output tem o formato exato esperado pelo pipeline (cli_envio.py).
    """

    def test_round_trip_formato_pipeline(self, alunos_1a: list[Aluno], tmp_path: Path):
        # 1. Gera planilha
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)

        # 2. Preenche notas
        wb = openpyxl.load_workbook(str(filepath))
        abas_disc = [s for s in wb.sheetnames if s != "_metadata"]
        ws = wb[abas_disc[0]]
        ws.protection.sheet = False

        # Alice: AV1(OBJ)=4, AV1(DISC)=3, AV2(OBJ)=5, AV2(DISC)=4
        ws.cell(row=2, column=4, value=4)
        ws.cell(row=2, column=5, value=3)
        ws.cell(row=2, column=6, value=5)
        ws.cell(row=2, column=7, value=4)

        wb.save(str(filepath))
        wb.close()

        # 3. Compila
        df = compilar_planilha_turma(filepath)

        # 4. Verifica formato pipeline
        assert len(df) == 1  # Só Alice tem notas

        row = df.iloc[0]
        assert row["Estudante"] == "Alice Silva"
        assert row["RA"] == "1001"
        assert row["Turma"] == "1A"
        assert row["Trimestre"] == "T1"
        assert row["Disciplina"] != ""
        assert row["Frente - Professor"] != ""
        assert row["AV 1 (OBJ)"] == 4
        assert row["AV 1 (DISC)"] == 3
        assert row["AV 2 (OBJ)"] == 5
        assert row["AV 2 (DISC)"] == 4

    def test_round_trip_multiplas_abas(self, alunos_1a: list[Aluno], tmp_path: Path):
        """Verifica que notas em abas diferentes geram linhas distintas."""
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)

        wb = openpyxl.load_workbook(str(filepath))
        abas_disc = [s for s in wb.sheetnames if s != "_metadata"]

        # Preenche notas em 2 abas diferentes para Alice
        for aba_name in abas_disc[:2]:
            ws = wb[aba_name]
            ws.protection.sheet = False
            ws.cell(row=2, column=4, value=7)  # AV1(OBJ) para Alice

        wb.save(str(filepath))
        wb.close()

        df = compilar_planilha_turma(filepath)

        # Alice deve ter 2 linhas (uma por disciplina)
        alice_rows = df[df["Estudante"] == "Alice Silva"]
        assert len(alice_rows) == 2

        # Disciplinas devem ser diferentes
        disciplinas = list(alice_rows["Disciplina"])
        assert len(set(disciplinas)) == 2, "Mesma disciplina em linhas diferentes"

    def test_round_trip_aluno_sem_nota_ignorado(self, alunos_1a: list[Aluno], tmp_path: Path):
        """Alunos sem nenhuma nota preenchida não aparecem no output."""
        filepath = gerar_planilha_turma("1A", "T1", 2026, alunos_1a, tmp_path)

        wb = openpyxl.load_workbook(str(filepath))
        abas_disc = [s for s in wb.sheetnames if s != "_metadata"]
        ws = wb[abas_disc[0]]
        ws.protection.sheet = False

        # Só Alice tem nota, Bruno não
        ws.cell(row=2, column=4, value=8)  # Alice: AV1(OBJ)

        wb.save(str(filepath))
        wb.close()

        df = compilar_planilha_turma(filepath)
        assert len(df) == 1
        assert df.iloc[0]["Estudante"] == "Alice Silva"
