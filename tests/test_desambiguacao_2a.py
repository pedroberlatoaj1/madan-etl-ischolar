"""
tests/test_desambiguacao_2a.py — Desambiguação de professor por turma no adaptador wide.

Cobre:
- _extrair_serie_letra: parsing de "2A", "1B", bordas
- _apelido_slug: apelido vs. primeiro nome
- _qualificar_chave_com_professor: todos os casos sensíveis do 2º ano e 1º ano
- despivotar_linha_wide: integração com Turma no row dict
- despivotar_dataframe: integração com DataFrame completo (2A_T1 e 1A_T1)
"""

from __future__ import annotations

import pytest
import pandas as pd

from wide_format_adapter import (
    _extrair_serie_letra,
    _apelido_slug,
    _qualificar_chave_com_professor,
    _get_turma_do_row,
    despivotar_linha_wide,
    despivotar_dataframe,
    _classificar_colunas,
)
from professores_madan import buscar_por_nome_ou_apelido, buscar_professor_para_turma


# ---------------------------------------------------------------------------
# _extrair_serie_letra
# ---------------------------------------------------------------------------

class TestExtrairSerieLetra:
    def test_2a(self):
        assert _extrair_serie_letra("2A") == (2, "A")

    def test_1b(self):
        assert _extrair_serie_letra("1B") == (1, "B")

    def test_lowercase(self):
        assert _extrair_serie_letra("2a") == (2, "A")

    def test_espacos(self):
        assert _extrair_serie_letra("  2A  ") == (2, "A")

    def test_none(self):
        assert _extrair_serie_letra(None) is None

    def test_string_vazia(self):
        assert _extrair_serie_letra("") is None

    def test_serie_dois_digitos(self):
        assert _extrair_serie_letra("10A") is None

    def test_sem_letra(self):
        assert _extrair_serie_letra("2") is None

    def test_valor_nao_string(self):
        # pandas pode passar float NaN
        assert _extrair_serie_letra(float("nan")) is None


# ---------------------------------------------------------------------------
# _apelido_slug
# ---------------------------------------------------------------------------

class TestApelidoSlug:
    def test_professor_com_apelido_perrone(self):
        prof = buscar_por_nome_ou_apelido("Perrone")
        assert prof is not None
        assert _apelido_slug(prof) == "perrone"

    def test_professor_com_apelido_moreto(self):
        prof = buscar_por_nome_ou_apelido("Moreto")
        assert prof is not None
        assert _apelido_slug(prof) == "moreto"

    def test_professor_com_apelido_carioca(self):
        prof = buscar_por_nome_ou_apelido("Carioca")
        assert prof is not None
        assert _apelido_slug(prof) == "carioca"

    def test_professor_sem_apelido_daniel(self):
        # Daniel Rojas Nascimento — sem apelido, usa primeiro nome
        profs = buscar_professor_para_turma("matematica", 2, "A")
        assert len(profs) == 1
        assert _apelido_slug(profs[0]) == "daniel"

    def test_professor_sem_apelido_luan(self):
        profs = buscar_professor_para_turma("matematica", 1, "A")
        assert len(profs) == 1
        assert _apelido_slug(profs[0]) == "luan"

    def test_professor_sem_apelido_carla(self):
        # Carla Christina Marques Fuentes — sem apelido
        profs = buscar_professor_para_turma("geografia", 2, "A")
        assert len(profs) == 1
        assert _apelido_slug(profs[0]) == "carla"


# ---------------------------------------------------------------------------
# _qualificar_chave_com_professor — casos sensíveis 2º ano
# ---------------------------------------------------------------------------

class TestQualificarChave2Ano:
    """Casos que mudavam de professor entre 1ª e 2ª série."""

    def test_matematica_a_2a(self):
        assert _qualificar_chave_com_professor("matematica a", "Matemática", 2, "A") \
            == "matematica a - daniel"

    def test_matematica_b_2b(self):
        # 2B → Matemática B → Luan
        assert _qualificar_chave_com_professor("matematica b", "Matemática", 2, "B") \
            == "matematica b - luan"

    def test_matematica_c_2c(self):
        # 2C → Matemática C → Carioca
        assert _qualificar_chave_com_professor("matematica c", "Matemática", 2, "C") \
            == "matematica c - carioca"

    def test_biologia_unica_2a(self):
        # "biologia" = Frente Única para 2A → Perrone
        assert _qualificar_chave_com_professor("biologia", "Biologia", 2, "A") \
            == "biologia - perrone"

    def test_biologia_a_2a(self):
        # "biologia a" = Frente A para 2A → Perrone
        assert _qualificar_chave_com_professor("biologia a", "Biologia", 2, "A") \
            == "biologia a - perrone"

    def test_geografia_a_2a(self):
        assert _qualificar_chave_com_professor("geografia a", "Geografia", 2, "A") \
            == "geografia a - carla"

    def test_geografia_b_2b(self):
        assert _qualificar_chave_com_professor("geografia b", "Geografia", 2, "B") \
            == "geografia b - moreto"


# ---------------------------------------------------------------------------
# _qualificar_chave_com_professor — 1º ano (comportamento preservado)
# ---------------------------------------------------------------------------

class TestQualificarChave1Ano:
    """1º ano deve produzir chaves qualificadas coerentes com o mapa (valor idêntico)."""

    def test_matematica_a_1a(self):
        # 1A → Luan → "matematica a - luan" (mapa tem esta chave → id 71, igual a base)
        assert _qualificar_chave_com_professor("matematica a", "Matemática", 1, "A") \
            == "matematica a - luan"

    def test_matematica_b_1b(self):
        # 1B → Carioca → "matematica b - carioca"
        assert _qualificar_chave_com_professor("matematica b", "Matemática", 1, "B") \
            == "matematica b - carioca"

    def test_biologia_a_1a(self):
        # 1A → Jamine → "biologia a - jamine"
        assert _qualificar_chave_com_professor("biologia a", "Biologia", 1, "A") \
            == "biologia a - jamine"

    def test_biologia_b_1b(self):
        assert _qualificar_chave_com_professor("biologia b", "Biologia", 1, "B") \
            == "biologia b - mayara"

    def test_geografia_a_1a(self):
        # 1A → Moreto → "geografia a - moreto"
        assert _qualificar_chave_com_professor("geografia a", "Geografia", 1, "A") \
            == "geografia a - moreto"

    def test_geografia_b_1b(self):
        # 1B → Carla → "geografia b - carla"
        assert _qualificar_chave_com_professor("geografia b", "Geografia", 1, "B") \
            == "geografia b - carla"


# ---------------------------------------------------------------------------
# _qualificar_chave_com_professor — disciplinas de professor único
# ---------------------------------------------------------------------------

class TestQualificarChaveUnico:
    """Disciplinas com um único professor (• em todas as turmas) também devem resolver."""

    def test_gramatica_1a(self):
        assert _qualificar_chave_com_professor("gramatica", "Gramática", 1, "A") \
            == "gramatica - nery"

    def test_ingles_2a(self):
        assert _qualificar_chave_com_professor("ingles", "Inglês", 2, "A") \
            == "ingles - cristina"

    def test_arte_1b(self):
        assert _qualificar_chave_com_professor("arte", "Arte", 1, "B") \
            == "arte - lenice"


# ---------------------------------------------------------------------------
# _qualificar_chave_com_professor — fallback (sem professor único)
# ---------------------------------------------------------------------------

class TestQualificarChaveFallback:
    def test_disciplina_desconhecida(self):
        # Disciplina inexistente → 0 professores → retorna base_key
        assert _qualificar_chave_com_professor("xpto xyz", "Xpto Xyz", 2, "A") \
            == "xpto xyz"

    def test_turma_sem_professor_mapeado(self):
        # Nenhum professor de Matemática mapeado para turma "Z"
        assert _qualificar_chave_com_professor("matematica a", "Matemática", 2, "Z") \
            == "matematica a"


# ---------------------------------------------------------------------------
# despivotar_linha_wide — integração com Turma no row
# ---------------------------------------------------------------------------

def _build_grupos():
    """Monta grupos_dinamicos para 'Matemática - Frente A - AV 1 Obj'."""
    from wide_format_adapter import parsear_coluna_dinamica, ColunaDinamica
    col = "Matemática - Frente A - AV 1 Obj"
    parsed = parsear_coluna_dinamica(col)
    assert parsed is not None
    colunas_fixas = ["Estudante", "RA", "Turma", "Trimestre"]
    grupos = {(parsed.disciplina, parsed.frente): [parsed]}
    return colunas_fixas, grupos


class TestDespivotar2A:
    def test_frente_professor_qualificado_com_turma_2a(self):
        colunas_fixas, grupos = _build_grupos()
        row = {
            "Estudante": "Ana",
            "RA": 100,
            "Turma": "2A",
            "Trimestre": "T1",
            "Matemática - Frente A - AV 1 Obj": 8.0,
        }
        linhas = despivotar_linha_wide(row, colunas_fixas, grupos)
        assert len(linhas) == 1
        assert linhas[0]["Frente - Professor"] == "matematica a - daniel"

    def test_frente_professor_qualificado_com_turma_1a(self):
        colunas_fixas, grupos = _build_grupos()
        row = {
            "Estudante": "João",
            "RA": 200,
            "Turma": "1A",
            "Trimestre": "T1",
            "Matemática - Frente A - AV 1 Obj": 7.5,
        }
        linhas = despivotar_linha_wide(row, colunas_fixas, grupos)
        assert len(linhas) == 1
        assert linhas[0]["Frente - Professor"] == "matematica a - luan"

    def test_sem_turma_usa_base_key(self):
        """Quando não há coluna Turma, o comportamento deve ser conservador."""
        from wide_format_adapter import parsear_coluna_dinamica
        col = "Matemática - Frente A - AV 1 Obj"
        parsed = parsear_coluna_dinamica(col)
        colunas_fixas = ["Estudante", "RA"]  # sem Turma
        grupos = {(parsed.disciplina, parsed.frente): [parsed]}
        row = {
            "Estudante": "Maria",
            "RA": 300,
            "Matemática - Frente A - AV 1 Obj": 9.0,
        }
        linhas = despivotar_linha_wide(row, colunas_fixas, grupos)
        assert len(linhas) == 1
        assert linhas[0]["Frente - Professor"] == "matematica a"

    def test_turma_invalida_usa_base_key(self):
        """Turma em formato não reconhecido não causa erro — usa base_key."""
        colunas_fixas, grupos = _build_grupos()
        row = {
            "Estudante": "Pedro",
            "RA": 400,
            "Turma": "INVALIDA",
            "Trimestre": "T1",
            "Matemática - Frente A - AV 1 Obj": 6.0,
        }
        linhas = despivotar_linha_wide(row, colunas_fixas, grupos)
        assert linhas[0]["Frente - Professor"] == "matematica a"

    def test_valores_fixos_copiados(self):
        colunas_fixas, grupos = _build_grupos()
        row = {
            "Estudante": "Bia",
            "RA": 500,
            "Turma": "2A",
            "Trimestre": "T2",
            "Matemática - Frente A - AV 1 Obj": 5.5,
        }
        linhas = despivotar_linha_wide(row, colunas_fixas, grupos)
        assert linhas[0]["Turma"] == "2A"
        assert linhas[0]["Trimestre"] == "T2"
        assert linhas[0]["AV 1 (OBJ)"] == 5.5


# ---------------------------------------------------------------------------
# despivotar_dataframe — integração DataFrame completo
# ---------------------------------------------------------------------------

def _df_2a_t1():
    """DataFrame mínimo simulando aba 2A_T1 após aplicar_contexto_aba."""
    return pd.DataFrame([
        {
            "Estudante": "Aluno 2A",
            "RA": 1001,
            "Turma": "2A",
            "Trimestre": "T1",
            "Matemática - Frente A - AV 1 Obj": 8.0,
            "Biologia - Frente Única - AV 1 Obj": 7.0,
            "Geografia - Frente A - AV 1 Obj": 6.5,
        }
    ])


def _df_1a_t1():
    return pd.DataFrame([
        {
            "Estudante": "Aluno 1A",
            "RA": 2001,
            "Turma": "1A",
            "Trimestre": "T1",
            "Matemática - Frente A - AV 1 Obj": 9.0,
            "Biologia - Frente A - AV 1 Obj": 8.5,
            "Geografia - Frente A - AV 1 Obj": 7.0,
        }
    ])


class TestDespivotarDataframe:
    def test_2a_materias_qualificadas(self):
        df_out = despivotar_dataframe(_df_2a_t1())
        fp = dict(zip(df_out["Disciplina"], df_out["Frente - Professor"]))
        assert fp["Matemática"] == "matematica a - daniel"
        assert fp["Biologia"] == "biologia - perrone"
        assert fp["Geografia"] == "geografia a - carla"

    def test_1a_materias_qualificadas(self):
        df_out = despivotar_dataframe(_df_1a_t1())
        fp = dict(zip(df_out["Disciplina"], df_out["Frente - Professor"]))
        assert fp["Matemática"] == "matematica a - luan"
        assert fp["Biologia"] == "biologia a - jamine"
        assert fp["Geografia"] == "geografia a - moreto"

    def test_linha_virtual_por_disciplina(self):
        df_out = despivotar_dataframe(_df_2a_t1())
        assert len(df_out) == 3  # mat + bio + geo

    def test_nota_propagada(self):
        df_out = despivotar_dataframe(_df_2a_t1())
        row_mat = df_out[df_out["Disciplina"] == "Matemática"].iloc[0]
        assert row_mat["AV 1 (OBJ)"] == 8.0
