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

from transformador import linha_madan_para_lancamentos
from validacao_pre_envio import validar_pre_envio_linha


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
        "AV 1 (OBJ)": "8,0",
        "AV 1 (DISÇ)": "9",
        "AV 2 (OBJ)": "6",
        "AV 2 (DISÇ)": "8",
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
        "AV 1 (OBJ)": "8",
        "AV 1 (DISÇ)": "8",
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
        "AV 1 (OBJ)": "8",
        "AV 1 (DISÇ)": "8",
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
        "Turma": "T3",
        "AV 1 (OBJ)": "12",   # inválido
        "AV 1 (DISÇ)": "8",
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
        "AV 1 (OBJ)": "8",
        "AV 1 (DISÇ)": "8",
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
        "AV 1 (OBJ)": "8",
        "AV 1 (DISÇ)": "8",
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
        "AV 1 (OBJ)": "8",
        "AV 1 (DISÇ)": "8",
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
        "AV 1 (OBJ)": "10",
        "AV 1 (DISÇ)": "10",
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
        "AV 1 (OBJ)": "10",
        "AV 1 (DISÇ)": "10",
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
        "AV 1 (OBJ)": "7",
        "AV 1 (DISÇ)": "7",
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