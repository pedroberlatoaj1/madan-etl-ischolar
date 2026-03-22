"""
avaliacao_rules.py — Regras avaliativas do Madan (Etapa 1)

Camada explícita, testável e isolada das regras pedagógicas. Não depende de fila,
worker, HTTP ou integração com iScholar.
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
# Tabela oficial de pesos (PDF "Sistema Avaliativo.pdf")
# ---------------------------------------------------------------------------

PESOS_OFICIAIS: dict[tuple[str, bool], dict[str, float]] = {
    # 1º e 2º trimestre, sem nivelamento
    ("t1t2", False): {AV1: 12.0, AV2: 15.0, SIMULADO: 3.0},
    # 1º e 2º trimestre, com nivelamento
    ("t1t2", True): {AV1: 9.0, AV2: 9.0, AV3: 9.0, SIMULADO: 3.0},
    # 3º trimestre, sem nivelamento
    ("t3", False): {AV1: 16.0, AV2: 18.0, SIMULADO: 6.0},
    # 3º trimestre, com nivelamento
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
    Regra oficial: Av3 (nivelamento) = 7,0 pontos de listas + 3,0 pontos de avaliação.
    Notas digitadas seguem 0..10, então:
      Av3 = (listas/10)*7 + (avaliacao/10)*3
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
    Regra oficial (PDF): pontos extras devem ser computados na coluna Av1,
    a menos que o aluno tenha fechado essa avaliação.

    Regras obrigatórias:
    - se Av1 já estiver em 10, ponto extra deve ser ignorado
    - se Av1 + ponto extra ultrapassar 10, truncar em 10
    - notas > 10 são inválidas, exceto no caso do somatório antes do truncamento
    - ponto extra negativo => erro
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
    policy: Literal["media_simples", "maximo"] = "media_simples",
    arredondar: int | None = 2,
) -> float | None:
    """
    Consolida subcomponentes (OBJ + DISC) em uma nota única 0..10.

    Política provisória (Etapa 2) — explícita e auditável:
    - Se OBJ e DISC existirem: usa a política indicada:
      - "media_simples": (obj + disc) / 2
      - "maximo": max(obj, disc)
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

    if policy == "media_simples":
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

