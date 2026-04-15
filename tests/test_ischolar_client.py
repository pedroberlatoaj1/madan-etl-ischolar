import pandas as pd
import pytest
import requests

from ischolar_client import (
    IScholarClient,
    ResultadoEnvio,
    ResultadoSyncNotas,
    ResultadoLancamentoNota,
    _SlidingWindowRateLimiter,
)


@pytest.fixture
def client() -> IScholarClient:
    # Não faz HTTP real nos testes (métodos serão mockados por teste).
    c = IScholarClient()
    # Evita falha em `_get_headers()` quando os testes chamarem métodos novos.
    c.token = "token_teste"
    c.codigo_escola = "codigo_escola_teste"
    c.base_url = "https://api.ischolar.app"
    return c


def df_notas(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def ok_get(dados) -> ResultadoEnvio:
    return ResultadoEnvio(sucesso=True, transitorio=False, status_code=200, dados=dados)


def transient_get(msg: str = "timeout") -> ResultadoEnvio:
    return ResultadoEnvio(sucesso=False, transitorio=True, status_code=503, mensagem=msg)


def ok_post() -> ResultadoEnvio:
    return ResultadoEnvio(sucesso=True, transitorio=False, status_code=201)


def transient_post(msg: str = "server error") -> ResultadoEnvio:
    return ResultadoEnvio(sucesso=False, transitorio=True, status_code=503, mensagem=msg)


def permanent_post_422(msg: str = "unprocessable") -> ResultadoEnvio:
    return ResultadoEnvio(sucesso=False, transitorio=False, status_code=422, mensagem=msg)


class TestRateLimiter:
    def test_aguarda_quando_janela_esta_cheia(self):
        agora = {"t": 0.0}
        esperas: list[float] = []

        def fake_clock():
            return agora["t"]

        def fake_sleep(segundos: float):
            esperas.append(segundos)
            agora["t"] += segundos

        limiter = _SlidingWindowRateLimiter(
            max_requests=2,
            window_seconds=10,
            clock=fake_clock,
            sleeper=fake_sleep,
        )

        assert limiter.acquire() == 0.0
        assert limiter.acquire() == 0.0
        waited = limiter.acquire()

        assert waited == pytest.approx(10.0)
        assert esperas == [pytest.approx(10.0)]

    def test_libera_sem_espera_quando_janela_expira(self):
        agora = {"t": 0.0}
        esperas: list[float] = []

        limiter = _SlidingWindowRateLimiter(
            max_requests=2,
            window_seconds=10,
            clock=lambda: agora["t"],
            sleeper=lambda segundos: esperas.append(segundos),
        )

        assert limiter.acquire() == 0.0
        assert limiter.acquire() == 0.0

        agora["t"] = 10.1
        assert limiter.acquire() == 0.0
        assert esperas == []


class TestSyncNotasIdempotente:
    def test_get_vazio_notas_novas_viram_created(self, client, monkeypatch):
        df = df_notas(
            [
                {"id_matricula": 115, "identificacao": 2045, "valor": 8.5, "data_lancamento": "2026-03-16"},
                {"id_matricula": 116, "identificacao": 2046, "valor": 9.0, "data_lancamento": "2026-03-16"},
            ]
        )

        monkeypatch.setattr(client, "consultar_notas", lambda id_matricula: ok_get([]))

        created_calls: list[dict] = []

        def fake_criar_nota(**kwargs):
            created_calls.append(kwargs)
            return ok_post()

        monkeypatch.setattr(client, "criar_nota", fake_criar_nota)

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is True
        assert res.transitorio is False
        assert res.total == 2
        assert res.created == 2
        assert res.skipped == 0
        assert res.conflicts == 0
        assert res.failed_permanent == 0
        assert res.failed_transient == 0
        assert len(created_calls) == 2

    def test_get_mesma_avaliacao_e_mesmo_valor_skipped(self, client, monkeypatch):
        df = df_notas(
            [{"id_matricula": 115, "identificacao": 2045, "valor": 8.5, "data_lancamento": "2026-03-16"}]
        )

        # Retorno já contém a mesma identificação e mesmo valor
        monkeypatch.setattr(
            client,
            "consultar_notas",
            lambda id_matricula: ok_get([{"identificacao": 2045, "valor": 8.5}]),
        )

        criar_chamado = {"n": 0}

        def fake_criar_nota(**kwargs):
            criar_chamado["n"] += 1
            return ok_post()

        monkeypatch.setattr(client, "criar_nota", fake_criar_nota)

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is True
        assert res.created == 0
        assert res.skipped == 1
        assert res.conflicts == 0
        assert criar_chamado["n"] == 0

    def test_get_mesma_avaliacao_valor_diferente_conflicts(self, client, monkeypatch):
        df = df_notas(
            [{"id_matricula": 115, "identificacao": 2045, "valor": 7.0, "data_lancamento": "2026-03-16"}]
        )

        monkeypatch.setattr(
            client,
            "consultar_notas",
            lambda id_matricula: ok_get([{"identificacao": 2045, "valor": 8.5}]),
        )

        criar_chamado = {"n": 0}

        def fake_criar_nota(**kwargs):
            criar_chamado["n"] += 1
            return ok_post()

        monkeypatch.setattr(client, "criar_nota", fake_criar_nota)

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is True
        assert res.created == 0
        assert res.skipped == 0
        assert res.conflicts == 1
        assert res.failed_permanent == 0
        assert criar_chamado["n"] == 0
        assert res.detalhes and res.detalhes[0]["erro"] == "Conflito"

    def test_varias_linhas_mesma_matricula_apenas_um_get_por_matricula(self, client, monkeypatch):
        df = df_notas(
            [
                {"id_matricula": 115, "identificacao": 2045, "valor": 8.0, "data_lancamento": "2026-03-16"},
                {"id_matricula": 115, "identificacao": 2046, "valor": 9.0, "data_lancamento": "2026-03-16"},
                {"id_matricula": 116, "identificacao": 2047, "valor": 10.0, "data_lancamento": "2026-03-16"},
            ]
        )

        calls: list[int] = []

        def fake_consultar(id_matricula):
            calls.append(int(id_matricula))
            return ok_get([])  # nada existente

        monkeypatch.setattr(client, "consultar_notas", fake_consultar)
        monkeypatch.setattr(client, "criar_nota", lambda **kwargs: ok_post())

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is True
        assert sorted(calls) == [115, 116]
        assert len(calls) == 2

    def test_erro_transitorio_no_get_retorna_sucesso_false_transitorio_true(self, client, monkeypatch):
        df = df_notas(
            [
                {"id_matricula": 115, "identificacao": 2045, "valor": 8.5, "data_lancamento": "2026-03-16"},
                {"id_matricula": 115, "identificacao": 2046, "valor": 9.0, "data_lancamento": "2026-03-16"},
            ]
        )

        monkeypatch.setattr(client, "consultar_notas", lambda id_matricula: transient_get("timeout"))
        monkeypatch.setattr(client, "criar_nota", lambda **kwargs: ok_post())

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is False
        assert res.transitorio is True
        assert res.failed_transient == 2  # len(group) da matrícula 115
        assert "Falha transitória ao consultar matrícula" in res.mensagem

    def test_erro_transitorio_no_post_apos_algumas_criacoes_aborta_lote(self, client, monkeypatch):
        df = df_notas(
            [
                {"id_matricula": 115, "identificacao": 2045, "valor": 8.5, "data_lancamento": "2026-03-16"},
                {"id_matricula": 115, "identificacao": 2046, "valor": 9.0, "data_lancamento": "2026-03-16"},
                # se chegasse aqui, criaria; mas deve abortar antes
                {"id_matricula": 116, "identificacao": 2047, "valor": 10.0, "data_lancamento": "2026-03-16"},
            ]
        )

        monkeypatch.setattr(client, "consultar_notas", lambda id_matricula: ok_get([]))

        post_calls: list[int] = []

        def fake_post(**kwargs):
            post_calls.append(int(kwargs["identificacao"]))
            if len(post_calls) == 1:
                return ok_post()
            return transient_post("503")

        monkeypatch.setattr(client, "criar_nota", fake_post)

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is False
        assert res.transitorio is True
        assert res.created == 1
        assert res.failed_transient == 1
        # Abortou após a 2ª tentativa de POST (não deve tentar a matrícula 116)
        assert post_calls == [2045, 2046]

    def test_erro_permanente_no_post_422_incrementa_failed_permanent_e_continua(self, client, monkeypatch):
        df = df_notas(
            [
                {"id_matricula": 115, "identificacao": 2045, "valor": 8.5, "data_lancamento": "2026-03-16"},
                {"id_matricula": 115, "identificacao": 2046, "valor": 9.0, "data_lancamento": "2026-03-16"},
            ]
        )

        monkeypatch.setattr(client, "consultar_notas", lambda id_matricula: ok_get([]))

        def fake_post(**kwargs):
            if int(kwargs["identificacao"]) == 2045:
                return permanent_post_422("422")
            return ok_post()

        monkeypatch.setattr(client, "criar_nota", fake_post)

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is True  # lote concluiu deterministicamente
        assert res.transitorio is False
        assert res.created == 1
        assert res.failed_permanent == 1
        assert res.failed_transient == 0
        assert res.conflicts == 0
        assert res.detalhes and res.detalhes[0]["erro"] == "POST failed"

    def test_dataframe_sem_colunas_obrigatorias_sucesso_false_transitorio_false(self, client):
        df = pd.DataFrame([{"id_matricula": 115, "valor": 8.5}])  # faltam identificacao e data_lancamento
        res = client.sync_notas_idempotente(df)
        assert res.sucesso is False
        assert res.transitorio is False
        assert "Colunas obrigatórias ausentes" in res.mensagem

    def test_mistura_created_skipped_conflicts_failed_permanent_no_mesmo_lote(self, client, monkeypatch):
        df = df_notas(
            [
                {"id_matricula": 115, "identificacao": 1, "valor": 8.5, "data_lancamento": "2026-03-16"},  # skip
                {"id_matricula": 115, "identificacao": 2, "valor": 7.0, "data_lancamento": "2026-03-16"},  # conflict
                {"id_matricula": 115, "identificacao": 3, "valor": 9.0, "data_lancamento": "2026-03-16"},  # create ok
                {"id_matricula": 115, "identificacao": 4, "valor": 10.0, "data_lancamento": "2026-03-16"},  # create 422
            ]
        )

        monkeypatch.setattr(
            client,
            "consultar_notas",
            lambda id_matricula: ok_get(
                [
                    {"identificacao": 1, "valor": 8.5},
                    {"identificacao": 2, "valor": 8.5},
                ]
            ),
        )

        def fake_post(**kwargs):
            if int(kwargs["identificacao"]) == 4:
                return permanent_post_422("422")
            return ok_post()

        monkeypatch.setattr(client, "criar_nota", fake_post)

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is True
        assert res.transitorio is False
        assert res.total == 4
        assert res.created == 1
        assert res.skipped == 1
        assert res.conflicts == 1
        assert res.failed_permanent == 1
        assert res.failed_transient == 0

    def test_get_permanente_para_uma_matricula_incrementa_failed_permanent_no_grupo_e_continua(self, client, monkeypatch):
        df = df_notas(
            [
                # matrícula 115 (falha permanente no GET) -> 2 linhas devem contar como failed_permanent
                {"id_matricula": 115, "identificacao": 1, "valor": 8.5, "data_lancamento": "2026-03-16"},
                {"id_matricula": 115, "identificacao": 2, "valor": 9.0, "data_lancamento": "2026-03-16"},
                # matrícula 116 (deve processar normalmente)
                {"id_matricula": 116, "identificacao": 3, "valor": 7.0, "data_lancamento": "2026-03-16"},
            ]
        )

        calls_get: list[int] = []

        def fake_get(id_matricula):
            calls_get.append(int(id_matricula))
            if int(id_matricula) == 115:
                return ResultadoEnvio(sucesso=False, transitorio=False, status_code=400, mensagem="bad request")
            return ok_get([])

        post_calls: list[int] = []

        def fake_post(**kwargs):
            post_calls.append(int(kwargs["id_matricula"]))
            return ok_post()

        monkeypatch.setattr(client, "consultar_notas", fake_get)
        monkeypatch.setattr(client, "criar_nota", fake_post)

        res = client.sync_notas_idempotente(df)
        assert res.sucesso is True  # continua e conclui deterministicamente
        assert res.failed_permanent == 2
        assert res.created == 1  # apenas a linha da matrícula 116
        assert calls_get == [115, 116]
        assert post_calls == [116]
        assert res.detalhes and res.detalhes[0]["erro"] == "GET failed"

    def test_retry_logico_apos_criacao_parcial_e_erro_transitorio_segunda_execucao_pula_ja_criadas(self, client, monkeypatch):
        df = df_notas(
            [
                {"id_matricula": 115, "identificacao": 2045, "valor": 8.5, "data_lancamento": "2026-03-16"},
                {"id_matricula": 115, "identificacao": 2046, "valor": 9.0, "data_lancamento": "2026-03-16"},
            ]
        )

        # Estado simulado do "servidor": o que já foi criado persiste entre execuções.
        server_state: dict[int, dict[int, float]] = {115: {}}
        run = {"n": 0}

        def fake_get(id_matricula):
            m = int(id_matricula)
            existentes = [{"identificacao": k, "valor": v} for k, v in server_state.get(m, {}).items()]
            return ok_get(existentes)

        def fake_post(**kwargs):
            ident = int(kwargs["identificacao"])
            m = int(kwargs["id_matricula"])
            if run["n"] == 1 and ident == 2046:
                # primeira execução: falha transitória na 2ª criação => aborta
                return transient_post("503")
            # sucesso: "cria" no servidor
            server_state.setdefault(m, {})[ident] = float(kwargs["valor"])
            return ok_post()

        monkeypatch.setattr(client, "consultar_notas", fake_get)
        monkeypatch.setattr(client, "criar_nota", fake_post)

        # Execução 1: cria 2045, falha transitória em 2046 e aborta
        run["n"] = 1
        res1 = client.sync_notas_idempotente(df)
        assert res1.sucesso is False
        assert res1.transitorio is True
        assert res1.created == 1
        assert res1.failed_transient == 1
        assert 2045 in server_state[115]

        # Execução 2: GET já vê 2045 existente => skip; cria 2046 => sucesso determinístico
        run["n"] = 2
        res2 = client.sync_notas_idempotente(df)
        assert res2.sucesso is True
        assert res2.transitorio is False
        assert res2.skipped == 1
        assert res2.created == 1
        assert res2.conflicts == 0
        assert res2.failed_permanent == 0


class TestEnviarNotasWrapper:
    def test_enviar_notas_reflete_falha_transitoria(self, client, monkeypatch):
        def fake_sync(df, **kwargs):
            return ResultadoSyncNotas(sucesso=False, transitorio=True, mensagem="GET 503", detalhes=[{"x": 1}])

        monkeypatch.setattr(client, "sync_notas_idempotente", fake_sync)

        res = client.enviar_notas(df_notas([]))
        assert res.sucesso is False
        assert res.transitorio is True
        assert res.mensagem == "GET 503"
        assert res.dados == [{"x": 1}]

    def test_enviar_notas_reflete_falha_nao_transitoria_estrutural(self, client, monkeypatch):
        def fake_sync(df, **kwargs):
            return ResultadoSyncNotas(
                sucesso=False,
                transitorio=False,
                mensagem="Colunas obrigatórias ausentes: {'identificacao'}",
                detalhes=None,
            )

        monkeypatch.setattr(client, "sync_notas_idempotente", fake_sync)

        res = client.enviar_notas(df_notas([]))
        assert res.sucesso is False
        assert res.transitorio is False
        assert "Colunas obrigatórias ausentes" in res.mensagem

    def test_enviar_notas_sucesso_true_quando_lote_conclui_com_conflicts_ou_failed_permanent(self, client, monkeypatch):
        def fake_sync(df, **kwargs):
            return ResultadoSyncNotas(
                sucesso=True,
                transitorio=False,
                total=3,
                created=1,
                skipped=1,
                conflicts=1,
                failed_permanent=1,
                mensagem="Sync concluído com ressalvas",
                detalhes=[{"erro": "Conflito"}, {"erro": "POST failed"}],
            )

        monkeypatch.setattr(client, "sync_notas_idempotente", fake_sync)

        res = client.enviar_notas(df_notas([]))
        assert res.sucesso is True
        assert res.transitorio is False
        assert "Conflitos" in res.mensagem
        assert res.dados and len(res.dados) == 2

    def test_enviar_notas_repassa_job_id_e_kwargs_para_sync(self, client, monkeypatch):
        capturado: dict = {}

        def fake_sync(df, job_id=None, **kwargs):
            capturado["job_id"] = job_id
            capturado["kwargs"] = kwargs
            return ResultadoSyncNotas(sucesso=True, total=len(df))

        monkeypatch.setattr(client, "sync_notas_idempotente", fake_sync)

        df = df_notas([{"id_matricula": 115, "identificacao": 1, "valor": 8.5, "data_lancamento": "2026-03-16"}])
        res = client.enviar_notas(df, job_id=123, origem="google_sheets", dry_run=True)

        assert res.sucesso is True
        assert capturado["job_id"] == 123
        assert capturado["kwargs"] == {"origem": "google_sheets", "dry_run": True}


class FakeResponse:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class TestContratoOficialIScholar:
    def test_montagem_headers_dry_run_lancar_nota(self, client):
        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=True,
        )
        assert isinstance(res, ResultadoLancamentoNota)
        assert res.dry_run is True
        assert res.headers is not None
        assert res.headers["X-Autorizacao"] == "token_teste"
        assert res.headers["X-Codigo-Escola"] == "codigo_escola_teste"
        assert res.endpoint_alvo.endswith("/notas/lanca_nota")

    def test_payload_lancar_nota_com_id_professor(self, client):
        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            id_professor=99,
            valor_bruta=8.5,
            dry_run=True,
        )
        assert res.sucesso is True
        assert res.payload is not None
        assert res.payload["id_professor"] == 99

    def test_payload_lancar_nota_sem_id_professor(self, client):
        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=True,
        )
        assert res.sucesso is True
        assert res.payload is not None
        assert "id_professor" not in res.payload

    def test_normaliza_valor_bruta_para_no_maximo_2_decimais(self, client):
        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.567,
            dry_run=True,
        )
        assert res.payload is not None
        assert res.payload["valor"] == 8.57

    def test_lancar_nota_nao_aceita_valor_ponderado(self, client):
        with pytest.raises(TypeError):
            client.lancar_nota(
                id_matricula=10,
                id_disciplina=1,
                id_avaliacao=2,
                valor_bruta=8.5,
                valor_ponderado=9.0,  # parâmetro inválido para o contrato oficial
                dry_run=True,
            )

    def test_dry_run_nao_chama_api(self, client, monkeypatch):
        def fail_post(*args, **kwargs):
            raise AssertionError("POST deveria ser evitado no dry_run=True")

        monkeypatch.setattr(client.session, "post", fail_post)

        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=True,
        )
        assert res.sucesso is True
        assert res.dry_run is True

    def test_tratamento_erro_http_422_validacao(self, client, monkeypatch):
        def fake_post(*args, **kwargs):
            return FakeResponse(422, text="unprocessable", json_data={"detail": "erro"})

        monkeypatch.setattr(client.session, "post", fake_post)

        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=False,
        )
        assert res.sucesso is False
        assert res.transitorio is False
        assert res.erro_categoria == "validacao"
        assert res.status_code == 422

    def test_tratamento_erro_rede_timeout(self, client, monkeypatch):
        def fake_post(*args, **kwargs):
            raise requests.Timeout("timeout")

        monkeypatch.setattr(client.session, "post", fake_post)

        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=False,
        )
        assert res.sucesso is False
        assert res.transitorio is True
        assert res.erro_categoria == "rede"

    def test_http200_com_status_erro_nao_e_sucesso(self, client, monkeypatch):
        """
        iScholar pode retornar HTTP 200 com corpo {"status": "erro", "mensagem": "..."}
        para erros de negócio (ex.: id_professor obrigatório).
        Nesse caso o lançamento NÃO foi gravado — deve reportar sucesso=False.
        Regressão do bug detectado em 2026-04-01 durante homologação assistida.
        """
        corpo_erro_negocio = {
            "status": "erro",
            "mensagem": "O Curriculo da disciplina exige id_professor obrigatório.",
        }

        def fake_post(*args, **kwargs):
            return FakeResponse(200, json_data=corpo_erro_negocio)

        monkeypatch.setattr(client.session, "post", fake_post)

        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=False,
        )
        assert res.sucesso is False
        assert res.transitorio is False
        assert res.erro_categoria == "negocio"
        assert res.status_code == 200
        assert "id_professor" in res.mensagem

    def test_http200_com_status_erro_preserva_mensagem_da_api(self, client, monkeypatch):
        """Mensagem do campo 'mensagem' do corpo deve ser propagada intacta."""
        mensagem_api = "Erro específico retornado pela API."

        def fake_post(*args, **kwargs):
            return FakeResponse(200, json_data={"status": "erro", "mensagem": mensagem_api})

        monkeypatch.setattr(client.session, "post", fake_post)

        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=False,
        )
        assert res.sucesso is False
        assert res.mensagem == mensagem_api

    def test_http200_sem_status_erro_e_sucesso(self, client, monkeypatch):
        """HTTP 200 com corpo normal (sem chave 'status': 'erro') continua sendo sucesso."""
        def fake_post(*args, **kwargs):
            return FakeResponse(200, json_data={"id": 42, "status": "ok"})

        monkeypatch.setattr(client.session, "post", fake_post)

        res = client.lancar_nota(
            id_matricula=10,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=False,
        )
        assert res.sucesso is True
        assert res.erro_categoria is None

    def test_busca_aluno_mock(self, client, monkeypatch):
        def fake_get(url, params=None, headers=None, timeout=None):
            assert url.endswith("/aluno/busca")
            assert params["id_aluno"] == 123
            return FakeResponse(200, json_data={"id_aluno": 123, "nome": "Ana"})

        monkeypatch.setattr(client.session, "get", fake_get)

        res = client.buscar_aluno(id_aluno=123)
        assert res.sucesso is True
        assert res.dados["id_aluno"] == 123
        assert res.params["id_aluno"] == 123

    def test_busca_aluno_por_ra(self, client, monkeypatch):
        def fake_get(url, params=None, headers=None, timeout=None):
            assert url.endswith("/aluno/busca")
            assert params["numero_re"] == "RA12345"
            return FakeResponse(200, json_data={"id_aluno": 77, "nome": "Bruno"})

        monkeypatch.setattr(client.session, "get", fake_get)

        res = client.buscar_aluno(ra="RA12345")
        assert res.sucesso is True
        assert res.dados["id_aluno"] == 77
        assert res.params["numero_re"] == "RA12345"

    def test_busca_aluno_por_cpf(self, client, monkeypatch):
        def fake_get(url, params=None, headers=None, timeout=None):
            assert url.endswith("/aluno/busca")
            # O client normaliza para dígitos apenas.
            assert params["cpf"] == "12345678900"
            return FakeResponse(200, json_data={"id_aluno": 88, "nome": "Carla"})

        monkeypatch.setattr(client.session, "get", fake_get)

        res = client.buscar_aluno(cpf="123.456.789-00")
        assert res.sucesso is True
        assert res.dados["id_aluno"] == 88
        assert res.params["cpf"] == "12345678900"

    def test_busca_aluno_erro_quando_sem_identificador(self, client):
        import pytest

        with pytest.raises(ValueError, match="informe exatamente um identificador"):
            client.buscar_aluno()

    def test_listar_matriculas_mock_resolve_id(self, client, monkeypatch):
        def fake_get(url, params=None, headers=None, timeout=None):
            assert url.endswith("/matricula/listar")
            assert params["id_aluno"] == 123
            assert params["id_responsavel"] == 7
            return FakeResponse(200, json_data=[{"id_matricula": 456}])

        monkeypatch.setattr(client.session, "get", fake_get)

        res = client.listar_matriculas(
            id_aluno=123,
            id_responsavel=7,
            id_turma=1,
            id_periodo=2,
            id_unidade=3,
            situacao="ATIVO",
            pagina=1,
        )
        assert res.sucesso is True
        assert res.id_matricula_resolvido == 456
        assert res.rastreabilidade["params"]["id_aluno"] == 123

    def test_listar_notas_mock(self, client, monkeypatch):
        def fake_get(url, params=None, headers=None, timeout=None):
            assert url.endswith("/diario/notas")
            assert params["id_matricula"] == 456
            assert params["identificacao"] == 999
            assert params["tipo"] == "nota"
            return FakeResponse(200, json_data=[{"identificacao": 999, "valor": 8.5}])

        monkeypatch.setattr(client.session, "get", fake_get)

        res = client.listar_notas(id_matricula=456, identificacao=999, tipo="nota")
        assert res.sucesso is True
        assert isinstance(res.dados, list)
        assert res.dados[0]["identificacao"] == 999

    def test_lancar_nota_resolve_id_matricula_via_busca_e_listagem(self, client, monkeypatch):
        # mock GET para buscar aluno e listar matrículas
        def fake_get(url, params=None, headers=None, timeout=None):
            if url.endswith("/aluno/busca"):
                assert params["id_aluno"] == 123
                return FakeResponse(200, json_data={"id_aluno": 123})
            if url.endswith("/matricula/listar"):
                assert params["id_aluno"] == 123
                return FakeResponse(200, json_data=[{"id_matricula": 456}])
            raise AssertionError(f"GET inesperado: {url}")

        monkeypatch.setattr(client.session, "get", fake_get)

        # mock POST para verificar payload final
        def fake_post(url, json=None, headers=None, timeout=None):
            assert url.endswith("/notas/lanca_nota")
            assert json["id_matricula"] == 456
            assert json["id_disciplina"] == 1
            assert json["id_avaliacao"] == 2
            assert json["valor"] == 8.5
            assert "id_professor" not in json
            return FakeResponse(201, json_data={"ok": True})

        monkeypatch.setattr(client.session, "post", fake_post)

        res = client.lancar_nota(
            id_matricula=None,
            id_aluno=123,
            matricula_resolver_params={"id_responsavel": 7, "id_turma": 1, "id_periodo": 2, "id_unidade": 3, "situacao": "ATIVO", "pagina": 1},
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=False,
        )
        assert res.sucesso is True
        assert res.dados is not None

    def test_idempotencia_sem_deduplicacao_previa(self, client, monkeypatch):
        # Se o client fizesse GET/consulta de notas antes do POST, este teste falharia.
        def fail_get(*args, **kwargs):
            raise AssertionError("Não deveria haver chamadas GET para deduplicação antes do POST.")

        monkeypatch.setattr(client.session, "get", fail_get)
        monkeypatch.setattr(client, "listar_notas", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("listar_notas não deveria ser chamado")))

        def fake_post(url, json=None, headers=None, timeout=None):
            assert url.endswith("/notas/lanca_nota")
            assert json["id_matricula"] == 456
            return FakeResponse(201, json_data={"ok": True})

        monkeypatch.setattr(client.session, "post", fake_post)

        res = client.lancar_nota(
            id_matricula=456,
            id_disciplina=1,
            id_avaliacao=2,
            valor_bruta=8.5,
            dry_run=False,
        )
        assert res.sucesso is True
