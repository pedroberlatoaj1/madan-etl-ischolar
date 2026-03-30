"""
test_recuperacao.py — Testes das regras de recuperação do Madan.

Cobertura das 4 regras confirmadas:
  1. Recuperação trimestral: rendimento < 60% no T1 ou T2
  2. Exceção do 3º trimestre: T3 NÃO tem recuperação trimestral
  3. Recuperação final: rendimento anual < 60%
  4. Rendimento anual = média ponderada (T1×30 + T2×30 + T3×40) / 100
"""

import pytest

import avaliacao_rules as ar
from transformador import linha_madan_para_lancamentos


# ---------------------------------------------------------------------------
# Regra 4: Cálculo do rendimento trimestral
# ---------------------------------------------------------------------------

class TestRendimentoTrimestral:
    def test_rendimento_t1_100_porcento(self):
        """Aluno com 30/30 pontos no T1 → rendimento = 100%."""
        assert ar.calcular_rendimento_trimestral(30.0, 1) == 100.0

    def test_rendimento_t2_100_porcento(self):
        """Aluno com 30/30 pontos no T2 → rendimento = 100%."""
        assert ar.calcular_rendimento_trimestral(30.0, 2) == 100.0

    def test_rendimento_t3_100_porcento(self):
        """Aluno com 40/40 pontos no T3 → rendimento = 100%."""
        assert ar.calcular_rendimento_trimestral(40.0, 3) == 100.0

    def test_rendimento_t1_zero(self):
        """Aluno com 0/30 pontos no T1 → rendimento = 0%."""
        assert ar.calcular_rendimento_trimestral(0.0, 1) == 0.0

    def test_rendimento_t1_exatamente_60_porcento(self):
        """18/30 = 60% — limite exato."""
        assert ar.calcular_rendimento_trimestral(18.0, 1) == 60.0

    def test_rendimento_t3_exatamente_60_porcento(self):
        """24/40 = 60% — limite exato para T3."""
        assert ar.calcular_rendimento_trimestral(24.0, 3) == 60.0

    def test_rendimento_t1_abaixo_60(self):
        """17/30 ≈ 56.67% — abaixo do limiar."""
        rend = ar.calcular_rendimento_trimestral(17.0, 1)
        assert rend < 60.0
        assert rend == pytest.approx(56.67, abs=0.01)

    def test_rendimento_aceita_string_trimestre(self):
        """Deve aceitar trimestre como string ('1º trimestre')."""
        assert ar.calcular_rendimento_trimestral(30.0, "1º") == 100.0
        assert ar.calcular_rendimento_trimestral(40.0, "3") == 100.0

    def test_rendimento_negativo_gera_erro(self):
        with pytest.raises(ValueError, match="negativa"):
            ar.calcular_rendimento_trimestral(-1.0, 1)


# ---------------------------------------------------------------------------
# Regra 1: Recuperação trimestral (T1/T2 apenas)
# ---------------------------------------------------------------------------

class TestRecuperacaoTrimestral:
    def test_rendimento_abaixo_60_t1_gera_recuperacao(self):
        """Rendimento 59.9% no T1 → recuperação trimestral."""
        assert ar.verificar_recuperacao_trimestral(59.9, 1) is True

    def test_rendimento_abaixo_60_t2_gera_recuperacao(self):
        """Rendimento 50% no T2 → recuperação trimestral."""
        assert ar.verificar_recuperacao_trimestral(50.0, 2) is True

    def test_rendimento_exatamente_60_nao_gera_recuperacao(self):
        """Rendimento = 60% exato → NÃO precisa de recuperação (é >= 60%)."""
        assert ar.verificar_recuperacao_trimestral(60.0, 1) is False
        assert ar.verificar_recuperacao_trimestral(60.0, 2) is False

    def test_rendimento_acima_60_nao_gera_recuperacao(self):
        """Rendimento 85% → NÃO precisa de recuperação."""
        assert ar.verificar_recuperacao_trimestral(85.0, 1) is False
        assert ar.verificar_recuperacao_trimestral(85.0, 2) is False

    def test_rendimento_zero_gera_recuperacao(self):
        """Rendimento 0% → recuperação."""
        assert ar.verificar_recuperacao_trimestral(0.0, 1) is True


# ---------------------------------------------------------------------------
# Regra 2: T3 NUNCA tem recuperação trimestral
# ---------------------------------------------------------------------------

class TestExcecaoT3:
    def test_t3_rendimento_abaixo_60_nao_gera_recuperacao(self):
        """T3 com 30% de rendimento → NÃO gera recuperação trimestral."""
        assert ar.verificar_recuperacao_trimestral(30.0, 3) is False

    def test_t3_rendimento_zero_nao_gera_recuperacao(self):
        """T3 com 0% → NÃO gera recuperação trimestral."""
        assert ar.verificar_recuperacao_trimestral(0.0, 3) is False

    def test_t3_rendimento_59_nao_gera_recuperacao(self):
        """T3 com 59% → NÃO gera recuperação trimestral (regra explícita)."""
        assert ar.verificar_recuperacao_trimestral(59.0, 3) is False

    def test_t3_aceita_string_trimestre(self):
        """T3 com formato string → NÃO gera recuperação."""
        assert ar.verificar_recuperacao_trimestral(10.0, "3") is False
        assert ar.verificar_recuperacao_trimestral(10.0, "3º") is False
        assert ar.verificar_recuperacao_trimestral(10.0, "3 trimestre") is False


# ---------------------------------------------------------------------------
# Regra 4: Rendimento anual (média ponderada 30-30-40)
# ---------------------------------------------------------------------------

class TestRendimentoAnual:
    def test_rendimento_anual_tudo_100(self):
        """100% em todos → anual = 100%."""
        assert ar.calcular_rendimento_anual(100.0, 100.0, 100.0) == 100.0

    def test_rendimento_anual_tudo_zero(self):
        """0% em todos → anual = 0%."""
        assert ar.calcular_rendimento_anual(0.0, 0.0, 0.0) == 0.0

    def test_rendimento_anual_pesos_corretos(self):
        """Verifica que os pesos 30-30-40 são aplicados corretamente."""
        # T1=100%, T2=0%, T3=0% → anual = (100×30 + 0×30 + 0×40)/100 = 30%
        assert ar.calcular_rendimento_anual(100.0, 0.0, 0.0) == 30.0
        # T1=0%, T2=100%, T3=0% → anual = (0×30 + 100×30 + 0×40)/100 = 30%
        assert ar.calcular_rendimento_anual(0.0, 100.0, 0.0) == 30.0
        # T1=0%, T2=0%, T3=100% → anual = (0×30 + 0×30 + 100×40)/100 = 40%
        assert ar.calcular_rendimento_anual(0.0, 0.0, 100.0) == 40.0

    def test_rendimento_anual_t3_tem_peso_maior(self):
        """T3 pesa mais (40) que T1/T2 (30 cada)."""
        # Mesmo rendimento em todos: (60×30 + 60×30 + 60×40)/100 = 60.0
        assert ar.calcular_rendimento_anual(60.0, 60.0, 60.0) == 60.0

    def test_rendimento_anual_caso_realista(self):
        """
        Caso realista:
          T1 = 75%, T2 = 80%, T3 = 50%
          anual = (75×30 + 80×30 + 50×40)/100 = (2250 + 2400 + 2000)/100 = 66.5%
        """
        assert ar.calcular_rendimento_anual(75.0, 80.0, 50.0) == 66.5

    def test_rendimento_anual_nao_e_media_simples(self):
        """
        Verifica que NÃO é média simples:
          T1=90%, T2=90%, T3=30%
          Média simples: (90+90+30)/3 = 70%
          Ponderada: (90×30 + 90×30 + 30×40)/100 = (2700+2700+1200)/100 = 66%
        """
        anual = ar.calcular_rendimento_anual(90.0, 90.0, 30.0)
        assert anual == 66.0
        assert anual != 70.0  # NÃO é média simples!

    def test_rendimento_anual_rejeita_valores_negativos(self):
        with pytest.raises(ValueError, match="fora da faixa"):
            ar.calcular_rendimento_anual(-10.0, 80.0, 70.0)

    def test_rendimento_anual_rejeita_valores_acima_100(self):
        with pytest.raises(ValueError, match="fora da faixa"):
            ar.calcular_rendimento_anual(80.0, 110.0, 70.0)


# ---------------------------------------------------------------------------
# Regra 3: Recuperação final (rendimento anual < 60%)
# ---------------------------------------------------------------------------

class TestRecuperacaoFinal:
    def test_rendimento_anual_abaixo_60_gera_recuperacao_final(self):
        assert ar.verificar_recuperacao_final(59.9) is True

    def test_rendimento_anual_exatamente_60_nao_gera_recuperacao(self):
        assert ar.verificar_recuperacao_final(60.0) is False

    def test_rendimento_anual_acima_60_nao_gera_recuperacao(self):
        assert ar.verificar_recuperacao_final(75.0) is False

    def test_rendimento_anual_zero_gera_recuperacao(self):
        assert ar.verificar_recuperacao_final(0.0) is True

    def test_caso_limiar_ponderado(self):
        """
        T1=60%, T2=60%, T3=60% → anual = 60.0% → NÃO recuperação final.
        T1=60%, T2=60%, T3=59% → anual = 59.6% → recuperação final.
        """
        anual_ok = ar.calcular_rendimento_anual(60.0, 60.0, 60.0)
        assert ar.verificar_recuperacao_final(anual_ok) is False

        anual_baixo = ar.calcular_rendimento_anual(60.0, 60.0, 59.0)
        assert anual_baixo < 60.0
        assert ar.verificar_recuperacao_final(anual_baixo) is True


# ---------------------------------------------------------------------------
# Função completa: avaliar_recuperacao_completa
# ---------------------------------------------------------------------------

class TestAvaliarRecuperacaoCompleta:
    def test_aluno_aprovado_sem_recuperacao(self):
        """T1=20, T2=20, T3=30 → todos ≥ 60% → sem recuperação."""
        # T1: 20/30 = 66.7%, T2: 20/30 = 66.7%, T3: 30/40 = 75%
        res = ar.avaliar_recuperacao_completa(20.0, 20.0, 30.0)
        assert res.recuperacao_t1 is False
        assert res.recuperacao_t2 is False
        assert res.recuperacao_t3 is False
        assert res.recuperacao_final is False

    def test_aluno_com_recuperacao_t1_apenas(self):
        """T1 baixo, T2 e T3 bons."""
        # T1: 15/30 = 50% < 60% → recuperação T1
        # T2: 25/30 = 83.3% → OK
        # T3: 35/40 = 87.5% → OK
        res = ar.avaliar_recuperacao_completa(15.0, 25.0, 35.0)
        assert res.recuperacao_t1 is True
        assert res.recuperacao_t2 is False
        assert res.recuperacao_t3 is False

    def test_aluno_com_recuperacao_t1_e_t2(self):
        """T1 e T2 baixos."""
        # T1: 10/30 = 33.3%, T2: 12/30 = 40%
        res = ar.avaliar_recuperacao_completa(10.0, 12.0, 30.0)
        assert res.recuperacao_t1 is True
        assert res.recuperacao_t2 is True
        assert res.recuperacao_t3 is False

    def test_t3_nunca_tem_recuperacao_mesmo_com_0(self):
        """T3 com 0 pontos → NÃO tem recuperação trimestral."""
        res = ar.avaliar_recuperacao_completa(20.0, 20.0, 0.0)
        assert res.recuperacao_t3 is False

    def test_recuperacao_final_com_rendimento_anual_baixo(self):
        """Rendimento anual < 60% → recuperação final."""
        # T1: 10/30=33.3%, T2: 10/30=33.3%, T3: 10/40=25%
        # Anual: (33.3×30 + 33.3×30 + 25×40)/100 = (999+999+1000)/100 ≈ 30%
        res = ar.avaliar_recuperacao_completa(10.0, 10.0, 10.0)
        assert res.rendimento_anual < 60.0
        assert res.recuperacao_final is True

    def test_recuperacao_final_sem_recuperacao_trimestral(self):
        """
        É possível não ter recuperação trimestral mas ter recuperação final.
        Ex: T1=62%, T2=62%, T3=56% → todos ≥ 56% mas anual < 60%.
        """
        # T1: 18.6/30=62%, T2: 18.6/30=62%, T3: 22.4/40=56%
        # Anual: (62×30 + 62×30 + 56×40)/100 = (1860+1860+2240)/100 = 59.6%
        res = ar.avaliar_recuperacao_completa(18.6, 18.6, 22.4)
        assert res.recuperacao_t1 is False  # 62% ≥ 60%
        assert res.recuperacao_t2 is False  # 62% ≥ 60%
        assert res.recuperacao_t3 is False  # T3 nunca
        assert res.rendimento_anual < 60.0
        assert res.recuperacao_final is True

    def test_rendimentos_sao_percentuais_corretos(self):
        """Verifica que os percentuais estão corretos no resultado."""
        res = ar.avaliar_recuperacao_completa(18.0, 24.0, 32.0)
        assert res.rendimento_t1 == 60.0   # 18/30 = 60%
        assert res.rendimento_t2 == 80.0   # 24/30 = 80%
        assert res.rendimento_t3 == 80.0   # 32/40 = 80%


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

class TestConstantes:
    def test_limiar_recuperacao(self):
        assert ar.LIMIAR_RECUPERACAO == 60.0

    def test_pesos_trimestrais_somam_100(self):
        total = sum(ar.PESOS_TRIMESTRAIS_ANUAIS.values())
        assert total == 100.0

    def test_trimestres_com_recuperacao(self):
        assert "t1" in ar.TRIMESTRES_COM_RECUPERACAO
        assert "t2" in ar.TRIMESTRES_COM_RECUPERACAO
        assert "t3" not in ar.TRIMESTRES_COM_RECUPERACAO


# ---------------------------------------------------------------------------
# Integração: transformador com recuperação
# ---------------------------------------------------------------------------

class TestTransformadorRecuperacao:
    def test_recuperacao_t1_preservada_como_pronto(self):
        """Nota de recuperação no T1 → status pronto com motivo confirmado."""
        row = {
            "Estudante": "Aluno Rec",
            "RA": "RA100",
            "Turma": "1A",
            "Trimestre": "1",
            "Disciplina": "Matemática",
            "Frente - Professor": "",
            "Recuperação": "7.5",
            "AV 1 (OBJ)": "3",
            "AV 1 (DISC)": "2",
        }
        lancs = linha_madan_para_lancamentos(row, linha_origem=1)
        rec = [l for l in lancs if l["componente"] == "recuperacao"]
        assert len(rec) == 1
        assert rec[0]["status"] == "pronto"
        assert rec[0]["nota_ajustada_0a10"] == 7.5
        assert "confirmada" in rec[0]["motivo_status"]

    def test_recuperacao_t3_ignorada(self):
        """Nota de recuperação no T3 → ignorada (regra 2: T3 não tem rec trimestral)."""
        row = {
            "Estudante": "Aluno T3",
            "RA": "RA200",
            "Turma": "2B",
            "Trimestre": "3",
            "Disciplina": "Física",
            "Frente - Professor": "",
            "Recuperação": "8.0",
            "AV 1 (OBJ)": "3",
            "AV 1 (DISC)": "4",
        }
        lancs = linha_madan_para_lancamentos(row, linha_origem=2)
        rec = [l for l in lancs if l["componente"] == "recuperacao"]
        assert len(rec) == 1
        assert rec[0]["status"] == "ignorado"
        assert "t3" in rec[0]["motivo_status"].lower()

    def test_sem_recuperacao_nao_gera_lancamento_rec(self):
        """Sem nota de recuperação na planilha → nenhum lançamento de recuperação."""
        row = {
            "Estudante": "Aluno OK",
            "RA": "RA300",
            "Turma": "1A",
            "Trimestre": "1",
            "Disciplina": "História",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISC)": "5",
        }
        lancs = linha_madan_para_lancamentos(row, linha_origem=3)
        rec = [l for l in lancs if l["componente"] == "recuperacao"]
        assert rec == []
