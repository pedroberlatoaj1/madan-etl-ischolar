"""
avaliacao_rules.py — Regras avaliativas do Madan (Etapa 1)

Camada explícita, testável e isolada das regras pedagógicas. Não depende de fila,
worker, HTTP ou integração com iScholar.

Fonte oficial: "Sistema Avaliativo.pdf" (documento interno do Madan, 1ª e 2ª séries).

STATUS DAS REGRAS (atualizado 2026-03-25):
─────────────────────────────────────────
✅ CONFIRMADO pelo PDF:
   - Tabela de pesos por trimestre e nivelamento (PESOS_OFICIAIS)
   - AV3 = 70% listas + 30% avaliação (calcular_av3_nivelamento)
   - Ponto extra aplicado na coluna AV1, teto de 10 (aplicar_ponto_extra_em_av1)
   - Ponto extra ignorado se avaliação "fechada" (avaliacao_fechada=True)
   - Notas digitadas de 0 a 10, pesos aplicados pelo iScholar (não pelo pipeline)
   - AV3 condicional: só para alunos com nivelamento

✅ CONFIRMADO pelo pedagógico do Madan:
   - consolidar_obj_disc: SOMA SIMPLES de OBJ + DISC (não média), com teto 10
   - 3ª série: EXCLUÍDA do processamento (regras diferentes, não documentadas)

✅ CONFIRMADO pelo pedagógico do Madan (regras de recuperação):
   - Recuperação trimestral: rendimento < 60% no T1 ou T2
   - T3 NÃO tem recuperação trimestral (exceção explícita)
   - Recuperação final: rendimento anual < 60%
   - Rendimento anual = média ponderada: (T1×30 + T2×30 + T3×40) / 100

ℹ️ NOTA IMPORTANTE:
   O pipeline envia notas BRUTAS (0 a 10) ao iScholar. Os pesos da tabela
   PESOS_OFICIAIS são aplicados PELO iScholar ao receber a nota, não pelo
   nosso código de envio. O pipeline usa os pesos apenas para validação,
   conferência e auditoria local.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isnan
from typing import Any, Mapping, Literal


# ---------------------------------------------------------------------------
# Nomes canônicos de componentes
# ---------------------------------------------------------------------------

AV1 = "av1"
AV2 = "av2"
AV3 = "av3"
SIMULADO = "simulado"

# Componentes internos do nivelamento (Av3)
AV3_LISTAS = "av3_listas"
AV3_AVALIACAO = "av3_avaliacao"

# Ponto extra (aplica em Av1)
PONTO_EXTRA = "ponto_extra"

COMPONENTES_PESADOS = (AV1, AV2, AV3, SIMULADO)
COMPONENTES_CANONICOS = (AV1, AV2, AV3, SIMULADO, AV3_LISTAS, AV3_AVALIACAO, PONTO_EXTRA)


# ---------------------------------------------------------------------------
# Tabela oficial de pesos — CONFIRMADA pelo PDF "Sistema Avaliativo.pdf"
# ---------------------------------------------------------------------------
# Totais: T1/T2 = 30 pontos | T3 = 40 pontos
# Sem nivelamento: AV3 não existe (peso redistributído entre AV1/AV2/Simulado)
# Com nivelamento: AV3 recebe peso próprio
# Aplica-se a 1ª e 2ª séries. Regras da 3ª série ainda não documentadas.

PESOS_OFICIAIS: dict[tuple[str, bool], dict[str, float]] = {
    # 1º e 2º trimestre, sem nivelamento (total = 30)
    ("t1t2", False): {AV1: 12.0, AV2: 15.0, SIMULADO: 3.0},
    # 1º e 2º trimestre, com nivelamento (total = 30)
    ("t1t2", True): {AV1: 9.0, AV2: 9.0, AV3: 9.0, SIMULADO: 3.0},
    # 3º trimestre, sem nivelamento (total = 40)
    ("t3", False): {AV1: 16.0, AV2: 18.0, SIMULADO: 6.0},
    # 3º trimestre, com nivelamento (total = 40)
    ("t3", True): {AV1: 12.0, AV2: 12.0, AV3: 12.0, SIMULADO: 4.0},
}


def _is_nan(value: Any) -> bool:
    try:
        return isinstance(value, float) and isnan(value)
    except Exception:
        return False


def is_blank(value: Any) -> bool:
    """
    Regra obrigatória: vazio/null/NaN/string vazia => ignorar componente.
    """
    if value is None:
        return True
    if _is_nan(value):
        return True
    # Compatível com pandas.NA sem importar pandas aqui
    if str(value) in {"<NA>"}:
        return True
    if isinstance(value, str):
        if value.strip() == "":
            return True
        if value.strip().lower() in {"nan", "none", "null"}:
            return True
    return False


def normalizar_trimestre(trimestre: Any) -> str:
    """
    Normaliza trimestre para uma das chaves canônicas usadas na tabela de pesos:
    - "t1t2" para 1º ou 2º trimestre
    - "t3" para 3º trimestre
    """
    if is_blank(trimestre):
        raise ValueError("Trimestre ausente (vazio).")

    if isinstance(trimestre, (int,)):
        t = trimestre
    elif isinstance(trimestre, float) and not _is_nan(trimestre):
        if trimestre.is_integer():
            t = int(trimestre)
        else:
            raise ValueError(f"Trimestre inválido (não-inteiro): {trimestre!r}")
    else:
        s = str(trimestre).strip().lower()
        # Aceita "1", "1º", "1o", "1°", "trimestre 1" etc.
        if "3" in s:
            t = 3
        elif "2" in s:
            t = 2
        elif "1" in s:
            t = 1
        else:
            raise ValueError(f"Trimestre inválido: {trimestre!r}")

    if t in (1, 2):
        return "t1t2"
    if t == 3:
        return "t3"
    raise ValueError(f"Trimestre fora do domínio (esperado 1, 2 ou 3): {trimestre!r}")


def obter_pesos(trimestre: Any, nivelamento: bool) -> dict[str, float]:
    key = (normalizar_trimestre(trimestre), bool(nivelamento))
    try:
        # cópia defensiva: chamadores não devem mutar a tabela global
        return dict(PESOS_OFICIAIS[key])
    except KeyError as e:
        raise ValueError(f"Combinação de pesos não encontrada para {key!r}.") from e


def _coerce_float(value: Any) -> float:
    if isinstance(value, (int, float)) and not _is_nan(value):
        return float(value)
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        return float(s)
    raise ValueError(f"Valor não numérico: {value!r}")


def validar_nota_0_10(nota: Any, *, allow_blank: bool = False) -> float | None:
    """
    Converte e valida nota (0 a 10). Por regra:
    - notas negativas => erro
    - notas > 10 => erro
    - vazio => None (se allow_blank=True) ou erro (se allow_blank=False)
    """
    if is_blank(nota):
        if allow_blank:
            return None
        raise ValueError("Nota ausente (vazio).")

    n = _coerce_float(nota)
    if n < 0:
        raise ValueError(f"Nota negativa inválida: {n!r}")
    if n > 10:
        raise ValueError(f"Nota acima de 10 inválida: {n!r}")
    return n


def calcular_nota_ponderada(nota_0_10: Any, peso: Any, *, arredondar: int | None = 2) -> float:
    """
    Regra oficial: avaliações são digitadas de 0 a 10, mas recebem pesos por trimestre.
    Nota ponderada = (nota / 10) * peso
    """
    n = validar_nota_0_10(nota_0_10, allow_blank=False)
    p = _coerce_float(peso)
    if p < 0:
        raise ValueError(f"Peso negativo inválido: {p!r}")
    v = (n / 10.0) * p
    return round(v, arredondar) if arredondar is not None else v


def calcular_av3_nivelamento(av3_listas: Any, av3_avaliacao: Any, *, arredondar: int | None = 2) -> float:
    """
    ✅ CONFIRMADO pelo PDF "Sistema Avaliativo.pdf":
    Av3 (nivelamento) = 7,0 pontos de listas + 3,0 pontos de avaliação.
    Notas digitadas seguem 0..10, então:
      Av3 = (listas/10)*7 + (avaliacao/10)*3

    Apenas alunos com nivelamento possuem AV3.
    """
    listas = validar_nota_0_10(av3_listas, allow_blank=False)
    avaliacao = validar_nota_0_10(av3_avaliacao, allow_blank=False)
    v = (listas / 10.0) * 7.0 + (avaliacao / 10.0) * 3.0
    return round(v, arredondar) if arredondar is not None else v


def aplicar_ponto_extra_em_av1(
    av1: Any,
    ponto_extra: Any,
    *,
    avaliacao_fechada: bool = False,
    arredondar: int | None = 2,
) -> float:
    """
    ✅ CONFIRMADO pelo PDF "Sistema Avaliativo.pdf":
    "Os pontos extras devem ser computados na coluna Av1, a menos que
     o aluno tenha fechado essa avaliação."

    Regras confirmadas:
    - Ponto extra é somado à nota da AV1
    - Se AV1 já estiver em 10, ponto extra deve ser ignorado
    - Se AV1 + ponto extra ultrapassar 10, truncar em 10 (teto)
    - Se avaliacao_fechada=True, retorna AV1 sem alteração
    - Ponto extra negativo => erro

    ⚠️ PENDENTE: definição exata de "fechada" (a confirmar na reunião).
    """
    n_av1 = validar_nota_0_10(av1, allow_blank=False)
    if avaliacao_fechada:
        return round(n_av1, arredondar) if arredondar is not None else n_av1

    if is_blank(ponto_extra):
        return round(n_av1, arredondar) if arredondar is not None else n_av1

    extra = _coerce_float(ponto_extra)
    if extra < 0:
        raise ValueError(f"Ponto extra negativo inválido: {extra!r}")

    if n_av1 >= 10.0:
        return 10.0

    somatorio = n_av1 + extra  # pode exceder 10 antes do truncamento (permitido)
    v = min(10.0, somatorio)
    return round(v, arredondar) if arredondar is not None else v


def consolidar_obj_disc(
    nota_obj: Any,
    nota_disc: Any,
    *,
    policy: Literal["soma", "media_simples", "maximo"] = "soma",
    arredondar: int | None = 2,
) -> float | None:
    """
    ✅ CONFIRMADO pelo pedagógico do Madan:
    AV1 e AV2 são compostas por duas provas (Objetiva e Discursiva).
    A nota final é a SOMA SIMPLES de OBJ + DISC, com restrição: soma ≤ 10.

    Políticas disponíveis:
    - "soma" (OFICIAL): obj + disc, com validação soma ≤ 10
    - "media_simples": (obj + disc) / 2  (legado, mantido por compatibilidade)
    - "maximo": max(obj, disc)  (legado, mantido por compatibilidade)

    Regras:
    - Se OBJ e DISC existirem: aplica a política indicada
    - Se apenas um existir: usa esse valor
    - Se nenhum existir: retorna None (componente deve ser ignorado)

    Observação: esta função NÃO aplica ponto extra; isso é específico de AV1.
    """
    obj = validar_nota_0_10(nota_obj, allow_blank=True)
    disc = validar_nota_0_10(nota_disc, allow_blank=True)

    if obj is None and disc is None:
        return None
    if obj is None:
        return round(disc, arredondar) if arredondar is not None else disc  # type: ignore[arg-type]
    if disc is None:
        return round(obj, arredondar) if arredondar is not None else obj

    if policy == "soma":
        v = obj + disc
        if v > 10:
            raise ValueError(
                f"Soma OBJ ({obj}) + DISC ({disc}) = {v} ultrapassa 10. "
                f"A soma das provas objetiva e discursiva deve ser ≤ 10."
            )
    elif policy == "media_simples":
        v = (obj + disc) / 2.0
    elif policy == "maximo":
        v = max(obj, disc)
    else:  # pragma: no cover
        raise ValueError(f"Policy inválida: {policy!r}")

    return round(v, arredondar) if arredondar is not None else v


@dataclass(frozen=True)
class ExtracaoComponentes:
    """
    Resultado puro da extração de componentes de uma linha da planilha.
    - componentes: apenas componentes com nota válida e presente (vazios são ignorados)
    - av3_incompleta: True se apenas um dos subcomponentes (listas/avaliacao) veio preenchido
    """

    componentes: dict[str, float]
    av3_incompleta: bool


def extrair_componentes_validos(linha: Mapping[str, Any]) -> ExtracaoComponentes:
    """
    Extrai componentes canônicos a partir de uma linha (dict-like), ignorando vazios.

    Regras obrigatórias:
    - vazio/null/NaN/string vazia => ignorar componente (não vira zero)
    - Av3 só é calculada se listas e avaliação estiverem ambas presentes
    - se só um componente da Av3 existir, marca como incompleto e não gera Av3
    """
    # Aceita chaves canônicas (Etapa 1) — aliases ficam fora desta camada.
    raw_av1 = linha.get(AV1)
    raw_av2 = linha.get(AV2)
    raw_sim = linha.get(SIMULADO)
    raw_listas = linha.get(AV3_LISTAS)
    raw_aval = linha.get(AV3_AVALIACAO)
    raw_extra = linha.get(PONTO_EXTRA)

    componentes: dict[str, float] = {}

    if not is_blank(raw_av1):
        componentes[AV1] = validar_nota_0_10(raw_av1, allow_blank=False)  # type: ignore[assignment]
    if not is_blank(raw_av2):
        componentes[AV2] = validar_nota_0_10(raw_av2, allow_blank=False)  # type: ignore[assignment]
    if not is_blank(raw_sim):
        componentes[SIMULADO] = validar_nota_0_10(raw_sim, allow_blank=False)  # type: ignore[assignment]

    listas_present = not is_blank(raw_listas)
    aval_present = not is_blank(raw_aval)
    av3_incompleta = (listas_present ^ aval_present)  # XOR: apenas um presente
    if listas_present and aval_present:
        componentes[AV3] = calcular_av3_nivelamento(raw_listas, raw_aval, arredondar=2)

    # Ponto extra é componente de decisão, não entra em COMPONENTES_PESADOS diretamente,
    # mas pode ser retornado para aplicação posterior fora desta função.
    if not is_blank(raw_extra):
        extra = _coerce_float(raw_extra)
        if extra < 0:
            raise ValueError(f"Ponto extra negativo inválido: {extra!r}")
        componentes[PONTO_EXTRA] = extra

    return ExtracaoComponentes(componentes=componentes, av3_incompleta=av3_incompleta)


# ---------------------------------------------------------------------------
# Recuperação — regras confirmadas pelo pedagógico do Madan
# ---------------------------------------------------------------------------
# ✅ CONFIRMADO:
#   1. Recuperação trimestral: rendimento < 60% no T1 ou T2.
#   2. Exceção do 3º trimestre: NÃO existe recuperação trimestral para T3.
#   3. Recuperação final: rendimento anual < 60%.
#   4. Rendimento anual = média ponderada: T1×30 + T2×30 + T3×40 (÷ 100).
#
# DEFINIÇÃO DE RENDIMENTO TRIMESTRAL:
#   rendimento_trimestral = (soma_ponderados / total_pesos_trimestre) * 100
#   Onde total_pesos_trimestre = 30 (T1/T2) ou 40 (T3).
#
# ℹ️ O pipeline processa cada trimestre isoladamente (uma planilha por
#   trimestre). O cálculo de rendimento anual e recuperação final exige
#   agregar os 3 trimestres — isso é feito no nível de lote/relatório,
#   não no transformador individual.

LIMIAR_RECUPERACAO: float = 60.0
"""Limiar de rendimento (%) abaixo do qual o aluno fica em recuperação."""

PESOS_TRIMESTRAIS_ANUAIS: dict[str, float] = {
    "t1": 30.0,
    "t2": 30.0,
    "t3": 40.0,
}
"""Pesos dos trimestres para cálculo do rendimento anual (total = 100)."""

TRIMESTRES_COM_RECUPERACAO: tuple[str, ...] = ("t1", "t2")
"""Apenas T1 e T2 têm recuperação trimestral. T3 NÃO tem."""


def calcular_rendimento_trimestral(
    soma_ponderados: Any,
    trimestre: Any,
    *,
    arredondar: int | None = 2,
) -> float:
    """
    Calcula o rendimento percentual do trimestre.

    rendimento = (soma_ponderados / total_pesos_trimestre) × 100

    Onde total_pesos_trimestre:
      - T1/T2: 30 pontos
      - T3:    40 pontos

    Retorna valor em percentual (0.0 a 100.0).
    """
    soma = _coerce_float(soma_ponderados)
    if soma < 0:
        raise ValueError(f"Soma de ponderados negativa: {soma!r}")

    tri_norm = normalizar_trimestre(trimestre)
    if tri_norm == "t1t2":
        total_pesos = 30.0
    elif tri_norm == "t3":
        total_pesos = 40.0
    else:
        raise ValueError(f"Trimestre inválido para rendimento: {trimestre!r}")

    rendimento = (soma / total_pesos) * 100.0
    return round(rendimento, arredondar) if arredondar is not None else rendimento


def verificar_recuperacao_trimestral(
    rendimento_percentual: Any,
    trimestre: Any,
) -> bool:
    """
    Verifica se o aluno fica em recuperação trimestral.

    ✅ Regra 1: rendimento < 60% → recuperação trimestral.
    ✅ Regra 2: T3 NUNCA tem recuperação trimestral.

    Retorna True se o aluno deve fazer recuperação trimestral.
    """
    rend = _coerce_float(rendimento_percentual)
    tri_norm = normalizar_trimestre(trimestre)

    # Regra 2: T3 nunca tem recuperação trimestral
    if tri_norm == "t3":
        return False

    # Regra 1: rendimento < 60% → recuperação
    return rend < LIMIAR_RECUPERACAO


def calcular_rendimento_anual(
    rendimento_t1: Any,
    rendimento_t2: Any,
    rendimento_t3: Any,
    *,
    arredondar: int | None = 2,
) -> float:
    """
    Calcula o rendimento anual por média ponderada.

    ✅ Regra 4:
      rendimento_anual = (T1 × 30 + T2 × 30 + T3 × 40) / 100

    Os rendimentos de entrada são percentuais (0.0 a 100.0).
    Retorna percentual (0.0 a 100.0).
    """
    r1 = _coerce_float(rendimento_t1)
    r2 = _coerce_float(rendimento_t2)
    r3 = _coerce_float(rendimento_t3)

    for label, val in [("T1", r1), ("T2", r2), ("T3", r3)]:
        if val < 0 or val > 100:
            raise ValueError(
                f"Rendimento {label} fora da faixa 0-100: {val!r}"
            )

    anual = (
        r1 * PESOS_TRIMESTRAIS_ANUAIS["t1"]
        + r2 * PESOS_TRIMESTRAIS_ANUAIS["t2"]
        + r3 * PESOS_TRIMESTRAIS_ANUAIS["t3"]
    ) / 100.0

    return round(anual, arredondar) if arredondar is not None else anual


def verificar_recuperacao_final(
    rendimento_anual: Any,
) -> bool:
    """
    Verifica se o aluno fica em recuperação final.

    ✅ Regra 3: rendimento anual < 60% → recuperação final.

    O rendimento_anual deve ser o resultado de calcular_rendimento_anual().
    Retorna True se o aluno deve fazer recuperação final.
    """
    rend = _coerce_float(rendimento_anual)
    return rend < LIMIAR_RECUPERACAO


@dataclass(frozen=True)
class ResultadoRecuperacao:
    """
    Resultado completo da avaliação de recuperação de um aluno.

    Campos:
      rendimento_t1, rendimento_t2, rendimento_t3: percentuais por trimestre
      rendimento_anual: média ponderada (30-30-40)
      recuperacao_t1: True se precisa de recuperação no T1
      recuperacao_t2: True se precisa de recuperação no T2
      recuperacao_t3: sempre False (T3 não tem recuperação)
      recuperacao_final: True se rendimento anual < 60%
    """
    rendimento_t1: float
    rendimento_t2: float
    rendimento_t3: float
    rendimento_anual: float
    recuperacao_t1: bool
    recuperacao_t2: bool
    recuperacao_t3: bool   # sempre False — explícito para auditoria
    recuperacao_final: bool


def avaliar_recuperacao_completa(
    soma_ponderados_t1: Any,
    soma_ponderados_t2: Any,
    soma_ponderados_t3: Any,
) -> ResultadoRecuperacao:
    """
    Avaliação completa de recuperação: calcula rendimentos e verifica
    todas as regras de recuperação de uma vez.

    Entrada: soma dos valores ponderados de cada trimestre.
    Saída: ResultadoRecuperacao com todos os flags e percentuais.
    """
    rend_t1 = calcular_rendimento_trimestral(soma_ponderados_t1, 1)
    rend_t2 = calcular_rendimento_trimestral(soma_ponderados_t2, 2)
    rend_t3 = calcular_rendimento_trimestral(soma_ponderados_t3, 3)

    rend_anual = calcular_rendimento_anual(rend_t1, rend_t2, rend_t3)

    return ResultadoRecuperacao(
        rendimento_t1=rend_t1,
        rendimento_t2=rend_t2,
        rendimento_t3=rend_t3,
        rendimento_anual=rend_anual,
        recuperacao_t1=verificar_recuperacao_trimestral(rend_t1, 1),
        recuperacao_t2=verificar_recuperacao_trimestral(rend_t2, 2),
        recuperacao_t3=False,  # Regra 2: T3 NUNCA tem recuperação
        recuperacao_final=verificar_recuperacao_final(rend_anual),
    )


# ---------------------------------------------------------------------------
# Constantes de status e motivo_status de lançamentos (Etapa 2)
# ---------------------------------------------------------------------------

class StatusLancamento:
    """Valores possíveis para o campo 'status' de um lançamento canônico."""
    PRONTO         = "pronto"
    IGNORADO       = "ignorado"
    ERRO_VALIDACAO = "erro_validacao"
    INCOMPLETO     = "incompleto"
    BLOQUEADO      = "bloqueado"


class MotivoStatus:
    """Valores possíveis para o campo 'motivo_status' de um lançamento canônico."""
    EM_BRANCO                      = "em_branco"
    OK                             = "ok"
    CAMPO_CONFERENCIA              = "campo_de_conferencia_apenas"
    METADADO_CONFERENCIA           = "metadado_de_conferencia"
    CONSOLIDADO_OBJ_DISC           = "consolidado_obj_disc"
    SUBCOMPONENTE_PRESERVADO       = "subcomponente_preservado"
    SUBCOMPONENTE_PRESERVADO_SEM_CONS = "subcomponente_preservado_sem_consolidacao"
    PESO_AUSENTE                   = "peso_ausente_para_cenario"
    PESO_SIMULADO_AUSENTE          = "peso_simulado_ausente_para_cenario"
    PESO_AV3_AUSENTE               = "peso_av3_ausente_para_cenario"
    AV3_INCOMPLETA                 = "av3_incompleta_precisa_listas_e_avaliacao"
    REC_T3_NAO_EXISTE              = "recuperacao_trimestral_nao_existe_para_t3"
    REC_TRIMESTRAL_CONFIRMADA      = "recuperacao_trimestral_confirmada"
    PRESERVADO_AV1_CONTRATO        = "preservado_aplicacao_em_av1_depende_de_contrato_avaliacao_fechada"

