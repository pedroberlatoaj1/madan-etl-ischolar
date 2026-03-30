"""
ischolar_client.py — Cliente HTTP para a API do ERP iScholar.

Este arquivo mantém DOIS caminhos. Código novo deve usar EXCLUSIVAMENTE o
fluxo oficial. O fluxo legado existe apenas para compatibilidade do worker
antigo e não deve ser estendido.

══════════════════════════════════════════════════════════════════
FLUXO OFICIAL (novo) — USE ESTE em código novo
══════════════════════════════════════════════════════════════════
Endpoints confirmados pelo suporte técnico iScholar:

  Resolução de IDs:
    buscar_aluno       → GET  /aluno/busca
    listar_matriculas  → GET  /matricula/listar
    pega_alunos        → GET  /matricula/pega_alunos  (fallback: id_aluno + id_matricula juntos)

  Discovery / autopreenchimento de mapas:
    listar_disciplinas → GET  /disciplinas
    listar_professores → GET  /funcionarios/professores

  Auditoria:
    listar_notas       → GET  /diario/notas

  Lançamento (idempotente):
    lancar_nota        → POST /notas/lanca_nota

══════════════════════════════════════════════════════════════════
FLUXO LEGADO — NÃO usar em código novo
══════════════════════════════════════════════════════════════════
Mantido apenas para o worker existente. Não será expandido.

  consultar_notas         → GET  /diario/notas   (wrapper legado)
  criar_nota              → POST /diario/notas   (endpoint diferente do oficial)
  sync_notas_idempotente  → GET+POST combinado   (lógica própria do worker)
  enviar_notas            → wrapper de sync_notas_idempotente
  get_client              → singleton para o worker legado
  enviar_notas_para_ischolar → entrada do pipeline legado
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Mapping, List

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import config
from logger import configurar_logger

log = configurar_logger("etl.ischolar_client")


@dataclass
class ResultadoEnvio:
    """Resultado da chamada à API, utilizado para decisão do worker."""
    sucesso: bool
    status_code: Optional[int] = None
    transitorio: bool = False
    mensagem: str = ""
    resposta_corpo: Optional[str] = None
    dados: Optional[Any] = None


@dataclass
class ResultadoSyncNotas:
    """Resultado da operação de sincronização idempotente de notas."""
    sucesso: bool
    transitorio: bool = False
    status_code: Optional[int] = None
    total: int = 0
    created: int = 0
    skipped: int = 0
    conflicts: int = 0
    failed_permanent: int = 0
    failed_transient: int = 0
    mensagem: str = ""
    detalhes: Optional[list[dict[str, Any]]] = None


@dataclass
class ResultadoBuscaAluno:
    """Resultado da busca de aluno na API."""

    sucesso: bool
    status_code: Optional[int] = None
    transitorio: bool = False
    erro_categoria: Optional[str] = None  # "auth" | "validacao" | "http" | "rede"
    mensagem: str = ""
    dados: Optional[Any] = None
    endpoint_alvo: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoListagemMatriculas:
    """Resultado da listagem de matrículas e resolução opcional de `id_matricula`."""

    sucesso: bool
    status_code: Optional[int] = None
    transitorio: bool = False
    erro_categoria: Optional[str] = None  # "auth" | "validacao" | "http" | "rede"
    mensagem: str = ""
    dados: Optional[Any] = None

    id_matricula_resolvido: Optional[int] = None
    rastreabilidade: dict[str, Any] = field(default_factory=dict)
    endpoint_alvo: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoListagemNotas:
    """Resultado da listagem de notas já lançadas (auditoria/reconciliação)."""

    sucesso: bool
    status_code: Optional[int] = None
    transitorio: bool = False
    erro_categoria: Optional[str] = None  # "auth" | "validacao" | "http" | "rede"
    mensagem: str = ""
    dados: Optional[Any] = None
    endpoint_alvo: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoLancamentoNota:
    """Resultado do lançamento de nota (POST /notas/lanca_nota)."""

    sucesso: bool
    transitorio: bool = False
    status_code: Optional[int] = None
    erro_categoria: Optional[str] = None  # "auth" | "validacao" | "http" | "rede"
    mensagem: str = ""
    dados: Optional[Any] = None

    # O endpoint /notas/lanca_nota é idempotente segundo suporte técnico.
    idempotente: bool = True

    # Modo auditoria (dry-run)
    dry_run: bool = False
    endpoint_alvo: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    payload: Optional[dict[str, Any]] = None
    rastreabilidade: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoListagemDisciplinas:
    """Resultado de GET /disciplinas — lista de disciplinas cadastradas."""

    sucesso: bool
    status_code: Optional[int] = None
    transitorio: bool = False
    erro_categoria: Optional[str] = None
    mensagem: str = ""
    dados: Optional[Any] = None
    disciplinas: Optional[List[Dict[str, Any]]] = None
    endpoint_alvo: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoListagemProfessores:
    """Resultado de GET /funcionarios/professores — lista de professores."""

    sucesso: bool
    status_code: Optional[int] = None
    transitorio: bool = False
    erro_categoria: Optional[str] = None
    mensagem: str = ""
    dados: Optional[Any] = None
    professores: Optional[List[Dict[str, Any]]] = None
    endpoint_alvo: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultadoPegaAlunos:
    """Resultado de GET /matricula/pega_alunos — busca alunos com id_aluno + id_matricula."""

    sucesso: bool
    status_code: Optional[int] = None
    transitorio: bool = False
    erro_categoria: Optional[str] = None
    mensagem: str = ""
    dados: Optional[Any] = None
    alunos: Optional[List[Dict[str, Any]]] = None
    endpoint_alvo: str = ""
    params: dict[str, Any] = field(default_factory=dict)


class IScholarClient:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        x_autorizacao: Optional[str] = None,
        x_codigo_escola: Optional[str] = None,
        ambiente: Optional[str] = None,
    ):
        self.base_url = self._resolve_base_url(base_url=base_url, ambiente=ambiente).rstrip("/")
        self.token = x_autorizacao or getattr(
            config, "ISCHOLAR_API_TOKEN", getattr(config, "ISCHOLAR_API_KEY", "")
        )
        self.codigo_escola = x_codigo_escola or getattr(config, "ISCHOLAR_CODIGO_ESCOLA", "")
        self.timeout = getattr(config, "ISCHOLAR_TIMEOUT_SEGUNDOS", 30)

        self.session = requests.Session()
        
        retries = Retry(
            total=getattr(config, "ISCHOLAR_MAX_RETRIES", 3),
            backoff_factor=1,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET"] 
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def close(self) -> None:
        """Libera recursos (sessão HTTP) com segurança."""
        try:
            self.session.close()
        except Exception:
            # Close nunca deve derrubar worker/caller.
            pass

    def _resolve_base_url(
        self, *, base_url: Optional[str], ambiente: Optional[str]
    ) -> str:
        """
        Resolve `base_url` por configuração.

        - `base_url` explícito tem prioridade.
        - `ambiente` (config/ENV) seleciona homologação/produção, se existirem
          base URLs específicas para cada caso.
        - fallback para `config.ISCHOLAR_BASE_URL`.
        """
        if base_url:
            return str(base_url).rstrip("/")

        default_base = getattr(
            config, "ISCHOLAR_BASE_URL", "https://api.ischolar.app"
        )

        amb = (
            ambiente
            or os.getenv("ISCHOLAR_AMBIENTE")
            or getattr(config, "ISCHOLAR_AMBIENTE", None)
        )
        if not amb:
            return str(default_base).rstrip("/")

        amb_norm = str(amb).strip().lower()
        if amb_norm in {"homologacao", "homolog", "homologation"}:
            cand = getattr(config, "ISCHOLAR_BASE_URL_HOMOLOGACAO", None) or os.getenv(
                "ISCHOLAR_BASE_URL_HOMOLOGACAO"
            )
            if cand:
                return str(cand).rstrip("/")

        if amb_norm in {"producao", "production", "prod"}:
            cand = getattr(config, "ISCHOLAR_BASE_URL_PRODUCAO", None) or os.getenv(
                "ISCHOLAR_BASE_URL_PRODUCAO"
            )
            if cand:
                return str(cand).rstrip("/")

        return str(default_base).rstrip("/")

    # --- Helpers de Validação e Coerção ---

    def _get_headers(self) -> Dict[str, str]:
        """Valida configuração e retorna headers obrigatórios."""
        if not self.token or not self.codigo_escola:
            raise ValueError("Configuração iScholar incompleta (Token ou Código da Escola ausentes).")
        return {
            "X-Autorizacao": self.token,
            "X-Codigo-Escola": self.codigo_escola,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _coerce_int_strict(self, val: Any, nome: str) -> int:
        """Garante que o valor seja um inteiro exato, sem truncamento perigoso."""
        if pd.isna(val):
            raise ValueError(f"O campo '{nome}' não pode ser nulo.")
        try:
            f_val = float(val)
            if not f_val.is_integer():
                raise ValueError(f"O campo '{nome}' deve ser um número inteiro (recebeu {val}).")
            return int(f_val)
        except (ValueError, TypeError):
            raise ValueError(f"O campo '{nome}' deve ser numérico inteiro (recebeu {val}).")

    def _coerce_float_strict(self, val: Any, nome: str) -> float:
        """Garante que o valor seja um float válido e não-nulo."""
        if pd.isna(val):
            raise ValueError(f"O campo '{nome}' não pode ser nulo.")
        try:
            return float(val)
        except (ValueError, TypeError):
            raise ValueError(f"O campo '{nome}' deve ser numérico (recebeu {val}).")

    def _coerce_iso_date(self, val: Any) -> str:
        """Valida estritamente o formato ISO YYYY-MM-DD."""
        s_val = str(val).strip() if pd.notna(val) else ""
        try:
            datetime.strptime(s_val, "%Y-%m-%d")
            return s_val
        except ValueError:
            raise ValueError(f"Data inválida: '{val}'. Use o formato ISO YYYY-MM-DD.")

    def _normalize_optional_text(self, val: Any) -> Optional[str]:
        """Normaliza textos opcionais, retornando None em vez de 'nan' ou vazio."""
        if pd.isna(val) or val is None:
            return None
        s_val = str(val).strip()
        return s_val if s_val else None

    def _normalize_valor_nota_bruta(self, valor_bruta: Any) -> float:
        """
        Normaliza `valor` como nota bruta (NÃO ponderada), com no máximo 2 casas.
        """
        if pd.isna(valor_bruta):
            raise ValueError("O campo 'valor_bruta' não pode ser nulo.")

        if isinstance(valor_bruta, str):
            s = valor_bruta.strip().replace(",", ".")
        else:
            s = str(valor_bruta).strip()

        try:
            d = Decimal(s)
        except Exception as exc:
            raise ValueError(f"Valor de nota bruta inválido: {valor_bruta!r}") from exc

        q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if q == Decimal("-0.00"):
            q = Decimal("0.00")
        return float(q)

    def _classificar_erro_http(
        self, *, status_code: int, mensagem: str
    ) -> tuple[Optional[str], bool]:
        """
        Retorna (erro_categoria, transitorio).
        """
        if status_code in (401, 403):
            return ("auth", False)
        if status_code in (400, 422):
            return ("validacao", False)
        if 400 <= status_code < 500:
            return ("http", False)
        if 500 <= status_code < 600:
            return ("http", True)
        return ("http", False)

    def _extract_id_matricula_from_item(
        self, item: Mapping[str, Any]
    ) -> Optional[int]:
        """
        Extrai `id_matricula` (heurística conservadora) a partir de um item retornado pela API.
        """
        for key in (
            "id_matricula",
            "idMatricula",
            "matricula_id",
            "matriculaId",
        ):
            if key in item:
                try:
                    return self._coerce_int_strict(item.get(key), key)
                except Exception:
                    continue
        # fallback genérico: se houver campo 'id' numérico, pode ser id_matricula
        if "id" in item:
            try:
                return self._coerce_int_strict(item.get("id"), "id")
            except Exception:
                return None
        return None

    # -----------------------------------------------------------------------
    # FLUXO OFICIAL (novo) — endpoints confirmados pelo suporte iScholar
    # Use estes métodos em todo código novo.
    # -----------------------------------------------------------------------

    def buscar_aluno(
        self,
        *,
        id_aluno: Optional[int] = None,
        ra: Optional[str] = None,
        cpf: Optional[str] = None,
    ) -> ResultadoBuscaAluno:
        """
        [FLUXO OFICIAL] GET /aluno/busca

        Passo 1 da resolução de matrícula. Retorna id_aluno a partir de um
        identificador único do aluno.

        A API aceita UM, e apenas um, dos identificadores abaixo:
          - `id_aluno` (inteiro)
          - `numero_re` (texto) — no projeto mapeado a partir do campo RA
          - `cpf` (texto)

        Nenhum identificador válido informado → levanta `ValueError`.
        Usar em conjunto com `listar_matriculas` para obter id_matricula.
        """
        endpoint = f"{self.base_url}/aluno/busca"

        # Monta parâmetros com rastreabilidade e sem enviar campos vazios.
        candidatos: list[tuple[str, Any]] = []
        if id_aluno is not None:
            candidatos.append(("id_aluno", id_aluno))
        if ra is not None and str(ra).strip() != "":
            candidatos.append(("numero_re", str(ra).strip()))
        if cpf is not None and str(cpf).strip() != "":
            # Normaliza CPF para apenas dígitos (reduz variações de formatação).
            cpf_norm = "".join(ch for ch in str(cpf) if ch.isdigit())
            if cpf_norm != "":
                candidatos.append(("cpf", cpf_norm))

        if not candidatos:
            raise ValueError(
                "buscar_aluno: informe exatamente um identificador válido entre `id_aluno`, `ra` (numero_re) ou `cpf`."
            )
        if len(candidatos) != 1:
            raise ValueError(
                "buscar_aluno: a API aceita UM, e apenas um, identificador. Forneça somente um de `id_aluno`, `ra` ou `cpf`."
            )

        chave, valor = candidatos[0]
        params: dict[str, Any] = {}
        if chave == "id_aluno":
            params["id_aluno"] = self._coerce_int_strict(valor, "id_aluno")
        else:
            # numero_re/cpf são strings; mantemos como informados (cpf já normalizado).
            params[chave] = valor

        try:
            resp = self.session.get(
                endpoint,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                try:
                    dados = resp.json()
                except Exception:
                    dados = resp.text
                return ResultadoBuscaAluno(
                    sucesso=True,
                    status_code=resp.status_code,
                    dados=dados,
                    endpoint_alvo=endpoint,
                    params=params,
                    erro_categoria=None,
                    mensagem="",
                )

            mensagem = f"{resp.status_code}: {resp.text}"
            erro_cat, trans = self._classificar_erro_http(
                status_code=resp.status_code, mensagem=mensagem
            )
            return ResultadoBuscaAluno(
                sucesso=False,
                status_code=resp.status_code,
                transitorio=trans,
                erro_categoria=erro_cat,
                mensagem=mensagem,
                dados=None,
                endpoint_alvo=endpoint,
                params=params,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            return ResultadoBuscaAluno(
                sucesso=False,
                transitorio=True,
                erro_categoria="rede",
                mensagem=f"Falha de rede ao buscar aluno: {exc!s}",
                endpoint_alvo=endpoint,
                params=params,
            )
        except Exception as exc:
            return ResultadoBuscaAluno(
                sucesso=False,
                transitorio=False,
                erro_categoria="http",
                mensagem=f"Erro inesperado ao buscar aluno: {exc!s}",
                endpoint_alvo=endpoint,
                params=params,
            )

    def listar_matriculas(
        self,
        *,
        id_aluno: int,
        id_responsavel: Optional[int] = None,
        id_turma: Optional[int] = None,
        id_periodo: Optional[int] = None,
        id_unidade: Optional[int] = None,
        situacao: Optional[str] = None,
        pagina: int = 1,
        resolver_id_matricula: bool = True,
    ) -> ResultadoListagemMatriculas:
        """
        [FLUXO OFICIAL] GET /matricula/listar

        Passo 2 da resolução de matrícula. Retorna id_matricula a partir do
        id_aluno obtido via `buscar_aluno`.

        Com `resolver_id_matricula=True` (padrão), retorna o id_matricula
        inequívoco ou erro explícito se houver ambiguidade.
        """
        endpoint = f"{self.base_url}/matricula/listar"
        params: dict[str, Any] = {"id_aluno": self._coerce_int_strict(id_aluno, "id_aluno"), "pagina": int(pagina)}
        if id_responsavel is not None:
            params["id_responsavel"] = self._coerce_int_strict(
                id_responsavel, "id_responsavel"
            )
        if id_turma is not None:
            params["id_turma"] = self._coerce_int_strict(id_turma, "id_turma")
        if id_periodo is not None:
            params["id_periodo"] = self._coerce_int_strict(
                id_periodo, "id_periodo"
            )
        if id_unidade is not None:
            params["id_unidade"] = self._coerce_int_strict(id_unidade, "id_unidade")
        if situacao is not None:
            params["situacao"] = str(situacao).strip()

        try:
            resp = self.session.get(
                endpoint,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                try:
                    dados: Any = resp.json()
                except Exception:
                    dados = resp.text

                items: Optional[list[Any]] = None
                if isinstance(dados, list):
                    items = dados
                elif isinstance(dados, dict):
                    # "dados" é o envelope padrão da API iScholar — deve ser
                    # verificado PRIMEIRO para garantir extração correta.
                    for k in ("dados", "matriculas", "items", "data"):
                        if isinstance(dados.get(k), list):
                            items = dados[k]
                            break
                    # Se "dados" contém um dict (envelope com item único), tenta lista de 1
                    if items is None and isinstance(dados.get("dados"), dict):
                        items = [dados["dados"]]

                rast: dict[str, Any] = {"endpoint_alvo": endpoint, "params": params, "items_count": (len(items) if isinstance(items, list) else None)}
                resolved: Optional[int] = None

                if resolver_id_matricula:
                    if not isinstance(items, list) or not items:
                        return ResultadoListagemMatriculas(
                            sucesso=False,
                            status_code=resp.status_code,
                            transitorio=False,
                            erro_categoria="http",
                            mensagem="Nenhuma matrícula retornada para resolver `id_matricula`.",
                            dados=dados,
                            id_matricula_resolvido=None,
                            rastreabilidade=rast,
                            endpoint_alvo=endpoint,
                            params=params,
                        )
                    extracted: list[Optional[int]] = []
                    for it in items:
                        if isinstance(it, Mapping):
                            extracted.append(self._extract_id_matricula_from_item(it))
                        else:
                            extracted.append(None)
                    extracted_clean = [x for x in extracted if x is not None]
                    rast["id_matriculas_extraiados"] = extracted_clean

                    if len(extracted_clean) == 1:
                        resolved = extracted_clean[0]
                        rast["id_matricula_resolvido_motivo"] = "unico_resultado"
                    elif len(set(extracted_clean)) == 1:
                        resolved = list(set(extracted_clean))[0]
                        rast["id_matricula_resolvido_motivo"] = "todos_iguais"
                    else:
                        return ResultadoListagemMatriculas(
                            sucesso=False,
                            status_code=resp.status_code,
                            transitorio=False,
                            erro_categoria="http",
                            mensagem="Resposta retornou múltiplos `id_matricula` distintos; resolução não determinística.",
                            dados=dados,
                            id_matricula_resolvido=None,
                            rastreabilidade=rast,
                            endpoint_alvo=endpoint,
                            params=params,
                        )

                return ResultadoListagemMatriculas(
                    sucesso=True,
                    status_code=resp.status_code,
                    transitorio=False,
                    dados=dados,
                    id_matricula_resolvido=resolved,
                    rastreabilidade=rast,
                    endpoint_alvo=endpoint,
                    params=params,
                )

            mensagem = f"{resp.status_code}: {resp.text}"
            erro_cat, trans = self._classificar_erro_http(
                status_code=resp.status_code, mensagem=mensagem
            )
            return ResultadoListagemMatriculas(
                sucesso=False,
                status_code=resp.status_code,
                transitorio=trans,
                erro_categoria=erro_cat,
                mensagem=mensagem,
                dados=None,
                id_matricula_resolvido=None,
                rastreabilidade={"endpoint_alvo": endpoint, "params": params},
                endpoint_alvo=endpoint,
                params=params,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            return ResultadoListagemMatriculas(
                sucesso=False,
                status_code=None,
                transitorio=True,
                erro_categoria="rede",
                mensagem=f"Falha de rede ao listar matrículas: {exc!s}",
                dados=None,
                id_matricula_resolvido=None,
                rastreabilidade={"endpoint_alvo": endpoint, "params": params},
                endpoint_alvo=endpoint,
                params=params,
            )
        except Exception as exc:
            return ResultadoListagemMatriculas(
                sucesso=False,
                status_code=None,
                transitorio=False,
                erro_categoria="http",
                mensagem=f"Erro inesperado ao listar matrículas: {exc!s}",
                dados=None,
                id_matricula_resolvido=None,
                rastreabilidade={"endpoint_alvo": endpoint, "params": params},
                endpoint_alvo=endpoint,
                params=params,
            )

    def listar_notas(
        self,
        *,
        id_matricula: Optional[int] = None,
        identificacao: Optional[int] = None,
        tipo: str = "nota",
    ) -> ResultadoListagemNotas:
        """
        [FLUXO OFICIAL] GET /diario/notas — auditoria e reconciliação.

        Consulta notas já lançadas para uma matrícula. Usar para verificar
        o estado atual antes/após `lancar_nota`, não como parte do loop
        de envio principal.

        GET /diario/notas?id_matricula=…&identificacao=…&tipo=…

        Nota: para tokens de integração, a API pode exigir `identificacao`
        (id_aluno) em vez de ou além de `id_matricula`.
        """
        endpoint = f"{self.base_url}/diario/notas"
        params: dict[str, Any] = {"tipo": str(tipo)}
        if id_matricula is not None:
            params["id_matricula"] = self._coerce_int_strict(id_matricula, "id_matricula")
        if identificacao is not None:
            params["identificacao"] = self._coerce_int_strict(
                identificacao, "identificacao"
            )

        try:
            resp = self.session.get(
                endpoint,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                try:
                    dados = resp.json()
                except Exception:
                    dados = resp.text
                return ResultadoListagemNotas(
                    sucesso=True,
                    status_code=resp.status_code,
                    dados=dados,
                    endpoint_alvo=endpoint,
                    params=params,
                )

            mensagem = f"{resp.status_code}: {resp.text}"
            erro_cat, trans = self._classificar_erro_http(
                status_code=resp.status_code, mensagem=mensagem
            )
            return ResultadoListagemNotas(
                sucesso=False,
                status_code=resp.status_code,
                transitorio=trans,
                erro_categoria=erro_cat,
                mensagem=mensagem,
                dados=None,
                endpoint_alvo=endpoint,
                params=params,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            return ResultadoListagemNotas(
                sucesso=False,
                status_code=None,
                transitorio=True,
                erro_categoria="rede",
                mensagem=f"Falha de rede ao listar notas: {exc!s}",
                dados=None,
                endpoint_alvo=endpoint,
                params=params,
            )
        except Exception as exc:
            return ResultadoListagemNotas(
                sucesso=False,
                status_code=None,
                transitorio=False,
                erro_categoria="http",
                mensagem=f"Erro inesperado ao listar notas: {exc!s}",
                dados=None,
                endpoint_alvo=endpoint,
                params=params,
            )

    def lancar_nota(
        self,
        *,
        id_matricula: Optional[int] = None,
        id_aluno: Optional[int] = None,
        matricula_resolver_params: Optional[Mapping[str, Any]] = None,
        id_disciplina: int,
        id_avaliacao: int,
        valor_bruta: Any,
        id_professor: Optional[int] = None,
        dry_run: bool = False,
    ) -> ResultadoLancamentoNota:
        """
        [FLUXO OFICIAL] POST /notas/lanca_nota — lançamento principal.

        Ponto de envio do fluxo oficial novo. Payload confirmado pelo suporte:
          {
            "id_matricula": INT,
            "id_disciplina": INT,
            "id_avaliacao": INT,
            "id_professor": INT (opcional),
            "valor": NUMERIC  # nota bruta (0-10, 2 casas decimais)
          }

        O endpoint é idempotente (cria ou substitui). O client NÃO faz GET
        de reconciliação prévia — a idempotência é garantida pelo servidor.
        Usar em conjunto com `buscar_aluno` + `listar_matriculas` para
        resolver id_matricula antes de chamar este método.
        """
        endpoint = f"{self.base_url}/notas/lanca_nota"

        try:
            headers = self._get_headers()
        except Exception as exc:
            return ResultadoLancamentoNota(
                sucesso=False,
                transitorio=False,
                erro_categoria="auth",
                mensagem=f"Configuração iScholar incompleta: {exc!s}",
                endpoint_alvo=endpoint,
                rastreabilidade={"erro": "headers"},
            )

        rast: dict[str, Any] = {}

        if id_matricula is None:
            if id_aluno is None or matricula_resolver_params is None:
                return ResultadoLancamentoNota(
                    sucesso=False,
                    transitorio=False,
                    erro_categoria="validacao",
                    mensagem="Para resolver `id_matricula`: informe `id_matricula` ou (id_aluno + matricula_resolver_params).",
                    endpoint_alvo=endpoint,
                    headers=headers,
                    rastreabilidade={"missing": ["id_matricula", "id_aluno", "matricula_resolver_params"]},
                )

            busca = self.buscar_aluno(id_aluno=id_aluno)
            rast["buscar_aluno"] = {"sucesso": busca.sucesso, "erro_categoria": busca.erro_categoria}
            if not busca.sucesso:
                return ResultadoLancamentoNota(
                    sucesso=False,
                    transitorio=busca.transitorio,
                    erro_categoria=busca.erro_categoria,
                    status_code=busca.status_code,
                    mensagem=busca.mensagem,
                    endpoint_alvo=endpoint,
                    headers=headers,
                    rastreabilidade=rast,
                )

            lista = self.listar_matriculas(
                id_aluno=id_aluno,
                resolver_id_matricula=True,
                **dict(matricula_resolver_params),
            )
            rast["listar_matriculas"] = {
                "sucesso": lista.sucesso,
                "erro_categoria": lista.erro_categoria,
                "id_matricula_resolvido": lista.id_matricula_resolvido,
            }
            if not lista.sucesso or lista.id_matricula_resolvido is None:
                return ResultadoLancamentoNota(
                    sucesso=False,
                    transitorio=lista.transitorio,
                    erro_categoria=lista.erro_categoria or "http",
                    status_code=lista.status_code,
                    mensagem=lista.mensagem,
                    endpoint_alvo=endpoint,
                    headers=headers,
                    rastreabilidade=rast,
                )
            id_matricula = lista.id_matricula_resolvido

        try:
            payload: dict[str, Any] = {
                "id_matricula": self._coerce_int_strict(id_matricula, "id_matricula"),
                "id_disciplina": self._coerce_int_strict(
                    id_disciplina, "id_disciplina"
                ),
                "id_avaliacao": self._coerce_int_strict(
                    id_avaliacao, "id_avaliacao"
                ),
                "valor": self._normalize_valor_nota_bruta(valor_bruta),
            }
            if id_professor is not None:
                payload["id_professor"] = self._coerce_int_strict(
                    id_professor, "id_professor"
                )
        except Exception as exc:
            return ResultadoLancamentoNota(
                sucesso=False,
                transitorio=False,
                erro_categoria="validacao",
                mensagem=f"Falha ao montar payload do lançamento: {exc!s}",
                endpoint_alvo=endpoint,
                headers=headers,
                rastreabilidade=rast,
            )

        if dry_run:
            return ResultadoLancamentoNota(
                sucesso=True,
                transitorio=False,
                erro_categoria=None,
                status_code=None,
                mensagem="dry_run=True: payload montado, sem chamada HTTP.",
                dados=None,
                idempotente=True,
                dry_run=True,
                endpoint_alvo=endpoint,
                headers=headers,
                payload=payload,
                rastreabilidade=rast,
            )

        try:
            resp = self.session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                try:
                    dados = resp.json()
                except Exception:
                    dados = resp.text
                return ResultadoLancamentoNota(
                    sucesso=True,
                    transitorio=False,
                    status_code=resp.status_code,
                    erro_categoria=None,
                    mensagem="Lançamento processado com sucesso.",
                    dados=dados,
                    idempotente=True,
                    dry_run=False,
                    endpoint_alvo=endpoint,
                    headers=headers,
                    payload=payload,
                    rastreabilidade=rast,
                )

            mensagem = f"{resp.status_code}: {resp.text}"
            erro_cat, trans = self._classificar_erro_http(
                status_code=resp.status_code, mensagem=mensagem
            )
            return ResultadoLancamentoNota(
                sucesso=False,
                transitorio=trans,
                status_code=resp.status_code,
                erro_categoria=erro_cat,
                mensagem=mensagem,
                dados=None,
                idempotente=True,
                dry_run=False,
                endpoint_alvo=endpoint,
                headers=headers,
                payload=payload,
                rastreabilidade=rast,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            return ResultadoLancamentoNota(
                sucesso=False,
                transitorio=True,
                status_code=None,
                erro_categoria="rede",
                mensagem=f"Falha de rede ao lançar nota: {exc!s}",
                dados=None,
                idempotente=True,
                dry_run=False,
                endpoint_alvo=endpoint,
                headers=headers,
                payload=payload,
                rastreabilidade=rast,
            )
        except Exception as exc:
            return ResultadoLancamentoNota(
                sucesso=False,
                transitorio=False,
                status_code=None,
                erro_categoria="http",
                mensagem=f"Erro inesperado ao lançar nota: {exc!s}",
                dados=None,
                idempotente=True,
                dry_run=False,
                endpoint_alvo=endpoint,
                headers=headers,
                payload=payload,
                rastreabilidade=rast,
            )

    # -----------------------------------------------------------------------
    # ENDPOINTS COMPLEMENTARES (novo) — discovery e autopreenchimento de mapas
    # -----------------------------------------------------------------------

    def listar_disciplinas(self) -> ResultadoListagemDisciplinas:
        """
        [FLUXO OFICIAL] GET /disciplinas — lista disciplinas cadastradas na escola.

        Retorna lista de disciplinas com id, nome e abreviação.
        Útil para autopreenchimento de mapa_disciplinas.json.

        Resposta esperada (envelope iScholar):
          {"status": "...", "mensagem": "...", "dados": [
            {"id": "1", "nome": "ARTE", "abreviacao": "ART"},
            ...
          ]}
        """
        endpoint = f"{self.base_url}/disciplinas"

        try:
            resp = self.session.get(
                endpoint,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                try:
                    dados = resp.json()
                except Exception:
                    dados = resp.text

                # Extrai lista de disciplinas do envelope "dados"
                disciplinas: Optional[List[Dict[str, Any]]] = None
                if isinstance(dados, list):
                    disciplinas = dados
                elif isinstance(dados, dict):
                    for k in ("dados", "disciplinas", "items", "data"):
                        if isinstance(dados.get(k), list):
                            disciplinas = dados[k]
                            break

                return ResultadoListagemDisciplinas(
                    sucesso=True,
                    status_code=resp.status_code,
                    dados=dados,
                    disciplinas=disciplinas,
                    endpoint_alvo=endpoint,
                )

            mensagem = f"{resp.status_code}: {resp.text}"
            erro_cat, trans = self._classificar_erro_http(
                status_code=resp.status_code, mensagem=mensagem
            )
            return ResultadoListagemDisciplinas(
                sucesso=False,
                status_code=resp.status_code,
                transitorio=trans,
                erro_categoria=erro_cat,
                mensagem=mensagem,
                dados=None,
                disciplinas=None,
                endpoint_alvo=endpoint,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            return ResultadoListagemDisciplinas(
                sucesso=False,
                status_code=None,
                transitorio=True,
                erro_categoria="rede",
                mensagem=f"Falha de rede ao listar disciplinas: {exc!s}",
                dados=None,
                disciplinas=None,
                endpoint_alvo=endpoint,
            )
        except Exception as exc:
            return ResultadoListagemDisciplinas(
                sucesso=False,
                status_code=None,
                transitorio=False,
                erro_categoria="http",
                mensagem=f"Erro inesperado ao listar disciplinas: {exc!s}",
                dados=None,
                disciplinas=None,
                endpoint_alvo=endpoint,
            )

    def listar_professores(self) -> ResultadoListagemProfessores:
        """
        [FLUXO OFICIAL] GET /funcionarios/professores — lista professores cadastrados.

        Retorna lista de professores com id_professor e nome_professor.
        Útil para autopreenchimento de mapa_professores.json.

        Resposta esperada (envelope iScholar):
          {"status": "...", "mensagem": "...", "dados": [
            {"id_professor": "2", "nome_professor": "ARNOLD"},
            ...
          ]}
        """
        endpoint = f"{self.base_url}/funcionarios/professores"

        try:
            resp = self.session.get(
                endpoint,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                try:
                    dados = resp.json()
                except Exception:
                    dados = resp.text

                # Extrai lista de professores do envelope "dados"
                professores: Optional[List[Dict[str, Any]]] = None
                if isinstance(dados, list):
                    professores = dados
                elif isinstance(dados, dict):
                    for k in ("dados", "professores", "items", "data"):
                        if isinstance(dados.get(k), list):
                            professores = dados[k]
                            break

                return ResultadoListagemProfessores(
                    sucesso=True,
                    status_code=resp.status_code,
                    dados=dados,
                    professores=professores,
                    endpoint_alvo=endpoint,
                )

            mensagem = f"{resp.status_code}: {resp.text}"
            erro_cat, trans = self._classificar_erro_http(
                status_code=resp.status_code, mensagem=mensagem
            )
            return ResultadoListagemProfessores(
                sucesso=False,
                status_code=resp.status_code,
                transitorio=trans,
                erro_categoria=erro_cat,
                mensagem=mensagem,
                dados=None,
                professores=None,
                endpoint_alvo=endpoint,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            return ResultadoListagemProfessores(
                sucesso=False,
                status_code=None,
                transitorio=True,
                erro_categoria="rede",
                mensagem=f"Falha de rede ao listar professores: {exc!s}",
                dados=None,
                professores=None,
                endpoint_alvo=endpoint,
            )
        except Exception as exc:
            return ResultadoListagemProfessores(
                sucesso=False,
                status_code=None,
                transitorio=False,
                erro_categoria="http",
                mensagem=f"Erro inesperado ao listar professores: {exc!s}",
                dados=None,
                professores=None,
                endpoint_alvo=endpoint,
            )

    def pega_alunos(
        self,
        *,
        id_turma: int,
        pagina: int = 1,
    ) -> ResultadoPegaAlunos:
        """
        [FLUXO OFICIAL] GET /matricula/pega_alunos — busca alunos de uma turma.

        Endpoint alternativo que retorna id_aluno, id_matricula e numero_re
        juntos. Pode ser usado como fallback quando buscar_aluno não retorna
        id_aluno, ou para resolver id_matricula em uma única chamada.

        GET /matricula/pega_alunos?id_turma=…&pagina=…

        Resposta esperada (envelope iScholar):
          {"status": "...", "mensagem": "...", "dados": [
            {"id_aluno": "42", "id_matricula": "97", "numero_re": "12345", ...},
            ...
          ]}
        """
        endpoint = f"{self.base_url}/matricula/pega_alunos"
        params: dict[str, Any] = {
            "id_turma": self._coerce_int_strict(id_turma, "id_turma"),
            "pagina": int(pagina),
        }

        try:
            resp = self.session.get(
                endpoint,
                params=params,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
            if resp.status_code in (200, 201):
                try:
                    dados = resp.json()
                except Exception:
                    dados = resp.text

                # Extrai lista de alunos do envelope "dados"
                alunos: Optional[List[Dict[str, Any]]] = None
                if isinstance(dados, list):
                    alunos = dados
                elif isinstance(dados, dict):
                    for k in ("dados", "alunos", "items", "data"):
                        if isinstance(dados.get(k), list):
                            alunos = dados[k]
                            break

                return ResultadoPegaAlunos(
                    sucesso=True,
                    status_code=resp.status_code,
                    dados=dados,
                    alunos=alunos,
                    endpoint_alvo=endpoint,
                    params=params,
                )

            mensagem = f"{resp.status_code}: {resp.text}"
            erro_cat, trans = self._classificar_erro_http(
                status_code=resp.status_code, mensagem=mensagem
            )
            return ResultadoPegaAlunos(
                sucesso=False,
                status_code=resp.status_code,
                transitorio=trans,
                erro_categoria=erro_cat,
                mensagem=mensagem,
                dados=None,
                alunos=None,
                endpoint_alvo=endpoint,
                params=params,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            return ResultadoPegaAlunos(
                sucesso=False,
                status_code=None,
                transitorio=True,
                erro_categoria="rede",
                mensagem=f"Falha de rede ao buscar alunos: {exc!s}",
                dados=None,
                alunos=None,
                endpoint_alvo=endpoint,
                params=params,
            )
        except Exception as exc:
            return ResultadoPegaAlunos(
                sucesso=False,
                status_code=None,
                transitorio=False,
                erro_categoria="http",
                mensagem=f"Erro inesperado ao buscar alunos: {exc!s}",
                dados=None,
                alunos=None,
                endpoint_alvo=endpoint,
                params=params,
            )

    # -----------------------------------------------------------------------
    # FLUXO LEGADO — NÃO usar em código novo
    # Mantido apenas para compatibilidade do worker existente.
    # Não deve ser estendido. Candidato a remoção quando o worker for migrado.
    # -----------------------------------------------------------------------

    def _indexar_avaliacoes_existentes(self, dados: Any) -> dict[int, dict]:
        """
        [LEGADO] Percorre recursivamente a resposta JSON (listas e dicts) e
        indexa objetos de avaliação pela chave 'identificacao' (int).
        Usado exclusivamente por `sync_notas_idempotente`.
        """
        indice: dict[int, dict] = {}

        def _varrer(nó: Any):
            if isinstance(nó, dict):
                if "identificacao" in nó and nó["identificacao"] is not None:
                    try:
                        id_int = int(nó["identificacao"])
                        indice[id_int] = nó
                    except (ValueError, TypeError):
                        pass # Ignora silenciosamente se não for conversível
                
                # Continua a varredura em profundidade
                for valor in nó.values():
                    _varrer(valor)
            elif isinstance(nó, list):
                for item in nó:
                    _varrer(item)

        _varrer(dados)
        return indice

    def _comparar_avaliacao_existente_com_payload(self, avaliacao_existente: Optional[dict], row_payload: dict) -> str:
        """
        [LEGADO] Compara nota existente com a nova nota do payload.
        Retorna: 'create', 'skip' ou 'conflict'.
        Usado exclusivamente por `sync_notas_idempotente`.
        """
        if not avaliacao_existente:
            return "create"
        
        try:
            # Extração defensiva forçando float para comparação matemática
            val_existente = float(avaliacao_existente.get("valor"))
            val_novo = float(row_payload.get("valor"))
            
            if val_existente == val_novo:
                return "skip"
            else:
                return "conflict"
        except (ValueError, TypeError):
            # Se a conversão falhar de algum dos lados, sinaliza conflito
            return "conflict"

    def consultar_notas(self, id_matricula: int) -> ResultadoEnvio:
        """
        [LEGADO] GET /diario/notas?id_matricula=…

        Wrapper do fluxo legado. Não usar em código novo — usar `listar_notas`
        (fluxo oficial) para consultas de auditoria.
        """
        try:
            v_id = self._coerce_int_strict(id_matricula, "id_matricula")
            url = f"{self.base_url}/diario/notas"
            params = {"id_matricula": v_id}
            
            resp = self.session.get(url, params=params, headers=self._get_headers(), timeout=self.timeout)
            resultado = self._processar_resposta(resp)
            
            if resultado.sucesso:
                try:
                    resultado.dados = resp.json()
                except Exception:
                    resultado.sucesso = False
                    resultado.mensagem = "Falha crítica: Resposta da API não é um JSON válido."
            return resultado
        except Exception as exc:
            return self._tratar_excecao(exc)

    def criar_nota(
        self,
        *,
        id_matricula: int,
        identificacao: int,
        valor: float,
        tipo: str = "nota",
        data_lancamento: str,
        observacao: Optional[str] = None
    ) -> ResultadoEnvio:
        """
        [LEGADO] POST /diario/notas — envio individual pelo fluxo legado.

        Endpoint diferente do fluxo oficial (POST /notas/lanca_nota).
        Não usar em código novo — usar `lancar_nota` (fluxo oficial).
        Chamado exclusivamente por `sync_notas_idempotente`.
        """
        url = f"{self.base_url}/diario/notas"
        
        try:
            obs = self._normalize_optional_text(observacao)
            payload = {
                "id_matricula": self._coerce_int_strict(id_matricula, "id_matricula"),
                "identificacao": self._coerce_int_strict(identificacao, "identificacao"),
                "tipo": str(tipo),
                "valor": self._coerce_float_strict(valor, "valor"),
                "data_lancamento": self._coerce_iso_date(data_lancamento),
            }
            if obs is not None:
                payload["observacao"] = obs

            resp = self.session.post(url, json=payload, headers=self._get_headers(), timeout=self.timeout)
            return self._processar_resposta(resp)
        except Exception as exc:
            return self._tratar_excecao(exc)

    def enviar_notas(self, df: pd.DataFrame, job_id: Optional[int] = None, **kwargs) -> ResultadoEnvio:
        """
        [LEGADO] Wrapper que delega para `sync_notas_idempotente`.

        Retorna ResultadoEnvio compatível com o loop do worker antigo.
        Não usar em código novo — o fluxo oficial usa `lancar_nota` por item.
        """
        resultado_sync = self.sync_notas_idempotente(df, job_id=job_id, **kwargs)

        # Trata qualquer falha que impeça a conclusão determinística do lote (falta de colunas, erro de rede, etc)
        if not resultado_sync.sucesso:
            return ResultadoEnvio(
                sucesso=False,
                transitorio=resultado_sync.transitorio,
                mensagem=resultado_sync.mensagem,
                dados=resultado_sync.detalhes
            )

        # Processamento concluído deterministicamente (com ou sem conflitos de dados)
        # O worker interpreta `sucesso=True` como "tarefa concluída, pode remover da fila"
        msg = (
            f"Lote finalizado. Total: {resultado_sync.total} | "
            f"Criadas: {resultado_sync.created} | Puladas: {resultado_sync.skipped} | "
            f"Conflitos: {resultado_sync.conflicts} | Falhas Permanentes: {resultado_sync.failed_permanent}"
        )
        return ResultadoEnvio(
            sucesso=True,
            mensagem=msg,
            transitorio=False,
            dados=resultado_sync.detalhes
        )

    def sync_notas_idempotente(self, df: pd.DataFrame, job_id: Optional[int] = None, **kwargs) -> ResultadoSyncNotas:
        """
        [LEGADO] Sincroniza notas via GET+POST pelo endpoint /diario/notas.

        Lógica própria do worker antigo: agrupa por matrícula, consulta estado
        existente e decide entre criar/pular/registrar conflito.
        Não usar em código novo — o fluxo oficial gerencia idempotência via
        `lancar_nota` (POST /notas/lanca_nota é idempotente por contrato).
        """
        colunas_necessarias = {"id_matricula", "identificacao", "valor", "data_lancamento"}
        faltantes = colunas_necessarias - set(df.columns)
        if faltantes:
            return ResultadoSyncNotas(sucesso=False, transitorio=False, mensagem=f"Colunas obrigatórias ausentes: {faltantes}")

        resultado = ResultadoSyncNotas(sucesso=True, total=len(df), detalhes=[])

        # 1. Agrupar por matrícula para otimizar requisições
        for id_matricula, group in df.groupby("id_matricula"):
            # GET: Consultar o boletim da matrícula
            resp_consulta = self.consultar_notas(id_matricula)

            if not resp_consulta.sucesso:
                if resp_consulta.transitorio:
                    # Falha de rede: abortar imediatamente para possibilitar retry do lote
                    resultado.sucesso = False
                    resultado.transitorio = True
                    resultado.failed_transient += len(group)
                    resultado.mensagem = f"Falha transitória ao consultar matrícula {id_matricula}: {resp_consulta.mensagem}"
                    return resultado
                else:
                    # Falha de cliente/dados: logar e avançar para a próxima matrícula
                    linhas_afetadas = len(group)
                    resultado.failed_permanent += linhas_afetadas
                    resultado.detalhes.append({
                        "id_matricula": id_matricula,
                        "erro": "GET failed",
                        "mensagem": resp_consulta.mensagem
                    })
                    continue
            
            # 2. Indexar notas que já estão no iScholar para este aluno
            avaliacoes_existentes = self._indexar_avaliacoes_existentes(resp_consulta.dados)

            # 3. Iterar e aplicar regras sobre o payload pretendido
            for _, row in group.iterrows():
                row_payload = {
                    "id_matricula": row.get("id_matricula"),
                    "identificacao": row.get("identificacao"),
                    "valor": row.get("valor"),
                    "tipo": row.get("tipo", "nota"),
                    "data_lancamento": row.get("data_lancamento"),
                    "observacao": row.get("observacao")
                }

                identificacao = row_payload["identificacao"]
                try:
                    id_idx = int(identificacao)
                except (ValueError, TypeError):
                    id_idx = None
                
                avaliacao_existente = avaliacoes_existentes.get(id_idx) if id_idx is not None else None
                acao = self._comparar_avaliacao_existente_com_payload(avaliacao_existente, row_payload)

                if acao == "skip":
                    resultado.skipped += 1
                
                elif acao == "conflict":
                    resultado.conflicts += 1
                    resultado.detalhes.append({
                        "id_matricula": row_payload["id_matricula"],
                        "identificacao": identificacao,
                        "erro": "Conflito",
                        "mensagem": f"Valor divergente (API: {avaliacao_existente.get('valor')} != Planilha: {row_payload['valor']})"
                    })
                
                elif acao == "create":
                    # POST: Lançar a nota nova
                    res_post = self.criar_nota(
                        id_matricula=row_payload["id_matricula"],
                        identificacao=row_payload["identificacao"],
                        valor=row_payload["valor"],
                        tipo=row_payload["tipo"],
                        data_lancamento=row_payload["data_lancamento"],
                        observacao=row_payload["observacao"]
                    )

                    if res_post.sucesso:
                        resultado.created += 1
                    elif res_post.transitorio:
                        resultado.sucesso = False
                        resultado.transitorio = True
                        resultado.failed_transient += 1
                        resultado.mensagem = f"Falha transitória ao criar nota (Matrícula {id_matricula}, Avaliação {identificacao}): {res_post.mensagem}"
                        return resultado
                    else:
                        resultado.failed_permanent += 1
                        resultado.detalhes.append({
                            "id_matricula": row_payload["id_matricula"],
                            "identificacao": identificacao,
                            "erro": "POST failed",
                            "mensagem": res_post.mensagem
                        })

        # Finalizar status: Execução concluída de forma determinística
        resultado.sucesso = True
        
        status_msg = "Sync concluído com ressalvas" if (resultado.conflicts > 0 or resultado.failed_permanent > 0) else "Sync concluído"
        
        resultado.mensagem = (
            f"{status_msg}: {resultado.total} notas processadas. "
            f"({resultado.created} criadas, {resultado.skipped} puladas, "
            f"{resultado.conflicts} conflitos, {resultado.failed_permanent} falhas)."
        )
        return resultado

    def _processar_resposta(self, resp: requests.Response) -> ResultadoEnvio:  # [LEGADO]
        if resp.status_code in (200, 201):
            return ResultadoEnvio(sucesso=True, status_code=resp.status_code)
        
        # 4xx: Erros de cliente (Auth, Validação 422, etc)
        if 400 <= resp.status_code < 500:
            msg = f"Erro Permanente ({resp.status_code}): {resp.text}"
            log.error("❌ %s", msg)
            return ResultadoEnvio(sucesso=False, status_code=resp.status_code, transitorio=False, mensagem=msg)

        # 5xx: Erros de servidor
        msg = f"Erro Transitório ({resp.status_code}): {resp.text}"
        log.warning("⚠️ %s", msg)
        return ResultadoEnvio(sucesso=False, status_code=resp.status_code, transitorio=True, mensagem=msg)

    def _tratar_excecao(self, exc: Exception) -> ResultadoEnvio:  # [LEGADO]
        is_transiente = isinstance(exc, (requests.Timeout, requests.ConnectionError))
        log.error("🚨 Falha %s: %s", "Transitória" if is_transiente else "Permanente", exc)
        return ResultadoEnvio(sucesso=False, transitorio=is_transiente, mensagem=str(exc))


# ---------------------------------------------------------------------------
# LEGADO — singleton e entrada do pipeline antigo
# Não usar em código novo.
# ---------------------------------------------------------------------------

_cliente_padrao: Optional[IScholarClient] = None


def get_client() -> IScholarClient:
    """[LEGADO] Singleton de IScholarClient para o worker existente."""
    global _cliente_padrao
    if _cliente_padrao is None:
        _cliente_padrao = IScholarClient()
    return _cliente_padrao


def enviar_notas_para_ischolar(df: pd.DataFrame, job_id: Optional[int] = None, **kwargs) -> bool:
    """[LEGADO] Entrada do pipeline antigo. Delega para get_client().enviar_notas()."""
    resultado = get_client().enviar_notas(df, job_id=job_id, **kwargs)
    return resultado.sucesso