"""Status final do envio externo (Apps Script): alunos fora da turma nao reprovam o lote."""
from status_execucao_externa import (
    STATUS_DRY_RUN_COMPLETED,
    STATUS_SEND_FAILED,
    STATUS_SENT,
    classificar_execucao_externa,
    contar_fora_da_turma,
    eh_aluno_fora_da_turma,
)

MSG_RA = "RA nao encontrado via pega_alunos."


def _classificar(**kw):
    base = dict(
        total_sendaveis=0,
        total_enviados=0,
        total_dry_run=0,
        total_erros_resolucao=0,
        total_erros_envio=0,
        total_fora_da_turma=0,
        dry_run=False,
    )
    base.update(kw)
    return classificar_execucao_externa(**base)


def test_identifica_aluno_fora_da_turma():
    assert eh_aluno_fora_da_turma("erro_resolucao", MSG_RA)
    assert eh_aluno_fora_da_turma("ERRO_RESOLUCAO", "  ra NAO encontrado ...")
    assert not eh_aluno_fora_da_turma("erro_envio", MSG_RA)
    assert not eh_aluno_fora_da_turma("erro_resolucao", "Item com erro local no pacote de execucao.")


def test_conta_fora_da_turma():
    resultados = [
        {"status": "enviado", "mensagem": "Nota enviada ao iScholar."},
        {"status": "erro_resolucao", "mensagem": MSG_RA},
        {"status": "erro_resolucao", "mensagem": MSG_RA},
        {"status": "erro_resolucao", "mensagem": "outro motivo"},
    ]
    assert contar_fora_da_turma(resultados) == 2


def test_envio_completo_com_alunos_que_sairam_vira_sent():
    # Caso real da 2B_T3: 1181 enviadas + 4 RAs de alunos que sairam.
    status, msg, sucesso = _classificar(
        total_sendaveis=1185, total_enviados=1181,
        total_erros_resolucao=4, total_fora_da_turma=4,
    )
    assert status == STATUS_SENT
    assert sucesso is True
    assert "1181/1185" in msg and "4 ignorado(s)" in msg


def test_envio_sem_nenhum_erro_vira_sent_sem_sufixo():
    status, msg, sucesso = _classificar(total_sendaveis=10, total_enviados=10)
    assert status == STATUS_SENT and sucesso is True
    assert msg == "envio externo concluido: 10/10 item(ns)."


def test_erro_de_envio_continua_send_failed():
    # Ex.: tempo limite / falha de rede — o lote precisa ser retomado.
    status, _, sucesso = _classificar(
        total_sendaveis=1185, total_enviados=866, total_erros_envio=315,
        total_erros_resolucao=4, total_fora_da_turma=4,
    )
    assert status == STATUS_SEND_FAILED and sucesso is False


def test_erro_de_resolucao_que_nao_e_ra_continua_send_failed():
    status, _, _ = _classificar(
        total_sendaveis=10, total_enviados=8,
        total_erros_resolucao=2, total_fora_da_turma=1,
    )
    assert status == STATUS_SEND_FAILED


def test_nada_enviado_continua_send_failed_mesmo_so_com_ra():
    status, _, sucesso = _classificar(
        total_sendaveis=3, total_erros_resolucao=3, total_fora_da_turma=3,
    )
    assert status == STATUS_SEND_FAILED and sucesso is False


def test_dry_run_com_alunos_que_sairam_vira_dry_run_completed():
    status, msg, sucesso = _classificar(
        total_sendaveis=100, total_dry_run=97,
        total_erros_resolucao=3, total_fora_da_turma=3, dry_run=True,
    )
    assert status == STATUS_DRY_RUN_COMPLETED and sucesso is True
    assert "97/100" in msg and "3 ignorado(s)" in msg
