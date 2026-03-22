"""
madan_planilha_mapper.py — Ponte planilha Madan (wide) -> chaves canônicas.

Responsabilidades:
- normalizar nomes de colunas (case/acentos/espaços/sinais)
- centralizar aliases de cabeçalho da planilha Madan
- normalizar uma linha wide em um dict canônico intermediário (sem aplicar regra pedagógica)
- inferir heurística de nivelamento (documentada)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

from avaliacao_rules import is_blank


# ---------------------------------------------------------------------------
# Chaves canônicas (contexto + componentes)
# ---------------------------------------------------------------------------

CAN_ESTUDANTE = "estudante"
CAN_RA = "ra"          # Registro do Aluno — obrigatório no template fixo
CAN_TRIMESTRE = "trimestre"
CAN_DISCIPLINA = "disciplina"
CAN_FRENTE_PROFESSOR = "frente_professor"
CAN_TURMA = "turma"

CAN_AV1_OBJ = "av1_obj"
CAN_AV1_DISC = "av1_disc"
CAN_AV2_OBJ = "av2_obj"
CAN_AV2_DISC = "av2_disc"
CAN_AV3_LISTAS = "av3_listas"
CAN_AV3_AVALIACAO = "av3_avaliacao"
CAN_SIMULADO = "simulado"
CAN_PONTO_EXTRA = "ponto_extra"

# Campos de conferência (não são fonte principal)
CAN_NOTA_SEM_AV3 = "nota_sem_av3"
CAN_NOTA_COM_AV3 = "nota_com_av3"
CAN_NOTA_FINAL = "nota_final"
CAN_RECUPERACAO = "recuperacao"
CAN_OBS_PONTO_EXTRA = "observacao_ponto_extra"


def normalizar_nome_coluna(nome: str) -> str:
    """
    Normaliza cabeçalho para uma forma comparável (não é a chave canônica final).
    Ex.: "AV 1 (OBJ)" -> "av_1_obj"
    """
    n = str(nome).strip().lower()
    n = "".join(
        c for c in unicodedata.normalize("NFD", n) if unicodedata.category(c) != "Mn"
    )
    # Padroniza separadores
    n = n.replace("-", " ").replace("/", " ").replace("\\", " ")
    # Remove parênteses e pontuação, mantendo palavras e números
    n = re.sub(r"[(){}\[\].,:;]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    n = n.replace(" ", "_")
    # Remove caracteres estranhos mantendo alnum/underscore
    n = "".join(c for c in n if c.isalnum() or c == "_")
    # Alguns cabeçalhos têm "av 1" separado: colapsa "av_1" e "av1"
    n = n.replace("av_", "av_")
    return n


def _aliases(*vals: str) -> set[str]:
    return {normalizar_nome_coluna(v) for v in vals}


# Aliases centralizados (forma normalizada -> chave canônica)
ALIASES_PARA_CANONICO: dict[str, str] = {}

def _register(canon: str, *aliases: str) -> None:
    for a in _aliases(*aliases):
        ALIASES_PARA_CANONICO[a] = canon


# Contexto
_register(CAN_ESTUDANTE, "estudante", "aluno", "nome_aluno", "nome do aluno")
_register(CAN_RA, "RA", "ra", "numero_re", "registro_aluno", "matricula_aluno")
_register(CAN_TRIMESTRE, "trimestre", "trimeste", "tri", "trimestre (t)", "trimestre_t")
_register(CAN_DISCIPLINA, "disciplina", "matéria", "materia")
_register(CAN_FRENTE_PROFESSOR, "frente_professor", "frente - professor", "frente professor", "frente")
_register(CAN_TURMA, "turma", "sala", "classe")

# Componentes avaliativos
_register(CAN_AV1_OBJ, "av 1 (obj)", "av1 (obj)", "av1_obj", "av_1_obj", "av 1 obj")
_register(CAN_AV1_DISC, "av 1 (disc)", "av 1 (disç)", "av1 (disc)", "av1_disc", "av_1_disc", "av 1 disc")
_register(CAN_AV2_OBJ, "av 2 (obj)", "av2 (obj)", "av2_obj", "av_2_obj", "av 2 obj")
_register(CAN_AV2_DISC, "av 2 (disc)", "av 2 (disç)", "av2 (disc)", "av2_disc", "av_2_disc", "av 2 disc")
_register(CAN_AV3_LISTAS, "av 3 (listas)", "av3 (listas)", "av3_listas", "av_3_listas", "av 3 listas")
_register(CAN_AV3_AVALIACAO, "av 3 (avaliacao)", "av 3 (avaliação)", "av3 (avaliacao)", "av3_avaliacao", "av_3_avaliacao", "av 3 avaliacao")
_register(CAN_SIMULADO, "simulado", "sim", "simul")
_register(CAN_PONTO_EXTRA, "ponto extra", "ponto_extra", "extra", "bonus", "bônus")

# Conferência/observações
_register(CAN_NOTA_SEM_AV3, "nota sem a av 3", "nota sem av3", "nota_sem_av3")
_register(CAN_NOTA_COM_AV3, "nota com a av 3", "nota com a av", "nota com av3", "nota_com_av3")
_register(CAN_NOTA_FINAL, "nota final", "nota_final")
_register(CAN_RECUPERACAO, "recuperacao", "recuperação", "rec")
_register(CAN_OBS_PONTO_EXTRA, "observacao relacionada ao ponto extra", "observação relacionada ao ponto extra", "obs ponto extra", "observacao_ponto_extra")


def mapear_colunas_madan(columns: list[str]) -> dict[str, str]:
    """
    Devolve um dict {coluna_original -> chave_canonica} para as colunas reconhecidas.
    Colunas não reconhecidas são ignoradas (não são apagadas; apenas não mapeadas).
    """
    out: dict[str, str] = {}
    for col in columns:
        norm = normalizar_nome_coluna(col)
        canon = ALIASES_PARA_CANONICO.get(norm)
        if canon:
            out[col] = canon
    return out


def normalizar_linha_madan(row: Mapping[str, Any]) -> dict[str, Any]:
    """
    Converte uma linha wide (dict-like / pandas.Series) em um dict com chaves canônicas
    (apenas para colunas reconhecidas).
    """
    mapping = mapear_colunas_madan(list(row.keys()))
    out: dict[str, Any] = {}
    for original, canon in mapping.items():
        out[canon] = row.get(original)
    return out


def inferir_tem_nivelamento(row_normalizada: Mapping[str, Any]) -> bool:
    """
    Heurística explícita (Etapa 2):
    - se houver conteúdo válido em av3_listas OU av3_avaliacao => tem_nivelamento=True
    - caso contrário => False
    """
    return (not is_blank(row_normalizada.get(CAN_AV3_LISTAS))) or (
        not is_blank(row_normalizada.get(CAN_AV3_AVALIACAO))
    )


def extrair_contexto_linha(row_normalizada: Mapping[str, Any]) -> dict[str, Any]:
    return {
        CAN_ESTUDANTE: row_normalizada.get(CAN_ESTUDANTE),
        CAN_RA: row_normalizada.get(CAN_RA),
        CAN_TURMA: row_normalizada.get(CAN_TURMA),
        CAN_DISCIPLINA: row_normalizada.get(CAN_DISCIPLINA),
        CAN_FRENTE_PROFESSOR: row_normalizada.get(CAN_FRENTE_PROFESSOR),
        CAN_TRIMESTRE: row_normalizada.get(CAN_TRIMESTRE),
    }


@dataclass(frozen=True)
class LinhaMadanCanonica:
    contexto: dict[str, Any]
    componentes: dict[str, Any]
    tem_nivelamento: bool


def linha_wide_para_canonica(row: Mapping[str, Any]) -> LinhaMadanCanonica:
    """
    Empacota a linha wide em uma estrutura intermediária:
    - contexto: estudante/turma/disciplina/frente_professor/trimestre
    - componentes: notas e campos auxiliares
    - tem_nivelamento: inferido pela heurística documentada
    """
    rn = normalizar_linha_madan(row)
    contexto = extrair_contexto_linha(rn)
    tem_nivelamento = inferir_tem_nivelamento(rn)

    componentes = {
        CAN_AV1_OBJ: rn.get(CAN_AV1_OBJ),
        CAN_AV1_DISC: rn.get(CAN_AV1_DISC),
        CAN_AV2_OBJ: rn.get(CAN_AV2_OBJ),
        CAN_AV2_DISC: rn.get(CAN_AV2_DISC),
        CAN_AV3_LISTAS: rn.get(CAN_AV3_LISTAS),
        CAN_AV3_AVALIACAO: rn.get(CAN_AV3_AVALIACAO),
        CAN_SIMULADO: rn.get(CAN_SIMULADO),
        CAN_PONTO_EXTRA: rn.get(CAN_PONTO_EXTRA),
        CAN_NOTA_SEM_AV3: rn.get(CAN_NOTA_SEM_AV3),
        CAN_NOTA_COM_AV3: rn.get(CAN_NOTA_COM_AV3),
        CAN_NOTA_FINAL: rn.get(CAN_NOTA_FINAL),
        CAN_RECUPERACAO: rn.get(CAN_RECUPERACAO),
        CAN_OBS_PONTO_EXTRA: rn.get(CAN_OBS_PONTO_EXTRA),
    }

    return LinhaMadanCanonica(contexto=contexto, componentes=componentes, tem_nivelamento=tem_nivelamento)


# ---------------------------------------------------------------------------
# Validação do template fixo
# ---------------------------------------------------------------------------

# Colunas obrigatórias do template Excel fixo entregue ao Madan.
# Se qualquer uma delas estiver completamente ausente do cabeçalho da planilha,
# o pipeline deve falhar antes de processar qualquer linha.
COLUNAS_OBRIGATORIAS_TEMPLATE: tuple[str, ...] = (
    CAN_ESTUDANTE,
    CAN_RA,
    CAN_TURMA,
    CAN_TRIMESTRE,
    CAN_DISCIPLINA,
)


def validar_colunas_obrigatorias_template(columns: list[str]) -> list[str]:
    """
    Verifica se as colunas obrigatórias do template fixo estão presentes.

    Retorna lista de chaves canônicas ausentes (vazia se tudo ok).

    Uso típico antes de processar qualquer linha:
        ausentes = validar_colunas_obrigatorias_template(list(df.columns))
        if ausentes:
            raise ValueError(f"Colunas obrigatórias ausentes no template: {ausentes}")
    """
    mapeadas = set(mapear_colunas_madan(columns).values())
    return [c for c in COLUNAS_OBRIGATORIAS_TEMPLATE if c not in mapeadas]


__all__ = [
    "normalizar_nome_coluna",
    "mapear_colunas_madan",
    "normalizar_linha_madan",
    "inferir_tem_nivelamento",
    "extrair_contexto_linha",
    "validar_colunas_obrigatorias_template",  # NOVO
    "COLUNAS_OBRIGATORIAS_TEMPLATE",          # NOVO
    "LinhaMadanCanonica",
    "linha_wide_para_canonica",
    # chaves canônicas
    "CAN_ESTUDANTE",
    "CAN_RA",           # NOVO
    "CAN_TRIMESTRE",
    "CAN_DISCIPLINA",
    "CAN_FRENTE_PROFESSOR",
    "CAN_TURMA",
    "CAN_AV1_OBJ",
    "CAN_AV1_DISC",
    "CAN_AV2_OBJ",
    "CAN_AV2_DISC",
    "CAN_AV3_LISTAS",
    "CAN_AV3_AVALIACAO",
    "CAN_SIMULADO",
    "CAN_PONTO_EXTRA",
    "CAN_NOTA_SEM_AV3",
    "CAN_NOTA_COM_AV3",
    "CAN_NOTA_FINAL",
    "CAN_RECUPERACAO",
    "CAN_OBS_PONTO_EXTRA",
]