import math

import pytest

import avaliacao_rules as ar


def test_normalizar_trimestre_aceita_1_2_3():
    assert ar.normalizar_trimestre(1) == "t1t2"
    assert ar.normalizar_trimestre(2) == "t1t2"
    assert ar.normalizar_trimestre(3) == "t3"


@pytest.mark.parametrize(
    "raw, esperado",
    [
        ("1", "t1t2"),
        ("1º", "t1t2"),
        ("1o", "t1t2"),
        ("2", "t1t2"),
        ("2º trimestre", "t1t2"),
        ("3", "t3"),
        ("3º", "t3"),
        ("3 trimestre", "t3"),
    ],
)
def test_normalizar_trimestre_strings(raw, esperado):
    assert ar.normalizar_trimestre(raw) == esperado


def test_obter_pesos_4_cenarios():
    assert ar.obter_pesos(1, False) == {ar.AV1: 12.0, ar.AV2: 15.0, ar.SIMULADO: 3.0}
    assert ar.obter_pesos(2, True) == {ar.AV1: 9.0, ar.AV2: 9.0, ar.AV3: 9.0, ar.SIMULADO: 3.0}
    assert ar.obter_pesos(3, False) == {ar.AV1: 16.0, ar.AV2: 18.0, ar.SIMULADO: 6.0}
    assert ar.obter_pesos("3º", True) == {ar.AV1: 12.0, ar.AV2: 12.0, ar.AV3: 12.0, ar.SIMULADO: 4.0}


def test_calcular_nota_ponderada_simples():
    assert ar.calcular_nota_ponderada(8, 12) == 9.6
    assert ar.calcular_nota_ponderada("8,5", "15") == 12.75


def test_is_blank_ignora_vazios_sem_virar_zero():
    assert ar.is_blank(None) is True
    assert ar.is_blank("") is True
    assert ar.is_blank("   ") is True
    assert ar.is_blank(float("nan")) is True


def test_calcular_av3_completa():
    # (listas/10)*7 + (avaliacao/10)*3
    assert ar.calcular_av3_nivelamento(10, 10) == 10.0
    assert ar.calcular_av3_nivelamento(0, 0) == 0.0
    assert ar.calcular_av3_nivelamento(8, 6) == 7.4


def test_extrair_componentes_av3_incompleta_nao_gera_av3():
    r = ar.extrair_componentes_validos({ar.AV3_LISTAS: 8})
    assert r.av3_incompleta is True
    assert ar.AV3 not in r.componentes

    r2 = ar.extrair_componentes_validos({ar.AV3_AVALIACAO: 6})
    assert r2.av3_incompleta is True
    assert ar.AV3 not in r2.componentes


def test_extrair_componentes_ignora_celulas_em_branco():
    r = ar.extrair_componentes_validos({ar.AV1: "", ar.AV2: None, ar.SIMULADO: "   "})
    assert r.componentes == {}
    assert r.av3_incompleta is False


def test_extrair_componentes_av3_completa_gera_av3():
    r = ar.extrair_componentes_validos({ar.AV3_LISTAS: 8, ar.AV3_AVALIACAO: 6})
    assert r.av3_incompleta is False
    assert r.componentes[ar.AV3] == 7.4


def test_aplicar_ponto_extra_em_av1_teto_10():
    assert ar.aplicar_ponto_extra_em_av1(9.5, 1.0) == 10.0
    assert ar.aplicar_ponto_extra_em_av1(10.0, 1.0) == 10.0


def test_aplicar_ponto_extra_em_av1_ignora_se_fechada():
    assert ar.aplicar_ponto_extra_em_av1(9.0, 1.0, avaliacao_fechada=True) == 9.0


def test_validacao_nota_negativa_gera_erro():
    with pytest.raises(ValueError, match="negativa"):
        ar.calcular_nota_ponderada(-1, 12)


def test_validacao_nota_acima_de_10_gera_erro():
    with pytest.raises(ValueError, match="acima de 10"):
        ar.calcular_nota_ponderada(10.1, 12)


def test_ponto_extra_nao_permite_negativo():
    with pytest.raises(ValueError, match="Ponto extra negativo"):
        ar.aplicar_ponto_extra_em_av1(9.0, -0.5)


# ---------------------------------------------------------------------------
# Testes de consolidar_obj_disc — policy "soma" (regra oficial Madan)
# ---------------------------------------------------------------------------

def test_consolidar_obj_disc_soma_simples():
    """Regra oficial: AV1/AV2 = OBJ + DISC (soma simples)."""
    assert ar.consolidar_obj_disc(4, 5) == 9.0
    assert ar.consolidar_obj_disc(3, 4) == 7.0
    assert ar.consolidar_obj_disc(0, 0) == 0.0
    assert ar.consolidar_obj_disc(5, 5) == 10.0


def test_consolidar_obj_disc_soma_ultrapassa_10_gera_erro():
    """Se OBJ + DISC > 10, o sistema deve bloquear com erro claro."""
    with pytest.raises(ValueError, match="ultrapassa 10"):
        ar.consolidar_obj_disc(6, 5)
    with pytest.raises(ValueError, match="ultrapassa 10"):
        ar.consolidar_obj_disc(8, 9)


def test_consolidar_obj_disc_soma_apenas_um_presente():
    """Se apenas OBJ ou DISC existir, usa esse valor diretamente."""
    assert ar.consolidar_obj_disc(7, None) == 7.0
    assert ar.consolidar_obj_disc(None, 8) == 8.0
    assert ar.consolidar_obj_disc("", 6) == 6.0


def test_consolidar_obj_disc_soma_ambos_ausentes():
    """Se nenhum existir, retorna None."""
    assert ar.consolidar_obj_disc(None, None) is None
    assert ar.consolidar_obj_disc("", "") is None


def test_consolidar_obj_disc_policy_media_simples_legado():
    """Policy media_simples mantida por compatibilidade."""
    assert ar.consolidar_obj_disc(8, 6, policy="media_simples") == 7.0


def test_consolidar_obj_disc_default_policy_e_soma():
    """O default deve ser 'soma', não 'media_simples'."""
    # 4 + 5 = 9 (soma), não 4.5 (média)
    assert ar.consolidar_obj_disc(4, 5) == 9.0

