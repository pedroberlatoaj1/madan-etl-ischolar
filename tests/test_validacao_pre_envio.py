"""
test_validacao_pre_envio.py  (patch corretivo — Etapa 3)

Semântica adotada (definitiva):
  - "bloqueado_por_erros"  : qualquer erro em lançamento, erro de linha,
                             ou pendência com bloqueante=True
  - "apto_com_avisos"      : avisos e/ou pendências não-bloqueantes, sem erros
  - "apto_para_aprovacao"  : inalcançável nesta etapa — IDENTIFICADOR_ISCHOLAR_PENDENTE
                             é sempre inserido com bloqueante=False, o que mantém o
                             status em "apto_com_avisos" no melhor caso

Cobertura:
  - caso limpo → "apto_com_avisos" (melhor resultado possível na Etapa 3)
  - IDENTIFICADOR_ISCHOLAR_PENDENTE não bloqueia (bloqueante=False) mas rebaixa
    de "apto_para_aprovacao" para "apto_com_avisos"
  - duplicidade sendável → erro bloqueante (DUPLICIDADE_SENDAVEL)
  - duplicidade não-sendável → aviso (DUPLICIDADE_INTERNA), não bloqueia
  - campo obrigatório ausente, nota fora de faixa, estudante ausente → bloqueiam
  - divergência de total → aviso; ausência de coluna de conferência → "ausente"
"""

import pytest

from avaliacao_rules import StatusLancamento
from transformador import linha_madan_para_lancamentos
from validacao_pre_envio import _is_sendavel, validar_pre_envio_linha


def _row_com_frente_professor(
    frente_professor: str,
    *,
    disciplina: str,
    turma: str,
    estudante: str = "Aluno Regressao",
) -> dict[str, str]:
    return {
        "Estudante": estudante,
        "Trimestre": "1",
        "Disciplina": disciplina,
        "Frente - Professor": frente_professor,
        "Turma": turma,
        "AV 1 (OBJ)": "4",
        "AV 1 (DISÇ)": "4",
    }


def _validar_com_frente_professor(
    frente_professor: str,
    *,
    disciplina: str,
    turma: str,
    linha_origem: int = 200,
) -> dict[str, object]:
    row = _row_com_frente_professor(
        frente_professor,
        disciplina=disciplina,
        turma=turma,
    )
    lancs = linha_madan_para_lancamentos(row, linha_origem=linha_origem)
    return validar_pre_envio_linha(row_wide=row, lancamentos=lancs)


# ---------------------------------------------------------------------------
# Caso válido — comportamento esperado após o patch
# ---------------------------------------------------------------------------

def test_validacao_caso_valido_pendencia_identificador_nao_bloqueia():
    """
    Linha com notas válidas e coluna de conferência (pode divergir).
    Após o patch, IDENTIFICADOR_ISCHOLAR_PENDENTE NÃO degrada para
    "bloqueado_por_erros" por si só.  O status deve ser apto_* (não bloqueado).
    """
    row = {
        "Estudante": "Aluno 1",
        "Trimestre": "1",
        "Disciplina": "Matemática",
        "Frente - Professor": "Frente X - Prof Y",
        "Turma": "T1",
        "AV 1 (OBJ)": "4,0",
        "AV 1 (DISÇ)": "5",
        "AV 2 (OBJ)": "3",
        "AV 2 (DISÇ)": "4",
        "AV 3 (listas)": "7",
        "AV 3 (avaliação)": "6",
        "Simulado": "10",
        "Ponto extra": "1",
        "Nota com a AV 3": "23,58",   # conferência; pode divergir
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=2)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs, tolerancia_total=0.05)

    # Não pode ser "bloqueado" por causa exclusiva do identificador pendente.
    # "apto_para_aprovacao" é inalcançável nesta etapa (pendência sempre presente);
    # o único valor esperado aqui é "apto_com_avisos".
    assert res["status_geral"] == "apto_com_avisos", (
        f"status inesperado: {res['status_geral']}"
    )
    # Pendência de identificador continua auditável.
    assert any(
        p["code"] == "IDENTIFICADOR_ISCHOLAR_PENDENTE" for p in res["pendencias"]
    )
    # Campo de comparação deve estar presente.
    assert "comparacoes_totais" in res

    # A pendência de identificador NÃO deve ser bloqueante.
    id_pend = next(
        p for p in res["pendencias"] if p["code"] == "IDENTIFICADOR_ISCHOLAR_PENDENTE"
    )
    assert id_pend["bloqueante"] is False


# ---------------------------------------------------------------------------
# Caso limpo → apto_com_avisos
# (apto_para_aprovacao é estruturalmente inalcançável nesta etapa porque
#  IDENTIFICADOR_ISCHOLAR_PENDENTE é sempre inserido; a semântica adotada é:
#  pendência não-bloqueante → apto_com_avisos, nunca bloqueia nem aprova cegamente)
# ---------------------------------------------------------------------------

def test_validacao_caso_limpo_resulta_em_apto_com_avisos():
    """
    Linha sem erros, sem avisos reais e sem colunas de conferência.
    A pendência IDENTIFICADOR_ISCHOLAR_PENDENTE (não-bloqueante) é sempre
    adicionada, o que torna "apto_para_aprovacao" inalcançável nesta etapa.
    O resultado esperado é "apto_com_avisos":
      - sem erros (lancamentos_com_erro vazio)
      - sem avisos de negócio (avisos vazio)
      - pendência auditável presente com bloqueante=False
    """
    row = {
        "Estudante": "Aluno Limpo",
        "Trimestre": "1",
        "Disciplina": "Física",
        "Turma": "T8",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISÇ)": "4",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=99)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs, tolerancia_total=0.05)

    assert res["status_geral"] == "apto_com_avisos", (
        f"Esperado 'apto_com_avisos', obtido '{res['status_geral']}'. "
        f"Erros: {res['lancamentos_com_erro']}  Avisos: {res['avisos']}"
    )
    assert res["lancamentos_com_erro"] == []
    assert res["avisos"] == []
    # Pendência não-bloqueante presente para auditoria.
    assert any(p["code"] == "IDENTIFICADOR_ISCHOLAR_PENDENTE" for p in res["pendencias"])


# ---------------------------------------------------------------------------
# Campo obrigatório ausente bloqueia
# ---------------------------------------------------------------------------

def test_validacao_campo_obrigatorio_ausente_bloqueia():
    row = {
        "Estudante": "Aluno 2",
        "Trimestre": "1",
        "Disciplina": "Química",
        "Turma": "T2",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISÇ)": "4",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=None)  # linha_origem ausente
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs)

    assert res["status_geral"] == "bloqueado_por_erros"
    assert any(
        e["code"] == "CAMPO_OBRIGATORIO_AUSENTE"
        and e.get("details", {}).get("campo") == "linha_origem"
        for l in res["lancamentos_com_erro"]
        for e in l["validacao_erros"]
    )


# ---------------------------------------------------------------------------
# Nota fora da faixa bloqueia
# ---------------------------------------------------------------------------

def test_validacao_nota_fora_da_faixa_detecta():
    row = {
        "Estudante": "Aluno 3",
        "Trimestre": "1",
        "Disciplina": "Bio",
        "Turma": "2A",
        "AV 1 (OBJ)": "12",   # inválido
        "AV 1 (DISÇ)": "4",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=1)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs)

    assert res["status_geral"] == "bloqueado_por_erros"
    assert any(l["validacao_erros"] for l in res["lancamentos_com_erro"])


# ---------------------------------------------------------------------------
# Duplicidade — não-sendável: aviso (não bloqueia)
# ---------------------------------------------------------------------------

def test_validacao_duplicidade_nao_sendavel_avisa_sem_bloquear():
    """
    Duplicar um lançamento não-sendável (subcomponente) deve gerar aviso
    e manter todos os lançamentos na saída, mas NÃO bloquear o status.
    """
    row = {
        "Estudante": "Aluno 4",
        "Trimestre": "1",
        "Disciplina": "Hist",
        "Turma": "T4",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISÇ)": "4",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=10)

    # Pega o primeiro lançamento não-sendável para duplicar.
    nao_sendaveis = [
        l for l in lancs
        if l.get("subcomponente") is not None or l.get("status") != "pronto"
    ]
    if not nao_sendaveis:
        pytest.skip("Nenhum lançamento não-sendável produzido para este row")

    lancs_dup = lancs + [nao_sendaveis[0]]
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs_dup)

    # Duplicidade detectada e registrada.
    assert res["duplicidades"]
    # Lançamentos preservados (não removidos).
    assert len(res["lancamentos_validos"]) + len(res["lancamentos_com_erro"]) == len(lancs_dup)
    # Status NÃO deve ser "bloqueado" somente por duplicidade não-sendável.
    assert res["status_geral"] != "bloqueado_por_erros", (
        "Duplicidade não-sendável não deveria bloquear"
    )
    # Aviso DUPLICIDADE_INTERNA presente.
    assert any(a["code"] == "DUPLICIDADE_INTERNA" for a in res["avisos"])


# ---------------------------------------------------------------------------
# Duplicidade — sendável: bloqueia
# ---------------------------------------------------------------------------

def test_duplicidade_sendavel_bloqueia():
    """
    Duplicar um lançamento sendável (consolidado pronto) deve:
      - registrar em res["duplicidades"]
      - marcar como erro no lançamento duplicado
      - resultar em status_geral == "bloqueado_por_erros"
      - preservar todos os lançamentos (não remove)
    """
    row = {
        "Estudante": "Aluno Dup",
        "Trimestre": "1",
        "Disciplina": "Física",
        "Turma": "T10",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISÇ)": "4",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=20)

    # Duplica todos: garante que o consolidado sendável seja duplicado.
    lancs_dup = lancs + lancs
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs_dup)

    assert res["duplicidades"], "Nenhuma duplicidade detectada"
    assert res["status_geral"] == "bloqueado_por_erros", (
        f"Duplicidade sendável deve bloquear; status obtido: {res['status_geral']}"
    )
    # Pelo menos um lançamento deve ter erro DUPLICIDADE_SENDAVEL.
    assert any(
        e["code"] == "DUPLICIDADE_SENDAVEL"
        for l in res["lancamentos_com_erro"]
        for e in l["validacao_erros"]
    )
    # Preservação: total deve bater.
    assert (
        len(res["lancamentos_validos"]) + len(res["lancamentos_com_erro"]) == len(lancs_dup)
    )


# ---------------------------------------------------------------------------
# Estudante ausente bloqueia
# ---------------------------------------------------------------------------

def test_validacao_estudante_ausente_bloqueia():
    row = {
        "Estudante": "",
        "Trimestre": "1",
        "Disciplina": "Geo",
        "Turma": "T5",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISÇ)": "4",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=2)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs)

    assert res["status_geral"] == "bloqueado_por_erros"
    assert any(
        e["code"] == "CAMPO_OBRIGATORIO_AUSENTE"
        and e.get("details", {}).get("campo") == "estudante"
        for l in res["lancamentos_com_erro"]
        for e in l["validacao_erros"]
    )


# ---------------------------------------------------------------------------
# Divergência de total gera aviso
# ---------------------------------------------------------------------------

def test_comparacao_total_divergente_gera_aviso():
    row = {
        "Estudante": "Aluno 6",
        "Trimestre": "1",
        "Disciplina": "Mat",
        "Turma": "T6",
        "AV 1 (OBJ)": "5",
        "AV 1 (DISÇ)": "5",
        "Simulado": "10",
        "Nota Final": "0",   # divergente de propósito
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=5)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs, tolerancia_total=0.01)

    assert any(a["code"] == "TOTAL_DIVERGENTE" for a in res["avisos"])


# ---------------------------------------------------------------------------
# Coluna de conferência ausente → resultado "ausente" (não é erro)
# ---------------------------------------------------------------------------

def test_comparacao_total_ausente_nao_gera_erro():
    row = {
        "Estudante": "Aluno 7",
        "Trimestre": "1",
        "Disciplina": "Mat",
        "Turma": "T7",
        "AV 1 (OBJ)": "5",
        "AV 1 (DISÇ)": "5",
        "Simulado": "10",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=6)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs, tolerancia_total=0.05)

    # Campos de conferência ausentes → resultado "ausente" (nunca erro/aviso).
    assert any(c["resultado"] == "ausente" for c in res["comparacoes_totais"])


# ---------------------------------------------------------------------------
# Invariante: pendência IDENTIFICADOR_ISCHOLAR_PENDENTE nunca é bloqueante
# ---------------------------------------------------------------------------

def test_identificador_pendente_nao_e_bloqueante():
    """
    Garante que o campo 'bloqueante' da pendência de identificador é False,
    independentemente do conteúdo da linha.
    """
    row = {
        "Estudante": "Aluno 9",
        "Trimestre": "2",
        "Disciplina": "Arte",
        "Turma": "T9",
        "AV 1 (OBJ)": "3",
        "AV 1 (DISÇ)": "4",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=50)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs)

    pend = next(
        (p for p in res["pendencias"] if p["code"] == "IDENTIFICADOR_ISCHOLAR_PENDENTE"),
        None,
    )
    assert pend is not None, "Pendência IDENTIFICADOR_ISCHOLAR_PENDENTE não encontrada"
    assert pend["bloqueante"] is False, (
        "IDENTIFICADOR_ISCHOLAR_PENDENTE deve ter bloqueante=False"
    )


# ---------------------------------------------------------------------------
# Regressao: aliases de disciplina/frente nao devem gerar warning falso
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("frente_professor", "disciplina", "turma"),
    [
        ("arte", "Arte", "1A"),
        ("biologia", "Biologia", "1A"),
        ("fisica a", "Fisica", "1A"),
        ("fisica b", "Fisica", "1B"),
        ("fisica c", "Fisica", "1C"),
    ],
)
def test_alias_disciplina_frente_nao_gera_professor_nao_encontrado(
    frente_professor: str,
    disciplina: str,
    turma: str,
):
    res = _validar_com_frente_professor(
        frente_professor,
        disciplina=disciplina,
        turma=turma,
    )

    assert not any(
        aviso["code"] == "PROFESSOR_NAO_ENCONTRADO_REGISTRO"
        for aviso in res["avisos"]
    ), f"Alias '{frente_professor}' gerou warning falso: {res['avisos']}"


# ---------------------------------------------------------------------------
# Regressao: nomes explicitos e apelidos continuam no caminho normal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("frente_professor", "disciplina", "turma"),
    [
        ("arte - lenice", "Arte", "1A"),
        ("fisica - cavaco", "Fisica", "1A"),
        ("cavaco", "Fisica", "1A"),
    ],
)
def test_nome_explicito_ou_apelido_valido_nao_e_suprimido_nem_gera_warning_falso(
    frente_professor: str,
    disciplina: str,
    turma: str,
):
    res = _validar_com_frente_professor(
        frente_professor,
        disciplina=disciplina,
        turma=turma,
    )

    assert not any(
        aviso["code"] == "PROFESSOR_NAO_ENCONTRADO_REGISTRO"
        for aviso in res["avisos"]
    ), f"Professor valido '{frente_professor}' deveria passar pelo lookup normal sem warning falso."
    assert not any(
        aviso["code"] == "PROFESSOR_DISCIPLINA_TURMA_INCOMPATIVEL"
        for aviso in res["avisos"]
    ), f"Professor valido '{frente_professor}' foi tratado como incompatível: {res['avisos']}"


@pytest.mark.parametrize(
    ("frente_professor", "disciplina", "turma"),
    [
        ("matematica a - daniel", "Matematica", "2A"),
        ("biologia a - perrone", "Biologia", "2A"),
        ("geografia a - carla", "Geografia", "2A"),
        ("redacao - sergio", "Redacao", "2A"),
    ],
)
def test_alias_explicito_2o_ano_nao_gera_warning_falso(
    frente_professor: str,
    disciplina: str,
    turma: str,
):
    res = _validar_com_frente_professor(
        frente_professor,
        disciplina=disciplina,
        turma=turma,
    )

    assert not any(
        aviso["code"] == "PROFESSOR_NAO_ENCONTRADO_REGISTRO"
        for aviso in res["avisos"]
    ), f"Alias explicito '{frente_professor}' gerou warning de lookup: {res['avisos']}"
    assert not any(
        aviso["code"] == "PROFESSOR_DISCIPLINA_TURMA_INCOMPATIVEL"
        for aviso in res["avisos"]
    ), f"Alias explicito '{frente_professor}' foi tratado como incompatível: {res['avisos']}"


# ---------------------------------------------------------------------------
# Regressao: nome explicito invalido continua gerando warning legitimo
# ---------------------------------------------------------------------------

def test_nome_explicito_invalido_continua_gerando_warning_legitimo():
    res = _validar_com_frente_professor(
        "fisica - professorinexistente",
        disciplina="Fisica",
        turma="1A",
    )

    avisos_nao_encontrado = [
        aviso for aviso in res["avisos"]
        if aviso["code"] == "PROFESSOR_NAO_ENCONTRADO_REGISTRO"
    ]
    assert avisos_nao_encontrado, "Nome explicito invalido deveria continuar gerando warning legitimo."
    assert any(
        "professorinexistente" in str(aviso.get("details", {}).get("nome_extraido", "")).lower()
        for aviso in avisos_nao_encontrado
    )


def test_is_sendavel_recuperacao_pronto_sem_peso_e_valor_ponderado():
    lancamento = {
        "status": StatusLancamento.PRONTO,
        "subcomponente": None,
        "componente": "recuperacao",
        "nota_ajustada_0a10": 7.5,
        "peso_avaliacao": None,
        "valor_ponderado": None,
    }

    assert _is_sendavel(lancamento) is True


def test_is_sendavel_recuperacao_pronto_sem_nota_retorna_false():
    lancamento = {
        "status": StatusLancamento.PRONTO,
        "subcomponente": None,
        "componente": "recuperacao",
        "nota_ajustada_0a10": None,
        "peso_avaliacao": None,
        "valor_ponderado": None,
    }

    assert _is_sendavel(lancamento) is False


def test_is_sendavel_recuperacao_ignorada_retorna_false():
    lancamento = {
        "status": StatusLancamento.IGNORADO,
        "subcomponente": None,
        "componente": "recuperacao",
        "nota_ajustada_0a10": 6.0,
        "peso_avaliacao": None,
        "valor_ponderado": None,
    }

    assert _is_sendavel(lancamento) is False


def test_is_sendavel_recuperacao_final_pronto_sem_peso_e_valor_ponderado():
    lancamento = {
        "status": StatusLancamento.PRONTO,
        "subcomponente": None,
        "componente": "recuperacao_final",
        "nota_ajustada_0a10": 6.0,
        "peso_avaliacao": None,
        "valor_ponderado": None,
    }

    assert _is_sendavel(lancamento) is True


def test_is_sendavel_recuperacao_final_pronto_sem_nota_retorna_false():
    lancamento = {
        "status": StatusLancamento.PRONTO,
        "subcomponente": None,
        "componente": "recuperacao_final",
        "nota_ajustada_0a10": None,
        "peso_avaliacao": None,
        "valor_ponderado": None,
    }

    assert _is_sendavel(lancamento) is False


@pytest.mark.parametrize("componente", ["av1", "av2", "av3", "simulado"])
@pytest.mark.parametrize(
    ("peso_avaliacao", "valor_ponderado"),
    [
        (None, 7.5),
        (12.0, None),
    ],
)
def test_is_sendavel_componentes_ponderados_continuam_exigindo_peso_e_valor(
    componente: str,
    peso_avaliacao: float | None,
    valor_ponderado: float | None,
):
    lancamento = {
        "status": StatusLancamento.PRONTO,
        "subcomponente": None,
        "componente": componente,
        "nota_ajustada_0a10": 7.5,
        "peso_avaliacao": peso_avaliacao,
        "valor_ponderado": valor_ponderado,
    }

    assert _is_sendavel(lancamento) is False


def test_validacao_pre_envio_aceita_recuperacao_sem_peso_e_valor_ponderado():
    row = {
        "Estudante": "Aluno Recuperacao",
        "Trimestre": "1",
        "Disciplina": "Arte",
        "Frente - Professor": "Frente Única",
        "Turma": "2B",
        "Recuperação": "10",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=49)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs)

    assert res["status_geral"] == "apto_com_avisos"
    assert res["lancamentos_com_erro"] == []
    rec = next(l for l in res["lancamentos_validos"] if l["componente"] == "recuperacao")
    assert rec["sendavel"] is True


def test_validacao_pre_envio_aceita_recuperacao_final_sem_peso_e_valor_ponderado():
    row = {
        "Estudante": "Aluno Recuperacao Final",
        "Trimestre": "T3",
        "Disciplina": "Arte",
        "Frente - Professor": "Frente Única",
        "Turma": "2B",
        "Recuperação Final": "6",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=50)
    res = validar_pre_envio_linha(row_wide=row, lancamentos=lancs)

    assert res["status_geral"] == "apto_com_avisos"
    assert res["lancamentos_com_erro"] == []
    rec_final = next(
        l for l in res["lancamentos_validos"] if l["componente"] == "recuperacao_final"
    )
    assert rec_final["sendavel"] is True


def test_constante_componentes_ponderacao_consistente():
    from validacao_pre_envio import COMPONENTES_QUE_EXIGEM_PONDERACAO_LOCAL

    assert "av1" in COMPONENTES_QUE_EXIGEM_PONDERACAO_LOCAL
    assert "recuperacao" not in COMPONENTES_QUE_EXIGEM_PONDERACAO_LOCAL
