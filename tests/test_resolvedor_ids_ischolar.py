"""
test_resolvedor_ids_ischolar.py — Resolvedor híbrido de IDs iScholar

Cobre os 11 cenários exigidos:
  1.  Resolução bem-sucedida de matrícula via API mockada
  2.  Erro de matrícula ambígua
  3.  Erro de matrícula ausente (nenhuma matrícula encontrada)
  4.  Disciplina encontrada via DE-PARA
  5.  Disciplina ausente no DE-PARA
  6.  Avaliação encontrada via DE-PARA
  7.  Avaliação ausente no DE-PARA
  8.  Professor opcional omitido (id_professor=None sem erro)
  9.  Professor obrigatório sem mapa → erro
 10.  Fluxo de envio novo usando resolvedor híbrido em dry_run
 11.  Garantia de que não há fallback silencioso por nome ou heurística não confirmada

Adicionais:
  - identificador_aluno_insuficiente (sem ra/cpf/id_aluno)
  - erro_api_transitorio na busca
  - lookup de avaliação com fallback componente-apenas
  - normalização de acentos no lookup de disciplina
  - categorias de erro em rastreabilidade

Convenções:
  - pytest puro, sem mock.patch
  - FakeClient inline — sem HTTP real, sem pandas
  - Dependências injetadas explicitamente
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import pytest

from resolvedor_ids_ischolar import (
    ResolvedorIDsHibrido,
    _extrair_identificador_aluno,
    _lookup_avaliacao,
    _normalizar_chave,
    carregar_mapa_avaliacoes,
    carregar_mapa_disciplinas,
    carregar_mapa_professores,
    validar_mapa_disciplinas,
    validar_mapa_avaliacoes,
)


# ---------------------------------------------------------------------------
# Stubs de IScholarClient (sem pandas, sem requests)
# ---------------------------------------------------------------------------

@dataclass
class FakeBuscaAluno:
    sucesso: bool
    dados: Any = None
    mensagem: str = ""
    transitorio: bool = False
    status_code: Optional[int] = 200
    endpoint_alvo: str = "https://api.ischolar.app/aluno/busca"
    erro_categoria: Optional[str] = None


@dataclass
class FakeListagemMatriculas:
    sucesso: bool
    id_matricula_resolvido: Optional[int] = None
    mensagem: str = ""
    transitorio: bool = False
    status_code: Optional[int] = 200
    endpoint_alvo: str = "https://api.ischolar.app/matricula/listar"
    rastreabilidade: dict = field(default_factory=dict)
    erro_categoria: Optional[str] = None


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
    """
    Stub de IScholarClient para testes do resolvedor híbrido.
    Configurado por cenário via parâmetros do construtor.
    """

    def __init__(
        self,
        busca_aluno_resultado: Optional[FakeBuscaAluno] = None,
        listagem_matriculas_resultado: Optional[FakeListagemMatriculas] = None,
    ) -> None:
        self._busca = busca_aluno_resultado or FakeBuscaAluno(
            sucesso=True,
            dados={"id_aluno": 42},
        )
        self._listagem = listagem_matriculas_resultado or FakeListagemMatriculas(
            sucesso=True,
            id_matricula_resolvido=999,
        )
        self.chamadas_buscar_aluno: list[dict] = []
        self.chamadas_listar_matriculas: list[dict] = []
        self.chamadas_lancar_nota: list[dict] = []

    def buscar_aluno(
        self,
        *,
        id_aluno: Optional[int] = None,
        ra: Optional[str] = None,
        cpf: Optional[str] = None,
    ) -> FakeBuscaAluno:
        self.chamadas_buscar_aluno.append(dict(id_aluno=id_aluno, ra=ra, cpf=cpf))
        return self._busca

    def listar_matriculas(
        self,
        *,
        id_aluno: int,
        resolver_id_matricula: bool = True,
        **kwargs: Any,
    ) -> FakeListagemMatriculas:
        self.chamadas_listar_matriculas.append(dict(id_aluno=id_aluno))
        return self._listagem

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
        self.chamadas_lancar_nota.append(dict(
            id_matricula=id_matricula, id_disciplina=id_disciplina,
            id_avaliacao=id_avaliacao, valor_bruta=valor_bruta,
            id_professor=id_professor, dry_run=dry_run,
        ))
        return FakeResultadoLancamento(
            sucesso=True, dry_run=dry_run,
            mensagem="dry_run=True: payload montado." if dry_run else "ok",
            payload={"id_matricula": id_matricula, "id_disciplina": id_disciplina},
        )


# ---------------------------------------------------------------------------
# Mapas de teste (inline, sem arquivos no disco)
# ---------------------------------------------------------------------------

MAPA_DISC = {
    "matematica": 101,
    "portugues": 102,
    "historia": 103,
    "ed fisica": 104,
}

MAPA_AVAL = [
    {"componente": "av1", "trimestre": "1", "id_avaliacao": 201},
    {"componente": "av1", "trimestre": "2", "id_avaliacao": 202},
    {"componente": "av2", "trimestre": "1", "id_avaliacao": 211},
    {"componente": "simulado",              "id_avaliacao": 230},  # sem trimestre
    {"componente": "recuperacao", "trimestre": "1", "id_avaliacao": 107},
    {"componente": "recuperacao", "trimestre": "2", "id_avaliacao": 108},
    {"componente": "recuperacao", "trimestre": "3", "id_avaliacao": 109},
    {"componente": "recuperacao_final", "id_avaliacao": 110},
]

MAPA_PROF = {
    "matematica prof silva": 301,   # normalized: hyphens removed by _normalizar_chave
    "portugues profa lima":  302,   # matches _normalizar_chave("Português - Profa Lima")
}


def _resolvedor(
    *,
    busca: Optional[FakeBuscaAluno] = None,
    listagem: Optional[FakeListagemMatriculas] = None,
    mapa_disc: dict = None,
    mapa_aval: list = None,
    mapa_prof: dict = None,
    professor_obrigatorio: bool = False,
) -> tuple[ResolvedorIDsHibrido, FakeClient]:
    cliente = FakeClient(
        busca_aluno_resultado=busca,
        listagem_matriculas_resultado=listagem,
    )
    r = ResolvedorIDsHibrido(
        cliente=cliente,
        mapa_disciplinas=mapa_disc if mapa_disc is not None else MAPA_DISC,
        mapa_avaliacoes=mapa_aval if mapa_aval is not None else MAPA_AVAL,
        mapa_professores=mapa_prof if mapa_prof is not None else MAPA_PROF,
        professor_obrigatorio=professor_obrigatorio,
    )
    return r, cliente


def _lancamento(
    *,
    ra: str = "12345",
    cpf: str = None,
    id_aluno: int = None,
    turma: str = "T1",
    disciplina: str = "Matemática",
    componente: str = "av1",
    trimestre: str = "1",
    frente_professor: str = None,
    nota: float = 8.0,
) -> dict:
    l = {
        "estudante":          "Ana Silva",
        "turma":              turma,
        "disciplina":         disciplina,
        "componente":         componente,
        "trimestre":          trimestre,
        "nota_ajustada_0a10": nota,
        "sendavel":           True,
        "hash_conteudo":      "abc123",
        "linha_origem":       1,
    }
    if ra is not None:
        l["ra"] = ra
    if cpf is not None:
        l["cpf"] = cpf
    if id_aluno is not None:
        l["id_aluno"] = id_aluno
    if frente_professor is not None:
        l["frente_professor"] = frente_professor
    return l


# ---------------------------------------------------------------------------
# 1. Resolução bem-sucedida de matrícula via API mockada
# ---------------------------------------------------------------------------

def test_matricula_resolvida_via_ra():
    """Cenário 1: ra presente → buscar_aluno → listar_matriculas → id_matricula resolvido."""
    r, cliente = _resolvedor()
    resultado = r.resolver_ids(_lancamento(ra="RA001"))

    assert resultado.resolvido
    assert resultado.id_matricula == 999
    assert resultado.id_disciplina == 101
    assert resultado.id_avaliacao == 201
    assert not resultado.erros
    assert len(cliente.chamadas_buscar_aluno) == 1
    assert cliente.chamadas_buscar_aluno[0]["ra"] == "RA001"
    assert len(cliente.chamadas_listar_matriculas) == 1
    assert resultado.rastreabilidade["fonte_resolucao"]["id_matricula"] == \
        "api:buscar_aluno+listar_matriculas"


def test_matricula_resolvida_via_id_aluno_direto():
    """id_aluno no lançamento → pula buscar_aluno, vai direto para listar_matriculas."""
    r, cliente = _resolvedor()
    resultado = r.resolver_ids(_lancamento(ra=None, id_aluno=42))

    assert resultado.resolvido
    assert resultado.id_matricula == 999
    # buscar_aluno não deve ser chamado quando id_aluno já está presente
    assert len(cliente.chamadas_buscar_aluno) == 0
    assert len(cliente.chamadas_listar_matriculas) == 1
    assert cliente.chamadas_listar_matriculas[0]["id_aluno"] == 42


def test_matricula_resolvida_via_cpf():
    """cpf presente → buscar_aluno(cpf=...) → matrícula resolvida."""
    r, cliente = _resolvedor()
    resultado = r.resolver_ids(_lancamento(ra=None, cpf="123.456.789-00"))

    assert resultado.resolvido
    assert len(cliente.chamadas_buscar_aluno) == 1
    assert cliente.chamadas_buscar_aluno[0]["cpf"] == "123.456.789-00"


# ---------------------------------------------------------------------------
# 2. Erro de matrícula ambígua
# ---------------------------------------------------------------------------

def test_matricula_ambigua():
    """Cenário 2: listar_matriculas retorna múltiplos ids distintos → matricula_ambigua."""
    listagem_ambigua = FakeListagemMatriculas(
        sucesso=False,
        id_matricula_resolvido=None,
        mensagem="Resposta retornou múltiplos `id_matricula` distintos; resolução não determinística.",
    )
    r, _ = _resolvedor(listagem=listagem_ambigua)
    resultado = r.resolver_ids(_lancamento())

    assert not resultado.resolvido
    assert resultado.id_matricula is None
    assert "matricula_ambigua" in resultado.rastreabilidade["categorias_erro"]
    assert any("matricula_ambigua" in e for e in resultado.erros)


def test_matricula_ambigua_nao_desempata():
    """Garantia: não há lógica de desempate silencioso — bloqueia sempre."""
    listagem_ambigua = FakeListagemMatriculas(
        sucesso=False,
        id_matricula_resolvido=None,
        mensagem="múltiplos id_matricula distintos",
    )
    r, cliente = _resolvedor(listagem=listagem_ambigua)
    resultado = r.resolver_ids(_lancamento())

    # Deve bloquear — não pode ter inventado um id_matricula
    assert resultado.id_matricula is None
    assert not resultado.resolvido


# ---------------------------------------------------------------------------
# 3. Erro de matrícula ausente (nenhuma matrícula encontrada)
# ---------------------------------------------------------------------------

def test_matricula_nao_encontrada_api_falha():
    """Cenário 3: buscar_aluno retorna sucesso=False → matricula_nao_encontrada."""
    busca_falha = FakeBuscaAluno(
        sucesso=False,
        mensagem="404: aluno não encontrado",
        status_code=404,
    )
    r, _ = _resolvedor(busca=busca_falha)
    resultado = r.resolver_ids(_lancamento())

    assert not resultado.resolvido
    assert resultado.id_matricula is None
    assert "matricula_nao_encontrada" in resultado.rastreabilidade["categorias_erro"]


def test_matricula_nao_encontrada_listagem_vazia():
    """listar_matriculas retorna sucesso=False sem múltiplos → matricula_nao_encontrada."""
    listagem_vazia = FakeListagemMatriculas(
        sucesso=False,
        id_matricula_resolvido=None,
        mensagem="Nenhuma matrícula retornada.",
    )
    r, _ = _resolvedor(listagem=listagem_vazia)
    resultado = r.resolver_ids(_lancamento())

    assert "matricula_nao_encontrada" in resultado.rastreabilidade["categorias_erro"]
    assert resultado.id_matricula is None


def test_identificador_aluno_insuficiente():
    """Lançamento sem ra/cpf/id_aluno → identificador_aluno_insuficiente."""
    r, cliente = _resolvedor()
    lancamento = _lancamento(ra=None, cpf=None, id_aluno=None)

    resultado = r.resolver_ids(lancamento)

    assert not resultado.resolvido
    assert resultado.id_matricula is None
    assert "identificador_aluno_insuficiente" in resultado.rastreabilidade["categorias_erro"]
    # buscar_aluno não deve ter sido chamado
    assert len(cliente.chamadas_buscar_aluno) == 0


def test_api_transitoria_marca_categoria_correta():
    """Falha de rede/5xx → erro_api_transitorio, não matricula_nao_encontrada."""
    busca_transitoria = FakeBuscaAluno(
        sucesso=False,
        transitorio=True,
        mensagem="503: Service Unavailable",
        status_code=503,
    )
    r, _ = _resolvedor(busca=busca_transitoria)
    resultado = r.resolver_ids(_lancamento())

    assert "erro_api_transitorio" in resultado.rastreabilidade["categorias_erro"]
    # Não deve classificar erroneamente como matricula_nao_encontrada
    assert "matricula_nao_encontrada" not in resultado.rastreabilidade["categorias_erro"]


# ---------------------------------------------------------------------------
# 4. Disciplina encontrada via DE-PARA
# ---------------------------------------------------------------------------

def test_disciplina_encontrada_exata():
    """Cenário 4: disciplina exata no mapa → id_disciplina resolvido."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(disciplina="matematica"))

    assert resultado.id_disciplina == 101
    assert resultado.rastreabilidade["fonte_resolucao"]["id_disciplina"] == \
        "de_para_local:mapa_disciplinas"


def test_disciplina_encontrada_com_acentos():
    """Normalização de acentos: 'Matemática' → 'matematica' → 101."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(disciplina="Matemática"))

    assert resultado.id_disciplina == 101


def test_disciplina_encontrada_case_insensitive():
    """'HISTÓRIA' normaliza para 'historia' → 103."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(disciplina="HISTÓRIA"))

    assert resultado.id_disciplina == 103


# ---------------------------------------------------------------------------
# 5. Disciplina ausente no DE-PARA
# ---------------------------------------------------------------------------

def test_disciplina_sem_mapeamento():
    """Cenário 5: disciplina não presente no mapa → disciplina_sem_mapeamento."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(disciplina="Filosofia"))

    assert resultado.id_disciplina is None
    assert "disciplina_sem_mapeamento" in resultado.rastreabilidade["categorias_erro"]
    assert any("disciplina_sem_mapeamento" in e for e in resultado.erros)
    assert not resultado.resolvido


def test_disciplina_sem_mapeamento_nao_usa_nome_vizinho():
    """
    Cenário 11 (parcial): não há fallback silencioso.
    'Matematica2' não resolve para 'matematica'.
    """
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(disciplina="Matematica2"))

    assert resultado.id_disciplina is None
    assert "disciplina_sem_mapeamento" in resultado.rastreabilidade["categorias_erro"]


# ---------------------------------------------------------------------------
# 6. Avaliação encontrada via DE-PARA
# ---------------------------------------------------------------------------

def test_avaliacao_encontrada_componente_trimestre():
    """Cenário 6: av1+trimestre 1 → 201."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="av1", trimestre="1"))

    assert resultado.id_avaliacao == 201
    assert resultado.rastreabilidade["fonte_resolucao"]["id_avaliacao"] == \
        "de_para_local:mapa_avaliacoes"


def test_avaliacao_encontrada_componente_trim2():
    """av1+trimestre 2 → 202."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="av1", trimestre="2"))

    assert resultado.id_avaliacao == 202


def test_avaliacao_fallback_sem_trimestre():
    """simulado sem trimestre → fallback entry 230."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="simulado", trimestre=None))

    assert resultado.id_avaliacao == 230


def test_avaliacao_fallback_trimestre_desconhecido():
    """
    simulado com trimestre "99" não encontrado → tenta fallback sem trimestre → 230.
    Componente `simulado` só tem entrada sem trimestre no mapa.
    """
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="simulado", trimestre="99"))

    # Fallback: trimestre 99 não existe, mas simulado sem trimestre existe
    assert resultado.id_avaliacao == 230


def test_avaliacao_recuperacao_t1_resolve_id_107():
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="recuperacao", trimestre="t1"))

    assert resultado.id_avaliacao == 107
    assert resultado.resolvido


def test_avaliacao_recuperacao_t2_resolve_id_108():
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="recuperacao", trimestre="t2"))

    assert resultado.id_avaliacao == 108
    assert resultado.resolvido


def test_avaliacao_recuperacao_t3_bloqueia_com_mensagem_clara():
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="recuperacao", trimestre="t3"))

    assert resultado.id_avaliacao is None
    assert not resultado.resolvido
    assert any(
        "recuperacao trimestral T3 nao existe" in erro
        and "recuperacao_final" in erro
        for erro in resultado.erros
    )
    assert resultado.rastreabilidade["fonte_resolucao"]["id_avaliacao"] == \
        "nao_resolvido:regra_recuperacao_t3"


def test_avaliacao_recuperacao_final_t3_resolve_id_110():
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="recuperacao_final", trimestre="t3"))

    assert resultado.id_avaliacao == 110
    assert resultado.resolvido


def test_avaliacao_recuperacao_final_t1_bloqueia_com_mensagem_clara():
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="recuperacao_final", trimestre="t1"))

    assert resultado.id_avaliacao is None
    assert not resultado.resolvido
    assert any(
        "recuperacao_final so existe no T3" in erro
        for erro in resultado.erros
    )
    assert resultado.rastreabilidade["fonte_resolucao"]["id_avaliacao"] == \
        "nao_resolvido:regra_recuperacao_final_fora_t3"


# ---------------------------------------------------------------------------
# 7. Avaliação ausente no DE-PARA
# ---------------------------------------------------------------------------

def test_avaliacao_sem_mapeamento():
    """Cenário 7: componente não presente no mapa → avaliacao_sem_mapeamento."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="tarefa", trimestre="1"))

    assert resultado.id_avaliacao is None
    assert "avaliacao_sem_mapeamento" in resultado.rastreabilidade["categorias_erro"]
    assert any("avaliacao_sem_mapeamento" in e for e in resultado.erros)


def test_avaliacao_sem_mapeamento_nao_usa_componente_vizinho():
    """
    Cenário 11 (parcial): 'av11' não resolve para 'av1'.
    Nenhuma heurística de similaridade silenciosa.
    """
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(componente="av11", trimestre="1"))

    assert resultado.id_avaliacao is None
    assert "avaliacao_sem_mapeamento" in resultado.rastreabilidade["categorias_erro"]


# ---------------------------------------------------------------------------
# 8. Professor opcional omitido
# ---------------------------------------------------------------------------

def test_professor_opcional_sem_frente():
    """Cenário 8: sem frente_professor + professor_obrigatorio=False → id_professor=None sem erro."""
    r, _ = _resolvedor(professor_obrigatorio=False)
    resultado = r.resolver_ids(_lancamento(frente_professor=None))

    assert resultado.id_professor is None
    # Não deve haver erro de professor
    assert "professor_sem_mapeamento" not in resultado.rastreabilidade["categorias_erro"]
    # O resto pode resolver normalmente
    assert resultado.id_matricula == 999
    assert resultado.id_disciplina == 101
    assert resultado.id_avaliacao == 201


def test_professor_opcional_frente_sem_mapa():
    """frente presente mas sem mapeamento + professor_obrigatorio=False → None sem bloquear."""
    r, _ = _resolvedor(professor_obrigatorio=False)
    resultado = r.resolver_ids(_lancamento(frente_professor="Biologia - Prof Desconhecido"))

    assert resultado.id_professor is None
    assert "professor_sem_mapeamento" not in resultado.rastreabilidade["categorias_erro"]
    # Demais campos podem ter resolvido
    assert resultado.id_disciplina == 101


def test_professor_opcional_com_mapeamento():
    """frente mapeada + professor_obrigatorio=False → id_professor resolvido."""
    r, _ = _resolvedor(professor_obrigatorio=False)
    resultado = r.resolver_ids(_lancamento(frente_professor="Matemática - Prof Silva"))

    assert resultado.id_professor == 301
    assert resultado.rastreabilidade["fonte_resolucao"]["id_professor"] == \
        "de_para_local:mapa_professores"


# ---------------------------------------------------------------------------
# 9. Professor obrigatório sem mapa → erro
# ---------------------------------------------------------------------------

def test_professor_obrigatorio_sem_frente_bloqueia():
    """Cenário 9: professor_obrigatorio=True, sem frente_professor → professor_sem_mapeamento."""
    r, _ = _resolvedor(professor_obrigatorio=True)
    resultado = r.resolver_ids(_lancamento(frente_professor=None))

    assert not resultado.resolvido
    assert "professor_sem_mapeamento" in resultado.rastreabilidade["categorias_erro"]
    assert any("professor_sem_mapeamento" in e for e in resultado.erros)


def test_professor_obrigatorio_frente_sem_mapeamento_bloqueia():
    """professor_obrigatorio=True, frente presente mas sem mapeamento → erro."""
    r, _ = _resolvedor(professor_obrigatorio=True)
    resultado = r.resolver_ids(_lancamento(frente_professor="Física - Prof Anônimo"))

    assert not resultado.resolvido
    assert resultado.id_professor is None
    assert "professor_sem_mapeamento" in resultado.rastreabilidade["categorias_erro"]


def test_professor_obrigatorio_com_mapeamento_resolve():
    """professor_obrigatorio=True com mapeamento correto → resolve sem erro."""
    r, _ = _resolvedor(professor_obrigatorio=True)
    resultado = r.resolver_ids(_lancamento(frente_professor="Matemática - Prof Silva"))

    assert resultado.id_professor == 301
    assert "professor_sem_mapeamento" not in resultado.rastreabilidade["categorias_erro"]


def test_professor_mapa_injetado_com_chave_bruta_resolve():
    """
    Mapa injetado programaticamente com chaves não-normalizadas (hífens, acentos)
    deve resolver igual a um mapa carregado via carregar_mapa_professores.

    Garante que ResolvedorIDsHibrido.__init__ normaliza internamente,
    independente da origem do mapa.
    """
    r, _ = _resolvedor(
        mapa_prof={"Matemática - Prof Silva": 301},  # chave bruta, não normalizada
        professor_obrigatorio=False,
    )
    resultado = r.resolver_ids(_lancamento(frente_professor="Matemática - Prof Silva"))

    assert resultado.id_professor == 301
    assert resultado.rastreabilidade["fonte_resolucao"]["id_professor"] == \
        "de_para_local:mapa_professores"


# ---------------------------------------------------------------------------
# Aliases de Frente Única no mapa_professores
# ---------------------------------------------------------------------------

def test_frente_unica_arte_resolve_via_alias_simples():
    """
    wide_format_adapter produz 'arte' (sem sufixo de professor) para colunas
    com frente 'Frente Única'.  O mapa_professores.json deve ter a chave 'arte'
    apontando para o id correto.  Regressão do bug detectado em 2026-04-01.
    """
    r, _ = _resolvedor(
        mapa_prof={"arte": 96},
        professor_obrigatorio=True,
    )
    resultado = r.resolver_ids(_lancamento(frente_professor="arte"))

    assert resultado.id_professor == 96
    assert resultado.resolvido
    assert resultado.rastreabilidade["fonte_resolucao"]["id_professor"] == \
        "de_para_local:mapa_professores"


def test_frente_unica_alias_chave_com_acento_normaliza():
    """
    Mapa injetado com chave acentuada 'Arte' deve normalizar para 'arte'
    e resolver igualmente — consistência com carregar_mapa_professores.
    """
    r, _ = _resolvedor(
        mapa_prof={"Arte": 96},
        professor_obrigatorio=True,
    )
    resultado = r.resolver_ids(_lancamento(frente_professor="arte"))

    assert resultado.id_professor == 96
    assert resultado.resolvido


def test_frente_unica_sem_alias_no_mapa_e_obrigatorio_bloqueia():
    """
    Se a disciplina Frente Única não tem alias no mapa e professor_obrigatorio=True,
    deve gerar erro de resolução (comportamento anterior ao bug fix — garante que a
    verificação de obrigatoriedade continua funcionando para keys ausentes).
    """
    r, _ = _resolvedor(
        mapa_prof={"matematica a": 71},   # mapa sem 'arte'
        professor_obrigatorio=True,
    )
    resultado = r.resolver_ids(_lancamento(frente_professor="arte"))

    assert not resultado.resolvido
    assert resultado.id_professor is None
    assert "professor_sem_mapeamento" in resultado.rastreabilidade["categorias_erro"]


@pytest.mark.parametrize(
    ("frente_professor", "id_professor"),
    [
        ("Matemática A - Daniel", 66),
        ("Matemática B - Luan", 71),
        ("Matemática C - Carioca", 57),
        ("Biologia A - Perrone", 86),
        ("Geografia A - Carla", 72),
        ("Geografia B - Moreto", 165),
    ],
)
def test_mapa_repo_tem_alias_explicito_2o_ano(frente_professor: str, id_professor: int):
    from pathlib import Path

    mapa = carregar_mapa_professores(
        Path(__file__).resolve().parents[1] / "mapa_professores.json"
    )
    r, _ = _resolvedor(
        mapa_prof=mapa,
        professor_obrigatorio=True,
    )

    resultado = r.resolver_ids(_lancamento(frente_professor=frente_professor))

    assert resultado.id_professor == id_professor
    assert resultado.resolvido


# ---------------------------------------------------------------------------
# 10. Fluxo de envio novo usando resolvedor híbrido em dry_run
# ---------------------------------------------------------------------------

def test_fluxo_envio_dry_run_com_resolvedor_hibrido():
    """
    Cenário 10: integração com enviar_lote em dry_run usando ResolvedorIDsHibrido.
    Verifica que o resolvedor hybrid plugs corretamente no envio_lote.
    """
    from aprovacao_lote import EstadoAprovacaoLote
    from envio_lote import enviar_lote
    from lote_itens_store import LoteItensStore

    resolvedor, cliente = _resolvedor()

    # Lançamento sendável com ra para resolução de matrícula
    lancamento = {
        "estudante":          "Ana Silva",
        "turma":              "T1",
        "disciplina":         "Matemática",
        "componente":         "av1",
        "trimestre":          "1",
        "nota_ajustada_0a10": 8.0,
        "sendavel":           True,
        "hash_conteudo":      "dryhybrid001",
        "linha_origem":       1,
        "ra":                 "RA999",
    }

    lote_id = "dry-hybrid-test"
    estado = EstadoAprovacaoLote(
        lote_id=lote_id,
        status="aprovado_para_envio",
        elegivel_para_aprovacao=True,
        resumo_atual={},
    )
    itens_store = LoteItensStore(":memory:")
    itens_store.salvar_itens(lote_id, [lancamento])

    res = enviar_lote(
        estado=estado,
        itens_store=itens_store,
        cliente=cliente,
        resolvedor=resolvedor,
        dry_run=True,
    )

    assert res.dry_run is True
    assert res.total_sendaveis == 1
    assert res.total_dry_run == 1
    assert res.total_erros_resolucao == 0
    assert res.sucesso is True
    assert res.itens[0].status == "dry_run"
    # Verifica que o resolvedor hybrid foi chamado
    assert res.itens[0].id_matricula == 999
    assert res.itens[0].id_disciplina == 101
    assert res.itens[0].id_avaliacao == 201


def test_fluxo_envio_dry_run_recuperacao_t1_usa_mesmo_payload_de_nota():
    from aprovacao_lote import EstadoAprovacaoLote
    from envio_lote import enviar_lote
    from lote_itens_store import LoteItensStore

    resolvedor, cliente = _resolvedor()

    lancamento = {
        "estudante": "Ana Silva",
        "turma": "T1",
        "disciplina": "Matemática",
        "componente": "recuperacao",
        "trimestre": "1",
        "nota_ajustada_0a10": 7.5,
        "sendavel": True,
        "hash_conteudo": "dryhybridrec001",
        "linha_origem": 7,
        "ra": "RA997",
    }

    lote_id = "dry-hybrid-rec"
    estado = EstadoAprovacaoLote(
        lote_id=lote_id,
        status="aprovado_para_envio",
        elegivel_para_aprovacao=True,
        resumo_atual={},
    )
    itens_store = LoteItensStore(":memory:")
    itens_store.salvar_itens(lote_id, [lancamento])

    res = enviar_lote(
        estado=estado,
        itens_store=itens_store,
        cliente=cliente,
        resolvedor=resolvedor,
        dry_run=True,
    )

    assert res.sucesso is True
    assert res.total_dry_run == 1
    assert res.itens[0].status == "dry_run"
    assert res.itens[0].id_avaliacao == 107
    assert cliente.chamadas_lancar_nota[0]["id_avaliacao"] == 107
    assert cliente.chamadas_lancar_nota[0]["valor_bruta"] == 7.5


def test_fluxo_envio_dry_run_com_erro_resolucao_disciplina():
    """dry_run com disciplina ausente no mapa → erro_resolucao, não envia."""
    from aprovacao_lote import EstadoAprovacaoLote
    from envio_lote import enviar_lote
    from lote_itens_store import LoteItensStore

    resolvedor, _ = _resolvedor()

    lancamento = {
        "estudante":          "Beto",
        "disciplina":         "Filosofia",  # não está no mapa
        "componente":         "av1",
        "trimestre":          "1",
        "nota_ajustada_0a10": 7.0,
        "sendavel":           True,
        "hash_conteudo":      "dryhybrid002",
        "linha_origem":       2,
        "ra":                 "RA998",
    }

    lote_id = "dry-hybrid-err"
    estado = EstadoAprovacaoLote(
        lote_id=lote_id, status="aprovado_para_envio",
        elegivel_para_aprovacao=True, resumo_atual={},
    )
    itens_store = LoteItensStore(":memory:")
    itens_store.salvar_itens(lote_id, [lancamento])

    res = enviar_lote(
        estado=estado, itens_store=itens_store,
        cliente=FakeClient(), resolvedor=resolvedor, dry_run=True,
    )

    assert res.total_erros_resolucao == 1
    assert res.itens[0].status == "erro_resolucao"
    assert res.sucesso is False


# ---------------------------------------------------------------------------
# 11. Garantia de que não há fallback silencioso
# ---------------------------------------------------------------------------

def test_nao_ha_fallback_silencioso_por_nome_similar():
    """
    Cenário 11: nomes parcialmente similares não resolvem silenciosamente.
    'Mat' não resolve para 'matematica'.
    'av_1' não resolve para 'av1'.
    """
    r, _ = _resolvedor()

    # Disciplina: 'mat' está no mapa como alias explícito, mas 'matematicaa' não
    resultado_disc = r.resolver_ids(_lancamento(disciplina="matematicaa"))
    assert resultado_disc.id_disciplina is None
    assert "disciplina_sem_mapeamento" in resultado_disc.rastreabilidade["categorias_erro"]

    # Avaliação: 'av_1' não é 'av1'
    resultado_aval = r.resolver_ids(_lancamento(componente="av_1", trimestre="1"))
    assert resultado_aval.id_avaliacao is None
    assert "avaliacao_sem_mapeamento" in resultado_aval.rastreabilidade["categorias_erro"]


def test_resultado_tem_fonte_resolucao_por_campo():
    """
    Rastreabilidade deve ter fonte_resolucao com entrada para cada campo tentado.
    """
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento())

    fr = resultado.rastreabilidade["fonte_resolucao"]
    assert "id_matricula" in fr
    assert "id_disciplina" in fr
    assert "id_avaliacao" in fr
    assert "id_professor" in fr


def test_resultado_tem_categorias_erro_vazio_em_sucesso():
    """Em resolução bem-sucedida, categorias_erro deve ser lista vazia."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento())

    assert resultado.rastreabilidade["categorias_erro"] == []
    assert resultado.erros == []


def test_erros_tem_prefixo_de_categoria():
    """Cada mensagem de erro deve conter o prefixo '[categoria_erro]'."""
    r, _ = _resolvedor()
    resultado = r.resolver_ids(_lancamento(ra=None, cpf=None, id_aluno=None))

    for erro in resultado.erros:
        # Deve ter prefixo entre colchetes
        assert erro.startswith("["), f"Erro sem prefixo de categoria: {erro!r}"


# ---------------------------------------------------------------------------
# Testes de carga e validação dos mapas (utilitários)
# ---------------------------------------------------------------------------

def test_carregar_mapa_disciplinas_do_arquivo(tmp_path):
    """carregar_mapa_disciplinas lê JSON corretamente."""
    import json
    arq = tmp_path / "disc.json"
    arq.write_text(json.dumps({
        "_schema": "mapa_disciplinas_v1",
        "disciplinas": {"matematica": 101, "portugues": 102}
    }), encoding="utf-8")

    mapa = carregar_mapa_disciplinas(arq)
    assert mapa["matematica"] == 101
    assert mapa["portugues"] == 102


def test_carregar_mapa_disciplinas_invalido_levanta(tmp_path):
    """JSON sem 'disciplinas' → ValueError."""
    import json
    arq = tmp_path / "bad.json"
    arq.write_text(json.dumps({"errado": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="falta chave 'disciplinas'"):
        carregar_mapa_disciplinas(arq)


def test_validar_mapa_disciplinas_vazio():
    assert len(validar_mapa_disciplinas({})) > 0


def test_carregar_mapa_avaliacoes_do_arquivo(tmp_path):
    import json
    arq = tmp_path / "aval.json"
    arq.write_text(json.dumps({
        "_schema": "mapa_avaliacoes_v1",
        "avaliacoes": [{"componente": "av1", "trimestre": "1", "id_avaliacao": 201}]
    }), encoding="utf-8")

    mapa = carregar_mapa_avaliacoes(arq)
    assert len(mapa) == 1
    assert mapa[0]["id_avaliacao"] == 201


def test_carregar_mapa_professores_do_arquivo(tmp_path):
    import json
    arq = tmp_path / "prof.json"
    arq.write_text(json.dumps({
        "_schema": "mapa_professores_v1",
        "professores": {"mat - prof silva": 301}
    }), encoding="utf-8")

    from resolvedor_ids_ischolar import carregar_mapa_professores
    mapa = carregar_mapa_professores(arq)
    # carregar_mapa_professores normaliza as chaves via _normalizar_chave:
    # "mat - prof silva" → hyphen vira espaço → "mat prof silva"
    assert mapa["mat prof silva"] == 301


# ---------------------------------------------------------------------------
# Testes de helpers internos
# ---------------------------------------------------------------------------

def test_normalizar_chave_remove_acentos():
    assert _normalizar_chave("Matemática") == "matematica"
    assert _normalizar_chave("Ed. Física") == "ed fisica"
    assert _normalizar_chave("  HISTÓRIA  ") == "historia"


def test_lookup_avaliacao_match_exato():
    resultado = _lookup_avaliacao(MAPA_AVAL, "av1", "1")
    assert resultado == 201


def test_lookup_avaliacao_fallback_sem_trimestre():
    resultado = _lookup_avaliacao(MAPA_AVAL, "simulado", "5")
    assert resultado == 230


def test_lookup_avaliacao_nao_encontrado():
    resultado = _lookup_avaliacao(MAPA_AVAL, "tarefa", "1")
    assert resultado is None


def test_lookup_avaliacao_recuperacao_t1():
    resultado = _lookup_avaliacao(MAPA_AVAL, "recuperacao", "t1")
    assert resultado == 107


def test_lookup_avaliacao_recuperacao_t2():
    resultado = _lookup_avaliacao(MAPA_AVAL, "recuperacao", "t2")
    assert resultado == 108


def test_lookup_avaliacao_recuperacao_t3_levanta_erro_explicito():
    with pytest.raises(ValueError, match="recuperacao trimestral T3 nao existe"):
        _lookup_avaliacao(MAPA_AVAL, "recuperacao", "t3")


def test_lookup_avaliacao_recuperacao_final_t3():
    resultado = _lookup_avaliacao(MAPA_AVAL, "recuperacao_final", "t3")
    assert resultado == 110


def test_lookup_avaliacao_recuperacao_final_t1_levanta_erro_explicito():
    with pytest.raises(ValueError, match="recuperacao_final so existe no T3"):
        _lookup_avaliacao(MAPA_AVAL, "recuperacao_final", "t1")


def test_extrair_identificador_aluno_ra():
    l = {"ra": "RA123", "estudante": "Ana"}
    ra, cpf, id_aluno = _extrair_identificador_aluno(l)
    assert ra == "RA123"
    assert cpf is None
    assert id_aluno is None


def test_extrair_identificador_aluno_nenhum():
    l = {"estudante": "Ana"}
    ra, cpf, id_aluno = _extrair_identificador_aluno(l)
    assert ra is None
    assert cpf is None
    assert id_aluno is None


# ---------------------------------------------------------------------------
# MICRO-PATCH — testes dos 3 pontos corrigidos
# ---------------------------------------------------------------------------

# --- Ponto 1: _normalizar_chave — pontuação ---

def test_normalizar_chave_ponto_virado_espaco():
    """`Ed. Física` e `Ed Fisica` devem convergir para a mesma chave."""
    assert _normalizar_chave("Ed. Física") == _normalizar_chave("Ed Fisica")


def test_normalizar_chave_hifen_virado_espaco():
    """`História-Geografia` e `Historia Geografia` devem convergir."""
    assert _normalizar_chave("História-Geografia") == _normalizar_chave("Historia Geografia")


def test_normalizar_chave_barra_virada_espaco():
    """`Hist./Geo.` → `hist geo`."""
    assert _normalizar_chave("Hist./Geo.") == "hist geo"


def test_normalizar_chave_espacos_multiplos_colapsados():
    assert _normalizar_chave("  lingua   portuguesa  ") == "lingua portuguesa"


def test_normalizar_chave_nao_colapsa_partes_distintas():
    """`matematica2` não deve igualar `matematica`."""
    assert _normalizar_chave("matematica2") != _normalizar_chave("matematica")


def test_normalizar_chave_resultado_sem_pontuacao_residual():
    """Nenhum caractere de pontuação deve sobrar após normalização."""
    resultado = _normalizar_chave("Língua Port. (Redação) / Lit.")
    assert "." not in resultado
    assert "/" not in resultado
    assert "(" not in resultado
    assert ")" not in resultado


# --- Ponto 2: _extrair_id_aluno_da_resposta — envelopes ---

from resolvedor_ids_ischolar import _extrair_id_aluno_da_resposta


def test_extrai_id_de_dict_direto():
    assert _extrair_id_aluno_da_resposta({"id_aluno": 42}) == 42


def test_extrai_id_de_lista_unitaria():
    assert _extrair_id_aluno_da_resposta([{"id_aluno": 42}]) == 42


def test_extrai_id_de_envelope_dados_dict():
    assert _extrair_id_aluno_da_resposta({"dados": {"id_aluno": 42}}) == 42


def test_extrai_id_de_envelope_dados_lista():
    assert _extrair_id_aluno_da_resposta({"dados": [{"id_aluno": 42}]}) == 42


def test_extrai_id_de_envelope_result_dict():
    assert _extrair_id_aluno_da_resposta({"result": {"idAluno": 99}}) == 99


def test_extrai_id_de_envelope_result_lista():
    assert _extrair_id_aluno_da_resposta({"result": [{"id_aluno": 7}]}) == 7


def test_extrai_id_de_envelope_aluno():
    assert _extrair_id_aluno_da_resposta({"aluno": {"id_aluno": 55}}) == 55


def test_extrai_id_campo_id_como_fallback():
    """Campo genérico `id` aceito quando id_aluno/idAluno ausentes."""
    assert _extrair_id_aluno_da_resposta({"id": 123}) == 123


def test_nao_extrai_id_envelope_lista_ambigua():
    """Lista com múltiplos alunos distintos → None (não desempata)."""
    assert _extrair_id_aluno_da_resposta(
        {"dados": [{"id_aluno": 1}, {"id_aluno": 2}]}
    ) is None


def test_nao_extrai_id_de_tipo_invalido():
    assert _extrair_id_aluno_da_resposta("string") is None
    assert _extrair_id_aluno_da_resposta(42) is None
    assert _extrair_id_aluno_da_resposta(None) is None


def test_nao_extrai_id_envelope_vazio():
    """Envelope sem conteúdo útil → None."""
    assert _extrair_id_aluno_da_resposta({"dados": {}}) is None
    assert _extrair_id_aluno_da_resposta({"dados": []}) is None


# --- Ponto 3: teste de integração resolvedor + client + lançamento ---

def test_integracao_resolvedor_client_lancamento_completo():
    """
    Integração leve: ResolvedorIDsHibrido + FakeClient + lançamento plausível.

    Valida a costura entre os três componentes:
      - lançamento com ra, disciplina e componente/trimestre válidos
      - FakeClient retornando resposta envelopada em `dados` (novo formato suportado)
      - mapas DE-PARA inline com entradas correspondentes
      - resultado deve ser totalmente resolvido, sem erros, com rastreabilidade
        correta por campo
    """
    # FakeClient com resposta envelopada — testa o novo caminho de desembrulho
    busca_envelopada = FakeBuscaAluno(
        sucesso=True,
        dados={"dados": {"id_aluno": 77}},  # envelope dados→dict
    )
    listagem_ok = FakeListagemMatriculas(
        sucesso=True,
        id_matricula_resolvido=500,
    )

    resolvedor, cliente = _resolvedor(
        busca=busca_envelopada,
        listagem=listagem_ok,
        mapa_disc={"lingua portuguesa": 102},
        mapa_aval=[{"componente": "av2", "trimestre": "2", "id_avaliacao": 212}],
        mapa_prof={"portugues profa lima": 302},  # normalized key
        professor_obrigatorio=False,
    )

    lancamento = {
        "estudante":          "Carla Souza",
        "turma":              "9A",
        "disciplina":         "Língua Portuguesa",   # acentuado → normaliza para "lingua portuguesa"
        "componente":         "av2",
        "trimestre":          "2",
        "nota_ajustada_0a10": 9.0,
        "sendavel":           True,
        "hash_conteudo":      "integ-001",
        "linha_origem":       3,
        "ra":                 "RA777",
        "frente_professor":   "Portugues - Profa Lima",  # deve normalizar e encontrar
    }

    resultado = resolvedor.resolver_ids(lancamento)

    # Resolução completa
    assert resultado.resolvido, f"Esperado resolvido=True; erros: {resultado.erros}"
    assert resultado.id_matricula == 500
    assert resultado.id_disciplina == 102
    assert resultado.id_avaliacao == 212
    assert resultado.id_professor == 302

    # Rastreabilidade por campo
    fr = resultado.rastreabilidade["fonte_resolucao"]
    assert fr["id_matricula"]  == "api:buscar_aluno+listar_matriculas"
    assert fr["id_disciplina"] == "de_para_local:mapa_disciplinas"
    assert fr["id_avaliacao"]  == "de_para_local:mapa_avaliacoes"
    assert fr["id_professor"]  == "de_para_local:mapa_professores"

    # Sem erros
    assert resultado.erros == []
    assert resultado.rastreabilidade["categorias_erro"] == []

    # FakeClient foi acionado corretamente
    assert len(cliente.chamadas_buscar_aluno) == 1
    assert cliente.chamadas_buscar_aluno[0]["ra"] == "RA777"
    assert len(cliente.chamadas_listar_matriculas) == 1
    assert cliente.chamadas_listar_matriculas[0]["id_aluno"] == 77  # extraído do envelope


def test_professor_por_turma_tem_prioridade_sobre_mapa_global():
    """Mapa por turma resolve inversoes de frente entre 1o e 2o ano."""
    r, _ = _resolvedor(
        mapa_prof={
            "matematica a": 71,
            "2b matematica a": 66,
        },
        professor_obrigatorio=True,
    )
    resultado = r.resolver_ids(
        _lancamento(turma="2B", frente_professor="Matemática A")
    )

    assert resultado.id_professor == 66
    assert resultado.rastreabilidade["fonte_resolucao"]["id_professor"] == \
        "de_para_local:mapa_professores_por_turma"


def test_carregar_mapa_professores_do_arquivo_com_mapa_por_turma(tmp_path):
    import json

    arq = tmp_path / "prof.json"
    arq.write_text(json.dumps({
        "_schema": "mapa_professores_v1",
        "professores": {"mat a": 71},
        "professores_por_turma": {
            "2B": {"mat a": 66}
        }
    }), encoding="utf-8")

    mapa = carregar_mapa_professores(arq)
    assert mapa["mat a"] == 71
    assert mapa["2b mat a"] == 66
