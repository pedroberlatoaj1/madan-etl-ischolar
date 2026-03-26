"""
gerador_planilhas.py — Gera planilhas Excel pré-preenchidas, uma por turma.

Cada arquivo contém uma aba por combinação disciplina-frente-professor,
com colunas de identidade (Nome, RA, Turma) pré-preenchidas e protegidas,
e colunas de nota editáveis.

O output é consumido pelo compilador_turma.py, que converte o formato
multi-abas de volta para o formato pipeline (1 linha = 1 aluno × 1 disciplina).

Uso:
    python gerador_planilhas.py --trimestre T1 --ano 2026 --alunos roster.csv --output ./planilhas/
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter

from madan_planilha_mapper import SERIES_SUPORTADAS, extrair_serie_da_turma
from professores_madan import (
    PROFESSORES,
    SIGLA_PARA_DISCIPLINA,
    buscar_professor_para_turma,
)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

BULLET = "\u2022"  # "•" — indica "todas as turmas/frentes"

COLUNAS_IDENTIDADE = ["Nome", "RA", "Turma"]

COLUNAS_NOTA = [
    "AV 1 (OBJ)",
    "AV 1 (DISC)",
    "AV 2 (OBJ)",
    "AV 2 (DISC)",
    "AV 3 (listas)",
    "AV 3 (avaliação)",
    "Simulado",
    "Ponto Extra",
    "Obs Ponto Extra",
    "Recuperação",
]

COLUNAS_CONFERENCIA = [
    "Nota sem a AV 3",
    "Nota com a AV 3",
    "Nota Final",
]

TODAS_COLUNAS = COLUNAS_IDENTIDADE + COLUNAS_NOTA + COLUNAS_CONFERENCIA


# ---------------------------------------------------------------------------
# Dataclass para configuração de aba
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TabConfig:
    """Representa uma aba a ser criada na planilha de uma turma."""
    disciplina: str           # Nome canônico (ex: "matematica")
    frente: str               # Frente (ex: "F2") ou "" se professor cobre todas
    professor_display: str    # Nome de exibição do professor
    professor_nome: str       # Nome completo do professor

    @property
    def nome_aba(self) -> str:
        """Nome da aba no Excel (max 31 chars)."""
        if self.frente:
            raw = f"{self.disciplina}_{self.frente}_{self.professor_display}"
        else:
            raw = f"{self.disciplina}_{self.professor_display}"
        # Excel limita nomes de abas a 31 caracteres
        sanitized = _sanitizar_nome_aba(raw)
        return sanitized[:31]


def _sanitizar_nome_aba(nome: str) -> str:
    """Remove caracteres proibidos em nomes de aba do Excel."""
    # Remove acentos
    nfkd = unicodedata.normalize("NFD", nome)
    sem_acento = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    # Substitui caracteres proibidos no Excel: \ / * ? : [ ]
    return re.sub(r'[\\/*?\[\]:]', '_', sem_acento)


# ---------------------------------------------------------------------------
# Lógica de descoberta de abas por turma
# ---------------------------------------------------------------------------

def descobrir_tabs_para_turma(serie: int, turma_letra: str) -> list[TabConfig]:
    """
    Consulta o registro de professores para determinar quais combinações
    disciplina-frente-professor se aplicam a uma turma.

    Retorna lista de TabConfig deduplicada e ordenada.
    """
    disciplinas = sorted(set(SIGLA_PARA_DISCIPLINA.values()))
    tabs: set[tuple[str, str, str, str]] = set()

    for disc in disciplinas:
        profs = buscar_professor_para_turma(disc, serie, turma_letra)
        for p in profs:
            all_frentes = p.frentes_med + p.frentes_ext + p.frentes_ita
            if not all_frentes:
                continue

            # Verifica se tem bullet (= todas as frentes)
            has_bullet = BULLET in all_frentes

            if has_bullet:
                tabs.add((disc, "", p.nome_display, p.nome))
            else:
                # Expande frentes compostas como "F2/F4"
                expanded: set[str] = set()
                for f in all_frentes:
                    for sub in f.split("/"):
                        s = sub.strip()
                        if s and s != BULLET:
                            expanded.add(s)
                for fr in expanded:
                    tabs.add((disc, fr, p.nome_display, p.nome))

    return sorted(
        [TabConfig(d, f, pd, pn) for d, f, pd, pn in tabs],
        key=lambda t: (t.disciplina, t.frente, t.professor_display),
    )


# ---------------------------------------------------------------------------
# Leitura de roster de alunos
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Aluno:
    """Dados base de um aluno para pré-preenchimento."""
    nome: str
    ra: str
    turma: str


def carregar_roster_csv(caminho: str | Path) -> list[Aluno]:
    """
    Carrega roster de alunos de um CSV.

    Espera colunas: Nome (ou Estudante), RA, Turma (case-insensitive).
    """
    path = Path(caminho)
    alunos: list[Aluno] = []

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV vazio ou sem cabeçalho: {path}")

        # Mapeia cabeçalhos case-insensitive
        header_map: dict[str, str] = {}
        for field in reader.fieldnames:
            low = field.strip().lower()
            if low in ("nome", "estudante", "aluno", "nome_aluno"):
                header_map["nome"] = field
            elif low in ("ra", "registro_aluno", "numero_re"):
                header_map["ra"] = field
            elif low in ("turma", "sala", "classe"):
                header_map["turma"] = field

        for key in ("nome", "ra", "turma"):
            if key not in header_map:
                raise ValueError(
                    f"Coluna '{key}' não encontrada no CSV. "
                    f"Colunas disponíveis: {reader.fieldnames}"
                )

        for row in reader:
            nome = (row.get(header_map["nome"]) or "").strip()
            ra = (row.get(header_map["ra"]) or "").strip()
            turma = (row.get(header_map["turma"]) or "").strip()
            if nome and ra:
                alunos.append(Aluno(nome=nome, ra=ra, turma=turma))

    return alunos


def agrupar_alunos_por_turma(alunos: list[Aluno]) -> dict[str, list[Aluno]]:
    """Agrupa alunos por turma, retornando dict ordenado."""
    grupos: dict[str, list[Aluno]] = {}
    for a in alunos:
        grupos.setdefault(a.turma, []).append(a)
    # Ordena alunos por nome dentro de cada turma
    for turma in grupos:
        grupos[turma].sort(key=lambda x: x.nome)
    return dict(sorted(grupos.items()))


# ---------------------------------------------------------------------------
# Geração de planilha Excel
# ---------------------------------------------------------------------------

# Estilos
_FILL_HEADER = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
_FONT_HEADER = Font(bold=True, color="FFFFFF", size=11)
_FILL_IDENTIDADE = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
_FONT_IDENTIDADE = Font(size=11)
_PROTECTION_LOCKED = Protection(locked=True)
_PROTECTION_UNLOCKED = Protection(locked=False)
_ALIGNMENT_CENTER = Alignment(horizontal="center", vertical="center")


def _criar_aba_disciplina(
    wb: openpyxl.Workbook,
    tab: TabConfig,
    alunos: list[Aluno],
    turma: str,
) -> None:
    """Cria uma aba de disciplina com cabeçalhos e dados pré-preenchidos."""
    ws = wb.create_sheet(title=tab.nome_aba)

    # Proteção da sheet: cells locked by default, unlock specific ones
    ws.protection.sheet = True
    ws.protection.password = ""  # Proteção sem senha (apenas para evitar edição acidental)

    # Header row
    for col_idx, col_name in enumerate(TODAS_COLUNAS, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = _FONT_HEADER
        cell.fill = _FILL_HEADER
        cell.alignment = _ALIGNMENT_CENTER
        cell.protection = _PROTECTION_LOCKED

    # Larguras de coluna
    ws.column_dimensions["A"].width = 35  # Nome
    ws.column_dimensions["B"].width = 15  # RA
    ws.column_dimensions["C"].width = 10  # Turma
    for i in range(4, len(TODAS_COLUNAS) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 14

    # Dados dos alunos
    n_id_cols = len(COLUNAS_IDENTIDADE)
    n_nota_cols = len(COLUNAS_NOTA)

    for row_idx, aluno in enumerate(alunos, 2):
        # Colunas de identidade (protegidas)
        for col_idx, val in enumerate([aluno.nome, aluno.ra, turma], 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill = _FILL_IDENTIDADE
            cell.font = _FONT_IDENTIDADE
            cell.protection = _PROTECTION_LOCKED

        # Colunas de nota (editáveis)
        for col_idx in range(n_id_cols + 1, n_id_cols + n_nota_cols + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.protection = _PROTECTION_UNLOCKED

        # Colunas de conferência (fórmulas, protegidas)
        for col_idx in range(n_id_cols + n_nota_cols + 1, len(TODAS_COLUNAS) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.protection = _PROTECTION_LOCKED

    # Freeze first row + identity columns
    ws.freeze_panes = "D2"


def _criar_aba_metadata(
    wb: openpyxl.Workbook,
    turma: str,
    trimestre: str,
    ano: int,
    tabs: list[TabConfig],
) -> None:
    """Cria aba _metadata oculta com informações da planilha."""
    ws = wb.create_sheet(title="_metadata")

    # Metadados gerais
    ws.cell(row=1, column=1, value="chave")
    ws.cell(row=1, column=2, value="valor")

    serie = extrair_serie_da_turma(turma)
    metadata = [
        ("trimestre", trimestre),
        ("turma", turma),
        ("serie", str(serie) if serie else ""),
        ("ano", str(ano)),
        ("gerado_em", date.today().isoformat()),
        ("total_abas", str(len(tabs))),
    ]

    for i, (k, v) in enumerate(metadata, 2):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)

    # Mapa de abas
    ws.cell(row=10, column=1, value="nome_aba")
    ws.cell(row=10, column=2, value="disciplina")
    ws.cell(row=10, column=3, value="frente")
    ws.cell(row=10, column=4, value="professor")
    ws.cell(row=10, column=5, value="professor_nome_completo")

    for i, tab in enumerate(tabs, 11):
        ws.cell(row=i, column=1, value=tab.nome_aba)
        ws.cell(row=i, column=2, value=tab.disciplina)
        ws.cell(row=i, column=3, value=tab.frente)
        ws.cell(row=i, column=4, value=tab.professor_display)
        ws.cell(row=i, column=5, value=tab.professor_nome)

    # Ocultar aba
    ws.sheet_state = "hidden"


def gerar_planilha_turma(
    turma: str,
    trimestre: str,
    ano: int,
    alunos: list[Aluno],
    output_dir: str | Path,
) -> Path:
    """
    Gera um arquivo Excel para uma turma com abas por disciplina-frente-professor.

    Retorna o caminho do arquivo gerado.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    serie = extrair_serie_da_turma(turma)
    if serie is None:
        raise ValueError(f"Não foi possível extrair série da turma: {turma!r}")
    if serie not in SERIES_SUPORTADAS:
        raise ValueError(
            f"Série {serie} (turma {turma!r}) não é suportada. "
            f"Séries suportadas: {SERIES_SUPORTADAS}"
        )

    # Extrai letra da turma
    turma_str = str(turma).strip()
    turma_letra = ""
    for c in turma_str:
        if c.isalpha():
            turma_letra = c.upper()
            break

    if not turma_letra:
        raise ValueError(f"Não foi possível extrair letra da turma: {turma!r}")

    # Descobre abas necessárias
    tabs = descobrir_tabs_para_turma(serie, turma_letra)
    if not tabs:
        raise ValueError(
            f"Nenhuma combinação disciplina-professor encontrada para "
            f"turma {turma!r} (série {serie}, letra {turma_letra})"
        )

    # Cria workbook
    wb = openpyxl.Workbook()
    # Remove sheet default
    default_sheet = wb.active
    if default_sheet is not None:
        wb.remove(default_sheet)

    # Cria abas de disciplina
    for tab in tabs:
        _criar_aba_disciplina(wb, tab, alunos, turma)

    # Cria aba metadata
    _criar_aba_metadata(wb, turma, trimestre, ano, tabs)

    # Salva
    filename = f"{turma}_{trimestre}_{ano}.xlsx"
    filepath = output_path / filename
    wb.save(str(filepath))

    return filepath


def gerar_todas_planilhas(
    trimestre: str,
    ano: int,
    alunos: list[Aluno],
    output_dir: str | Path,
) -> list[Path]:
    """
    Gera planilhas para todas as turmas presentes no roster.

    Retorna lista de caminhos dos arquivos gerados.
    """
    grupos = agrupar_alunos_por_turma(alunos)
    arquivos: list[Path] = []

    for turma, alunos_turma in grupos.items():
        serie = extrair_serie_da_turma(turma)
        if serie is None or serie not in SERIES_SUPORTADAS:
            continue  # Pula turmas de séries não suportadas

        filepath = gerar_planilha_turma(
            turma=turma,
            trimestre=trimestre,
            ano=ano,
            alunos=alunos_turma,
            output_dir=output_dir,
        )
        arquivos.append(filepath)

    return arquivos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera planilhas Excel pré-preenchidas por turma."
    )
    parser.add_argument("--trimestre", required=True, help="Trimestre (T1, T2, T3)")
    parser.add_argument("--ano", type=int, required=True, help="Ano letivo (ex: 2026)")
    parser.add_argument("--alunos", required=True, help="Caminho do CSV com roster de alunos")
    parser.add_argument("--output", default="./planilhas", help="Diretório de saída")
    args = parser.parse_args()

    alunos = carregar_roster_csv(args.alunos)
    print(f"Roster carregado: {len(alunos)} alunos")

    arquivos = gerar_todas_planilhas(
        trimestre=args.trimestre.upper(),
        ano=args.ano,
        alunos=alunos,
        output_dir=args.output,
    )

    print(f"\n{len(arquivos)} planilha(s) gerada(s):")
    for arq in arquivos:
        print(f"  {arq}")


if __name__ == "__main__":
    main()
