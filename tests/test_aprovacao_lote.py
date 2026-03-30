"""
test_aprovacao_lote.py  (patch cirúrgico — Etapa 4)

Testes organizados em dois blocos:

A) Testes originais — comportamento preservado.
   Ajuste mínimo: snapshot_resumo_aprovado antes da aprovação é calculado
   sobre resumo_atual, que agora é deepcopy de resumo.__dict__.
   O campo `hash_resumo_aprovado` é novo; os testes originais ignoram-no
   ou verificam sua presença explicitamente onde faz sentido.

B) Testes novos do patch:
   - elegibilidade endurecida (total_erros, total_bloqueados)
   - persistência SQLite em banco :memory: (sobrevive a reinício simulado)
   - integridade do snapshot via hash
   - verificar_integridade_snapshot detecta adulteração
"""

import pytest

from aprovacao_lote import (
    EstadoAprovacaoLote,
    aprovar_lote,
    carregar_estado_lote,
    criar_estado_lote,
    gerar_resumo_lote,
    rejeitar_lote,
    verificar_integridade_snapshot,
)
from aprovacao_lote_store import AprovacaoLoteStore
from transformador import linha_madan_para_lancamentos
from validacao_pre_envio import validar_pre_envio_linha


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validar_lote(rows):
    resultados = []
    for i, row in enumerate(rows, start=1):
        lancs = linha_madan_para_lancamentos(row, linha_origem=i)
        resultados.append(validar_pre_envio_linha(row_wide=row, lancamentos=lancs))
    return resultados


def _store_mem() -> AprovacaoLoteStore:
    """Store em memória — isolado por teste, não polui disco."""
    return AprovacaoLoteStore(":memory:")


# ---------------------------------------------------------------------------
# A) Testes originais (comportamento preservado)
# ---------------------------------------------------------------------------

def test_lote_bloqueado_nao_pode_aprovar():
    rows = [
        {
            "Estudante": "Aluno 1",
            "Trimestre": "1",
            "Disciplina": "Mat",
            "Turma": "T1",
            "AV 1 (OBJ)": "12",  # inválido -> erro_validacao
            "AV 1 (DISÇ)": "8",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="l1", resumo=resumo)

    assert estado.status == "aguardando_aprovacao"
    assert estado.elegivel_para_aprovacao is False

    with pytest.raises(ValueError, match="não é elegível"):
        aprovar_lote(estado, aprovado_por="operador")


def test_lote_elegivel_ainda_fica_aguardando_sem_aprovar_automatico():
    rows = [
        {
            "Estudante": "Aluno 2",
            "Trimestre": "1",
            "Disciplina": "Mat",
            "Turma": "T2",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "4",
            "Simulado": "10",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="l2", resumo=resumo)

    assert estado.status == "aguardando_aprovacao"
    assert estado.elegivel_para_aprovacao is True


def test_aprovacao_explicita_registra_aprovador_timestamp_e_snapshot():
    rows = [
        {
            "Estudante": "Aluno 3",
            "Trimestre": "1",
            "Disciplina": "Mat",
            "Turma": "2A",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "5",
            "Ponto extra": "1",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="l3", resumo=resumo)

    snap_before = dict(estado.resumo_atual)
    aprovar_lote(estado, aprovado_por="admin")

    assert estado.status == "aprovado_para_envio"
    assert estado.aprovado_por == "admin"
    assert estado.aprovado_em is not None
    assert estado.snapshot_resumo_aprovado == snap_before

    # Snapshot é congelado: mutar resumo_atual não altera snapshot.
    estado.resumo_atual["total_linhas"] = 999
    assert estado.snapshot_resumo_aprovado["total_linhas"] == snap_before["total_linhas"]


def test_rejeicao_registra_rejeitador_timestamp_motivo():
    rows = [
        {
            "Estudante": "Aluno 4",
            "Trimestre": "1",
            "Disciplina": "Hist",
            "Turma": "T4",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "4",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="l4", resumo=resumo)

    rejeitar_lote(estado, rejeitado_por="operador", motivo="Arquivo incorreto")
    assert estado.status == "rejeitado"
    assert estado.rejeitado_por == "operador"
    assert estado.rejeitado_em is not None
    assert estado.motivo_rejeicao == "Arquivo incorreto"


def test_resumo_lote_consolida_contagens_basicas():
    rows = [
        {
            "Estudante": "Aluno 5",
            "Trimestre": "1",
            "Disciplina": "Mat",
            "Turma": "T5",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "4",
            "Simulado": "10",
        },
        {
            "Estudante": "Aluno 6",
            "Trimestre": "1",
            "Disciplina": "Fis",
            "Turma": "T5",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "5",
        },
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)

    assert resumo.total_linhas == 2
    assert resumo.total_alunos == 2
    assert resumo.total_disciplinas == 2
    assert resumo.total_lancamentos > 0
    assert resumo.status_sugerido in {"aguardando_aprovacao", "bloqueado_por_erros"}


# ---------------------------------------------------------------------------
# B1) Elegibilidade endurecida
# ---------------------------------------------------------------------------

def test_elegibilidade_total_erros_impede_aprovacao():
    """
    Lote com total_erros > 0 deve ser inelegível, independentemente de
    como status_sugerido for derivado.
    AV1(OBJ)=12 → nota fora de faixa → lançamento com erro → total_erros > 0.
    """
    rows = [
        {
            "Estudante": "Aluno Err",
            "Trimestre": "1",
            "Disciplina": "Quim",
            "Turma": "TE1",
            "AV 1 (OBJ)": "12",   # inválido
            "AV 1 (DISÇ)": "8",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)

    assert resumo.total_erros > 0, "Pré-condição: deve haver erros"

    estado = criar_estado_lote(lote_id="le1", resumo=resumo)
    assert estado.elegivel_para_aprovacao is False

    with pytest.raises(ValueError, match="não é elegível"):
        aprovar_lote(estado, aprovado_por="operador")


def test_elegibilidade_total_bloqueados_impede_aprovacao():
    """
    Lote com total_bloqueados > 0 (lançamento sendável com erro de validação)
    deve ser inelegível.
    """
    rows = [
        {
            "Estudante": "Aluno Blk",
            "Trimestre": "1",
            "Disciplina": "Bio",
            "Turma": "TB1",
            "AV 1 (OBJ)": "12",   # lançamento consolidado sendável com nota inválida
            "AV 1 (DISÇ)": "8",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)

    assert resumo.total_bloqueados > 0 or resumo.total_erros > 0, (
        "Pré-condição: deve haver bloqueio ou erro no lançamento sendável"
    )

    estado = criar_estado_lote(lote_id="lb1", resumo=resumo)
    assert estado.elegivel_para_aprovacao is False


def test_elegibilidade_lote_limpo_e_elegivel():
    """
    Lote sem erros, sem bloqueados e sem linhas bloqueadas deve ser elegível.
    total_erros == 0 e total_bloqueados == 0.
    """
    rows = [
        {
            "Estudante": "Aluno Ok",
            "Trimestre": "1",
            "Disciplina": "Arte",
            "Turma": "TOk",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "4",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)

    assert resumo.total_erros == 0
    assert resumo.total_bloqueados == 0
    assert resumo.status_sugerido != "bloqueado_por_erros"

    estado = criar_estado_lote(lote_id="lok", resumo=resumo)
    assert estado.elegivel_para_aprovacao is True


# ---------------------------------------------------------------------------
# B2) Persistência SQLite
# ---------------------------------------------------------------------------

def test_persistencia_criar_e_carregar():
    """
    criar_estado_lote com store persiste; carregar_estado_lote recupera
    o mesmo estado (simula reinício de processo).
    """
    store = _store_mem()
    rows = [
        {
            "Estudante": "Aluno P1",
            "Trimestre": "1",
            "Disciplina": "Mat",
            "Turma": "TP1",
            "AV 1 (OBJ)": "3",
            "AV 1 (DISÇ)": "4",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="persist-1", resumo=resumo, store=store)

    # Simula reinício: lê do banco sem referência ao objeto original.
    recuperado = carregar_estado_lote("persist-1", store)

    assert recuperado.lote_id == "persist-1"
    assert recuperado.status == "aguardando_aprovacao"
    assert recuperado.elegivel_para_aprovacao == estado.elegivel_para_aprovacao
    assert recuperado.resumo_atual["total_linhas"] == 1


def test_persistencia_aprovacao_sobrevive_releitura():
    """
    Após aprovar_lote com store, carregar_estado_lote retorna o estado
    aprovado completo: aprovado_por, aprovado_em, snapshot e hash.
    """
    store = _store_mem()
    rows = [
        {
            "Estudante": "Aluno P2",
            "Trimestre": "1",
            "Disciplina": "Fis",
            "Turma": "TP2",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "5",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="persist-2", resumo=resumo, store=store)
    aprovar_lote(estado, aprovado_por="gestor", store=store)

    # "Reinício" — lê do banco.
    recuperado = carregar_estado_lote("persist-2", store)

    assert recuperado.status == "aprovado_para_envio"
    assert recuperado.aprovado_por == "gestor"
    assert recuperado.aprovado_em is not None
    assert recuperado.snapshot_resumo_aprovado is not None
    assert recuperado.hash_resumo_aprovado is not None


def test_persistencia_rejeicao_sobrevive_releitura():
    """
    Após rejeitar_lote com store, carregar_estado_lote retorna estado
    rejeitado com todos os campos preenchidos.
    """
    store = _store_mem()
    rows = [
        {
            "Estudante": "Aluno P3",
            "Trimestre": "1",
            "Disciplina": "Quim",
            "Turma": "TP2",
            "AV 1 (OBJ)": "3",
            "AV 1 (DISÇ)": "3",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="persist-3", resumo=resumo, store=store)
    rejeitar_lote(estado, rejeitado_por="supervisor", motivo="Dados inconsistentes", store=store)

    recuperado = carregar_estado_lote("persist-3", store)

    assert recuperado.status == "rejeitado"
    assert recuperado.rejeitado_por == "supervisor"
    assert recuperado.motivo_rejeicao == "Dados inconsistentes"
    assert recuperado.rejeitado_em is not None


def test_persistencia_lote_inexistente_lanca_keyerror():
    store = _store_mem()
    with pytest.raises(KeyError, match="nao-existe"):
        carregar_estado_lote("nao-existe", store)


def test_persistencia_listar_ids():
    store = _store_mem()
    rows = [
        {"Estudante": "A", "Trimestre": "1", "Disciplina": "X", "Turma": "T",
         "AV 1 (OBJ)": "5", "AV 1 (DISÇ)": "5"},
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    criar_estado_lote(lote_id="lista-a", resumo=resumo, store=store)
    criar_estado_lote(lote_id="lista-b", resumo=resumo, store=store)

    ids = store.listar_ids()
    assert "lista-a" in ids
    assert "lista-b" in ids


# ---------------------------------------------------------------------------
# B3) Integridade do snapshot
# ---------------------------------------------------------------------------

def test_snapshot_hash_e_gerado_na_aprovacao():
    """
    Após aprovar_lote, hash_resumo_aprovado deve estar presente e ser
    uma string hexadecimal SHA-256 (64 chars).
    """
    rows = [
        {
            "Estudante": "Aluno H1",
            "Trimestre": "1",
            "Disciplina": "Geo",
            "Turma": "TH1",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "4",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="hash-1", resumo=resumo)

    assert estado.hash_resumo_aprovado is None  # antes da aprovação

    aprovar_lote(estado, aprovado_por="auditor")

    assert estado.hash_resumo_aprovado is not None
    assert len(estado.hash_resumo_aprovado) == 64   # SHA-256 hex
    assert estado.hash_resumo_aprovado.isalnum()


def test_verificar_integridade_snapshot_ok():
    """
    verificar_integridade_snapshot retorna True para snapshot íntegro.
    """
    rows = [
        {
            "Estudante": "Aluno H2",
            "Trimestre": "1",
            "Disciplina": "Bio",
            "Turma": "TH2",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "5",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="hash-2", resumo=resumo)
    aprovar_lote(estado, aprovado_por="auditor")

    assert verificar_integridade_snapshot(estado) is True


def test_verificar_integridade_snapshot_detecta_adulteracao():
    """
    verificar_integridade_snapshot retorna False se snapshot_resumo_aprovado
    for adulterado após a aprovação.
    """
    rows = [
        {
            "Estudante": "Aluno H3",
            "Trimestre": "1",
            "Disciplina": "Fis",
            "Turma": "TH2",
            "AV 1 (OBJ)": "3",
            "AV 1 (DISÇ)": "4",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="hash-3", resumo=resumo)
    aprovar_lote(estado, aprovado_por="auditor")

    # Simula adulteração direta do snapshot.
    estado.snapshot_resumo_aprovado["total_linhas"] = 9999

    assert verificar_integridade_snapshot(estado) is False


def test_verificar_integridade_sem_aprovacao_retorna_false():
    """
    verificar_integridade_snapshot retorna False se o lote ainda não foi
    aprovado (snapshot e hash ausentes).
    """
    rows = [
        {
            "Estudante": "Aluno H4",
            "Trimestre": "1",
            "Disciplina": "Mat",
            "Turma": "TH4",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "4",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="hash-4", resumo=resumo)

    assert verificar_integridade_snapshot(estado) is False


def test_snapshot_congelado_persistencia_integra():
    """
    Aprovação persistida e relida: snapshot permanece igual ao resumo_atual
    no momento da aprovação, mesmo que resumo_atual seja mutado depois.
    Hash deve confirmar integridade após releitura.
    """
    store = _store_mem()
    rows = [
        {
            "Estudante": "Aluno H5",
            "Trimestre": "1",
            "Disciplina": "Hist",
            "Turma": "TH5",
            "AV 1 (OBJ)": "4",
            "AV 1 (DISÇ)": "4",
        }
    ]
    res = _validar_lote(rows)
    resumo = gerar_resumo_lote(res)
    estado = criar_estado_lote(lote_id="hash-5", resumo=resumo, store=store)

    total_original = estado.resumo_atual["total_linhas"]
    aprovar_lote(estado, aprovado_por="gestor", store=store)

    # Mutação pós-aprovação (simula bug ou replay).
    estado.resumo_atual["total_linhas"] = 999

    # Releitura do banco.
    recuperado = carregar_estado_lote("hash-5", store)

    # Snapshot no banco deve refletir o valor no momento da aprovação.
    assert recuperado.snapshot_resumo_aprovado["total_linhas"] == total_original
    # Hash deve confirmar integridade.
    assert verificar_integridade_snapshot(recuperado) is True