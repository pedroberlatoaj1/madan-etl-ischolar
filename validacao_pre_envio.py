"""
validacao_pre_envio.py — Etapa 3  (patch corretivo)

Camada explícita de validação pré-envio (NÃO envia nada).

Entrada : linha original (wide) + lançamentos canônicos (Etapa 2)
Saída   : resultado estruturado e auditável com erros / avisos / pendências /
          duplicidades / comparações.

--- Mudanças em relação à versão anterior ---

1. Issue.bloqueante (bool, padrão False)
   - Pendências não-bloqueantes (ex.: IDENTIFICADOR_ISCHOLAR_PENDENTE) não
     degradam o status_geral para "bloqueado_por_erros" nem impedem
     "apto_para_aprovacao".  Elas continuam auditáveis em res["pendencias"].
   - O campo "bloqueante" é serializado normalmente em __dict__, portanto
     consumidores podem inspecioná-lo.

2. Duplicidade diferenciada por sendabilidade
   - Sendável duplicado  → erro bloqueante (DUPLICIDADE_SENDAVEL)
     Risco real: dois lançamentos idênticos chegando ao iScholar.
   - Não-sendável duplicado → aviso (DUPLICIDADE_INTERNA)
     Ocorre em subcomponentes e itens ignorados; sinaliza sem bloquear.

3. Semântica de status_geral corrigida
   - "bloqueado_por_erros"   : erros em lancamentos, erros de linha,
                               ou pendência com bloqueante=True
   - "apto_com_avisos"       : avisos e/ou pendências não-bloqueantes,
                               sem erros
   - "apto_para_aprovacao"   : nenhum erro, aviso ou pendência
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from avaliacao_rules import StatusLancamento, is_blank
from madan_planilha_mapper import (
    CAN_DISCIPLINA,
    CAN_FRENTE_PROFESSOR,
    CAN_NOTA_COM_AV3,
    CAN_NOTA_FINAL,
    CAN_NOTA_SEM_AV3,
    CAN_TURMA,
    extrair_serie_da_turma,
    normalizar_linha_madan,
)
from professores_madan import (
    buscar_por_nome_ou_apelido,
    extrair_professor_da_frente,
    parece_chave_disciplina_frente,
    validar_professor_disciplina_turma,
)


# ---------------------------------------------------------------------------
# Constantes de status_geral
# ---------------------------------------------------------------------------

STATUS_APROVADO       = "apto_para_aprovacao"
STATUS_COM_AVISOS     = "apto_com_avisos"
STATUS_BLOQUEADO_ERROS = "bloqueado_por_erros"

COMPONENTES_QUE_EXIGEM_PONDERACAO_LOCAL = frozenset({"av1", "av2", "av3", "simulado"})
"""
Componentes cuja ponderação é calculada PELO PIPELINE antes do envio.
Para esses, peso_avaliacao e valor_ponderado são obrigatórios.
Componentes fora desse conjunto (ex.: "recuperacao", "recuperacao_final")
são enviados sem ponderação — o iScholar calcula.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _componente_exige_ponderacao_local(componente: Any) -> bool:
    return componente in COMPONENTES_QUE_EXIGEM_PONDERACAO_LOCAL


def _try_float(value: Any) -> Optional[float]:
    if is_blank(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Tipos de dados
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Issue:
    severity: str          # "erro" | "aviso" | "pendencia"
    code: str
    message: str
    details: dict[str, Any] | None = None
    # Para pendências: True indica que a pendência é bloqueante para o
    # status_geral (impede "apto_para_aprovacao" e "apto_com_avisos").
    # Para erros e avisos este campo é ignorado no cálculo do status
    # (erros sempre bloqueiam; avisos nunca bloqueiam diretamente).
    bloqueante: bool = False


@dataclass(frozen=True)
class ComparacaoTotal:
    campo: str             # "nota_final" | "nota_com_av3" | "nota_sem_av3"
    informado: float | None
    calculado: float | None
    diferenca_absoluta: float | None
    tolerancia: float
    resultado: str         # "confere" | "divergente" | "ausente" | "nao_comparavel"


# ---------------------------------------------------------------------------
# Predicados internos
# ---------------------------------------------------------------------------

def _is_sendavel(l: Mapping[str, Any]) -> bool:
    """
    Heurística de "potencialmente enviável" nesta etapa (sem iScholar):
      - status == StatusLancamento.PRONTO
      - componente em {av1, av2, av3, simulado, recuperacao, recuperacao_final}
      - subcomponente None  →  lançamento consolidado
      - AV1/AV2/AV3/Simulado exigem peso_avaliacao e valor_ponderado
      - Recuperacao trimestral/final exigem apenas nota_ajustada_0a10
    """
    if l.get("status") != StatusLancamento.PRONTO:
        return False
    if l.get("subcomponente") is not None:
        return False
    componente = l.get("componente")
    if _componente_exige_ponderacao_local(componente):
        return (l.get("peso_avaliacao") is not None) and (l.get("valor_ponderado") is not None)
    if componente in {"recuperacao", "recuperacao_final"}:
        # A ponderacao da recuperacao e feita pelo iScholar. O pipeline so
        # transporta a nota bruta da prova, por isso peso_avaliacao e
        # valor_ponderado ficam ausentes por design nesse componente.
        return l.get("nota_ajustada_0a10") is not None
    return False


def _chave_duplicidade(l: Mapping[str, Any]) -> tuple[Any, ...]:
    """
    Chave de identidade para detecção de duplicata exata dentro do lote.
    Política (Etapa 3):
      - Duplicata sendável  → erro bloqueante (DUPLICIDADE_SENDAVEL)
      - Duplicata não-sendável → aviso (DUPLICIDADE_INTERNA)
    O lançamento duplicado é marcado e mantido na lista (não removido),
    garantindo rastreabilidade.
    """
    return (
        l.get("estudante"),
        l.get("turma"),
        l.get("disciplina"),
        l.get("trimestre"),
        l.get("componente"),
        l.get("subcomponente"),
        l.get("nota_ajustada_0a10"),
        l.get("linha_origem"),
    )


# ---------------------------------------------------------------------------
# Validadores atômicos
# ---------------------------------------------------------------------------

def _validar_estudante_basico(estudante: Any) -> list[Issue]:
    issues: list[Issue] = []
    if is_blank(estudante):
        issues.append(Issue("erro", "ESTUDANTE_AUSENTE", "Campo 'estudante' ausente/vazio."))
        return issues

    nome = str(estudante).strip()
    if nome.lower() in {"n/a", "na", "null", "none", "-", "0"}:
        issues.append(
            Issue("erro", "ESTUDANTE_INVALIDO",
                  "Nome de estudante claramente inválido.", {"valor": nome})
        )
    elif len(nome) < 3:
        issues.append(
            Issue("aviso", "ESTUDANTE_CURTO",
                  "Nome de estudante muito curto (pode ser inválido).", {"valor": nome})
        )
    elif nome.isdigit():
        issues.append(
            Issue("aviso", "ESTUDANTE_NUMERICO",
                  "Nome de estudante é apenas numérico (pode ser ID incorreto).", {"valor": nome})
        )
    return issues


def _validar_campos_obrigatorios_lancamento(l: Mapping[str, Any]) -> list[Issue]:
    issues: list[Issue] = []

    # Transformador já classificou como inválido → bloqueante por definição.
    if l.get("status") == StatusLancamento.ERRO_VALIDACAO:
        issues.append(
            Issue(
                "erro",
                "STATUS_ERRO_VALIDACAO",
                "Lançamento marcado como erro_validacao na transformação (bloqueante).",
                {"motivo_status": l.get("motivo_status")},
            )
        )

    # Campos mínimos de auditabilidade (sempre exigidos).
    for campo in ("estudante", "trimestre", "disciplina", "componente",
                  "linha_origem", "hash_conteudo"):
        if is_blank(l.get(campo)):
            issues.append(
                Issue("erro", "CAMPO_OBRIGATORIO_AUSENTE",
                      f"Campo obrigatório ausente: {campo}", {"campo": campo})
            )

    # Campos adicionais exigidos apenas para lançamentos sendáveis.
    if _is_sendavel(l):
        campos_sendaveis = ("nota_ajustada_0a10",)
        if _componente_exige_ponderacao_local(l.get("componente")):
            campos_sendaveis += ("peso_avaliacao", "valor_ponderado")
        for campo in campos_sendaveis:
            if l.get(campo) is None:
                issues.append(
                    Issue("erro", "CAMPO_OBRIGATORIO_AUSENTE",
                          f"Campo obrigatório ausente para enviável: {campo}",
                          {"campo": campo})
                )

    # Lançamento pronto sem qualquer nota registrada.
    if l.get("status") == StatusLancamento.PRONTO:
        if (l.get("nota_original") is None) and (l.get("nota_ajustada_0a10") is None):
            issues.append(
                Issue("erro", "NOTA_AUSENTE",
                      "Lançamento 'pronto' sem nota_original e sem nota_ajustada_0a10.")
            )

    return issues


def _validar_faixa_lancamento(l: Mapping[str, Any]) -> list[Issue]:
    issues: list[Issue] = []

    n_adj = l.get("nota_ajustada_0a10")
    if n_adj is not None:
        try:
            n = float(n_adj)
            if n < 0 or n > 10:
                issues.append(
                    Issue("erro", "NOTA_FORA_FAIXA",
                          "nota_ajustada_0a10 fora de 0..10.", {"valor": n})
                )
        except Exception:
            issues.append(
                Issue("erro", "NOTA_NAO_NUMERICA",
                      "nota_ajustada_0a10 não numérica.", {"valor": n_adj})
            )

    v_pond = l.get("valor_ponderado")
    if v_pond is not None:
        try:
            vp = float(v_pond)
            if vp < 0:
                issues.append(
                    Issue("erro", "PONDERADO_NEGATIVO",
                          "valor_ponderado não pode ser negativo.", {"valor": vp})
                )
        except Exception:
            issues.append(
                Issue("erro", "PONDERADO_NAO_NUMERICO",
                      "valor_ponderado não numérico.", {"valor": v_pond})
            )

    # AV1 com ponto extra não pode ficar >10 (truncamento obrigatório na regra).
    if (l.get("componente") == "av1"
            and l.get("subcomponente") is None
            and l.get("nota_ajustada_0a10") is not None):
        obs = l.get("observacoes") or {}
        if isinstance(obs, dict) and obs.get("ponto_extra_aplicado_em_av1"):
            try:
                if float(l["nota_ajustada_0a10"]) > 10:
                    issues.append(
                        Issue("erro", "AV1_ACIMA_10",
                              "AV1 consolidada acima de 10 após ponto extra (faltou truncamento).")
                    )
            except Exception:
                pass

    # nota_original negativa é sempre suspeita.
    raw_num = _try_float(l.get("nota_original"))
    if raw_num is not None and raw_num < 0:
        issues.append(
            Issue("erro", "NOTA_ORIGINAL_NEGATIVA",
                  "nota_original negativa.", {"valor": raw_num})
        )

    return issues


# ---------------------------------------------------------------------------
# Comparação de totais
# ---------------------------------------------------------------------------

def _comparar_totais(
    row_wide: Mapping[str, Any],
    lancamentos: list[Mapping[str, Any]],
    *,
    tolerancia: float,
) -> list[ComparacaoTotal]:
    rn = normalizar_linha_madan(row_wide)

    informado_final = _try_float(rn.get(CAN_NOTA_FINAL))
    informado_com   = _try_float(rn.get(CAN_NOTA_COM_AV3))
    informado_sem   = _try_float(rn.get(CAN_NOTA_SEM_AV3))

    def _sum_componentes(comps: set[str]) -> float | None:
        vals: list[float] = []
        for l in lancamentos:
            if not _is_sendavel(l):
                continue
            if l.get("componente") in comps:
                v = _try_float(l.get("valor_ponderado"))
                if v is not None:
                    vals.append(v)
        return round(sum(vals), 2) if vals else None

    total_sem_av3 = _sum_componentes({"av1", "av2", "simulado"})
    total_com_av3 = _sum_componentes({"av1", "av2", "av3", "simulado"})
    tem_av3 = any(
        l.get("componente") == "av3" and _is_sendavel(l) for l in lancamentos
    )
    total_final = total_com_av3 if tem_av3 else total_sem_av3

    def _mk(campo: str, informado: float | None, calculado: float | None) -> ComparacaoTotal:
        if informado is None:
            return ComparacaoTotal(campo, None, calculado, None, tolerancia, "ausente")
        if calculado is None:
            return ComparacaoTotal(campo, informado, None, None, tolerancia, "nao_comparavel")
        diff = abs(calculado - informado)
        return ComparacaoTotal(
            campo, informado, calculado, diff, tolerancia,
            "confere" if diff <= tolerancia else "divergente",
        )

    return [
        _mk("nota_sem_av3", informado_sem, total_sem_av3),
        _mk("nota_com_av3", informado_com, total_com_av3),
        _mk("nota_final",   informado_final, total_final),
    ]


# ---------------------------------------------------------------------------
# Validação cruzada professor ↔ disciplina ↔ turma (PDF Madan 2026)
# ---------------------------------------------------------------------------

def _validar_professor_disciplina_turma(row_normalizada: Mapping[str, Any]) -> list[Issue]:
    """
    Valida se o professor indicado no campo 'Frente - Professor' é compatível
    com a disciplina e turma da linha, segundo o registro oficial do Madan.

    Gera AVISOS (não bloqueia) porque:
    - O campo pode ter formato inesperado
    - Professores substitutos podem não estar no registro
    - Erros de digitação na planilha são comuns
    """
    issues: list[Issue] = []

    frente_raw = row_normalizada.get(CAN_FRENTE_PROFESSOR)
    if is_blank(frente_raw):
        return issues  # sem frente_professor → nada a validar

    # Chaves como "arte", "fisica a", "biologia" são aliases de disciplina/frente
    # gerados automaticamente pelo wide_format_adapter para colunas sem nome de
    # professor explícito.  Não representam nome de pessoa — não há o que validar
    # no registro oficial.  Warning aqui seria falso positivo.
    if parece_chave_disciplina_frente(str(frente_raw)):
        return issues

    # Tenta extrair o nome do professor do campo
    nome_prof = extrair_professor_da_frente(str(frente_raw))
    if not nome_prof:
        return issues

    disciplina = row_normalizada.get(CAN_DISCIPLINA)
    turma = row_normalizada.get(CAN_TURMA)

    serie = extrair_serie_da_turma(turma) if turma else None
    turma_letra = None
    if turma and isinstance(turma, str):
        # Extrai a letra da turma (ex: "1A" → "A", "2B" → "B")
        for c in str(turma).strip():
            if c.isalpha():
                turma_letra = c.upper()
                break

    # Busca o professor no registro
    prof = buscar_por_nome_ou_apelido(nome_prof)
    if not prof:
        # Professor não encontrado — pode ser substituto ou formato diferente
        issues.append(Issue(
            "aviso",
            "PROFESSOR_NAO_ENCONTRADO_REGISTRO",
            f"Professor '{nome_prof}' (de '{frente_raw}') não encontrado no "
            f"registro oficial Madan 2026. Pode ser substituto ou formato diferente.",
            {"frente_professor": frente_raw, "nome_extraido": nome_prof},
        ))
        return issues

    # Valida compatibilidade com disciplina
    if not is_blank(disciplina):
        resultado = validar_professor_disciplina_turma(
            nome_professor=nome_prof,
            disciplina=str(disciplina),
            serie=serie,
            turma_letra=turma_letra,
        )
        for problema in resultado["problemas"]:
            issues.append(Issue(
                "aviso",
                "PROFESSOR_DISCIPLINA_TURMA_INCOMPATIVEL",
                problema,
                {
                    "frente_professor": frente_raw,
                    "professor": prof.nome_display,
                    "disciplina": disciplina,
                    "turma": turma,
                    "serie": serie,
                },
            ))

    return issues


# ---------------------------------------------------------------------------
# Ponto de entrada principal
# ---------------------------------------------------------------------------

def validar_pre_envio_linha(
    *,
    row_wide: Mapping[str, Any],
    lancamentos: list[Mapping[str, Any]],
    tolerancia_total: float = 0.05,
) -> dict[str, Any]:
    """
    Valida uma linha (wide) + seus lançamentos canônicos (Etapa 2).

    Retorna um dict estruturado para auditoria e decisão operacional:

        lancamentos_validos   – lançamentos sem erros de validação
        lancamentos_com_erro  – lançamentos com pelo menos um erro
        avisos                – lista de Issue.__dict__ (severity="aviso")
        pendencias            – lista de Issue.__dict__ (severity="pendencia")
                                inclui campo "bloqueante" para diferenciação
        duplicidades          – lista de conflitos detectados (não removidos)
        comparacoes_totais    – lista de ComparacaoTotal.__dict__
        status_geral          – "apto_para_aprovacao" | "apto_com_avisos"
                                | "bloqueado_por_erros"

    Política de status_geral
    ------------------------
    bloqueado_por_erros  : qualquer erro em lançamento, qualquer erro de linha,
                           ou qualquer pendência com bloqueante=True
    apto_com_avisos      : avisos e/ou pendências não-bloqueantes, sem erros
    apto_para_aprovacao  : nenhum erro, aviso nem pendência
    """
    lancs_annot: list[dict[str, Any]] = []
    erros: list[Issue] = []
    avisos: list[Issue] = []
    pendencias: list[Issue] = []

    # --- Validação de linha (estudante) ------------------------------------
    rn = normalizar_linha_madan(row_wide)
    for it in _validar_estudante_basico(rn.get("estudante")):
        (erros if it.severity == "erro"
         else avisos if it.severity == "aviso"
         else pendencias).append(it)

    # --- Validação cruzada professor ↔ disciplina ↔ turma -------------------
    for it in _validar_professor_disciplina_turma(rn):
        (erros if it.severity == "erro"
         else avisos if it.severity == "aviso"
         else pendencias).append(it)

    # --- Pendência de identificador ----------------------------------------
    # bloqueante=False: sinaliza que a validação de matrícula iScholar ainda
    # não existe nesta etapa, mas não impede "apto_para_aprovacao" por si só.
    # Na Etapa 4 (integração iScholar) este código será substituído pela
    # checagem real de id_matricula; até lá fica como lembrete auditável.
    pendencias.append(
        Issue(
            "pendencia",
            "IDENTIFICADOR_ISCHOLAR_PENDENTE",
            "Identificador canônico (id_matricula iScholar) ainda não validado nesta etapa.",
            bloqueante=False,
        )
    )

    # --- Validação por lançamento ------------------------------------------
    for l in lancamentos:
        issues_l: list[Issue] = []
        issues_l.extend(_validar_campos_obrigatorios_lancamento(l))
        issues_l.extend(_validar_faixa_lancamento(l))

        ann = dict(l)
        ann["validacao_erros"]     = [i.__dict__ for i in issues_l if i.severity == "erro"]
        ann["validacao_avisos"]    = [i.__dict__ for i in issues_l if i.severity == "aviso"]
        ann["validacao_pendencias"]= [i.__dict__ for i in issues_l if i.severity == "pendencia"]
        ann["sendavel"] = _is_sendavel(l)
        lancs_annot.append(ann)

        for i in issues_l:
            (erros if i.severity == "erro"
             else avisos if i.severity == "aviso"
             else pendencias).append(i)

    # --- Duplicidades dentro do lote ---------------------------------------
    # Política:
    #   sendável duplicado     → DUPLICIDADE_SENDAVEL  (erro bloqueante)
    #   não-sendável duplicado → DUPLICIDADE_INTERNA   (aviso)
    # Em ambos os casos o lançamento duplicado é marcado e MANTIDO na lista
    # (não-remoção garante rastreabilidade e idempotência futura).
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicidades: list[dict[str, Any]] = []

    for idx, l in enumerate(lancs_annot):
        key = _chave_duplicidade(l)
        if key in seen:
            first = seen[key]
            duplicidades.append(
                {
                    "chave": key,
                    "primeiro_idx": first["idx"],
                    "duplicado_idx": idx,
                    "primeiro_hash": first["hash"],
                    "duplicado_hash": l.get("hash_conteudo"),
                    "sendavel": l.get("sendavel", False),
                }
            )

            if l.get("sendavel", False):
                # Bloqueante: risco real de envio duplicado para o iScholar.
                dup_issue = Issue(
                    "erro",
                    "DUPLICIDADE_SENDAVEL",
                    "Lançamento sendável duplicado no mesmo lote — bloqueante.",
                    {"chave": key},
                )
                l.setdefault("validacao_erros", []).append(dup_issue.__dict__)
                erros.append(dup_issue)
            else:
                # Não-sendável: subcomponente ou item ignorado duplicado.
                # Sinaliza sem bloquear; pode ocorrer em merges de planilha.
                dup_issue = Issue(
                    "aviso",
                    "DUPLICIDADE_INTERNA",
                    "Lançamento não-sendável duplicado no mesmo lote.",
                    {"chave": key},
                )
                l.setdefault("validacao_avisos", []).append(dup_issue.__dict__)
                avisos.append(dup_issue)
        else:
            seen[key] = {"idx": idx, "hash": l.get("hash_conteudo")}

    # --- Comparação de totais ----------------------------------------------
    comparacoes = _comparar_totais(row_wide, lancs_annot, tolerancia=tolerancia_total)
    comparacoes_totais = [c.__dict__ for c in comparacoes]

    # Divergência vira aviso (não bloqueia automaticamente nesta etapa).
    for c in comparacoes:
        if c.resultado == "divergente":
            avisos.append(
                Issue(
                    "aviso",
                    "TOTAL_DIVERGENTE",
                    f"Total divergente para {c.campo}.",
                    {
                        "campo": c.campo,
                        "informado": c.informado,
                        "calculado": c.calculado,
                        "diff": c.diferenca_absoluta,
                    },
                )
            )

    # --- Partição de lançamentos -------------------------------------------
    # Re-lê validacao_erros depois da marcação de duplicidade.
    lancamentos_com_erro = [l for l in lancs_annot if l.get("validacao_erros")]
    lancamentos_validos  = [l for l in lancs_annot if not l.get("validacao_erros")]

    # --- Decisão de status_geral -------------------------------------------
    pendencias_bloqueantes = [p for p in pendencias if p.bloqueante]

    if erros or lancamentos_com_erro or pendencias_bloqueantes:
        status_geral = "bloqueado_por_erros"
    elif avisos or pendencias:           # pendências não-bloqueantes chegam aqui
        status_geral = "apto_com_avisos"
    else:
        status_geral = "apto_para_aprovacao"

    return {
        "lancamentos_validos":  lancamentos_validos,
        "lancamentos_com_erro": lancamentos_com_erro,
        "erros":                [e.__dict__ for e in erros],
        "avisos":               [a.__dict__ for a in avisos],
        "pendencias":           [p.__dict__ for p in pendencias],
        "duplicidades":         duplicidades,
        "comparacoes_totais":   comparacoes_totais,
        "status_geral":         status_geral,
    }


def criar_resultado_falha_linha(
    *,
    linha_origem: int,
    estudante: str,
    componente: str,
    mensagem_erro: str,
) -> dict[str, Any]:
    """
    Constrói um resultado pré-envio de falha interna para linhas que não
    puderam ser processadas (erro na transformação ou validação).

    Preserva auditabilidade no relatório do lote com o mesmo schema de
    ``validar_pre_envio_linha``.
    """
    erro_validacao = {
        "severity": "erro",
        "code": "ERRO_INTERNO_PROCESSAMENTO",
        "message": mensagem_erro,
        "bloqueante": True,
    }
    lancamento_falha: dict[str, Any] = {
        "estudante":       estudante,
        "componente":      componente,
        "linha_origem":    linha_origem,
        "validacao_erros": [erro_validacao],
        "sendavel": False,
    }
    return {
        "lancamentos_validos":  [],
        "lancamentos_com_erro": [lancamento_falha],
        "erros":                [erro_validacao],
        "avisos":               [],
        "pendencias":           [],
        "duplicidades":         [],
        "comparacoes_totais":   [],
        "status_geral":         STATUS_BLOQUEADO_ERROS,
    }


__all__ = [
    "validar_pre_envio_linha",
    "criar_resultado_falha_linha",
    "Issue",
    "ComparacaoTotal",
    "STATUS_APROVADO",
    "STATUS_COM_AVISOS",
    "STATUS_BLOQUEADO_ERROS",
]
