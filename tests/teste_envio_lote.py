"""
test_envio_lote.py — Etapa 5 (v2)

Testes unitários de envio_lote.py, envio_lote_audit_store.py e lote_itens_store.py.

Cobertura dos 5 critérios de aceite:
  1. Erro quando lote aprovado não tem itens persistidos no itens_store
  2. Envio usando itens persistidos do lote (não iterable externo)
  3. Auditoria por item com identidade forte (item_key, não nome/componente)
  4. Preservação do dry_run
  5. Preservação da recusa de lote não aprovado

Organização:
  A) Pré-condição: lote não aprovado
  B) Pré-condição: lote aprovado sem itens persistidos
  C) Vínculo aprovação → envio (itens do store, não externos)
  D) Dry-run
  E) Identidade estável (item_key)
  F) Auditoria (EnvioLoteAuditStore com chave forte)
  G) Falha parcial (erro não aborta lote)
  H) Resolvedores
  I) LoteItensStore (integridade e existência)
  J) extrair_itens_sendaveis (preparação do conjunto)
  K) Trilha canônica completa: aprovar → persistir → enviar → auditar

Convenções:
  - pytest puro, sem unittest
  - SQLite :memory: para todos os stores (lote_itens_store, aprovacao_lote_store,
    envio_lote_audit_store já corrigidos para manter conexão compartilhada em :memory:)
  - FakeClient stub inline — sem chamadas HTTP reais
  - Dependências injetadas explicitamente, sem mock.patch
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import pytest

from aprovacao_lote import (
    EstadoAprovacaoLote,
    aprovar_lote,
    criar_estado_lote,
    extrair_itens_sendaveis,
    gerar_resumo_lote,
)
from aprovacao_lote_store import AprovacaoLoteStore
from envio_lote import (
    ResolvedorDireto,
    ResolvedorIDsAbstrato,
    ResolvedorNaoImplementado,
    ResultadoResolucaoIDs,
    _compute_item_key,
    enviar_lote,
)
from envio_lote_audit_store import EnvioLoteAuditStore
from lote_itens_store import LoteItensStore


# ---------------------------------------------------------------------------
# Helpers e stubs
# ---------------------------------------------------------------------------

def _estado_aprovado(lote_id: str = "lote-test") -> EstadoAprovacaoLote:
    return EstadoAprovacaoLote(
        lote_id=lote_id,
        status="aprovado_para_envio",
        elegivel_para_aprovacao=True,
        resumo_atual={"total_linhas": 1},
    )


def _estado_aguardando(lote_id: str = "lote-test") -> EstadoAprovacaoLote:
    return EstadoAprovacaoLote(
        lote_id=lote_id,
        status="aguardando_aprovacao",
        elegivel_para_aprovacao=True,
        resumo_atual={},
    )


def _estado_rejeitado(lote_id: str = "lote-test") -> EstadoAprovacaoLote:
    return EstadoAprovacaoLote(
        lote_id=lote_id,
        status="rejeitado",
        elegivel_para_aprovacao=False,
        resumo_atual={},
    )


def _lancamento_sendavel(**extra: Any) -> dict[str, Any]:
    """Lançamento mínimo válido e sendável."""
    base = {
        "estudante":          "Ana Silva",
        "turma":              "T1",
        "disciplina":         "Matemática",
        "componente":         "av1",
        "subcomponente":      None,
        "trimestre":          "1",
        "nota_ajustada_0a10": 8.0,
        "sendavel":           True,
        "status":             "pronto",
        "hash_conteudo":      "deadbeef1234",
        "linha_origem":       1,
    }
    base.update(extra)
    return base


def _lancamento_nao_sendavel(**extra: Any) -> dict[str, Any]:
    base = _lancamento_sendavel(**extra)
    base["sendavel"] = False
    return base


def _resultado_etapa3(
    lancamentos_validos: list,
    lancamentos_com_erro: list | None = None,
) -> dict:
    return {
        "lancamentos_validos":  lancamentos_validos,
        "lancamentos_com_erro": lancamentos_com_erro or [],
        "status_geral": "apto_para_aprovacao",
        "avisos": [], "pendencias": [], "duplicidades": [], "comparacoes_totais": [],
    }


# --- FakeResultadoLancamento e FakeClient ---

@dataclass
class FakeResultadoLancamento:
    sucesso: bool
    transitorio: bool = False
    mensagem: str = "ok"
    payload: Optional[dict] = None
    dados: Optional[Any] = None
    rastreabilidade: dict = field(default_factory=dict)
    dry_run: bool = False


class FakeClient:
    """Stub de IScholarClient. Não importa pandas/requests."""

    def __init__(self, *, sucesso: bool = True, transitorio: bool = False, mensagem: str = "ok") -> None:
        self._sucesso = sucesso
        self._transitorio = transitorio
        self._mensagem = mensagem
        self.chamadas: list[dict] = []

    def lancar_nota(
        self,
        *,
        id_matricula: Optional[int] = None,
        id_disciplina: int,
        id_avaliacao: int,
        valor_bruta: Any,
        id_professor: Optional[int] = None,
        dry_run: bool = False,
    ) -> FakeResultadoLancamento:
        self.chamadas.append(dict(
            id_matricula=id_matricula, id_disciplina=id_disciplina,
            id_avaliacao=id_avaliacao, valor_bruta=valor_bruta,
            id_professor=id_professor, dry_run=dry_run,
        ))
        if dry_run:
            return FakeResultadoLancamento(
                sucesso=True, dry_run=True,
                mensagem="dry_run=True: payload montado, sem chamada HTTP.",
                payload={"id_matricula": id_matricula, "id_disciplina": id_disciplina,
                         "id_avaliacao": id_avaliacao, "valor": valor_bruta},
            )
        return FakeResultadoLancamento(sucesso=self._sucesso, transitorio=self._transitorio, mensagem=self._mensagem)


def _resolvedor_com_ids(
    id_matricula: int = 101, id_disciplina: int = 202,
    id_avaliacao: int = 303, id_professor: Optional[int] = None,
) -> ResolvedorIDsAbstrato:
    class _R(ResolvedorIDsAbstrato):
        def resolver_ids(self, lancamento: Mapping[str, Any]) -> ResultadoResolucaoIDs:
            return ResultadoResolucaoIDs(
                id_matricula=id_matricula, id_disciplina=id_disciplina,
                id_avaliacao=id_avaliacao, id_professor=id_professor, erros=[],
            )
    return _R()


# --- Stores em memória ---

def _itens_store_mem() -> LoteItensStore:
    return LoteItensStore(":memory:")


def _audit_store_mem() -> EnvioLoteAuditStore:
    return EnvioLoteAuditStore(":memory:")


# --- Helper: estado aprovado COM itens persistidos (o caminho correto) ---

def _setup_lote_com_itens(
    lote_id: str = "lote-test",
    lancamentos: list[dict] | None = None,
) -> tuple[EstadoAprovacaoLote, LoteItensStore]:
    """
    Retorna (estado aprovado, itens_store com itens persistidos).
    Simula o resultado correto de extrair_itens_sendaveis() + aprovar_lote().
    """
    if lancamentos is None:
        lancamentos = [
            _lancamento_sendavel(
                _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
                hash_conteudo="abc001",
            )
        ]
    store = _itens_store_mem()
    store.salvar_itens(lote_id, lancamentos)
    return _estado_aprovado(lote_id), store


# ---------------------------------------------------------------------------
# A) Pré-condição: lote não aprovado
# ---------------------------------------------------------------------------

def test_rejeita_lote_aguardando_aprovacao():
    """enviar_lote deve levantar ValueError se status != 'aprovado_para_envio'."""
    _, itens_store = _setup_lote_com_itens()
    with pytest.raises(ValueError, match="não está aprovado para envio"):
        enviar_lote(
            estado=_estado_aguardando(),
            itens_store=itens_store,
            cliente=FakeClient(),
            resolvedor=_resolvedor_com_ids(),
        )


def test_rejeita_lote_rejeitado():
    _, itens_store = _setup_lote_com_itens()
    with pytest.raises(ValueError, match="não está aprovado para envio"):
        enviar_lote(
            estado=_estado_rejeitado(),
            itens_store=itens_store,
            cliente=FakeClient(),
            resolvedor=_resolvedor_com_ids(),
        )


def test_mensagem_pré_condicao_cita_lote_id():
    lote_id = "lote-xyz-999"
    _, itens_store = _setup_lote_com_itens(lote_id)
    # Estado com lote_id diferente do store — vai falhar na pré-condição de status
    with pytest.raises(ValueError, match=lote_id):
        enviar_lote(
            estado=_estado_aguardando(lote_id),
            itens_store=itens_store,
            cliente=FakeClient(),
            resolvedor=_resolvedor_com_ids(),
        )


# ---------------------------------------------------------------------------
# B) Pré-condição: lote aprovado sem itens persistidos
# ---------------------------------------------------------------------------

def test_erro_quando_lote_aprovado_sem_itens_persistidos():
    """
    Critério 1: Se o lote foi aprovado sem chamar aprovar_lote(itens_sendaveis,
    itens_store), enviar_lote deve levantar ValueError explícito — não silenciar
    nem enviar conjunto vazio.
    """
    estado = _estado_aprovado("sem-itens")
    itens_store_vazio = _itens_store_mem()  # nenhum item salvo

    with pytest.raises(ValueError, match="não tem itens sendáveis persistidos"):
        enviar_lote(
            estado=estado,
            itens_store=itens_store_vazio,
            cliente=FakeClient(),
            resolvedor=_resolvedor_com_ids(),
        )


def test_mensagem_de_erro_de_itens_ausentes_menciona_fluxo_correto():
    """A mensagem de erro deve orientar o caller sobre o fluxo correto."""
    estado = _estado_aprovado("sem-itens-2")
    itens_store_vazio = _itens_store_mem()

    with pytest.raises(ValueError, match="extrair_itens_sendaveis"):
        enviar_lote(
            estado=estado,
            itens_store=itens_store_vazio,
            cliente=FakeClient(),
            resolvedor=_resolvedor_com_ids(),
        )


def test_lote_diferente_no_store_e_tratado_como_ausente():
    """
    Store com itens para lote-A; enviar_lote chamado com lote-B.
    Deve falhar na pré-condição de itens (não vai buscar itens errados).
    """
    lote_a, itens_store = _setup_lote_com_itens("lote-A")
    estado_b = _estado_aprovado("lote-B")  # diferente do que está no store

    with pytest.raises(ValueError, match="não tem itens sendáveis persistidos"):
        enviar_lote(
            estado=estado_b,
            itens_store=itens_store,
            cliente=FakeClient(),
            resolvedor=_resolvedor_com_ids(),
        )


# ---------------------------------------------------------------------------
# C) Critério 2: vínculo aprovação → envio (itens do store, não externos)
# ---------------------------------------------------------------------------

def test_envio_usa_itens_do_store_nao_externos():
    """
    Critério 2: O conjunto enviado deve vir do itens_store, não de um
    iterable arbitrário externo.
    Verificamos que o cliente recebe exatamente os IDs injetados nos itens do store.
    """
    lance = _lancamento_sendavel(
        _id_matricula=42, _id_disciplina=99, _id_avaliacao=77,
        hash_conteudo="chave-store-001",
    )
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])
    cliente = FakeClient()

    res = enviar_lote(
        estado=estado,
        itens_store=itens_store,
        cliente=cliente,
        resolvedor=ResolvedorDireto(),
    )

    assert res.total_sendaveis == 1
    assert res.total_enviados == 1
    chamada = cliente.chamadas[0]
    assert chamada["id_matricula"] == 42
    assert chamada["id_disciplina"] == 99
    assert chamada["id_avaliacao"] == 77


def test_multiplos_itens_no_store_todos_processados():
    """Todos os itens persistidos devem ser processados."""
    lancamentos = [
        _lancamento_sendavel(_id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
                             hash_conteudo="h1", linha_origem=1),
        _lancamento_sendavel(_id_matricula=4, _id_disciplina=2, _id_avaliacao=3,
                             hash_conteudo="h2", linha_origem=2),
        _lancamento_sendavel(_id_matricula=7, _id_disciplina=2, _id_avaliacao=3,
                             hash_conteudo="h3", linha_origem=3),
    ]
    estado, itens_store = _setup_lote_com_itens(lancamentos=lancamentos)
    cliente = FakeClient()

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=cliente, resolvedor=ResolvedorDireto(),
    )

    assert res.total_sendaveis == 3
    assert res.total_enviados == 3
    assert len(cliente.chamadas) == 3


def test_itens_vazio_no_store_retorna_sucesso_sem_envio():
    """Store com lista vazia persistida: sucesso=True, total=0, sem chamada ao cliente."""
    estado = _estado_aprovado("lote-vazio")
    itens_store = _itens_store_mem()
    itens_store.salvar_itens("lote-vazio", [])  # explicitamente vazio
    cliente = FakeClient()

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=cliente, resolvedor=_resolvedor_com_ids(),
    )

    assert res.sucesso is True
    assert res.total_sendaveis == 0
    assert cliente.chamadas == []


def test_extrair_itens_sendaveis_filtra_nao_sendaveis():
    """
    extrair_itens_sendaveis deve incluir apenas sendavel=True em lancamentos_validos.
    """
    resultados = [
        _resultado_etapa3(
            lancamentos_validos=[
                _lancamento_sendavel(estudante="Ana"),
                _lancamento_nao_sendavel(estudante="Beto"),
            ]
        ),
        _resultado_etapa3(
            lancamentos_validos=[_lancamento_sendavel(estudante="Carol")],
            lancamentos_com_erro=[_lancamento_sendavel(estudante="Davi")],  # ignorado
        ),
    ]
    itens = extrair_itens_sendaveis(resultados)
    estudantes = [i["estudante"] for i in itens]
    assert "Ana" in estudantes
    assert "Carol" in estudantes
    assert "Beto" not in estudantes
    assert "Davi" not in estudantes
    assert len(itens) == 2


# ---------------------------------------------------------------------------
# D) Critério 4: Preservação do dry_run
# ---------------------------------------------------------------------------

def test_dry_run_nao_faz_post_real():
    """dry_run=True deve repassar ao cliente sem executar POST."""
    lance = _lancamento_sendavel(
        _id_matricula=10, _id_disciplina=20, _id_avaliacao=30,
        hash_conteudo="dryrun-001",
    )
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])
    cliente = FakeClient()

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=cliente, resolvedor=ResolvedorDireto(), dry_run=True,
    )

    assert res.dry_run is True
    assert res.total_dry_run == 1
    assert res.total_enviados == 0
    assert res.itens[0].status == "dry_run"
    assert cliente.chamadas[0]["dry_run"] is True


def test_dry_run_payload_presente_no_item():
    lance = _lancamento_sendavel(
        _id_matricula=10, _id_disciplina=20, _id_avaliacao=30,
        hash_conteudo="dryrun-002",
    )
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(), dry_run=True,
    )

    assert res.itens[0].payload_enviado is not None
    assert res.itens[0].payload_enviado["id_matricula"] == 10


def test_dry_run_sucesso_true_sem_erros():
    lance = _lancamento_sendavel(
        _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
        hash_conteudo="dryrun-003",
    )
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(), dry_run=True,
    )
    assert res.sucesso is True


# ---------------------------------------------------------------------------
# E) Critério 3: Identidade estável (item_key)
# ---------------------------------------------------------------------------

def test_item_key_usa_hash_conteudo_quando_presente():
    """_compute_item_key deve retornar hash_conteudo quando presente."""
    l = {"hash_conteudo": "abc123def456", "linha_origem": 5, "componente": "av1"}
    key = _compute_item_key("lote-x", l)
    assert key == "abc123def456"


def test_item_key_fallback_estrutural_sem_hash_conteudo():
    """Sem hash_conteudo, deve retornar SHA-256 estrutural (não string de nome)."""
    l = {"hash_conteudo": "", "linha_origem": 3, "componente": "av2", "subcomponente": None}
    key = _compute_item_key("lote-y", l)
    # Deve ser um hexdigest de 64 chars (SHA-256)
    assert len(key) == 64
    assert all(c in "0123456789abcdef" for c in key)


def test_item_key_fallback_nao_colide_por_nome_de_aluno():
    """
    Dois alunos com o mesmo nome mas linha_origem diferentes devem ter
    item_key diferentes (usando o fallback estrutural).
    """
    l1 = {"hash_conteudo": "", "linha_origem": 1, "componente": "av1", "subcomponente": None}
    l2 = {"hash_conteudo": "", "linha_origem": 2, "componente": "av1", "subcomponente": None}
    key1 = _compute_item_key("lote-z", l1)
    key2 = _compute_item_key("lote-z", l2)
    assert key1 != key2


def test_item_key_hash_conteudo_tem_prioridade_sobre_linha_origem():
    """hash_conteudo prevalece mesmo quando linha_origem também existe."""
    l = {"hash_conteudo": "prioridade-hash", "linha_origem": 99, "componente": "av3"}
    key = _compute_item_key("lote-p", l)
    assert key == "prioridade-hash"


def test_resultado_item_envio_tem_item_key_preenchido():
    """ResultadoItemEnvio.item_key deve ser preenchido pelo enviar_lote."""
    lance = _lancamento_sendavel(
        _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
        hash_conteudo="minha-chave-estavel",
    )
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(),
    )

    assert res.itens[0].item_key == "minha-chave-estavel"


def test_item_key_unico_por_lancamento_no_mesmo_lote():
    """Lançamentos diferentes no mesmo lote devem ter item_key diferentes."""
    lancamentos = [
        _lancamento_sendavel(
            _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
            hash_conteudo="key-A",
        ),
        _lancamento_sendavel(
            _id_matricula=4, _id_disciplina=2, _id_avaliacao=3,
            hash_conteudo="key-B",
        ),
    ]
    estado, itens_store = _setup_lote_com_itens(lancamentos=lancamentos)

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(),
    )

    keys = [it.item_key for it in res.itens]
    assert len(set(keys)) == 2   # sem colisão


# ---------------------------------------------------------------------------
# F) Auditoria: EnvioLoteAuditStore com chave forte
# ---------------------------------------------------------------------------

def test_audit_store_usa_item_key_como_chave():
    """O registro no audit store deve ter item_key correspondente ao lançamento."""
    lance = _lancamento_sendavel(
        _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
        hash_conteudo="audit-key-001",
    )
    estado, itens_store = _setup_lote_com_itens(lote_id="audit-a", lancamentos=[lance])
    audit = _audit_store_mem()

    enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(),
        audit_store=audit,
    )

    itens = audit.listar_itens("audit-a")
    assert len(itens) == 1
    assert itens[0]["item_key"] == "audit-key-001"
    assert itens[0]["status"] == "enviado"


def test_audit_store_nao_duplica_em_reenvio_mesmo_item():
    """
    Re-enviar o mesmo lote com o mesmo item_key deve UPSERT (não duplicar).
    Testa a idempotência do audit store com a nova chave forte.
    """
    lance = _lancamento_sendavel(
        _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
        hash_conteudo="idem-key",
    )
    estado, itens_store = _setup_lote_com_itens(lote_id="idem-b", lancamentos=[lance])
    audit = _audit_store_mem()

    enviar_lote(estado=estado, itens_store=itens_store,
                cliente=FakeClient(), resolvedor=ResolvedorDireto(), audit_store=audit)
    enviar_lote(estado=estado, itens_store=itens_store,
                cliente=FakeClient(), resolvedor=ResolvedorDireto(), audit_store=audit)

    itens = audit.listar_itens("idem-b")
    assert len(itens) == 1   # não duplicou


def test_audit_store_registra_erro_resolucao_com_chave_estrutural():
    """
    Lançamento sem _id_* → erro resolução. Mesmo sem hash_conteudo explícito,
    item_key deve ser preenchido com chave estrutural (não colide).
    """
    lance = _lancamento_sendavel(
        hash_conteudo="",  # sem hash → fallback estrutural
        linha_origem=7, componente="av2",
    )
    # Remove os campos _id_* para forçar erro de resolução
    lance.pop("_id_matricula", None)

    estado = _estado_aprovado("audit-c")
    itens_store = _itens_store_mem()
    itens_store.salvar_itens("audit-c", [lance])
    audit = _audit_store_mem()

    enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(),
        audit_store=audit,
    )

    itens = audit.listar_itens("audit-c")
    assert len(itens) == 1
    assert itens[0]["status"] == "erro_resolucao"
    # item_key deve ser string não vazia (fallback estrutural)
    assert itens[0]["item_key"]
    assert len(itens[0]["item_key"]) > 0


def test_audit_store_resumo_por_status():
    lancamentos = [
        _lancamento_sendavel(_id_matricula=1, _id_disciplina=2, _id_avaliacao=3, hash_conteudo="r1"),
        _lancamento_sendavel(hash_conteudo="r2"),  # sem _id_* → erro resolução
    ]
    estado, itens_store = _setup_lote_com_itens(lote_id="resumo-a", lancamentos=lancamentos)
    audit = _audit_store_mem()

    enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(), audit_store=audit,
    )

    resumo = audit.resumo_lote("resumo-a")
    assert resumo.get("enviado", 0) == 1
    assert resumo.get("erro_resolucao", 0) == 1


def test_audit_store_dry_run_registrado():
    lance = _lancamento_sendavel(
        _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
        hash_conteudo="dry-audit",
    )
    estado, itens_store = _setup_lote_com_itens(lote_id="audit-dry", lancamentos=[lance])
    audit = _audit_store_mem()

    enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(),
        dry_run=True, audit_store=audit,
    )

    itens = audit.listar_itens("audit-dry")
    assert itens[0]["status"] == "dry_run"
    assert itens[0]["dry_run"] == 1


# ---------------------------------------------------------------------------
# G) Falha parcial
# ---------------------------------------------------------------------------

def test_erro_resolucao_nao_aborta_demais_itens():
    """
    Item com erro de resolução não deve impedir os itens seguintes.
    """
    lancamentos = [
        _lancamento_sendavel(_id_matricula=1, _id_disciplina=2, _id_avaliacao=3, hash_conteudo="ok-1"),
        _lancamento_sendavel(hash_conteudo="err-2"),   # sem _id_* → erro resolução
        _lancamento_sendavel(_id_matricula=7, _id_disciplina=2, _id_avaliacao=3, hash_conteudo="ok-3"),
    ]
    estado, itens_store = _setup_lote_com_itens(lancamentos=lancamentos)
    cliente = FakeClient()

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=cliente, resolvedor=ResolvedorDireto(),
    )

    assert res.total_sendaveis == 3
    assert res.total_erros_resolucao == 1
    assert res.total_enviados == 2
    assert len(cliente.chamadas) == 2
    assert res.sucesso is False


def test_erro_envio_nao_aborta_demais_itens():
    """Falha de POST em um item não impede o próximo."""

    class _ClienteAlternado(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self._contador = 0

        def lancar_nota(self, *, id_matricula=None, id_disciplina, id_avaliacao,
                        valor_bruta, id_professor=None, dry_run=False) -> FakeResultadoLancamento:
            self._contador += 1
            self.chamadas.append({})
            if self._contador == 2:   # segundo item falha
                return FakeResultadoLancamento(sucesso=False, mensagem="erro no segundo")
            return FakeResultadoLancamento(sucesso=True, mensagem="ok")

    lancamentos = [
        _lancamento_sendavel(_id_matricula=1, _id_disciplina=2, _id_avaliacao=3, hash_conteudo="fe1"),
        _lancamento_sendavel(_id_matricula=4, _id_disciplina=2, _id_avaliacao=3, hash_conteudo="fe2"),
        _lancamento_sendavel(_id_matricula=7, _id_disciplina=2, _id_avaliacao=3, hash_conteudo="fe3"),
    ]
    estado, itens_store = _setup_lote_com_itens(lancamentos=lancamentos)

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=_ClienteAlternado(), resolvedor=ResolvedorDireto(),
    )

    assert res.total_sendaveis == 3
    assert res.total_enviados == 2
    assert res.total_erros_envio == 1


def test_falha_transitoria_marca_transitorio_no_item():
    lance = _lancamento_sendavel(
        _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
        hash_conteudo="trans-001",
    )
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(sucesso=False, transitorio=True, mensagem="503 timeout"),
        resolvedor=ResolvedorDireto(),
    )

    assert res.itens[0].status == "erro_envio"
    assert res.itens[0].transitorio is True


# ---------------------------------------------------------------------------
# H) Resolvedores
# ---------------------------------------------------------------------------

def test_resolvedor_nao_implementado_direto():
    """ResolvedorNaoImplementado levanta NotImplementedError na chamada direta."""
    with pytest.raises(NotImplementedError, match="resolvedor de IDs iScholar"):
        ResolvedorNaoImplementado().resolver_ids({})


def test_resolvedor_nao_implementado_em_enviar_lote_registra_erro():
    """Na enviar_lote, a exceção do resolvedor é capturada como erro_resolucao."""
    lance = _lancamento_sendavel(hash_conteudo="ni-001")
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorNaoImplementado(),
    )

    assert res.total_erros_resolucao == 1
    assert res.itens[0].status == "erro_resolucao"


def test_resolvedor_que_levanta_excecao_e_capturado():
    class _Bugado(ResolvedorIDsAbstrato):
        def resolver_ids(self, lancamento: Mapping[str, Any]) -> ResultadoResolucaoIDs:
            raise RuntimeError("bug interno")

    lance = _lancamento_sendavel(hash_conteudo="bug-001")
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=_Bugado(),
    )

    assert res.itens[0].status == "erro_resolucao"
    assert "bug interno" in res.itens[0].mensagem


def test_id_professor_opcional_repassado():
    lance = _lancamento_sendavel(hash_conteudo="prof-001")
    estado, itens_store = _setup_lote_com_itens(lancamentos=[lance])
    cliente = FakeClient()

    enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=cliente, resolvedor=_resolvedor_com_ids(id_professor=777),
    )
    assert cliente.chamadas[0]["id_professor"] == 777


# ---------------------------------------------------------------------------
# I) LoteItensStore
# ---------------------------------------------------------------------------

def test_lote_itens_store_salvar_e_carregar():
    store = _itens_store_mem()
    itens = [_lancamento_sendavel(estudante="Teste")]
    store.salvar_itens("lote-s1", itens)

    recuperados = store.carregar_itens("lote-s1")
    assert recuperados is not None
    assert len(recuperados) == 1
    assert recuperados[0]["estudante"] == "Teste"


def test_lote_itens_store_retorna_none_se_inexistente():
    store = _itens_store_mem()
    assert store.carregar_itens("nao-existe") is None


def test_lote_itens_store_existe():
    store = _itens_store_mem()
    assert store.existe("nao-existe") is False
    store.salvar_itens("existe", [])
    assert store.existe("existe") is True


def test_lote_itens_store_verificar_integridade():
    store = _itens_store_mem()
    itens = [_lancamento_sendavel()]
    store.salvar_itens("integr-1", itens)
    assert store.verificar_integridade("integr-1") is True


def test_lote_itens_store_verifica_integridade_falsa_se_inexistente():
    store = _itens_store_mem()
    assert store.verificar_integridade("nao-existe") is False


def test_lote_itens_store_idempotente():
    """Re-salvar os mesmos itens não duplica — UPSERT correto."""
    store = _itens_store_mem()
    itens = [_lancamento_sendavel()]
    store.salvar_itens("idem-s", itens)
    store.salvar_itens("idem-s", itens)
    recuperados = store.carregar_itens("idem-s")
    assert recuperados is not None
    assert len(recuperados) == 1


# ---------------------------------------------------------------------------
# J) extrair_itens_sendaveis (preparação do conjunto)
# ---------------------------------------------------------------------------

def test_extrair_itens_sendaveis_vazio():
    assert extrair_itens_sendaveis([]) == []


def test_extrair_itens_sendaveis_ignora_com_erro():
    """lancamentos_com_erro não devem aparecer nos sendáveis."""
    res = _resultado_etapa3(
        lancamentos_validos=[_lancamento_sendavel()],
        lancamentos_com_erro=[_lancamento_sendavel(estudante="Erro")],
    )
    itens = extrair_itens_sendaveis([res])
    assert all(i["estudante"] != "Erro" for i in itens)


def test_extrair_itens_sendaveis_todos_nao_sendaveis():
    """Se todos são não-sendáveis, retorna lista vazia."""
    res = _resultado_etapa3(
        lancamentos_validos=[_lancamento_nao_sendavel(), _lancamento_nao_sendavel()]
    )
    assert extrair_itens_sendaveis([res]) == []


# ---------------------------------------------------------------------------
# K) Trilha canônica completa: aprovar → persistir itens → enviar → auditar
# ---------------------------------------------------------------------------

def _aprov_store_mem() -> AprovacaoLoteStore:
    return AprovacaoLoteStore(":memory:")


def test_trilha_completa_aprovacao_persistencia_envio_auditoria():
    """
    Prova a trilha arquitetural canônica de ponta a ponta — sem atalhos:

      extrair_itens_sendaveis(resultados_etapa3)
        → aprovar_lote(itens_sendaveis=..., itens_store=...)
        → enviar_lote(itens_store=...)
        → audit_store registra item por item

    Nenhuma chamada a salvar_itens() fora do fluxo de aprovação.
    Nenhum iterable externo injetado em enviar_lote().
    """
    lote_id = "trilha-completa-001"

    # 1. Simula o output da Etapa 3 (resultado de validar_pre_envio_linha)
    lancamento = _lancamento_sendavel(
        _id_matricula=10, _id_disciplina=20, _id_avaliacao=30,
        hash_conteudo="trilha-hash-001",
        estudante="Ana Canônica",
    )
    resultados_etapa3 = [
        _resultado_etapa3(lancamentos_validos=[lancamento])
    ]

    # 2. Gera o resumo e cria o estado do lote via criar_estado_lote
    resumo = gerar_resumo_lote(resultados_etapa3)
    aprov_store = _aprov_store_mem()
    estado = criar_estado_lote(
        lote_id=lote_id,
        resumo=resumo,
        store=aprov_store,
    )
    assert estado.status == "aguardando_aprovacao"
    assert estado.elegivel_para_aprovacao is True

    # 3. Extrai os itens sendáveis — esta é a única fonte canônica
    itens_sendaveis = extrair_itens_sendaveis(resultados_etapa3)
    assert len(itens_sendaveis) == 1
    assert itens_sendaveis[0]["estudante"] == "Ana Canônica"

    # 4. Aprova o lote e persiste os itens atomicamente via aprovar_lote
    itens_store = _itens_store_mem()
    aprovar_lote(
        estado,
        aprovado_por="gestor-teste",
        store=aprov_store,
        itens_sendaveis=itens_sendaveis,
        itens_store=itens_store,
    )
    assert estado.status == "aprovado_para_envio"

    # 5. Confirma que o vínculo aprovação→itens_store está íntegro
    assert itens_store.existe(lote_id)
    assert itens_store.verificar_integridade(lote_id)
    carregados = itens_store.carregar_itens(lote_id)
    assert carregados is not None and len(carregados) == 1

    # 6. Envia a partir do store (nunca recebe resultados_etapa3)
    audit_store = _audit_store_mem()
    cliente = FakeClient()

    res = enviar_lote(
        estado=estado,
        itens_store=itens_store,
        cliente=cliente,
        resolvedor=ResolvedorDireto(),
        dry_run=False,
        audit_store=audit_store,
    )

    # 7. Verifica o resultado do envio
    assert res.sucesso is True
    assert res.total_sendaveis == 1
    assert res.total_enviados == 1
    assert res.total_erros_resolucao == 0
    assert res.total_erros_envio == 0
    assert len(cliente.chamadas) == 1
    assert cliente.chamadas[0]["id_matricula"] == 10
    assert cliente.chamadas[0]["id_disciplina"] == 20
    assert cliente.chamadas[0]["id_avaliacao"] == 30

    # 8. Verifica a auditoria: item_key estável, status correto
    itens_audit = audit_store.listar_itens(lote_id)
    assert len(itens_audit) == 1
    assert itens_audit[0]["item_key"] == "trilha-hash-001"
    assert itens_audit[0]["status"] == "enviado"
    assert itens_audit[0]["dry_run"] == 0

    # 9. Resumo do audit_store deve refletir exatamente 1 enviado
    resumo_audit = audit_store.resumo_lote(lote_id)
    assert resumo_audit == {"enviado": 1}


def test_trilha_completa_dry_run():
    """Mesma trilha canônica, mas com dry_run=True. Status deve ser 'dry_run'."""
    lote_id = "trilha-dry-001"

    lancamento = _lancamento_sendavel(
        _id_matricula=1, _id_disciplina=2, _id_avaliacao=3,
        hash_conteudo="dry-trilha-hash",
    )
    resultados_etapa3 = [_resultado_etapa3(lancamentos_validos=[lancamento])]

    resumo = gerar_resumo_lote(resultados_etapa3)
    aprov_store = _aprov_store_mem()
    estado = criar_estado_lote(lote_id=lote_id, resumo=resumo, store=aprov_store)

    itens_sendaveis = extrair_itens_sendaveis(resultados_etapa3)
    itens_store = _itens_store_mem()
    aprovar_lote(
        estado,
        aprovado_por="gestor-dry",
        store=aprov_store,
        itens_sendaveis=itens_sendaveis,
        itens_store=itens_store,
    )

    audit_store = _audit_store_mem()
    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(),
        dry_run=True, audit_store=audit_store,
    )

    assert res.dry_run is True
    assert res.total_dry_run == 1
    assert res.total_enviados == 0

    itens_audit = audit_store.listar_itens(lote_id)
    assert itens_audit[0]["status"] == "dry_run"
    assert itens_audit[0]["dry_run"] == 1


def test_trilha_completa_falha_resolucao_registrada_na_auditoria():
    """
    Na trilha canônica, um item sem _id_* produz erro_resolucao
    persistido no audit_store — sem abortar o fluxo.
    """
    lote_id = "trilha-err-001"

    # Lançamento sem _id_* → ResolvedorDireto vai falhar
    lancamento = _lancamento_sendavel(hash_conteudo="err-trilha-hash")
    resultados_etapa3 = [_resultado_etapa3(lancamentos_validos=[lancamento])]

    resumo = gerar_resumo_lote(resultados_etapa3)
    aprov_store = _aprov_store_mem()
    estado = criar_estado_lote(lote_id=lote_id, resumo=resumo, store=aprov_store)

    itens_sendaveis = extrair_itens_sendaveis(resultados_etapa3)
    itens_store = _itens_store_mem()
    aprovar_lote(
        estado,
        aprovado_por="gestor-err",
        store=aprov_store,
        itens_sendaveis=itens_sendaveis,
        itens_store=itens_store,
    )

    audit_store = _audit_store_mem()
    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=ResolvedorDireto(),
        audit_store=audit_store,
    )

    assert res.sucesso is False
    assert res.total_erros_resolucao == 1
    assert res.total_enviados == 0

    itens_audit = audit_store.listar_itens(lote_id)
    assert len(itens_audit) == 1
    assert itens_audit[0]["status"] == "erro_resolucao"
    assert itens_audit[0]["item_key"] == "err-trilha-hash"


def test_trilha_completa_sem_itens_sendaveis_lista_vazia_nao_envia():
    """
    Quando extrair_itens_sendaveis retorna lista vazia e o lote é aprovado
    com lista vazia, enviar_lote deve retornar sucesso sem chamar o cliente.
    """
    lote_id = "trilha-vazia-001"

    # Todos os lançamentos são não-sendáveis
    resultados_etapa3 = [
        _resultado_etapa3(lancamentos_validos=[_lancamento_nao_sendavel()])
    ]
    resumo = gerar_resumo_lote(resultados_etapa3)
    aprov_store = _aprov_store_mem()
    estado = criar_estado_lote(lote_id=lote_id, resumo=resumo, store=aprov_store)

    itens_sendaveis = extrair_itens_sendaveis(resultados_etapa3)
    assert itens_sendaveis == []

    itens_store = _itens_store_mem()
    aprovar_lote(
        estado,
        aprovado_por="gestor-vazio",
        store=aprov_store,
        itens_sendaveis=itens_sendaveis,
        itens_store=itens_store,
    )

    cliente = FakeClient()
    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=cliente, resolvedor=ResolvedorDireto(),
    )

    assert res.sucesso is True
    assert res.total_sendaveis == 0
    assert cliente.chamadas == []