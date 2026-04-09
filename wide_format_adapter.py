"""
wide_format_adapter.py — Adaptador de formato wide novo → formato semi-wide antigo.

O formato wide novo tem 1 linha por aluno com colunas dinâmicas que codificam
disciplina, frente e tipo de avaliação no próprio nome da coluna:

    Estudante | RA | Turma | Trimestre | Matemática - Frente A - AV 1 Obj | ...

Este módulo desdobra (unpivot) cada linha em N linhas virtuais no formato
semi-wide antigo (1 linha por aluno × disciplina × frente), permitindo que
o pipeline existente (transformador.py, validacao_pre_envio.py) funcione
sem alterações.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import pandas as pd

from madan_planilha_mapper import (
    normalizar_nome_coluna,
    mapear_colunas_madan,
    CAN_ESTUDANTE,
    CAN_RA,
    CAN_TRIMESTRE,
    CAN_TURMA,
)
from professores_madan import buscar_professor_para_turma, ProfessorMadan


# ---------------------------------------------------------------------------
# Constantes — colunas fixas do formato wide novo
# ---------------------------------------------------------------------------

COLUNAS_FIXAS_WIDE_NOVO = (CAN_ESTUDANTE, CAN_RA, CAN_TURMA, CAN_TRIMESTRE)
"""Colunas obrigatórias presentes no formato wide novo (contexto do aluno)."""


# ---------------------------------------------------------------------------
# Parser de colunas dinâmicas
# ---------------------------------------------------------------------------

REGEX_COLUNA_DINAMICA = re.compile(
    r"^(.+?)\s*-\s*(Frente\s+\S+)\s*-\s*(.+)$",
    re.IGNORECASE,
)
"""
Captura 3 grupos no nome da coluna dinâmica:
  grupo 1: disciplina  (ex: "Matemática", "Interpretação de Texto")
  grupo 2: frente      (ex: "Frente A", "Frente Única")
  grupo 3: tipo avaliação (ex: "AV 1 Obj", "Simulado")
"""


@dataclass(frozen=True)
class ColunaDinamica:
    """Resultado do parsing de uma coluna dinâmica."""
    coluna_original: str
    disciplina: str
    frente: str
    tipo_avaliacao: str


def parsear_coluna_dinamica(nome_coluna: str) -> ColunaDinamica | None:
    """
    Tenta parsear uma coluna como dinâmica no formato:
        "{Disciplina} - {Frente X} - {Tipo Avaliação}"

    Retorna ColunaDinamica ou None se não bater no padrão.
    """
    nome = str(nome_coluna).strip()
    m = REGEX_COLUNA_DINAMICA.match(nome)
    if not m:
        return None
    return ColunaDinamica(
        coluna_original=nome_coluna,
        disciplina=m.group(1).strip(),
        frente=m.group(2).strip(),
        tipo_avaliacao=m.group(3).strip(),
    )


# ---------------------------------------------------------------------------
# Mapeamento tipo_avaliacao → coluna canônica do template antigo
# ---------------------------------------------------------------------------

def _normalizar_texto(s: str) -> str:
    """Remove acentos e converte para minúsculas para comparação."""
    n = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in n if unicodedata.category(c) != "Mn")


MAPA_TIPO_AVALIACAO: dict[str, str] = {
    "av 1 obj":       "AV 1 (OBJ)",
    "av 1 disc":      "AV 1 (DISC)",
    "av 2 obj":       "AV 2 (OBJ)",
    "av 2 disc":      "AV 2 (DISC)",
    "av 3 listas":    "AV 3 (listas)",
    "av 3 avaliacao": "AV 3 (avaliação)",
    "simulado":       "Simulado",
    "ponto extra":    "Ponto extra",
    "recuperacao":    "Recuperação",
}
"""Mapa de tipo_avaliacao (normalizado, sem acento) → nome de coluna no template antigo."""


def mapear_tipo_avaliacao(tipo: str) -> str | None:
    """
    Converte o tipo de avaliação extraído da coluna dinâmica para o nome de
    coluna do template antigo.

    Retorna None se o tipo não for reconhecido.
    """
    chave = _normalizar_texto(tipo.strip())
    # Tenta match direto
    resultado = MAPA_TIPO_AVALIACAO.get(chave)
    if resultado:
        return resultado
    # Tenta com underscores trocados por espaços
    chave_alt = chave.replace("_", " ")
    return MAPA_TIPO_AVALIACAO.get(chave_alt)


# ---------------------------------------------------------------------------
# Construtor de frente_professor sintético
# ---------------------------------------------------------------------------

def construir_frente_professor(disciplina: str, frente: str) -> str:
    """
    Constrói a chave sintética de frente_professor compatível com
    mapa_professores.json.

    Exemplos:
        ("Matemática", "Frente A")     → "matematica a"
        ("Gramática",  "Frente Única") → "gramatica"
        ("Física",     "Frente B")     → "fisica b"
    """
    disc_norm = _normalizar_texto(disciplina.strip())
    frente_norm = _normalizar_texto(frente.strip())

    # Extrai a letra/identificador da frente
    # "frente a" → "a", "frente unica" → "unica", "frente b" → "b"
    partes = frente_norm.split()
    if len(partes) >= 2:
        identificador = partes[-1]  # "a", "b", "c", "unica"
    else:
        identificador = "unica"

    if identificador == "unica":
        return disc_norm
    return f"{disc_norm} {identificador}"


# ---------------------------------------------------------------------------
# Desambiguação de professor por turma (2º ano e qualquer série)
# ---------------------------------------------------------------------------

def _apelido_slug(prof: ProfessorMadan) -> str:
    """
    Retorna a chave de apelido do professor normalizada (sem acentos, minúsculas).

    Usa o ``apelido`` oficial se definido; caso contrário, usa o primeiro nome.

    Exemplos:
        Perrone (apelido="Perrone")  → "perrone"
        Luan    (apelido=None)       → "luan"
        Carioca (apelido="Carioca") → "carioca"
    """
    s = prof.apelido if prof.apelido else prof.nome.split()[0]
    return _normalizar_texto(s)


def _extrair_serie_letra(turma: Any) -> tuple[int, str] | None:
    """
    Extrai (série, letra) de uma string de turma.

    Exemplos:
        "2A"  → (2, "A")
        "1B"  → (1, "B")
        "10A" → None  (série > 9 não reconhecida)
        ""    → None
        None  → None
    """
    if turma is None:
        return None
    m = re.match(r"^([1-9])([A-Za-z])$", str(turma).strip())
    if not m:
        return None
    return int(m.group(1)), m.group(2).upper()


def _qualificar_chave_com_professor(
    base_key: str,
    disciplina: str,
    serie: int,
    letra: str,
) -> str:
    """
    Tenta qualificar ``base_key`` com o professor responsável pela
    disciplina na série/turma informada.

    Regra:
    - Se ``buscar_professor_para_turma`` retorna exatamente 1 professor →
      retorna ``"{base_key} - {apelido_slug}"``.
    - Se retorna 0 ou mais de 1 (ambíguo / não mapeado) → retorna ``base_key``
      sem alteração (fail-safe conservador).

    Exemplos:
        ("matematica a", "Matemática", 2, "A") → "matematica a - daniel"
        ("matematica a", "Matemática", 1, "A") → "matematica a - luan"
        ("biologia",     "Biologia",   2, "A") → "biologia - perrone"
        ("geografia a",  "Geografia",  2, "A") → "geografia a - carla"
        ("fisica a",     "Física",     1, "A") → "fisica a - cavaco"
    """
    profs = buscar_professor_para_turma(disciplina, serie, letra)
    if len(profs) != 1:
        return base_key
    return f"{base_key} - {_apelido_slug(profs[0])}"


def _get_turma_do_row(row: dict[str, Any]) -> Any:
    """Extrai o valor da coluna Turma do row dict (case-insensitive)."""
    for k, v in row.items():
        if str(k).strip().lower() == "turma":
            return v
    return None


# ---------------------------------------------------------------------------
# Detecção de formato
# ---------------------------------------------------------------------------

FORMATO_WIDE_NOVO = "wide_novo"
FORMATO_SEMI_WIDE_ANTIGO = "semi_wide_antigo"


def detectar_formato(colunas: list[str]) -> str:
    """
    Detecta o formato da planilha analisando os nomes das colunas.

    Retorna:
        "semi_wide_antigo" — formato original com colunas Disciplina e Frente - Professor
        "wide_novo"        — formato novo com colunas dinâmicas
    """
    mapeadas = mapear_colunas_madan(colunas)
    canonicas_presentes = set(mapeadas.values())

    tem_disciplina = "disciplina" in canonicas_presentes
    tem_frente_professor = "frente_professor" in canonicas_presentes

    # Formato antigo: tem as colunas fixas de disciplina e frente
    if tem_disciplina and tem_frente_professor:
        return FORMATO_SEMI_WIDE_ANTIGO

    # Verifica se há colunas dinâmicas no padrão novo
    n_dinamicas = sum(1 for c in colunas if parsear_coluna_dinamica(c) is not None)

    if n_dinamicas > 0:
        return FORMATO_WIDE_NOVO

    # Fallback: assume formato antigo (a validação de template vai pegar os erros)
    return FORMATO_SEMI_WIDE_ANTIGO


# ---------------------------------------------------------------------------
# Validação de template para formato wide novo
# ---------------------------------------------------------------------------

def validar_colunas_wide_novo(colunas: list[str]) -> list[str]:
    """
    Valida as colunas do formato wide novo.

    Retorna lista de problemas encontrados (vazia se tudo ok).
    """
    problemas: list[str] = []

    mapeadas = mapear_colunas_madan(colunas)
    canonicas_presentes = set(mapeadas.values())

    # Verifica colunas fixas obrigatórias
    for obrig in COLUNAS_FIXAS_WIDE_NOVO:
        if obrig not in canonicas_presentes:
            problemas.append(f"Coluna obrigatória ausente: {obrig}")

    # Verifica se tem pelo menos uma coluna dinâmica válida
    dinamicas = [c for c in colunas if parsear_coluna_dinamica(c) is not None]
    if not dinamicas:
        problemas.append(
            "Nenhuma coluna dinâmica encontrada no padrão "
            "'Disciplina - Frente X - Tipo Avaliação'"
        )

    # Verifica se os tipos de avaliação são reconhecidos
    tipos_nao_reconhecidos = []
    for col in dinamicas:
        parsed = parsear_coluna_dinamica(col)
        if parsed and mapear_tipo_avaliacao(parsed.tipo_avaliacao) is None:
            tipos_nao_reconhecidos.append(
                f"Tipo de avaliação não reconhecido em '{col}': '{parsed.tipo_avaliacao}'"
            )
    problemas.extend(tipos_nao_reconhecidos)

    return problemas


# ---------------------------------------------------------------------------
# Despivotamento (unpivot) — wide novo → semi-wide antigo
# ---------------------------------------------------------------------------

def _classificar_colunas(
    colunas: list[str],
) -> tuple[list[str], dict[tuple[str, str], list[ColunaDinamica]]]:
    """
    Separa colunas fixas de dinâmicas e agrupa dinâmicas por (disciplina, frente).

    Retorna:
        (lista_colunas_fixas, dict[(disciplina, frente) → lista de ColunaDinamica])
    """
    fixas: list[str] = []
    grupos: dict[tuple[str, str], list[ColunaDinamica]] = {}

    for col in colunas:
        parsed = parsear_coluna_dinamica(col)
        if parsed is None:
            fixas.append(col)
        else:
            chave = (parsed.disciplina, parsed.frente)
            grupos.setdefault(chave, []).append(parsed)

    return fixas, grupos


def despivotar_linha_wide(
    row: dict[str, Any],
    colunas_fixas: list[str],
    grupos_dinamicos: dict[tuple[str, str], list[ColunaDinamica]],
) -> list[dict[str, Any]]:
    """
    Converte 1 linha no formato wide novo em N linhas virtuais no formato
    semi-wide antigo.

    Cada grupo (disciplina, frente) gera uma linha virtual com:
    - Colunas fixas copiadas (Estudante, RA, Turma, Trimestre)
    - "Disciplina" = disciplina extraída
    - "Frente - Professor" = chave sintética para mapa_professores.json
    - Colunas de avaliação mapeadas para nomes do template antigo
    """
    # Valores fixos (copiar para cada linha virtual)
    valores_fixos = {col: row.get(col) for col in colunas_fixas}

    # Contexto de turma para desambiguação de professor
    turma_raw = _get_turma_do_row(row)
    serie_letra = _extrair_serie_letra(turma_raw)

    linhas_virtuais: list[dict[str, Any]] = []

    for (disciplina, frente), cols_dinamicas in grupos_dinamicos.items():
        linha = dict(valores_fixos)
        linha["Disciplina"] = disciplina

        base_key = construir_frente_professor(disciplina, frente)
        if serie_letra is not None:
            serie, letra = serie_letra
            chave_professor = _qualificar_chave_com_professor(
                base_key, disciplina, serie, letra
            )
        else:
            chave_professor = base_key
        linha["Frente - Professor"] = chave_professor

        for col_din in cols_dinamicas:
            nome_antigo = mapear_tipo_avaliacao(col_din.tipo_avaliacao)
            if nome_antigo:
                linha[nome_antigo] = row.get(col_din.coluna_original)

        linhas_virtuais.append(linha)

    return linhas_virtuais


def despivotar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converte um DataFrame no formato wide novo em um DataFrame no formato
    semi-wide antigo (1 linha por aluno × disciplina × frente).

    Todas as colunas dinâmicas são parseadas uma vez e agrupadas por
    (disciplina, frente). Para cada linha, cada grupo gera uma linha virtual.
    """
    colunas_fixas, grupos_dinamicos = _classificar_colunas(list(df.columns))

    if not grupos_dinamicos:
        raise ValueError(
            "Nenhuma coluna dinâmica encontrada no padrão "
            "'Disciplina - Frente X - Tipo Avaliação'. "
            "Verifique o formato da planilha."
        )

    todas_linhas: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        linhas_virtuais = despivotar_linha_wide(
            row_dict, colunas_fixas, grupos_dinamicos,
        )
        todas_linhas.extend(linhas_virtuais)

    return pd.DataFrame(todas_linhas)


__all__ = [
    "parsear_coluna_dinamica",
    "ColunaDinamica",
    "mapear_tipo_avaliacao",
    "construir_frente_professor",
    "detectar_formato",
    "validar_colunas_wide_novo",
    "despivotar_linha_wide",
    "despivotar_dataframe",
    "FORMATO_WIDE_NOVO",
    "FORMATO_SEMI_WIDE_ANTIGO",
    "COLUNAS_FIXAS_WIDE_NOVO",
    "MAPA_TIPO_AVALIACAO",
    # desambiguação por turma
    "_apelido_slug",
    "_extrair_serie_letra",
    "_qualificar_chave_com_professor",
]
