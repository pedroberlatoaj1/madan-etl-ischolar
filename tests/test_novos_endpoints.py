"""
test_novos_endpoints.py — Testes com mock para os novos endpoints da API iScholar.

Testa:
  1. Bug #1 fix: envelope "dados" em listar_matriculas
  2. GET /aluno/busca com mock de sucesso e falha
  3. GET /disciplinas — autopreenchimento de mapa_disciplinas
  4. GET /funcionarios/professores — autopreenchimento de mapa_professores
  5. GET /matricula/pega_alunos — fallback quando buscar_aluno não retorna id_aluno

Todos os testes rodam offline sem token, usando mocks de respostas HTTP.
"""

import json
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from ischolar_client import (
    IScholarClient,
    ResultadoBuscaAluno,
    ResultadoListagemDisciplinas,
    ResultadoListagemMatriculas,
    ResultadoListagemProfessores,
    ResultadoPegaAlunos,
)
from resolvedor_ids_ischolar import _extrair_id_aluno_da_resposta


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def client() -> IScholarClient:
    """Cliente com credenciais fake — nunca faz HTTP real."""
    c = IScholarClient()
    c.token = "token_mock_teste"
    c.codigo_escola = "madan_homolog"
    c.base_url = "https://api.ischolar.app"
    return c


def _mock_response(status_code: int, json_data: Any) -> MagicMock:
    """Cria um objeto Response mockado."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = json.dumps(json_data) if json_data else ""
    return resp


# ===================================================================
# MOCKS DE RESPOSTAS DA API
# ===================================================================

# --- GET /aluno/busca ---

MOCK_BUSCAR_ALUNO_SUCESSO = {
    "status": "sucesso",
    "mensagem": "Aluno encontrado",
    "dados": {
        "id_aluno": "42",
        "nome": "JOAO SILVA",
        "numero_re": "12345",
        "cpf": "12345678901",
    },
}

MOCK_BUSCAR_ALUNO_NAO_ENCONTRADO = {
    "status": "erro",
    "mensagem": "Aluno nao encontrado",
    "dados": None,
}

MOCK_BUSCAR_ALUNO_LISTA = {
    "status": "sucesso",
    "mensagem": "Aluno encontrado",
    "dados": [
        {
            "id_aluno": "42",
            "nome": "JOAO SILVA",
            "numero_re": "12345",
        }
    ],
}

# --- GET /matricula/listar (com envelope "dados") ---

MOCK_LISTAR_MATRICULAS_ENVELOPE_DADOS = {
    "status": "sucesso",
    "mensagem": "Matriculas listadas",
    "dados": [
        {
            "id_matricula": "97",
            "id_aluno": "42",
            "id_turma": "5",
            "situacao": "ATIVO",
        }
    ],
}

MOCK_LISTAR_MATRICULAS_MULTIPLAS = {
    "status": "sucesso",
    "mensagem": "Matriculas listadas",
    "dados": [
        {"id_matricula": "97", "id_aluno": "42", "situacao": "ATIVO"},
        {"id_matricula": "98", "id_aluno": "42", "situacao": "TRANSFERIDO"},
    ],
}

# --- GET /disciplinas ---

MOCK_LISTAR_DISCIPLINAS = {
    "status": "sucesso",
    "mensagem": "Disciplinas listadas",
    "dados": [
        {"id": "1", "nome": "ARTE", "abreviacao": "ART"},
        {"id": "2", "nome": "BIOLOGIA", "abreviacao": "BIO"},
        {"id": "3", "nome": "CIENCIAS", "abreviacao": "CIE"},
        {"id": "4", "nome": "EDUCACAO FISICA", "abreviacao": "EDF"},
        {"id": "5", "nome": "FILOSOFIA", "abreviacao": "FIL"},
        {"id": "6", "nome": "FISICA", "abreviacao": "FIS"},
        {"id": "7", "nome": "GEOGRAFIA", "abreviacao": "GEO"},
        {"id": "8", "nome": "HISTORIA", "abreviacao": "HIS"},
        {"id": "9", "nome": "LINGUA INGLESA", "abreviacao": "ING"},
        {"id": "10", "nome": "LINGUA PORTUGUESA", "abreviacao": "POR"},
        {"id": "11", "nome": "MATEMATICA", "abreviacao": "MAT"},
        {"id": "12", "nome": "QUIMICA", "abreviacao": "QUI"},
        {"id": "13", "nome": "SOCIOLOGIA", "abreviacao": "SOC"},
    ],
}

# --- GET /funcionarios/professores ---

MOCK_LISTAR_PROFESSORES = {
    "status": "sucesso",
    "mensagem": "Professores listados",
    "dados": [
        {"id_professor": "2", "nome_professor": "ARNOLD SCHWARZENEGGER"},
        {"id_professor": "5", "nome_professor": "MARIA SILVA"},
        {"id_professor": "8", "nome_professor": "CARLOS OLIVEIRA"},
    ],
}

# --- GET /matricula/pega_alunos ---

MOCK_PEGA_ALUNOS = {
    "status": "sucesso",
    "mensagem": "Alunos da turma",
    "dados": [
        {
            "id_aluno": "42",
            "id_matricula": "97",
            "numero_re": "12345",
            "nome": "JOAO SILVA",
        },
        {
            "id_aluno": "43",
            "id_matricula": "98",
            "numero_re": "12346",
            "nome": "MARIA SOUZA",
        },
        {
            "id_aluno": "44",
            "id_matricula": "99",
            "numero_re": "12347",
            "nome": "PEDRO SANTOS",
        },
    ],
}


# ===================================================================
# 1. TESTES DO BUG #1 — envelope "dados" em listar_matriculas
# ===================================================================

class TestBug1EnvelopeDados:
    """Verifica que listar_matriculas extrai itens do envelope 'dados' da API."""

    def test_envelope_dados_lista(self, client):
        """API retorna {"dados": [...]} — deve extrair a lista."""
        mock_resp = _mock_response(200, MOCK_LISTAR_MATRICULAS_ENVELOPE_DADOS)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_matriculas(id_aluno=42, resolver_id_matricula=True)

        assert resultado.sucesso is True
        assert resultado.id_matricula_resolvido == 97

    def test_envelope_dados_dict_unico(self, client):
        """API retorna {"dados": {item}} — deve tratar como lista de 1."""
        dados_dict = {
            "status": "sucesso",
            "dados": {"id_matricula": "97", "id_aluno": "42"},
        }
        mock_resp = _mock_response(200, dados_dict)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_matriculas(id_aluno=42, resolver_id_matricula=True)

        assert resultado.sucesso is True
        assert resultado.id_matricula_resolvido == 97

    def test_envelope_dados_multiplos_distintos_bloqueia(self, client):
        """Múltiplos id_matricula distintos → fail-closed."""
        mock_resp = _mock_response(200, MOCK_LISTAR_MATRICULAS_MULTIPLAS)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_matriculas(id_aluno=42, resolver_id_matricula=True)

        assert resultado.sucesso is False
        assert "múltiplos" in resultado.mensagem.lower()

    def test_envelope_dados_sem_resolver(self, client):
        """Sem resolver_id_matricula, apenas retorna dados brutos."""
        mock_resp = _mock_response(200, MOCK_LISTAR_MATRICULAS_ENVELOPE_DADOS)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_matriculas(id_aluno=42, resolver_id_matricula=False)

        assert resultado.sucesso is True
        assert resultado.id_matricula_resolvido is None
        assert resultado.dados == MOCK_LISTAR_MATRICULAS_ENVELOPE_DADOS

    def test_lista_direta_sem_envelope(self, client):
        """API retorna lista direta (sem envelope) — compatibilidade."""
        dados_lista = [{"id_matricula": "97", "id_aluno": "42"}]
        mock_resp = _mock_response(200, dados_lista)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_matriculas(id_aluno=42, resolver_id_matricula=True)

        assert resultado.sucesso is True
        assert resultado.id_matricula_resolvido == 97

    def test_envelope_antigo_matriculas_ainda_funciona(self, client):
        """Chave "matriculas" (legado) ainda é reconhecida."""
        dados_antigo = {"matriculas": [{"id_matricula": "50"}]}
        mock_resp = _mock_response(200, dados_antigo)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_matriculas(id_aluno=42, resolver_id_matricula=True)

        assert resultado.sucesso is True
        assert resultado.id_matricula_resolvido == 50


# ===================================================================
# 2. TESTES DO GET /aluno/busca
# ===================================================================

class TestBuscarAluno:
    """Testa buscar_aluno com mocks de respostas reais da API."""

    def test_busca_por_ra_sucesso(self, client):
        mock_resp = _mock_response(200, MOCK_BUSCAR_ALUNO_SUCESSO)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.buscar_aluno(ra="12345")

        assert resultado.sucesso is True
        assert resultado.dados == MOCK_BUSCAR_ALUNO_SUCESSO

    def test_extrair_id_aluno_de_envelope_dados(self):
        """_extrair_id_aluno_da_resposta com envelope {"dados": {...}}."""
        id_aluno = _extrair_id_aluno_da_resposta(MOCK_BUSCAR_ALUNO_SUCESSO)
        assert id_aluno == 42

    def test_extrair_id_aluno_de_envelope_dados_lista(self):
        """_extrair_id_aluno_da_resposta com envelope {"dados": [...]}."""
        id_aluno = _extrair_id_aluno_da_resposta(MOCK_BUSCAR_ALUNO_LISTA)
        assert id_aluno == 42

    def test_extrair_id_aluno_falha_quando_nao_encontrado(self):
        """Dados None → None."""
        id_aluno = _extrair_id_aluno_da_resposta(MOCK_BUSCAR_ALUNO_NAO_ENCONTRADO)
        assert id_aluno is None

    def test_busca_por_ra_inexistente(self, client):
        mock_resp = _mock_response(200, MOCK_BUSCAR_ALUNO_NAO_ENCONTRADO)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.buscar_aluno(ra="99999")

        # A API retorna 200 mesmo sem resultado — sucesso HTTP, mas dados vazios.
        assert resultado.sucesso is True
        id_aluno = _extrair_id_aluno_da_resposta(resultado.dados)
        assert id_aluno is None

    def test_busca_401_token_invalido(self, client):
        mock_resp = _mock_response(401, {"status": "erro", "mensagem": "Token invalido"})
        mock_resp.text = "Token invalido"
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.buscar_aluno(ra="12345")

        assert resultado.sucesso is False
        assert resultado.erro_categoria == "auth"

    def test_busca_403_cloudflare_bloqueado_trata_como_rate_limit(self, client):
        mock_resp = _mock_response(403, None)
        mock_resp.text = "<html><title>Attention Required! | Cloudflare</title>Sorry, you have been blocked</html>"
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.buscar_aluno(ra="12345")

        assert resultado.sucesso is False
        assert resultado.transitorio is True
        assert resultado.erro_categoria == "rate_limit"

    def test_busca_sem_identificador_levanta_valueerror(self, client):
        with pytest.raises(ValueError, match="informe exatamente um"):
            client.buscar_aluno()

    def test_int_coercion_string_id_aluno(self):
        """API retorna id_aluno como string "42" — int() deve funcionar."""
        dados = {"id_aluno": "42"}
        assert _extrair_id_aluno_da_resposta(dados) == 42

    def test_int_coercion_int_id_aluno(self):
        """API retorna id_aluno como int 42 — também funciona."""
        dados = {"id_aluno": 42}
        assert _extrair_id_aluno_da_resposta(dados) == 42


# ===================================================================
# 3. TESTES DO GET /disciplinas — autopreenchimento de mapa
# ===================================================================

class TestListarDisciplinas:
    """Testa listar_disciplinas e lógica de autopreenchimento de mapa."""

    def test_listar_disciplinas_sucesso(self, client):
        mock_resp = _mock_response(200, MOCK_LISTAR_DISCIPLINAS)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_disciplinas()

        assert resultado.sucesso is True
        assert resultado.disciplinas is not None
        assert len(resultado.disciplinas) == 13
        assert resultado.disciplinas[0]["nome"] == "ARTE"
        assert resultado.disciplinas[0]["id"] == "1"

    def test_gerar_mapa_disciplinas_a_partir_do_mock(self, client):
        """Simula o autopreenchimento de mapa_disciplinas.json."""
        mock_resp = _mock_response(200, MOCK_LISTAR_DISCIPLINAS)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_disciplinas()

        assert resultado.disciplinas is not None
        mapa = _gerar_mapa_disciplinas(resultado.disciplinas)

        assert mapa["schema"] == "mapa_disciplinas_v1"
        assert len(mapa["disciplinas"]) == 13
        # Verifica um item
        arte = next(d for d in mapa["disciplinas"] if d["nome_planilha"] == "arte")
        assert arte["id_disciplina"] == 1

    def test_listar_disciplinas_erro_auth(self, client):
        mock_resp = _mock_response(403, {"status": "erro", "mensagem": "Acesso negado"})
        mock_resp.text = "Acesso negado"
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_disciplinas()

        assert resultado.sucesso is False
        assert resultado.erro_categoria == "auth"

    def test_listar_disciplinas_lista_direta(self, client):
        """API retorna lista direta sem envelope."""
        dados_lista = [{"id": "1", "nome": "ARTE"}]
        mock_resp = _mock_response(200, dados_lista)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_disciplinas()

        assert resultado.sucesso is True
        assert resultado.disciplinas is not None
        assert len(resultado.disciplinas) == 1


# ===================================================================
# 4. TESTES DO GET /funcionarios/professores — autopreenchimento
# ===================================================================

class TestListarProfessores:
    """Testa listar_professores e lógica de autopreenchimento de mapa."""

    def test_listar_professores_sucesso(self, client):
        mock_resp = _mock_response(200, MOCK_LISTAR_PROFESSORES)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_professores()

        assert resultado.sucesso is True
        assert resultado.professores is not None
        assert len(resultado.professores) == 3
        assert resultado.professores[0]["id_professor"] == "2"
        assert resultado.professores[0]["nome_professor"] == "ARNOLD SCHWARZENEGGER"

    def test_gerar_mapa_professores_a_partir_do_mock(self, client):
        """Simula o autopreenchimento de mapa_professores.json."""
        mock_resp = _mock_response(200, MOCK_LISTAR_PROFESSORES)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.listar_professores()

        assert resultado.professores is not None
        mapa = _gerar_mapa_professores(resultado.professores)

        assert mapa["schema"] == "mapa_professores_v1"
        assert len(mapa["professores"]) == 3
        arnold = next(p for p in mapa["professores"] if "arnold" in p["nome_planilha"])
        assert arnold["id_professor"] == 2

    def test_listar_professores_erro_rede(self, client):
        """Timeout de rede → erro transitório."""
        import requests as req
        with patch.object(client.session, "get", side_effect=req.Timeout("timeout")):
            resultado = client.listar_professores()

        assert resultado.sucesso is False
        assert resultado.transitorio is True
        assert resultado.erro_categoria == "rede"


# ===================================================================
# 5. TESTES DO FALLBACK pega_alunos
# ===================================================================

class TestPegaAlunos:
    """Testa pega_alunos e a lógica de fallback."""

    def test_pega_alunos_sucesso(self, client):
        mock_resp = _mock_response(200, MOCK_PEGA_ALUNOS)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.pega_alunos(id_turma=5)

        assert resultado.sucesso is True
        assert resultado.alunos is not None
        assert len(resultado.alunos) == 3

    def test_encontrar_aluno_por_ra_no_pega_alunos(self, client):
        """Simula fallback: buscar_aluno não retornou id_aluno, usa pega_alunos."""
        mock_resp = _mock_response(200, MOCK_PEGA_ALUNOS)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.pega_alunos(id_turma=5)

        assert resultado.alunos is not None
        # Procurar o aluno pelo RA (numero_re)
        aluno = _encontrar_aluno_por_ra(resultado.alunos, "12345")
        assert aluno is not None
        assert int(aluno["id_aluno"]) == 42
        assert int(aluno["id_matricula"]) == 97

    def test_fallback_aluno_nao_encontrado_por_ra(self, client):
        """RA inexistente na turma → None."""
        mock_resp = _mock_response(200, MOCK_PEGA_ALUNOS)
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.pega_alunos(id_turma=5)

        assert resultado.alunos is not None
        aluno = _encontrar_aluno_por_ra(resultado.alunos, "99999")
        assert aluno is None

    def test_fallback_completo_buscar_aluno_falha_pega_alunos_resolve(self, client):
        """
        Cenário completo de fallback:
        1. buscar_aluno retorna dados sem id_aluno
        2. pega_alunos retorna a lista com id_aluno + id_matricula
        3. Encontramos o aluno pelo RA
        """
        # Passo 1: buscar_aluno retorna sucesso mas sem id_aluno nos dados
        mock_busca = _mock_response(200, {
            "status": "sucesso",
            "dados": {"nome": "JOAO SILVA", "numero_re": "12345"},  # sem id_aluno!
        })

        # Passo 2: pega_alunos retorna lista completa
        mock_pega = _mock_response(200, MOCK_PEGA_ALUNOS)

        call_count = [0]

        def side_effect_get(*args, **kwargs):
            call_count[0] += 1
            url = args[0] if args else kwargs.get("url", "")
            if "aluno/busca" in url:
                return mock_busca
            elif "pega_alunos" in url:
                return mock_pega
            return _mock_response(404, {})

        with patch.object(client.session, "get", side_effect=side_effect_get):
            # Passo 1: Tenta buscar_aluno
            resultado_busca = client.buscar_aluno(ra="12345")
            assert resultado_busca.sucesso is True
            id_aluno = _extrair_id_aluno_da_resposta(resultado_busca.dados)
            assert id_aluno is None  # Não encontrou id_aluno!

            # Passo 2: Fallback para pega_alunos
            resultado_pega = client.pega_alunos(id_turma=5)
            assert resultado_pega.sucesso is True

            # Passo 3: Resolve pelo RA
            aluno = _encontrar_aluno_por_ra(resultado_pega.alunos, "12345")
            assert aluno is not None
            assert int(aluno["id_aluno"]) == 42
            assert int(aluno["id_matricula"]) == 97

    def test_pega_alunos_erro_404(self, client):
        mock_resp = _mock_response(404, {"status": "erro", "mensagem": "Turma nao encontrada"})
        mock_resp.text = "Turma nao encontrada"
        with patch.object(client.session, "get", return_value=mock_resp):
            resultado = client.pega_alunos(id_turma=999)

        assert resultado.sucesso is False


# ===================================================================
# 6. TESTES DE COERCION int() — strings da API
# ===================================================================

class TestCoercionIntStrings:
    """Verifica que todos os caminhos int() tratam strings da API."""

    def test_coerce_int_strict_string(self, client):
        assert client._coerce_int_strict("97", "id_matricula") == 97

    def test_coerce_int_strict_int(self, client):
        assert client._coerce_int_strict(97, "id_matricula") == 97

    def test_coerce_int_strict_float_inteiro(self, client):
        assert client._coerce_int_strict(97.0, "id_matricula") == 97

    def test_coerce_int_strict_float_decimal_rejeita(self, client):
        with pytest.raises(ValueError, match="inteiro"):
            client._coerce_int_strict(97.5, "id_matricula")

    def test_coerce_int_strict_none_rejeita(self, client):
        with pytest.raises(ValueError, match="nulo"):
            client._coerce_int_strict(None, "id_matricula")

    def test_extract_id_matricula_string(self, client):
        """API retorna id_matricula como string."""
        item = {"id_matricula": "97", "situacao": "ATIVO"}
        assert client._extract_id_matricula_from_item(item) == 97

    def test_extract_id_matricula_int(self, client):
        """API retorna id_matricula como int."""
        item = {"id_matricula": 97, "situacao": "ATIVO"}
        assert client._extract_id_matricula_from_item(item) == 97

    def test_extract_id_matricula_campo_id(self, client):
        """Fallback para campo "id" genérico."""
        item = {"id": "97", "situacao": "ATIVO"}
        assert client._extract_id_matricula_from_item(item) == 97

    def test_extrair_id_aluno_string(self):
        """_extrair_id_aluno_da_resposta com string id."""
        assert _extrair_id_aluno_da_resposta({"id_aluno": "42"}) == 42

    def test_extrair_id_aluno_via_idAluno(self):
        """Forma camelCase."""
        assert _extrair_id_aluno_da_resposta({"idAluno": "42"}) == 42


# ===================================================================
# FUNÇÕES AUXILIARES DE AUTOPREENCHIMENTO DE MAPAS
# ===================================================================

def _normalizar_nome(nome: str) -> str:
    """Normaliza nome para chave de mapa (minúsculas, sem acentos)."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", nome)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sem_acento.strip().lower()


def _gerar_mapa_disciplinas(disciplinas: list[dict]) -> dict:
    """
    Gera esqueleto de mapa_disciplinas.json a partir da resposta de GET /disciplinas.

    Formato de saída:
      {"schema": "mapa_disciplinas_v1", "disciplinas": [
        {"nome_planilha": "arte", "id_disciplina": 1},
        ...
      ]}
    """
    items = []
    for d in disciplinas:
        nome = d.get("nome", "")
        id_val = d.get("id", d.get("id_disciplina", ""))
        if nome and id_val:
            items.append({
                "nome_planilha": _normalizar_nome(nome),
                "id_disciplina": int(id_val),
            })
    return {"schema": "mapa_disciplinas_v1", "disciplinas": items}


def _gerar_mapa_professores(professores: list[dict]) -> dict:
    """
    Gera esqueleto de mapa_professores.json a partir da resposta de GET /funcionarios/professores.

    Formato de saída:
      {"schema": "mapa_professores_v1", "professores": [
        {"nome_planilha": "arnold schwarzenegger", "id_professor": 2},
        ...
      ]}
    """
    items = []
    for p in professores:
        nome = p.get("nome_professor", "")
        id_val = p.get("id_professor", "")
        if nome and id_val:
            items.append({
                "nome_planilha": _normalizar_nome(nome),
                "id_professor": int(id_val),
            })
    return {"schema": "mapa_professores_v1", "professores": items}


def _encontrar_aluno_por_ra(
    alunos: list[dict], ra: str
) -> Optional[dict]:
    """
    Procura um aluno na lista de pega_alunos pelo numero_re (RA).

    Estratégia fail-closed:
    - Compara RA normalizado (strip + lowercase)
    - Retorna None se não encontrar ou se encontrar múltiplos
    """
    ra_norm = str(ra).strip().lower()
    matches = []
    for aluno in alunos:
        aluno_ra = str(aluno.get("numero_re", "")).strip().lower()
        if aluno_ra == ra_norm:
            matches.append(aluno)

    if len(matches) == 1:
        return matches[0]
    return None  # Zero ou múltiplos → fail-closed
