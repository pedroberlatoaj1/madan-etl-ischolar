import pytest

import madan_planilha_mapper as m


def test_normalizar_nome_coluna_remove_acentos_espacos_sinais():
    assert m.normalizar_nome_coluna("AV 1 (OBJ)") == "av_1_obj"
    assert m.normalizar_nome_coluna("AV 1 (DISÇ)") == "av_1_disc"
    assert m.normalizar_nome_coluna("Frente - Professor") == "frente_professor"
    assert m.normalizar_nome_coluna("Nota sem a AV 3") == "nota_sem_a_av_3"


def test_mapear_colunas_madan_reconhece_cabecalhos_da_planilha():
    cols = [
        "Estudante",
        "Trimestre",
        "Disciplina",
        "Frente - Professor",
        "Turma",
        "AV 1 (OBJ)",
        "AV 1 (DISÇ)",
        "AV 2 (OBJ)",
        "AV 2 (DISÇ)",
        "AV 3 (listas)",
        "AV 3 (avaliação)",
        "Simulado",
        "Nota sem a AV 3",
        "Nota com a AV 3",
        "Ponto extra",
        "Observação relacionada ao ponto extra",
        "Nota Final",
        "Recuperação",
    ]
    mapping = m.mapear_colunas_madan(cols)

    assert mapping["Estudante"] == m.CAN_ESTUDANTE
    assert mapping["Trimestre"] == m.CAN_TRIMESTRE
    assert mapping["Disciplina"] == m.CAN_DISCIPLINA
    assert mapping["Frente - Professor"] == m.CAN_FRENTE_PROFESSOR
    assert mapping["Turma"] == m.CAN_TURMA
    assert mapping["AV 1 (OBJ)"] == m.CAN_AV1_OBJ
    assert mapping["AV 1 (DISÇ)"] == m.CAN_AV1_DISC
    assert mapping["AV 2 (OBJ)"] == m.CAN_AV2_OBJ
    assert mapping["AV 2 (DISÇ)"] == m.CAN_AV2_DISC
    assert mapping["AV 3 (listas)"] == m.CAN_AV3_LISTAS
    assert mapping["AV 3 (avaliação)"] == m.CAN_AV3_AVALIACAO
    assert mapping["Simulado"] == m.CAN_SIMULADO
    assert mapping["Ponto extra"] == m.CAN_PONTO_EXTRA


def test_inferir_tem_nivelamento_heuristica():
    assert m.inferir_tem_nivelamento({m.CAN_AV3_LISTAS: ""}) is False
    assert m.inferir_tem_nivelamento({m.CAN_AV3_AVALIACAO: None}) is False
    assert m.inferir_tem_nivelamento({m.CAN_AV3_LISTAS: 8}) is True
    assert m.inferir_tem_nivelamento({m.CAN_AV3_AVALIACAO: 6}) is True


def test_linha_wide_para_canonica_preserva_contexto_e_componentes():
    row = {
        "Estudante": "A",
        "Trimestre": "1",
        "Disciplina": "Mat",
        "Frente - Professor": "F - P",
        "Turma": "T1",
        "AV 1 (OBJ)": "8,0",
        "AV 3 (listas)": "7",
    }
    canon = m.linha_wide_para_canonica(row)
    assert canon.contexto[m.CAN_ESTUDANTE] == "A"
    assert canon.contexto[m.CAN_TRIMESTRE] == "1"
    assert canon.componentes[m.CAN_AV1_OBJ] == "8,0"
    assert canon.componentes[m.CAN_AV3_LISTAS] == "7"
    assert canon.tem_nivelamento is True


# ---------------------------------------------------------------------------
# Testes de RA — schema canônico fixo
# ---------------------------------------------------------------------------

def test_ra_reconhecido_pelo_mapper():
    """Cabeçalho 'RA' do template fixo deve mapear para CAN_RA."""
    cols = ["Estudante", "RA", "Turma", "Trimestre", "Disciplina"]
    mapping = m.mapear_colunas_madan(cols)
    assert "RA" in mapping
    assert mapping["RA"] == m.CAN_RA


def test_ra_entra_no_contexto_canonico():
    """RA presente na linha deve aparecer em canon.contexto[CAN_RA]."""
    row = {
        "Estudante": "Ana Silva",
        "RA": "RA2024001",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Matemática",
        "AV 1 (OBJ)": "8",
        "AV 1 (DISC)": "8",
    }
    canon = m.linha_wide_para_canonica(row)
    assert canon.contexto[m.CAN_RA] == "RA2024001"


def test_ra_ausente_na_linha_resulta_em_none_no_contexto():
    """Linha sem coluna RA deve ter CAN_RA=None no contexto, sem erro."""
    row = {
        "Estudante": "Beto",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Mat",
        "AV 1 (OBJ)": "7",
    }
    canon = m.linha_wide_para_canonica(row)
    # Não levanta — a ausência é propagada como None para o resolvedor tratar
    assert canon.contexto.get(m.CAN_RA) is None


def test_validar_colunas_obrigatorias_template_completo():
    """Template com todas as colunas obrigatórias não retorna ausentes."""
    cols = ["Estudante", "RA", "Turma", "Trimestre", "Disciplina",
            "Frente - Professor", "AV 1 (OBJ)", "AV 1 (DISC)", "Simulado"]
    ausentes = m.validar_colunas_obrigatorias_template(cols)
    assert ausentes == []


def test_validar_colunas_obrigatorias_template_frente_ausente():
    """Template sem coluna Frente - Professor deve retornar 'frente_professor' como ausente."""
    cols = ["Estudante", "RA", "Turma", "Trimestre", "Disciplina", "AV 1 (OBJ)"]
    ausentes = m.validar_colunas_obrigatorias_template(cols)
    assert m.CAN_FRENTE_PROFESSOR in ausentes


def test_validar_colunas_obrigatorias_template_ra_ausente():
    """Template sem coluna RA deve retornar 'ra' como ausente."""
    cols = ["Estudante", "Turma", "Trimestre", "Disciplina", "AV 1 (OBJ)"]
    ausentes = m.validar_colunas_obrigatorias_template(cols)
    assert m.CAN_RA in ausentes


def test_validar_colunas_obrigatorias_template_multiplas_ausentes():
    """Template sem RA e sem Estudante retorna ambos como ausentes."""
    cols = ["Turma", "Trimestre", "AV 1 (OBJ)"]
    ausentes = m.validar_colunas_obrigatorias_template(cols)
    assert m.CAN_RA in ausentes
    assert m.CAN_ESTUDANTE in ausentes
    assert m.CAN_DISCIPLINA in ausentes