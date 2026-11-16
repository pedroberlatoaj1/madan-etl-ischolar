"""
Classificação do status final de uma execução externa (envio pelo Apps Script).

Módulo sem dependências pesadas (sem Flask/psycopg2/pandas) para poder ser
testado isoladamente.

Regra de negócio: o Madan mantém na planilha alunos que SAÍRAM da escola. No
envio, esses alunos não estão mais na turma do iScholar e o Apps Script os
reporta como `erro_resolucao` com a mensagem "RA nao encontrado via
pega_alunos.". Isso é esperado e NÃO pode deixar o lote como `send_failed` para
sempre — senão um lote 100% enviado parece falho e induz reenvios.

Esses itens continuam contados em `total_erros_resolucao` (transparência) e
também em `total_fora_da_turma`; só deixam de bloquear o status `sent`.
"""
from __future__ import annotations

from typing import Iterable, Mapping

STATUS_SEND_FAILED = "send_failed"
STATUS_DRY_RUN_COMPLETED = "dry_run_completed"
STATUS_SENT = "sent"

# Prefixo da mensagem que o Apps Script grava quando o RA da planilha não está
# na lista de matrículas da turma no iScholar (resolverMatriculasPorTurma_).
PREFIXO_RA_FORA_DA_TURMA = "ra nao encontrado"


def eh_aluno_fora_da_turma(status: str, mensagem: str) -> bool:
    """True para `erro_resolucao` causado por RA ausente da turma no iScholar."""
    return (
        str(status or "").strip().lower() == "erro_resolucao"
        and str(mensagem or "").strip().lower().startswith(PREFIXO_RA_FORA_DA_TURMA)
    )


def contar_fora_da_turma(resultados: Iterable[Mapping]) -> int:
    return sum(
        1
        for r in resultados
        if eh_aluno_fora_da_turma(r.get("status"), r.get("mensagem"))
    )


def classificar_execucao_externa(
    *,
    total_sendaveis: int,
    total_enviados: int,
    total_dry_run: int,
    total_erros_resolucao: int,
    total_erros_envio: int,
    total_fora_da_turma: int,
    dry_run: bool,
) -> tuple[str, str, bool]:
    """Devolve (status_final, mensagem_final, sucesso)."""
    processados = total_enviados + total_dry_run
    erros_bloqueantes = (total_erros_resolucao - total_fora_da_turma) + total_erros_envio
    sufixo_fora = (
        f"; {total_fora_da_turma} ignorado(s): RA fora da turma no iScholar (aluno que saiu)"
        if total_fora_da_turma
        else ""
    )

    if erros_bloqueantes or total_sendaveis <= 0 or processados == 0:
        total_erros = total_erros_resolucao + total_erros_envio
        return (
            STATUS_SEND_FAILED,
            f"execucao externa: {processados}/{total_sendaveis} processados; {total_erros} erro(s).",
            False,
        )
    if dry_run or total_dry_run == processados:
        return (
            STATUS_DRY_RUN_COMPLETED,
            f"dry_run externo concluido: {total_dry_run}/{total_sendaveis} item(ns){sufixo_fora}.",
            True,
        )
    return (
        STATUS_SENT,
        f"envio externo concluido: {total_enviados}/{total_sendaveis} item(ns){sufixo_fora}.",
        True,
    )
