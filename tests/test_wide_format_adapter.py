"""Testes do wide_format_adapter — parser, detector, despivotamento."""

import pandas as pd
import pytest

from wide_format_adapter import (
    ColunaDinamica,
    parsear_coluna_dinamica,
    mapear_tipo_avaliacao,
    construir_frente_professor,
    detectar_formato,
    validar_colunas_wide_novo,
    despivotar_linha_wide,
    despivotar_dataframe,
    FORMATO_WIDE_NOVO,
    FORMATO_SEMI_WIDE_ANTIGO,
    _classificar_colunas,
)


# =========================================================================
# 1. Parser de colunas dinâmicas
# =========================================================================

class TestParsearColunaDinamica:
    """Testa extração de disciplina, frente e tipo de avaliação."""

    def test_coluna_simples(self):
        r = parsear_coluna_dinamica("Matemática - Frente A - AV 1 Obj")
        assert r is not None
        assert r.disciplina == "Matemática"
        assert r.frente == "Frente A"
        assert r.tipo_avaliacao == "AV 1 Obj"

    def test_frente_unica(self):
        r = parsear_coluna_dinamica("Química - Frente Única - Simulado")
        assert r is not None
        assert r.disciplina == "Química"
        assert r.frente == "Frente Única"
        assert r.tipo_avaliacao == "Simulado"

    def test_disciplina_com_espacos(self):
        r = parsear_coluna_dinamica("Interpretação de Texto - Frente Única - AV 2 Disc")
        assert r is not None
        assert r.disciplina == "Interpretação de Texto"
        assert r.frente == "Frente Única"
        assert r.tipo_avaliacao == "AV 2 Disc"

    def test_av3_listas(self):
        r = parsear_coluna_dinamica("Física - Frente B - AV 3 Listas")
        assert r is not None
        assert r.disciplina == "Física"
        assert r.frente == "Frente B"
        assert r.tipo_avaliacao == "AV 3 Listas"

    def test_ponto_extra(self):
        r = parsear_coluna_dinamica("Biologia - Frente A - Ponto Extra")
        assert r is not None
        assert r.tipo_avaliacao == "Ponto Extra"

    def test_recuperacao(self):
        r = parsear_coluna_dinamica("História - Frente A - Recuperação")
        assert r is not None
        assert r.tipo_avaliacao == "Recuperação"

    def test_recuperacao_final(self):
        r = parsear_coluna_dinamica("História - Frente A - Recuperação Final")
        assert r is not None
        assert r.tipo_avaliacao == "Recuperação Final"

    def test_coluna_fixa_retorna_none(self):
        assert parsear_coluna_dinamica("Estudante") is None
        assert parsear_coluna_dinamica("RA") is None
        assert parsear_coluna_dinamica("Turma") is None
        assert parsear_coluna_dinamica("Trimestre") is None

    def test_coluna_formato_antigo_retorna_none(self):
        assert parsear_coluna_dinamica("AV 1 (OBJ)") is None
        assert parsear_coluna_dinamica("Disciplina") is None
        assert parsear_coluna_dinamica("Frente - Professor") is None

    def test_string_vazia_retorna_none(self):
        assert parsear_coluna_dinamica("") is None
        assert parsear_coluna_dinamica("   ") is None

    def test_preserva_coluna_original(self):
        col = "Matemática - Frente A - AV 1 Obj"
        r = parsear_coluna_dinamica(col)
        assert r.coluna_original == col

    def test_case_insensitive(self):
        r = parsear_coluna_dinamica("matemática - frente a - av 1 obj")
        assert r is not None
        assert r.disciplina == "matemática"
        assert r.frente == "frente a"

    def test_frente_c(self):
        r = parsear_coluna_dinamica("Matemática - Frente C - AV 2 Obj")
        assert r is not None
        assert r.frente == "Frente C"


# =========================================================================
# 2. Mapeamento tipo_avaliacao → coluna canônica
# =========================================================================

class TestMapearTipoAvaliacao:
    """Testa conversão de tipo de avaliação para nome de coluna antigo."""

    @pytest.mark.parametrize("tipo,esperado", [
        ("AV 1 Obj", "AV 1 (OBJ)"),
        ("AV 1 Disc", "AV 1 (DISC)"),
        ("AV 2 Obj", "AV 2 (OBJ)"),
        ("AV 2 Disc", "AV 2 (DISC)"),
        ("AV 3 Listas", "AV 3 (listas)"),
        ("AV 3 Avaliação", "AV 3 (avaliação)"),
        ("AV 3 Avaliacao", "AV 3 (avaliação)"),
        ("Simulado", "Simulado"),
        ("Ponto Extra", "Ponto extra"),
        ("Recuperação Final", "Recuperação Final"),
        ("Recuperacao Final", "Recuperação Final"),
        ("Recuperação", "Recuperação"),
        ("Recuperacao", "Recuperação"),
    ])
    def test_mapeamento_todos_tipos(self, tipo, esperado):
        assert mapear_tipo_avaliacao(tipo) == esperado

    def test_tipo_desconhecido_retorna_none(self):
        assert mapear_tipo_avaliacao("Nota Final") is None
        assert mapear_tipo_avaliacao("xyz") is None

    def test_case_insensitive(self):
        assert mapear_tipo_avaliacao("av 1 obj") == "AV 1 (OBJ)"
        assert mapear_tipo_avaliacao("SIMULADO") == "Simulado"

    def test_whitespace(self):
        assert mapear_tipo_avaliacao("  AV 1 Obj  ") == "AV 1 (OBJ)"

    def test_tolerancia_a_encoding_quebrado_em_recuperacao(self):
        assert mapear_tipo_avaliacao("Recupera??o") == "Recuperação"

    def test_tolerancia_a_header_compactado_em_recuperacao_final(self):
        assert mapear_tipo_avaliacao("recuperacaofinal") == "Recuperação Final"

    def test_recuperacao_final_nao_cai_no_fallback_de_recuperacao(self):
        assert mapear_tipo_avaliacao("Recuperação Final") != "Recuperação"


# =========================================================================
# 3. Construtor de frente_professor
# =========================================================================

class TestConstruirFrenteProfessor:
    """Testa construção de chave sintética para mapa_professores.json."""

    def test_frente_com_letra(self):
        assert construir_frente_professor("Matemática", "Frente A") == "matematica a"
        assert construir_frente_professor("Física", "Frente B") == "fisica b"
        assert construir_frente_professor("Matemática", "Frente C") == "matematica c"

    def test_frente_unica(self):
        assert construir_frente_professor("Gramática", "Frente Única") == "gramatica"
        assert construir_frente_professor("Inglês", "Frente Única") == "ingles"
        assert construir_frente_professor("Educação Física", "Frente Única") == "educacao fisica"

    def test_disciplina_com_espacos(self):
        assert construir_frente_professor("Interpretação de Texto", "Frente Única") == "interpretacao de texto"

    def test_frente_unica_com_encoding_quebrado(self):
        assert construir_frente_professor("Arte", "Frente ?nica") == "arte"

    def test_remove_acentos(self):
        assert construir_frente_professor("Química", "Frente A") == "quimica a"
        assert construir_frente_professor("História", "Frente B") == "historia b"

    def test_normaliza_case(self):
        assert construir_frente_professor("MATEMÁTICA", "FRENTE A") == "matematica a"


# =========================================================================
# 4. Detecção de formato
# =========================================================================

class TestDetectarFormato:
    """Testa auto-detecção de formato de planilha."""

    def test_formato_antigo_detectado(self):
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Disciplina", "Frente - Professor",
            "AV 1 (OBJ)", "AV 1 (DISC)", "Simulado",
        ]
        assert detectar_formato(colunas) == FORMATO_SEMI_WIDE_ANTIGO

    def test_formato_novo_detectado(self):
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Matemática - Frente A - AV 1 Obj",
            "Matemática - Frente A - AV 1 Disc",
            "Física - Frente B - Simulado",
        ]
        assert detectar_formato(colunas) == FORMATO_WIDE_NOVO

    def test_sem_colunas_dinamicas_assume_antigo(self):
        colunas = ["Estudante", "RA", "Turma"]
        assert detectar_formato(colunas) == FORMATO_SEMI_WIDE_ANTIGO

    def test_com_disciplina_e_frente_prioriza_antigo(self):
        """Se tem Disciplina + Frente - Professor, é formato antigo mesmo com dinâmicas."""
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Disciplina", "Frente - Professor",
            "Matemática - Frente A - AV 1 Obj",  # pode ser coincidência
        ]
        assert detectar_formato(colunas) == FORMATO_SEMI_WIDE_ANTIGO


# =========================================================================
# 5. Validação de template wide novo
# =========================================================================

class TestValidarColunasWideNovo:
    """Testa validação de colunas no formato wide novo."""

    def test_valido_sem_problemas(self):
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Matemática - Frente A - AV 1 Obj",
            "Matemática - Frente A - AV 1 Disc",
        ]
        problemas = validar_colunas_wide_novo(colunas)
        assert problemas == []

    def test_faltando_coluna_obrigatoria(self):
        colunas = [
            "Estudante", "Turma", "Trimestre",  # falta RA
            "Matemática - Frente A - AV 1 Obj",
        ]
        problemas = validar_colunas_wide_novo(colunas)
        assert any("ra" in p for p in problemas)

    def test_sem_colunas_dinamicas(self):
        colunas = ["Estudante", "RA", "Turma", "Trimestre"]
        problemas = validar_colunas_wide_novo(colunas)
        assert any("dinâmica" in p.lower() or "dinamica" in p.lower() for p in problemas)

    def test_tipo_avaliacao_nao_reconhecido(self):
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Matemática - Frente A - Nota Final",  # tipo não reconhecido
        ]
        problemas = validar_colunas_wide_novo(colunas)
        assert any("não reconhecido" in p or "nao reconhecido" in p for p in problemas)


# =========================================================================
# 6. Despivotamento de linha única
# =========================================================================

class TestDespivotar:
    """Testa conversão de 1 linha wide → N linhas virtuais."""

    def _make_row_and_groups(self):
        """Helper: cria row e grupos para uma planilha de teste."""
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Matemática - Frente A - AV 1 Obj",
            "Matemática - Frente A - AV 1 Disc",
            "Matemática - Frente A - Simulado",
            "Física - Frente Única - AV 1 Obj",
            "Física - Frente Única - AV 1 Disc",
        ]
        fixas, grupos = _classificar_colunas(colunas)
        row = {
            "Estudante": "João Silva",
            "RA": "1234",
            "Turma": "1A",
            "Trimestre": "1",
            "Matemática - Frente A - AV 1 Obj": 8.0,
            "Matemática - Frente A - AV 1 Disc": 7.0,
            "Matemática - Frente A - Simulado": 9.0,
            "Física - Frente Única - AV 1 Obj": 6.0,
            "Física - Frente Única - AV 1 Disc": 5.0,
        }
        return row, fixas, grupos

    def test_gera_n_linhas_por_grupo(self):
        row, fixas, grupos = self._make_row_and_groups()
        linhas = despivotar_linha_wide(row, fixas, grupos)
        # 2 grupos: (Matemática, Frente A) e (Física, Frente Única)
        assert len(linhas) == 2

    def test_colunas_fixas_copiadas(self):
        row, fixas, grupos = self._make_row_and_groups()
        linhas = despivotar_linha_wide(row, fixas, grupos)
        for l in linhas:
            assert l["Estudante"] == "João Silva"
            assert l["RA"] == "1234"
            assert l["Turma"] == "1A"
            assert l["Trimestre"] == "1"

    def test_disciplina_e_frente_professor_gerados(self):
        row, fixas, grupos = self._make_row_and_groups()
        linhas = despivotar_linha_wide(row, fixas, grupos)
        discs = {l["Disciplina"] for l in linhas}
        assert "Matemática" in discs
        assert "Física" in discs

        frentes = {l["Frente - Professor"] for l in linhas}
        # Turma=1A → qualificado com professor (chaves existem no mapa_professores.json)
        assert "matematica a - luan" in frentes
        assert "fisica - cavaco" in frentes  # frente única qualificada com Cavaco (1A)

    def test_notas_mapeadas_para_colunas_antigas(self):
        row, fixas, grupos = self._make_row_and_groups()
        linhas = despivotar_linha_wide(row, fixas, grupos)

        # Encontrar linha de Matemática
        mat = [l for l in linhas if l["Disciplina"] == "Matemática"][0]
        assert mat["AV 1 (OBJ)"] == 8.0
        assert mat["AV 1 (DISC)"] == 7.0
        assert mat["Simulado"] == 9.0

        # Encontrar linha de Física
        fis = [l for l in linhas if l["Disciplina"] == "Física"][0]
        assert fis["AV 1 (OBJ)"] == 6.0
        assert fis["AV 1 (DISC)"] == 5.0

    def test_valores_vazios_propagados(self):
        """Colunas dinâmicas com None/NaN devem ser propagadas como None."""
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Matemática - Frente A - AV 1 Obj",
            "Matemática - Frente A - AV 1 Disc",
        ]
        fixas, grupos = _classificar_colunas(colunas)
        row = {
            "Estudante": "Maria",
            "RA": "5678",
            "Turma": "2B",
            "Trimestre": "2",
            "Matemática - Frente A - AV 1 Obj": None,
            "Matemática - Frente A - AV 1 Disc": 5.0,
        }
        linhas = despivotar_linha_wide(row, fixas, grupos)
        assert len(linhas) == 1
        assert linhas[0]["AV 1 (OBJ)"] is None
        assert linhas[0]["AV 1 (DISC)"] == 5.0

    def test_recuperacao_com_header_degradado_ainda_e_mapeada(self):
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Arte - Frente ?nica - Recupera??o",
        ]
        fixas, grupos = _classificar_colunas(colunas)
        row = {
            "Estudante": "Maria",
            "RA": "5678",
            "Turma": "2B",
            "Trimestre": "2",
            "Arte - Frente ?nica - Recupera??o": 10,
        }

        linhas = despivotar_linha_wide(row, fixas, grupos)

        assert len(linhas) == 1
        assert linhas[0]["Disciplina"] == "Arte"
        assert linhas[0]["Frente - Professor"] == "arte - lenice"
        assert linhas[0]["Recuperação"] == 10

    def test_recuperacao_final_com_header_compactado_ainda_e_mapeada(self):
        colunas = [
            "Estudante", "RA", "Turma", "Trimestre",
            "Arte - Frente ?nica - recuperacaofinal",
        ]
        fixas, grupos = _classificar_colunas(colunas)
        row = {
            "Estudante": "Maria",
            "RA": "5678",
            "Turma": "2B",
            "Trimestre": "3",
            "Arte - Frente ?nica - recuperacaofinal": 6.5,
        }

        linhas = despivotar_linha_wide(row, fixas, grupos)

        assert len(linhas) == 1
        assert linhas[0]["Recuperação Final"] == 6.5
        assert "Recuperação" not in linhas[0]


# =========================================================================
# 7. Despivotamento de DataFrame
# =========================================================================

class TestDespivorarDataFrame:
    """Testa conversão de DataFrame wide → DataFrame semi-wide."""

    def test_dataframe_basico(self):
        df = pd.DataFrame({
            "Estudante": ["Alice", "Bob"],
            "RA": ["1222", "1239"],
            "Turma": ["1A", "1A"],
            "Trimestre": ["1", "1"],
            "Matemática - Frente A - AV 1 Obj": [8.0, 7.0],
            "Matemática - Frente A - AV 1 Disc": [6.0, 5.0],
            "Física - Frente Única - AV 1 Obj": [9.0, 8.0],
            "Física - Frente Única - AV 1 Disc": [7.0, 6.0],
        })
        resultado = despivotar_dataframe(df)

        # 2 alunos × 2 grupos = 4 linhas
        assert len(resultado) == 4

        # Deve ter colunas do formato antigo
        assert "Disciplina" in resultado.columns
        assert "Frente - Professor" in resultado.columns
        assert "AV 1 (OBJ)" in resultado.columns
        assert "AV 1 (DISC)" in resultado.columns

        # Não deve ter colunas dinâmicas
        assert "Matemática - Frente A - AV 1 Obj" not in resultado.columns

    def test_dataframe_tres_frentes_matematica(self):
        """Simula caso real: Matemática com 3 frentes."""
        df = pd.DataFrame({
            "Estudante": ["Alice"],
            "RA": ["1222"],
            "Turma": ["1A"],
            "Trimestre": ["1"],
            "Matemática - Frente A - AV 1 Obj": [8.0],
            "Matemática - Frente A - AV 1 Disc": [7.0],
            "Matemática - Frente B - AV 1 Obj": [6.0],
            "Matemática - Frente B - AV 1 Disc": [5.0],
            "Matemática - Frente C - AV 1 Obj": [9.0],
            "Matemática - Frente C - AV 1 Disc": [8.0],
        })
        resultado = despivotar_dataframe(df)

        # 1 aluno × 3 frentes = 3 linhas
        assert len(resultado) == 3

        frentes = sorted(resultado["Frente - Professor"].tolist())
        # Turma=1A → 1 professor de MAT na turma (Luan) → todas as frentes qualificadas com "luan"
        assert frentes == ["matematica a - luan", "matematica b - luan", "matematica c - luan"]

    def test_dataframe_sem_colunas_dinamicas_levanta_erro(self):
        df = pd.DataFrame({
            "Estudante": ["Alice"],
            "RA": ["1222"],
        })
        with pytest.raises(ValueError, match="dinâmica"):
            despivotar_dataframe(df)

    def test_valores_preservados_corretamente(self):
        df = pd.DataFrame({
            "Estudante": ["Alice"],
            "RA": ["1222"],
            "Turma": ["1A"],
            "Trimestre": ["2"],
            "Química - Frente A - AV 2 Obj": [4.5],
            "Química - Frente A - AV 2 Disc": [3.5],
            "Química - Frente A - Simulado": [7.0],
            "Química - Frente A - Ponto Extra": [0.5],
        })
        resultado = despivotar_dataframe(df)

        assert len(resultado) == 1
        row = resultado.iloc[0]
        assert row["Disciplina"] == "Química"
        assert row["Frente - Professor"] == "quimica a - leo"  # Turma=1A → Leo
        assert row["AV 2 (OBJ)"] == 4.5
        assert row["AV 2 (DISC)"] == 3.5
        assert row["Simulado"] == 7.0
        assert row["Ponto extra"] == 0.5


# =========================================================================
# 8. Teste de integração round-trip (adapter → transformador)
# =========================================================================

class TestIntegracaoComTransformador:
    """Verifica que linhas despivotadas passam pelo transformador corretamente."""

    def test_round_trip_gera_lancamentos_validos(self):
        from transformador import linha_madan_para_lancamentos

        df = pd.DataFrame({
            "Estudante": ["Alice Barcelos"],
            "RA": ["1222"],
            "Turma": ["1A"],
            "Trimestre": ["1"],
            "Matemática - Frente A - AV 1 Obj": [4.0],
            "Matemática - Frente A - AV 1 Disc": [5.0],
            "Matemática - Frente A - AV 2 Obj": [3.0],
            "Matemática - Frente A - AV 2 Disc": [4.0],
            "Matemática - Frente A - Simulado": [8.0],
        })

        resultado = despivotar_dataframe(df)
        assert len(resultado) == 1

        row_dict = resultado.iloc[0].to_dict()
        lancamentos = linha_madan_para_lancamentos(row_dict, linha_origem=0)

        # Deve gerar múltiplos lançamentos canônicos
        assert isinstance(lancamentos, list)
        assert len(lancamentos) > 0

        # Todos devem ter os campos obrigatórios
        for lanc in lancamentos:
            assert "estudante" in lanc
            assert "ra" in lanc
            assert "componente" in lanc
            assert "status" in lanc
            assert "hash_conteudo" in lanc

        # Deve ter AV1 consolidado com status pronto
        av1_consolidados = [
            l for l in lancamentos
            if l["componente"] == "av1" and l.get("subcomponente") is None
        ]
        assert len(av1_consolidados) == 1
        assert av1_consolidados[0]["nota_ajustada_0a10"] == 9.0  # 4+5

    def test_round_trip_com_nivelamento(self):
        from transformador import linha_madan_para_lancamentos

        df = pd.DataFrame({
            "Estudante": ["Bob"],
            "RA": ["9999"],
            "Turma": ["1A"],
            "Trimestre": ["1"],
            "Física - Frente Única - AV 1 Obj": [4.0],
            "Física - Frente Única - AV 1 Disc": [5.0],
            "Física - Frente Única - AV 2 Obj": [3.0],
            "Física - Frente Única - AV 2 Disc": [4.0],
            "Física - Frente Única - AV 3 Listas": [7.0],
            "Física - Frente Única - AV 3 Avaliacao": [6.0],
            "Física - Frente Única - Simulado": [8.0],
        })

        resultado = despivotar_dataframe(df)
        row_dict = resultado.iloc[0].to_dict()
        lancamentos = linha_madan_para_lancamentos(row_dict, linha_origem=0)

        # Com nivelamento, deve ter AV3 consolidado
        av3_final = [
            l for l in lancamentos
            if l["componente"] == "av3" and l.get("subcomponente") is None
        ]
        assert len(av3_final) == 1

    def test_round_trip_multiplas_frentes_geram_lancamentos_separados(self):
        from transformador import linha_madan_para_lancamentos

        df = pd.DataFrame({
            "Estudante": ["Alice"],
            "RA": ["1222"],
            "Turma": ["1A"],
            "Trimestre": ["1"],
            "Matemática - Frente A - AV 1 Obj": [4.0],
            "Matemática - Frente A - AV 1 Disc": [5.0],
            "Matemática - Frente A - Simulado": [8.0],
            "Matemática - Frente B - AV 1 Obj": [6.0],
            "Matemática - Frente B - AV 1 Disc": [3.0],
            "Matemática - Frente B - Simulado": [7.0],
        })

        resultado = despivotar_dataframe(df)
        assert len(resultado) == 2  # 2 frentes

        todos_lancamentos = []
        for _, row in resultado.iterrows():
            lancs = linha_madan_para_lancamentos(row.to_dict(), linha_origem=0)
            todos_lancamentos.extend(lancs)

        # Deve ter lançamentos de ambas as frentes (Turma=1A → qualificado com Luan)
        frentes = {l.get("frente_professor") for l in todos_lancamentos}
        assert "matematica a - luan" in frentes
        assert "matematica b - luan" in frentes
