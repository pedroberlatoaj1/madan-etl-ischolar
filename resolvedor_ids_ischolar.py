"""
resolvedor_ids_ischolar.py — Resolvedor híbrido provisório de IDs iScholar

Plugs em envio_lote.ResolvedorIDsAbstrato.

ESTRATÉGIA (fail closed):
  id_matricula  → API oficial (buscar_aluno + listar_matriculas)
  id_disciplina → DE-PARA local (mapa_disciplinas.json)
  id_avaliacao  → DE-PARA local (mapa_avaliacoes.json)
  id_professor  → DE-PARA local (mapa_professores.json), opcional

PRINCÍPIO: se não souber com segurança, não envia.
  - nenhuma inferência por nome solto
  - nenhum endpoint não confirmado pelo suporte técnico
  - qualquer ambiguidade → bloqueia, não desempata

CATEGORIAS DE ERRO (machine-readable em rastreabilidade["categorias_erro"]):
  identificador_aluno_insuficiente  — lançamento sem ra/cpf/id_aluno
  matricula_nao_encontrada          — buscar_aluno ou listar_matriculas falhou
  matricula_ambigua                 — múltiplos id_matricula distintos retornados
  disciplina_sem_mapeamento         — disciplina não presente no mapa local
  avaliacao_sem_mapeamento          — componente/trimestre não presente no mapa local
  professor_sem_mapeamento          — professor_obrigatorio=True mas frente sem mapeamento
  erro_api_transitorio              — falha de rede/5xx (candidato a retry)

PROVISÓRIO — o que muda quando o suporte confirmar endpoints:
  - Se um endpoint de disciplina/avaliação for confirmado, substituir a
    resolução local por chamada de API nessa função sem mudar a interface.
  - Não há suposição escondida sobre payloads ou campos não documentados.

USO TÍPICO:

    from ischolar_client import IScholarClient
    from resolvedor_ids_ischolar import (
        ResolvedorIDsHibrido,
        carregar_mapa_disciplinas,
        carregar_mapa_avaliacoes,
        carregar_mapa_professores,
    )

    cliente = IScholarClient()
    resolvedor = ResolvedorIDsHibrido(
        cliente=cliente,
        mapa_disciplinas=carregar_mapa_disciplinas("mapa_disciplinas.json"),
        mapa_avaliacoes=carregar_mapa_avaliacoes("mapa_avaliacoes.json"),
        mapa_professores=carregar_mapa_professores("mapa_professores.json"),  # opcional
        professor_obrigatorio=False,
    )
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Optional, TYPE_CHECKING

from envio_lote import ResolvedorIDsAbstrato, ResultadoResolucaoIDs

if TYPE_CHECKING:
    from ischolar_client import IScholarClient


# ---------------------------------------------------------------------------
# Normalização de strings para lookup
# ---------------------------------------------------------------------------

def _normalizar_chave(s: str) -> str:
    """
    Normaliza string para lookup nos mapas DE-PARA.
    Passos em ordem:
      1. strip + lower
      2. remove diacríticos (NFD → filtra Mn)
      3. converte separadores de pontuação (. - / \\) em espaço
         — "Ed. Física" e "Ed Fisica" convergem para "ed fisica"
      4. remove pontuação residual que não seja alfanumérica nem espaço
         (parênteses, vírgulas, aspas…)
      5. colapsa múltiplos espaços e faz strip final

    Exemplos:
      "Matemática"    → "matematica"
      "Ed. Física"    → "ed fisica"
      "Ed. Física"    → "ed fisica"   (idem com ponto após "Ed")
      "Hist./Geo."    → "hist geo"
      "Língua Port."  → "lingua port"
      "AV 1 "         → "av 1"
    """
    n = str(s).strip().lower()
    # Remove diacríticos
    n = "".join(
        c for c in unicodedata.normalize("NFD", n) if unicodedata.category(c) != "Mn"
    )
    # Pontuação separadora → espaço (ponto, hífen, barra, barra invertida)
    n = re.sub(r"[.\-/\\]", " ", n)
    # Remove pontuação residual não-alfanumérica (mantém letras, dígitos, espaço)
    n = re.sub(r"[^\w\s]", "", n)
    # Colapsa espaços múltiplos
    n = re.sub(r"\s+", " ", n).strip()
    return n


# ---------------------------------------------------------------------------
# Utilitários de carga e validação dos mapas DE-PARA
# ---------------------------------------------------------------------------

def carregar_mapa_disciplinas(caminho: str | Path) -> dict[str, int]:
    """
    Carrega mapa disciplina_nome → id_disciplina de um arquivo JSON.

    Formato esperado (ver mapa_disciplinas.json de exemplo):
    {
      "_schema": "mapa_disciplinas_v1",
      "disciplinas": {
        "matematica": 101,
        "portugues": 102,
        "ed fisica": 104
      }
    }

    As chaves são normalizadas (sem acentos, minúsculas) no arquivo.
    Raises:
      FileNotFoundError, json.JSONDecodeError, ValueError (schema inválido)
    """
    p = Path(caminho)
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict) or "disciplinas" not in raw:
        raise ValueError(
            f"mapa_disciplinas.json inválido: falta chave 'disciplinas' em {caminho}"
        )

    disc = raw["disciplinas"]
    if not isinstance(disc, dict):
        raise ValueError(f"'disciplinas' deve ser um dict em {caminho}")

    resultado: dict[str, int] = {}
    for nome, id_d in disc.items():
        if not isinstance(id_d, int):
            raise ValueError(
                f"id_disciplina deve ser int; encontrado {id_d!r} para '{nome}' em {caminho}"
            )
        resultado[_normalizar_chave(nome)] = id_d
    return resultado


def validar_mapa_disciplinas(mapa: dict[str, int]) -> list[str]:
    """
    Valida estrutura do mapa carregado.
    Retorna lista de problemas (vazia se tudo ok).
    """
    problemas: list[str] = []
    if not mapa:
        problemas.append("mapa_disciplinas está vazio; nenhuma disciplina mapeada.")
    for k, v in mapa.items():
        if not isinstance(v, int) or v <= 0:
            problemas.append(f"id_disciplina inválido para '{k}': {v!r} (deve ser int > 0).")
    return problemas


def carregar_mapa_avaliacoes(caminho: str | Path) -> list[dict[str, Any]]:
    """
    Carrega mapa de avaliações de um arquivo JSON.

    Formato esperado (ver mapa_avaliacoes.json de exemplo):
    {
      "_schema": "mapa_avaliacoes_v1",
      "avaliacoes": [
        {"componente": "av1", "trimestre": "1", "id_avaliacao": 201},
        {"componente": "av1", "trimestre": "2", "id_avaliacao": 202},
        {"componente": "av1",                   "id_avaliacao": 299}  <- fallback sem trimestre
      ]
    }

    Lookup (do mais específico ao mais geral):
      1. componente + trimestre (exact match)
      2. componente apenas (fallback, se trimestre não estiver no mapa)

    Raises:
      FileNotFoundError, json.JSONDecodeError, ValueError (schema inválido)
    """
    p = Path(caminho)
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict) or "avaliacoes" not in raw:
        raise ValueError(
            f"mapa_avaliacoes.json inválido: falta chave 'avaliacoes' em {caminho}"
        )

    avals = raw["avaliacoes"]
    if not isinstance(avals, list):
        raise ValueError(f"'avaliacoes' deve ser uma lista em {caminho}")

    for i, entry in enumerate(avals):
        if not isinstance(entry, dict):
            raise ValueError(f"Entrada {i} de 'avaliacoes' não é um dict em {caminho}")
        if "componente" not in entry:
            raise ValueError(f"Entrada {i} de 'avaliacoes' falta 'componente' em {caminho}")
        if "id_avaliacao" not in entry:
            raise ValueError(f"Entrada {i} de 'avaliacoes' falta 'id_avaliacao' em {caminho}")
        if not isinstance(entry["id_avaliacao"], int):
            raise ValueError(
                f"id_avaliacao deve ser int; entrada {i} em {caminho}: {entry['id_avaliacao']!r}"
            )

    return list(avals)


def validar_mapa_avaliacoes(mapa: list[dict[str, Any]]) -> list[str]:
    """Retorna lista de problemas (vazia se tudo ok)."""
    problemas: list[str] = []
    if not mapa:
        problemas.append("mapa_avaliacoes está vazio; nenhuma avaliação mapeada.")
    return problemas


def carregar_mapa_professores(caminho: str | Path) -> dict[str, int]:
    """
    Carrega mapa frente_professor → id_professor de um arquivo JSON.

    Formato esperado (ver mapa_professores.json de exemplo):
    {
      "_schema": "mapa_professores_v1",
      "professores": {
        "matematica - prof silva": 301,
        "portugues - profa lima": 302
      }
    }

    Chave: valor do campo `frente_professor` da planilha Madan, normalizado.

    Raises:
      FileNotFoundError, json.JSONDecodeError, ValueError (schema inválido)
    """
    p = Path(caminho)
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, dict) or "professores" not in raw:
        raise ValueError(
            f"mapa_professores.json inválido: falta chave 'professores' em {caminho}"
        )

    profs = raw["professores"]
    if not isinstance(profs, dict):
        raise ValueError(f"'professores' deve ser um dict em {caminho}")

    resultado: dict[str, int] = {}
    for frente, id_p in profs.items():
        if not isinstance(id_p, int):
            raise ValueError(
                f"id_professor deve ser int; encontrado {id_p!r} para '{frente}' em {caminho}"
            )
        resultado[_normalizar_chave(frente)] = id_p
    return resultado


def validar_mapa_professores(mapa: dict[str, int]) -> list[str]:
    """Retorna lista de problemas (vazia se tudo ok)."""
    problemas: list[str] = []
    for k, v in mapa.items():
        if not isinstance(v, int) or v <= 0:
            problemas.append(f"id_professor inválido para '{k}': {v!r} (deve ser int > 0).")
    return problemas


# ---------------------------------------------------------------------------
# Lógica de lookup de avaliação
# ---------------------------------------------------------------------------

def _lookup_avaliacao(
    mapa_avaliacoes: list[dict[str, Any]],
    componente: str,
    trimestre: Optional[str],
) -> Optional[int]:
    """
    Lookup com fallback progressivo:
    1. componente + trimestre (exact match)
    2. componente apenas (fallback)

    Retorna id_avaliacao int, ou None se não encontrado.
    """
    comp_norm = _normalizar_chave(componente)
    tri_norm  = _normalizar_chave(trimestre) if trimestre else None

    # Tentativa 1: componente + trimestre
    if tri_norm:
        for entry in mapa_avaliacoes:
            if (_normalizar_chave(entry.get("componente", "")) == comp_norm
                    and "trimestre" in entry
                    and _normalizar_chave(str(entry["trimestre"])) == tri_norm):
                return int(entry["id_avaliacao"])

    # Tentativa 2: componente apenas (entries sem trimestre explícito)
    for entry in mapa_avaliacoes:
        if (_normalizar_chave(entry.get("componente", "")) == comp_norm
                and "trimestre" not in entry):
            return int(entry["id_avaliacao"])

    return None


# ---------------------------------------------------------------------------
# Extração de identificadores do aluno do lançamento
# ---------------------------------------------------------------------------

def _extrair_identificador_aluno(
    lancamento: Mapping[str, Any],
) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """
    Extrai (ra, cpf, id_aluno) do lançamento.
    Campos esperados: `ra`, `numero_re`, `cpf`, `id_aluno`.
    Retorna (ra, cpf, id_aluno) — qualquer um pode ser None.

    NOTA: O campo `ra` faz parte do schema canônico desde o patch de propagação
    de RA (transformador.py). Os campos `cpf` e `id_aluno` podem ser injetados
    externamente se disponíveis. Sem ao menos um deles, a resolução via API
    retorna `identificador_aluno_insuficiente`.
    """
    ra: Optional[str] = None
    cpf: Optional[str] = None
    id_aluno: Optional[int] = None

    for campo_ra in ("ra", "numero_re"):
        val = lancamento.get(campo_ra)
        if val is not None and str(val).strip():
            ra = str(val).strip()
            break

    val_cpf = lancamento.get("cpf")
    if val_cpf is not None and str(val_cpf).strip():
        cpf = str(val_cpf).strip()

    val_id = lancamento.get("id_aluno")
    if val_id is not None:
        try:
            id_aluno = int(val_id)
        except (ValueError, TypeError):
            pass

    return ra, cpf, id_aluno


# ---------------------------------------------------------------------------
# Extração de id_aluno da resposta de buscar_aluno
# ---------------------------------------------------------------------------

def _extrair_id_aluno_da_resposta(dados: Any) -> Optional[int]:
    """
    Extrai id_aluno do payload retornado por buscar_aluno().
    Heurística conservadora: procura campos conhecidos em ordem de preferência.
    Retorna None se não encontrar valor numérico inequívoco.

    Suporta:
      - dict direto do aluno:        {"id_aluno": 42, ...}
      - lista de alunos:             [{"id_aluno": 42}]
      - envelopes comuns (1 nível):  {"dados": {...}}, {"dados": [...]},
                                     {"result": {...}}, {"result": [...]},
                                     {"aluno": {...}}

    PROVISÓRIO: a estrutura exata da resposta de GET /aluno/busca não foi
    completamente documentada pelo suporte técnico. Esta função será ajustada
    quando o contrato for confirmado.
    """
    _CAMPOS_ID = ("id_aluno", "idAluno", "id")
    _ENVELOPES  = ("dados", "result", "aluno")

    def _de_dict(d: dict) -> Optional[int]:
        """Extrai id de um dict de aluno."""
        for campo in _CAMPOS_ID:
            val = d.get(campo)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    continue
        return None

    def _de_lista(lst: list) -> Optional[int]:
        """Extrai id de uma lista de dicts — somente se resultado for único."""
        ids: list[int] = []
        for item in lst:
            if isinstance(item, dict):
                v = _de_dict(item)
                if v is not None:
                    ids.append(v)
        if len(ids) == 1:
            return ids[0]
        return None  # zero ou múltiplos → não desempata

    if not isinstance(dados, (dict, list)):
        return None

    # --- Caso 1: dict direto --------------------------------------------------
    if isinstance(dados, dict):
        # Tenta resolver direto
        resultado = _de_dict(dados)
        if resultado is not None:
            return resultado

        # Tenta desembrulhar envelopes conhecidos (um nível)
        for env in _ENVELOPES:
            conteudo = dados.get(env)
            if isinstance(conteudo, dict):
                r = _de_dict(conteudo)
                if r is not None:
                    return r
            elif isinstance(conteudo, list):
                r = _de_lista(conteudo)
                if r is not None:
                    return r

        return None

    # --- Caso 2: lista direta ------------------------------------------------
    if isinstance(dados, list):
        return _de_lista(dados)

    return None


# ---------------------------------------------------------------------------
# Resolvedor híbrido
# ---------------------------------------------------------------------------

class ResolvedorIDsHibrido(ResolvedorIDsAbstrato):
    """
    Resolvedor provisório de IDs iScholar.

    Estratégia por campo:
      id_matricula  → API (buscar_aluno + listar_matriculas)
      id_disciplina → DE-PARA local (mapa_disciplinas)
      id_avaliacao  → DE-PARA local (mapa_avaliacoes)
      id_professor  → DE-PARA local (mapa_professores), opcional

    Fail closed: qualquer ambiguidade ou mapeamento ausente → erro explícito.

    Parâmetros:
      cliente              : IScholarClient configurado com token e código de escola
      mapa_disciplinas     : dict {nome_normalizado → id_disciplina}, de carregar_mapa_disciplinas()
      mapa_avaliacoes      : list de entries, de carregar_mapa_avaliacoes()
      mapa_professores     : dict {frente_normalizada → id_professor} ou None
      professor_obrigatorio: True → bloqueia se frente_professor sem mapeamento
                             False → permite id_professor=None (padrão)
    """

    def __init__(
        self,
        *,
        cliente: "IScholarClient",
        mapa_disciplinas: dict[str, int],
        mapa_avaliacoes: list[dict[str, Any]],
        mapa_professores: Optional[dict[str, int]] = None,
        professor_obrigatorio: bool = False,
    ) -> None:
        self._cliente              = cliente
        self._mapa_disciplinas     = mapa_disciplinas
        self._mapa_avaliacoes      = mapa_avaliacoes
        # Normaliza as chaves do mapa de professores no construtor para garantir
        # consistência independente da origem (arquivo via carregar_mapa_professores
        # ou injeção programática direta). A operação é idempotente: chaves já
        # normalizadas não são afetadas.
        self._mapa_professores     = {
            _normalizar_chave(k): v
            for k, v in (mapa_professores or {}).items()
        }
        self._professor_obrigatorio = professor_obrigatorio

    def resolver_ids(self, lancamento: Mapping[str, Any]) -> ResultadoResolucaoIDs:
        """
        Resolve todos os IDs para um lançamento sendável.
        NUNCA levanta exceção — erros vão para .erros e rastreabilidade.
        Idempotente.
        """
        erros: list[str] = []
        categorias_erro: list[str] = []
        fonte_resolucao: dict[str, str] = {}
        detalhes: dict[str, Any] = {}

        # --- 1. id_matricula: via API ------------------------------------------
        id_matricula = self._resolver_matricula(
            lancamento, erros, categorias_erro, fonte_resolucao, detalhes
        )

        # --- 2. id_disciplina: via DE-PARA local --------------------------------
        id_disciplina = self._resolver_disciplina(
            lancamento, erros, categorias_erro, fonte_resolucao, detalhes
        )

        # --- 3. id_avaliacao: via DE-PARA local ---------------------------------
        id_avaliacao = self._resolver_avaliacao(
            lancamento, erros, categorias_erro, fonte_resolucao, detalhes
        )

        # --- 4. id_professor: via DE-PARA local (opcional) ----------------------
        id_professor = self._resolver_professor(
            lancamento, erros, categorias_erro, fonte_resolucao, detalhes
        )

        rastreabilidade: dict[str, Any] = {
            "fonte_resolucao": fonte_resolucao,
            "categorias_erro": categorias_erro,
            "detalhes": detalhes,
        }

        return ResultadoResolucaoIDs(
            id_matricula  = id_matricula,
            id_disciplina = id_disciplina,
            id_avaliacao  = id_avaliacao,
            id_professor  = id_professor,
            erros         = erros,
            rastreabilidade = rastreabilidade,
        )

    # ------------------------------------------------------------------
    # Resolução por campo (privados)
    # ------------------------------------------------------------------

    def _resolver_matricula(
        self,
        lancamento: Mapping[str, Any],
        erros: list[str],
        categorias_erro: list[str],
        fonte_resolucao: dict[str, str],
        detalhes: dict[str, Any],
    ) -> Optional[int]:
        """
        Resolve id_matricula via buscar_aluno + listar_matriculas.

        Passos:
        1. Extrai identificador do aluno (ra/cpf/id_aluno) do lançamento.
        2. Se nenhum → identificador_aluno_insuficiente.
        3. Chama buscar_aluno para obter id_aluno.
        4. Chama listar_matriculas para obter id_matricula.
        5. Se múltiplos → matricula_ambigua.
        6. Se zero → matricula_nao_encontrada.
        """
        ra, cpf, id_aluno = _extrair_identificador_aluno(lancamento)

        if ra is None and cpf is None and id_aluno is None:
            erros.append(
                "[identificador_aluno_insuficiente] Lançamento não contém ra, "
                "cpf nem id_aluno. Adicione o identificador à planilha ou ao "
                "lançamento antes de enviar."
            )
            categorias_erro.append("identificador_aluno_insuficiente")
            fonte_resolucao["id_matricula"] = "nao_resolvido:identificador_insuficiente"
            detalhes["matricula"] = {
                "campos_tentados": ["ra", "numero_re", "cpf", "id_aluno"],
                "encontrado": None,
            }
            return None

        # Passo 3: buscar_aluno para obter id_aluno (se não veio direto)
        id_aluno_resolvido: Optional[int] = id_aluno

        if id_aluno_resolvido is None:
            try:
                if ra is not None:
                    busca = self._cliente.buscar_aluno(ra=ra)
                else:
                    busca = self._cliente.buscar_aluno(cpf=cpf)
            except Exception as exc:
                erros.append(f"[matricula_nao_encontrada] Exceção em buscar_aluno: {exc!s}")
                categorias_erro.append("matricula_nao_encontrada")
                fonte_resolucao["id_matricula"] = "nao_resolvido:excecao_buscar_aluno"
                return None

            if not busca.sucesso:
                categoria = "erro_api_transitorio" if busca.transitorio else "matricula_nao_encontrada"
                erros.append(
                    f"[{categoria}] buscar_aluno falhou: {busca.mensagem}"
                )
                categorias_erro.append(categoria)
                fonte_resolucao["id_matricula"] = f"nao_resolvido:{categoria}"
                detalhes["buscar_aluno"] = {
                    "endpoint": busca.endpoint_alvo,
                    "status_code": busca.status_code,
                    "mensagem": busca.mensagem,
                }
                return None

            id_aluno_resolvido = _extrair_id_aluno_da_resposta(busca.dados)
            detalhes["buscar_aluno"] = {
                "endpoint": busca.endpoint_alvo,
                "status_code": busca.status_code,
                "id_aluno_extraido": id_aluno_resolvido,
            }

            if id_aluno_resolvido is None:
                erros.append(
                    "[matricula_nao_encontrada] buscar_aluno retornou sucesso "
                    "mas id_aluno não pôde ser extraído da resposta. "
                    "PROVISÓRIO: estrutura da resposta de /aluno/busca "
                    "ainda não totalmente documentada pelo suporte técnico."
                )
                categorias_erro.append("matricula_nao_encontrada")
                fonte_resolucao["id_matricula"] = "nao_resolvido:id_aluno_nao_extraido"
                return None

        # Passo 4: listar_matriculas para obter id_matricula
        try:
            lista = self._cliente.listar_matriculas(
                id_aluno=id_aluno_resolvido,
                resolver_id_matricula=True,
            )
        except Exception as exc:
            erros.append(f"[matricula_nao_encontrada] Exceção em listar_matriculas: {exc!s}")
            categorias_erro.append("matricula_nao_encontrada")
            fonte_resolucao["id_matricula"] = "nao_resolvido:excecao_listar_matriculas"
            return None

        detalhes["listar_matriculas"] = {
            "endpoint": lista.endpoint_alvo,
            "status_code": lista.status_code,
            "id_matricula_resolvido": lista.id_matricula_resolvido,
            "rastreabilidade_client": lista.rastreabilidade,
        }

        if not lista.sucesso or lista.id_matricula_resolvido is None:
            # Client já distingue: múltiplos distintos → mensagem de ambiguidade
            if lista.mensagem and "múltiplos" in lista.mensagem.lower():
                categoria = "matricula_ambigua"
            elif lista.transitorio:
                categoria = "erro_api_transitorio"
            else:
                categoria = "matricula_nao_encontrada"

            erros.append(f"[{categoria}] listar_matriculas: {lista.mensagem}")
            categorias_erro.append(categoria)
            fonte_resolucao["id_matricula"] = f"nao_resolvido:{categoria}"
            return None

        fonte_resolucao["id_matricula"] = "api:buscar_aluno+listar_matriculas"
        return lista.id_matricula_resolvido

    def _resolver_disciplina(
        self,
        lancamento: Mapping[str, Any],
        erros: list[str],
        categorias_erro: list[str],
        fonte_resolucao: dict[str, str],
        detalhes: dict[str, Any],
    ) -> Optional[int]:
        """
        Resolve id_disciplina via DE-PARA local.
        Chave: campo `disciplina` do lançamento, normalizado.
        """
        disciplina_raw = lancamento.get("disciplina")
        if not disciplina_raw or not str(disciplina_raw).strip():
            erros.append("[disciplina_sem_mapeamento] Campo 'disciplina' ausente no lançamento.")
            categorias_erro.append("disciplina_sem_mapeamento")
            fonte_resolucao["id_disciplina"] = "nao_resolvido:campo_ausente"
            return None

        chave = _normalizar_chave(str(disciplina_raw))
        id_d = self._mapa_disciplinas.get(chave)

        detalhes["disciplina"] = {
            "valor_original": disciplina_raw,
            "chave_normalizada": chave,
            "id_encontrado": id_d,
        }

        if id_d is None:
            erros.append(
                f"[disciplina_sem_mapeamento] '{disciplina_raw}' (chave: '{chave}') "
                "não encontrada em mapa_disciplinas. "
                "Adicione a entrada ao mapa antes de enviar."
            )
            categorias_erro.append("disciplina_sem_mapeamento")
            fonte_resolucao["id_disciplina"] = "nao_resolvido:sem_mapeamento"
            return None

        fonte_resolucao["id_disciplina"] = "de_para_local:mapa_disciplinas"
        return id_d

    def _resolver_avaliacao(
        self,
        lancamento: Mapping[str, Any],
        erros: list[str],
        categorias_erro: list[str],
        fonte_resolucao: dict[str, str],
        detalhes: dict[str, Any],
    ) -> Optional[int]:
        """
        Resolve id_avaliacao via DE-PARA local.
        Lookup progressivo: componente+trimestre → componente.
        """
        componente = lancamento.get("componente")
        trimestre  = lancamento.get("trimestre")

        if not componente or not str(componente).strip():
            erros.append("[avaliacao_sem_mapeamento] Campo 'componente' ausente no lançamento.")
            categorias_erro.append("avaliacao_sem_mapeamento")
            fonte_resolucao["id_avaliacao"] = "nao_resolvido:campo_ausente"
            return None

        id_av = _lookup_avaliacao(self._mapa_avaliacoes, str(componente), str(trimestre) if trimestre else None)

        detalhes["avaliacao"] = {
            "componente": componente,
            "trimestre": trimestre,
            "id_encontrado": id_av,
        }

        if id_av is None:
            erros.append(
                f"[avaliacao_sem_mapeamento] Componente '{componente}' "
                f"(trimestre={trimestre!r}) não encontrado em mapa_avaliacoes. "
                "Adicione a entrada ao mapa antes de enviar."
            )
            categorias_erro.append("avaliacao_sem_mapeamento")
            fonte_resolucao["id_avaliacao"] = "nao_resolvido:sem_mapeamento"
            return None

        fonte_resolucao["id_avaliacao"] = "de_para_local:mapa_avaliacoes"
        return id_av

    def _resolver_professor(
        self,
        lancamento: Mapping[str, Any],
        erros: list[str],
        categorias_erro: list[str],
        fonte_resolucao: dict[str, str],
        detalhes: dict[str, Any],
    ) -> Optional[int]:
        """
        Resolve id_professor via DE-PARA local.
        Chave: campo `frente_professor` do lançamento, normalizado.

        Se professor_obrigatorio=False e não houver mapeamento → None (sem erro).
        Se professor_obrigatorio=True e não houver mapeamento → erro explícito.
        """
        frente_raw = lancamento.get("frente_professor")

        # Sem valor no lançamento: opcional → ok; obrigatório → erro
        if not frente_raw or not str(frente_raw).strip():
            if self._professor_obrigatorio:
                erros.append(
                    "[professor_sem_mapeamento] professor_obrigatorio=True mas "
                    "campo 'frente_professor' ausente no lançamento."
                )
                categorias_erro.append("professor_sem_mapeamento")
                fonte_resolucao["id_professor"] = "nao_resolvido:campo_ausente"
            else:
                fonte_resolucao["id_professor"] = "nao_aplicavel:opcional"
            detalhes["professor"] = {"valor_original": frente_raw, "id_encontrado": None}
            return None

        chave = _normalizar_chave(str(frente_raw))
        id_p = self._mapa_professores.get(chave)

        detalhes["professor"] = {
            "valor_original": frente_raw,
            "chave_normalizada": chave,
            "id_encontrado": id_p,
        }

        if id_p is None:
            if self._professor_obrigatorio:
                erros.append(
                    f"[professor_sem_mapeamento] '{frente_raw}' (chave: '{chave}') "
                    "não encontrado em mapa_professores. "
                    "professor_obrigatorio=True: adicione a entrada ao mapa."
                )
                categorias_erro.append("professor_sem_mapeamento")
                fonte_resolucao["id_professor"] = "nao_resolvido:sem_mapeamento"
                return None
            else:
                # Opcional: frente presente mas sem mapeamento → None sem bloquear
                fonte_resolucao["id_professor"] = "nao_mapeado:opcional"
                return None

        fonte_resolucao["id_professor"] = "de_para_local:mapa_professores"
        return id_p


__all__ = [
    # Resolvedor principal
    "ResolvedorIDsHibrido",
    # Utilitários de carga
    "carregar_mapa_disciplinas",
    "carregar_mapa_avaliacoes",
    "carregar_mapa_professores",
    # Utilitários de validação
    "validar_mapa_disciplinas",
    "validar_mapa_avaliacoes",
    "validar_mapa_professores",
    # Helpers internos exportados para testes
    "_normalizar_chave",
    "_lookup_avaliacao",
    "_extrair_identificador_aluno",
    "_extrair_id_aluno_da_resposta",
]