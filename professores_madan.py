"""
professores_madan.py — Registro oficial de professores do Madan (2026)

Fonte: "Lista de Professores por frente.pdf" (documento interno Madan, 2026).

Responsabilidades:
- Codificar o registro completo de professores, matérias, turmas e frentes
- Mapear siglas de matérias (HIS, MAT, FÍS…) para nomes canônicos
- Fornecer lookup por apelido, nome, matéria, turma ou frente
- Validar se um professor está designado para uma combinação matéria/turma
- Gerar chaves para mapa_professores.json

IMPORTANTE: os IDs do iScholar NÃO estão neste módulo. Eles ficam em
mapa_professores.json e são preenchidos via descobrir_ids_ischolar.py.
Este módulo apenas organiza os dados oficiais do PDF.
"""

from __future__ import annotations

import unicodedata
import re
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Siglas de matéria → nome canônico (compatível com mapa_disciplinas.json)
# ---------------------------------------------------------------------------

SIGLA_PARA_DISCIPLINA: dict[str, str] = {
    "HIS":         "historia",
    "MAT":         "matematica",
    "FÍS":         "fisica",
    "FIS":         "fisica",
    "GEO":         "geografia",
    "BIO":         "biologia",
    "QUÍ":         "quimica",
    "QUI":         "quimica",
    "RED":         "redacao",
    "ING":         "ingles",
    "SOC":         "sociologia",
    "FIL":         "filosofia",
    "SOC/FIL/HIS": "sociologia",  # Bravin leciona as 3; principal = sociologia
    "LIT":         "literatura",
    "ED FÍS":      "educacao fisica",
    "ED FIS":      "educacao fisica",
    "ART":         "arte",
    "GRA":         "gramatica",
    "XAD":         "xadrez",
}


def normalizar_sigla(sigla: str) -> str:
    """Normaliza sigla de matéria para lookup no dicionário."""
    s = str(sigla).strip().upper()
    # Remove acentos
    s = "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )
    return s


def sigla_para_disciplina(sigla: str) -> str | None:
    """Converte sigla do PDF para nome canônico de disciplina."""
    norm = normalizar_sigla(sigla)
    return SIGLA_PARA_DISCIPLINA.get(norm)


# ---------------------------------------------------------------------------
# Registro de professores — fonte: PDF "Lista de Professores - 2026"
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfessorMadan:
    """Registro de um professor do Madan extraído do PDF oficial."""
    nome: str
    apelido: str | None
    materia_sigla: str          # Sigla como aparece no PDF (HIS, MAT, FÍS…)
    turmas_1a: list[str]        # Turmas da 1ª série: ["A", "B"] ou ["•"] (todas)
    turmas_2a: list[str]        # Turmas da 2ª série
    turmas_3a: list[str]        # Turmas da 3ª série (bloqueada no pipeline)
    frentes_med: list[str]      # Frentes MED: ["F1", "F2"] ou ["•"]
    frentes_ext: list[str]      # Frentes EXT
    frentes_ita: list[str]      # Frentes ITA
    email: str | None = None

    @property
    def disciplina_canonica(self) -> str | None:
        """Retorna nome canônico da disciplina (compatível com mapa_disciplinas)."""
        return sigla_para_disciplina(self.materia_sigla)

    @property
    def nome_display(self) -> str:
        """Nome de exibição: apelido se existir, senão primeiro+último nome."""
        if self.apelido:
            return self.apelido
        partes = self.nome.split()
        if len(partes) >= 2:
            return f"{partes[0]} {partes[-1]}"
        return self.nome

    def leciona_em_turma(self, serie: int, turma_letra: str) -> bool:
        """Verifica se o professor leciona na turma dada (ex: serie=1, turma_letra='A')."""
        if serie == 1:
            turmas = self.turmas_1a
        elif serie == 2:
            turmas = self.turmas_2a
        elif serie == 3:
            turmas = self.turmas_3a
        else:
            return False

        if not turmas:
            return False
        if "•" in turmas:  # bullet = todas as turmas
            return True
        return turma_letra.upper() in [t.upper() for t in turmas]

    def leciona_em_frente(self, frente: str) -> bool:
        """Verifica se o professor leciona na frente dada (ex: 'F1', 'F2')."""
        frente_upper = frente.upper().strip()
        todas_frentes = self.frentes_med + self.frentes_ext + self.frentes_ita
        if not todas_frentes:
            return False
        if "•" in todas_frentes:
            return True
        # Lida com frentes compostas como "F2/F4"
        for f in todas_frentes:
            for sub in f.split("/"):
                if sub.strip().upper() == frente_upper:
                    return True
        return False


def _parse_turmas(valor: str) -> list[str]:
    """Parse colunas de turma do PDF: 'A', 'B', '•', '', 'C'."""
    v = str(valor).strip()
    if not v:
        return []
    return [v]


def _parse_frentes(valor: str) -> list[str]:
    """Parse colunas de frente do PDF: 'F1', 'F2/F4', '•', ''."""
    v = str(valor).strip()
    if not v:
        return []
    return [v]


# ---------------------------------------------------------------------------
# Base de dados completa — transcrita do PDF "Lista de Professores - 2026"
# ---------------------------------------------------------------------------

PROFESSORES: list[ProfessorMadan] = [
    ProfessorMadan(
        nome="ADRIANO BELO BARBOSA", apelido="Buyú", materia_sigla="HIS",
        turmas_1a=["A"], turmas_2a=["A"], turmas_3a=["F2"], frentes_med=["F2"],
        frentes_ext=[], frentes_ita=[],
        email="adrianobelo@gmail.com",
    ),
    ProfessorMadan(
        nome="ALBA VALÉRIA SANTOS DA SILVA", apelido="Alba", materia_sigla="HIS",
        turmas_1a=["B"], turmas_2a=["B"], turmas_3a=["F1"], frentes_med=["F1"],
        frentes_ext=["F1"], frentes_ita=[],
        email="albaelisachico@gmail.com",
    ),
    ProfessorMadan(
        nome="BEATRIZ PEREIRA MARCHI", apelido="Bia", materia_sigla="RED",
        turmas_1a=["•"], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=[],
        email="biamarchi1@gmail.com",
    ),
    ProfessorMadan(
        nome="CARLA CHRISTINA MARQUES FUENTES", apelido=None, materia_sigla="GEO",
        turmas_1a=["B"], turmas_2a=["A"], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=[],
        email="carlageo.fuentes@gmail.com",
    ),
    ProfessorMadan(
        nome="CARLOS DE' CARLI FILHO", apelido=None, materia_sigla="XAD",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=[],
        email="carlosdecarlifilho07@gmail.com",
    ),
    ProfessorMadan(
        nome="CRISTINA DE ARRUDA BRAVIM", apelido=None, materia_sigla="ING",
        turmas_1a=["•"], turmas_2a=["•"], turmas_3a=["•"], frentes_med=["•"],
        frentes_ext=["•"], frentes_ita=["•"],
        email="cristina.arruda.bravim@gmail.com",
    ),
    ProfessorMadan(
        nome="DANIEL ROJAS NASCIMENTO", apelido=None, materia_sigla="MAT",
        turmas_1a=["C"], turmas_2a=["A"], turmas_3a=["F3"], frentes_med=["F3"],
        frentes_ext=[], frentes_ita=["F2/F4"],
        email="daniel@madan.com.br",
    ),
    ProfessorMadan(
        nome="DIEGO DE OLIVEIRA PEZZIN", apelido="Pezzin", materia_sigla="FÍS",
        turmas_1a=["B"], turmas_2a=["B"], turmas_3a=["F1"], frentes_med=["F1"],
        frentes_ext=["F1/F2"], frentes_ita=[],
        email="diego.pezzin@hotmail.com",
    ),
    ProfessorMadan(
        nome="DIOGO BORGES VAREJÃO", apelido="Varejão", materia_sigla="GEO",
        turmas_1a=[], turmas_2a=[], turmas_3a=["F1"], frentes_med=["F1"],
        frentes_ext=[], frentes_ita=[],
        email="dbvarejao@gmail.com",
    ),
    ProfessorMadan(
        nome="EDSON CAMPOS PERRONE", apelido="Perrone", materia_sigla="BIO",
        turmas_1a=[], turmas_2a=["A"], turmas_3a=["F3"], frentes_med=[],
        frentes_ext=[], frentes_ita=[],
        email="ecperrone@gmail.com",
    ),
    ProfessorMadan(
        nome="EDUARDO DA SILVA BASSOLI", apelido="Bassoli", materia_sigla="FÍS",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=["F4"],
        email="eduardo.bassoli@gmail.com",
    ),
    ProfessorMadan(
        nome="EMANUELLY DUARTE VALENTE", apelido=None, materia_sigla="RED",
        turmas_1a=[], turmas_2a=[], turmas_3a=["•"], frentes_med=["•"],
        frentes_ext=["•"], frentes_ita=["•"],
        email=None,
    ),
    ProfessorMadan(
        nome="EZIMAR BRAVIN", apelido="Bravin", materia_sigla="SOC/FIL/HIS",
        turmas_1a=["•"], turmas_2a=["•"], turmas_3a=["•"], frentes_med=["•"],
        frentes_ext=["H/F2"], frentes_ita=[],
        email="professorbravin@gmail.com",
    ),
    ProfessorMadan(
        nome="FELIPE DE CASTRO SILVEIRA BARBOSA", apelido="Carioca", materia_sigla="MAT",
        turmas_1a=["B"], turmas_2a=["C"], turmas_3a=["F1"], frentes_med=["F1"],
        frentes_ext=["F1"], frentes_ita=["F1/F3"],
        email="proveqmatematica@gmail.com",
    ),
    ProfessorMadan(
        nome="FILIPE PINEL BERBERT BERMUDES", apelido=None, materia_sigla="MAT",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=["F3"], frentes_ita=[],
        email="filipe.pinel@gmail.com",
    ),
    ProfessorMadan(
        nome="GESIANE CABRAL DE FREITAS", apelido=None, materia_sigla="QUÍ",
        turmas_1a=[], turmas_2a=[], turmas_3a=["F3"], frentes_med=["F3"],
        frentes_ext=["F2"], frentes_ita=["F3"],
        email="gesicf@gmail.com",
    ),
    ProfessorMadan(
        nome="GUILHERME AUGUSTO SANTOS PEIXOTO", apelido=None, materia_sigla="BIO",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=[],
        email="guilherme.augusto@madan.com.br",
    ),
    ProfessorMadan(
        nome="GUILHERME FIGUEIREDO", apelido="Bromo", materia_sigla="FÍS",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=["F3"],
        email="guilherme.fig87@gmail.com",
    ),
    ProfessorMadan(
        nome="MARCUS VINÍCIUS LISBOA MOTTA", apelido="Vinícius", materia_sigla="QUÍ",
        turmas_1a=["B"], turmas_2a=["B"], turmas_3a=["F2"], frentes_med=["F2"],
        frentes_ext=["F1"], frentes_ita=[],
        email="marcus@ucl.br",
    ),
    ProfessorMadan(
        nome="IANA LIMA CORDEIRO", apelido=None, materia_sigla="LIT",
        turmas_1a=["•"], turmas_2a=["•"], turmas_3a=[], frentes_med=[],
        frentes_ext=["•"], frentes_ita=[],
        email="iana-cordeiro@hotmail.com",
    ),
    ProfessorMadan(
        nome="JAMINE DILLEM REZENDE", apelido=None, materia_sigla="BIO",
        turmas_1a=["A"], turmas_2a=[], turmas_3a=["F1"], frentes_med=["F1"],
        frentes_ext=["F1"], frentes_ita=[],
        email="jadillem@hotmail.com",
    ),
    ProfessorMadan(
        nome="JANAINA DEZAN GARCIA", apelido=None, materia_sigla="LIT",
        turmas_1a=[], turmas_2a=[], turmas_3a=["•"], frentes_med=["•"],
        frentes_ext=[], frentes_ita=[],
        email="janaina_literatura@hotmail.com",
    ),
    ProfessorMadan(
        nome="JOAO PAULO FERNANDES PINTO", apelido=None, materia_sigla="ED FÍS",
        turmas_1a=["•"], turmas_2a=["•"], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=[],
        email="prof.jpedfisica@gmail.com",
    ),
    ProfessorMadan(
        nome="JULIANO TOREZANI TONON", apelido=None, materia_sigla="GEO",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=["F2"], frentes_ita=[],
        email="julianottonon@gmail.com",
    ),
    ProfessorMadan(
        nome="LENICE DE OLIVEIRA COELHO SILVA", apelido=None, materia_sigla="ART",
        turmas_1a=["•"], turmas_2a=["•"], turmas_3a=["•"], frentes_med=["•"],
        frentes_ext=[], frentes_ita=[],
        email="lenicecoelho1987@gmail.com",
    ),
    ProfessorMadan(
        nome="LEONARDO MONTE PIMENTEL", apelido="LEO", materia_sigla="QUÍ",
        turmas_1a=["A"], turmas_2a=["A"], turmas_3a=["F1"], frentes_med=["F1"],
        frentes_ext=["F1"], frentes_ita=[],
        email="profleonardopimentel@gmail.com",
    ),
    ProfessorMadan(
        nome="LUAN MENDES SCHUNCK", apelido=None, materia_sigla="MAT",
        turmas_1a=["A"], turmas_2a=["B"], turmas_3a=["F2"], frentes_med=["F2"],
        frentes_ext=["F2"], frentes_ita=[],
        email="schunckluan@gmail.com",
    ),
    ProfessorMadan(
        nome="LUCAS PAVAN BARROS", apelido="Frika", materia_sigla="MAT",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=["F4/F5"],
        email="lucasbarroses@gmail.com",
    ),
    ProfessorMadan(
        nome="MARCELO ALMEIDA MORETO", apelido="Moreto", materia_sigla="GEO",
        turmas_1a=["A"], turmas_2a=["B"], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=[],
        email="moretogeo@gmail.com",
    ),
    ProfessorMadan(
        nome="MARINA LIMA MONTEIRO", apelido=None, materia_sigla="LIT",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=["•"],
        email="marina@madan.com.br",
    ),
    ProfessorMadan(
        nome="MAYARA DOS SANTOS GUARIEIRO", apelido=None, materia_sigla="BIO",
        turmas_1a=["B"], turmas_2a=["B"], turmas_3a=["F2"], frentes_med=["F2"],
        frentes_ext=["F2"], frentes_ita=[],
        email="profmguarieiro@gmail.com",
    ),
    ProfessorMadan(
        nome="NERYANNE REIS ZANOTELLI", apelido="Nery", materia_sigla="GRA",
        turmas_1a=["•"], turmas_2a=["•"], turmas_3a=["•"], frentes_med=["•"],
        frentes_ext=["•"], frentes_ita=["•"],
        email="neryane@yahoo.com.br",
    ),
    ProfessorMadan(
        nome="PAULA FAVARATO NUNES", apelido=None, materia_sigla="GEO",
        turmas_1a=[], turmas_2a=[], turmas_3a=["F2"], frentes_med=["F2"],
        frentes_ext=["F1"], frentes_ita=[],
        email="paulafavaratovix@gmail.com",
    ),
    ProfessorMadan(
        nome="SÉRGIO GOMES DA SILVA JUNIOR", apelido=None, materia_sigla="RED",
        turmas_1a=[], turmas_2a=["•"], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=[],
        email=None,
    ),
    ProfessorMadan(
        nome="THIAGO CARDOSO DA COSTA", apelido="Tchê", materia_sigla="QUÍ",
        turmas_1a=[], turmas_2a=[], turmas_3a=[], frentes_med=[],
        frentes_ext=[], frentes_ita=["F2/F4/F5"],
        email="profthiagoccosta@gmail.com",
    ),
    ProfessorMadan(
        nome="THIAGO HENRIQUE VIEIRA SILVA", apelido="Cavaco", materia_sigla="FÍS",
        turmas_1a=["A"], turmas_2a=["A"], turmas_3a=["F3"], frentes_med=["F3"],
        frentes_ext=["F2"], frentes_ita=["F5"],
        email="thiagohvieira@gmail.com",
    ),
]


# ---------------------------------------------------------------------------
# Índices de busca (construídos automaticamente)
# ---------------------------------------------------------------------------

def _normalizar_para_busca(s: str) -> str:
    """Normaliza string para busca: sem acentos, minúsculas, espaços colapsados."""
    n = str(s).strip().lower()
    n = "".join(
        c for c in unicodedata.normalize("NFD", n) if unicodedata.category(c) != "Mn"
    )
    n = re.sub(r"\s+", " ", n).strip()
    return n


# Índice por apelido normalizado
_INDICE_APELIDO: dict[str, ProfessorMadan] = {}
# Índice por nome normalizado
_INDICE_NOME: dict[str, ProfessorMadan] = {}
# Índice por primeiro nome normalizado quando único no registro
_INDICE_PRIMEIRO_NOME_UNICO: dict[str, ProfessorMadan] = {}
# Índice por disciplina canônica → lista de professores
_INDICE_DISCIPLINA: dict[str, list[ProfessorMadan]] = {}


def _construir_indices() -> None:
    """Constrói os índices de busca na primeira importação."""
    primeiros_nomes: dict[str, list[ProfessorMadan]] = {}

    for prof in PROFESSORES:
        if prof.apelido:
            _INDICE_APELIDO[_normalizar_para_busca(prof.apelido)] = prof
        _INDICE_NOME[_normalizar_para_busca(prof.nome)] = prof
        primeiro_nome = _normalizar_para_busca(prof.nome.split()[0]) if prof.nome.split() else ""
        if primeiro_nome:
            primeiros_nomes.setdefault(primeiro_nome, []).append(prof)

        disciplinas_indexadas: set[str] = set()

        disc = prof.disciplina_canonica
        if disc:
            disciplinas_indexadas.add(disc)

        # Expande siglas compostas, como SOC/FIL/HIS, para que a mesma
        # designação oficial alimente os lookups de Sociologia, Filosofia
        # e História sem exigir duplicação manual no cadastro base.
        if "/" in prof.materia_sigla:
            for sigla in prof.materia_sigla.split("/"):
                d = sigla_para_disciplina(sigla.strip())
                if d:
                    disciplinas_indexadas.add(d)

        for disciplina in disciplinas_indexadas:
            _INDICE_DISCIPLINA.setdefault(disciplina, []).append(prof)

    for primeiro_nome, professores in primeiros_nomes.items():
        if len(professores) == 1:
            _INDICE_PRIMEIRO_NOME_UNICO[primeiro_nome] = professores[0]


_construir_indices()


# ---------------------------------------------------------------------------
# Funções de busca
# ---------------------------------------------------------------------------

def parece_chave_disciplina_frente(frente_professor: str) -> bool:
    """
    Retorna True se o valor parece ser uma chave de disciplina/frente gerada
    automaticamente pelo pipeline (ex.: "arte", "fisica a", "biologia"), e não
    um nome ou apelido de professor.

    Essas chaves são produzidas por wide_format_adapter.construir_frente_professor()
    para colunas sem sufixo de professor explícito (tipicamente Frente Única e
    frentes múltiplas sem nome no cabeçalho).

    Critério conservador — retorna True apenas quando:
      1. Não contém " - " (sem separador de nome de professor explícito); E
      2. A string normalizada bate exatamente com uma disciplina canônica conhecida,
         OU começa com uma disciplina canônica seguida de espaço + identificador de
         frente curto (1–5 letras, sem dígitos — ex.: "a", "b", "unica").

    Exemplos que retornam True  : "arte", "biologia", "fisica a", "fisica b",
                                  "matematica c", "ingles", "gramatica"
    Exemplos que retornam False : "arte - lenice", "fisica - cavaco",
                                  "cavaco", "perrone", "xyz"
    """
    s = str(frente_professor).strip()
    # Presença de " - " indica nome de professor explícito → não é chave pura
    if " - " in s:
        return False

    norm = _normalizar_para_busca(s)

    # Correspondência exata com disciplina canônica conhecida
    if norm in _INDICE_DISCIPLINA:
        return True

    # Disciplina canônica + espaço + identificador de frente (ex.: "fisica a")
    for disc in _INDICE_DISCIPLINA:
        if norm.startswith(disc + " "):
            resto = norm[len(disc) + 1:].strip()
            # Identificador de frente: 1–5 caracteres, somente letras
            if 1 <= len(resto) <= 5 and resto.isalpha():
                return True

    return False


def buscar_por_apelido(apelido: str) -> ProfessorMadan | None:
    """Busca professor por apelido (case-insensitive, sem acentos)."""
    return _INDICE_APELIDO.get(_normalizar_para_busca(apelido))


def buscar_por_nome(nome: str) -> ProfessorMadan | None:
    """Busca professor por nome completo (case-insensitive, sem acentos)."""
    return _INDICE_NOME.get(_normalizar_para_busca(nome))


def buscar_por_primeiro_nome_unico(nome: str) -> ProfessorMadan | None:
    """
    Busca por primeiro nome apenas quando ele é único no registro.

    Mantém o lookup conservador: nomes ambíguos como "guilherme" ou "thiago"
    não resolvem para nenhum professor.
    """
    return _INDICE_PRIMEIRO_NOME_UNICO.get(_normalizar_para_busca(nome))


def buscar_por_nome_ou_apelido(valor: str) -> ProfessorMadan | None:
    """Busca professor por apelido primeiro, depois por nome."""
    resultado = buscar_por_apelido(valor)
    if resultado:
        return resultado
    resultado = buscar_por_nome(valor)
    if resultado:
        return resultado
    return buscar_por_primeiro_nome_unico(valor)


def buscar_por_disciplina(disciplina: str) -> list[ProfessorMadan]:
    """Retorna todos os professores de uma disciplina canônica."""
    return list(_INDICE_DISCIPLINA.get(_normalizar_para_busca(disciplina), []))


def buscar_professor_para_turma(
    disciplina: str,
    serie: int,
    turma_letra: str,
) -> list[ProfessorMadan]:
    """
    Retorna professores que lecionam a disciplina na série+turma informada.

    Ex: buscar_professor_para_turma("matematica", 1, "A") → [Luan Schunck]
    """
    candidatos = buscar_por_disciplina(disciplina)
    return [p for p in candidatos if p.leciona_em_turma(serie, turma_letra)]


# ---------------------------------------------------------------------------
# Validação cruzada professor ↔ disciplina ↔ turma
# ---------------------------------------------------------------------------

def validar_professor_disciplina_turma(
    nome_professor: str,
    disciplina: str,
    serie: int | None,
    turma_letra: str | None,
) -> dict[str, Any]:
    """
    Valida se o professor leciona a disciplina na série/turma informada.

    Retorna dict com:
      - "professor_encontrado": bool
      - "disciplina_compativel": bool
      - "turma_compativel": bool | None (None se serie/turma não informada)
      - "professor": ProfessorMadan | None
      - "problemas": list[str]
    """
    resultado: dict[str, Any] = {
        "professor_encontrado": False,
        "disciplina_compativel": False,
        "turma_compativel": None,
        "professor": None,
        "problemas": [],
    }

    prof = buscar_por_nome_ou_apelido(nome_professor)
    if prof is None or prof is False:
        resultado["problemas"].append(
            f"Professor '{nome_professor}' não encontrado no registro Madan 2026."
        )
        return resultado

    resultado["professor_encontrado"] = True
    resultado["professor"] = prof

    # Verifica disciplina
    disc_norm = _normalizar_para_busca(disciplina)
    prof_disc = prof.disciplina_canonica
    if prof_disc and _normalizar_para_busca(prof_disc) == disc_norm:
        resultado["disciplina_compativel"] = True
    else:
        # Verifica se é matéria composta (SOC/FIL/HIS)
        if "/" in prof.materia_sigla:
            siglas = prof.materia_sigla.split("/")
            for s in siglas:
                d = sigla_para_disciplina(s.strip())
                if d and _normalizar_para_busca(d) == disc_norm:
                    resultado["disciplina_compativel"] = True
                    break
        if not resultado["disciplina_compativel"]:
            resultado["problemas"].append(
                f"Professor '{prof.nome_display}' leciona {prof.materia_sigla} "
                f"({prof_disc}), não '{disciplina}'."
            )

    # Verifica turma (se informada)
    if serie is not None and turma_letra is not None:
        if prof.leciona_em_turma(serie, turma_letra):
            resultado["turma_compativel"] = True
        else:
            resultado["turma_compativel"] = False
            resultado["problemas"].append(
                f"Professor '{prof.nome_display}' não leciona na {serie}ª série "
                f"turma {turma_letra}. Turmas 1ª: {prof.turmas_1a}, 2ª: {prof.turmas_2a}."
            )

    return resultado


# ---------------------------------------------------------------------------
# Geração de chaves para mapa_professores.json
# ---------------------------------------------------------------------------

def extrair_professor_da_frente(frente_professor: str) -> str | None:
    """
    Extrai o nome/apelido do professor do campo "Frente - Professor".

    Padrões reconhecidos:
      "Frente X - Prof Y"  →  "Y"
      "Mat - Carioca"      →  "Carioca"
      "Carioca"            →  "Carioca"
      "F1 - Pezzin"        →  "Pezzin"

    Retorna None se não conseguir extrair.
    """
    if not frente_professor or not str(frente_professor).strip():
        return None

    s = str(frente_professor).strip()

    # Se contém " - ", pega a parte depois do último " - "
    if " - " in s:
        partes = s.split(" - ")
        candidato = partes[-1].strip()
        # Remove prefixos como "Prof ", "Prof. ", "Profa "
        candidato = re.sub(r"^(Prof\.?a?\.?\s+)", "", candidato, flags=re.IGNORECASE)
        return candidato if candidato else None

    # Sem separador: pode ser só o nome/apelido
    return s


def gerar_chaves_professor(prof: ProfessorMadan) -> list[str]:
    """
    Gera todas as variações de chave para o professor no mapa_professores.json.

    Para cada professor gera chaves com:
    - apelido (se existir)
    - disciplina + apelido
    - disciplina + nome
    - frente + apelido (para cada frente)
    """
    chaves: list[str] = []
    disc = prof.disciplina_canonica or prof.materia_sigla.lower()

    # Apelido puro
    if prof.apelido:
        chaves.append(prof.apelido.lower())
        chaves.append(f"{disc} - {prof.apelido.lower()}")
        chaves.append(f"{disc} {prof.apelido.lower()}")

    # Nome completo
    chaves.append(f"{disc} - {prof.nome.lower()}")

    # Primeiro nome
    primeiro_nome = prof.nome.split()[0].lower()
    chaves.append(f"{disc} - {primeiro_nome}")

    # Combinações com frentes
    todas_frentes = set()
    for f in prof.frentes_med + prof.frentes_ext + prof.frentes_ita:
        if f != "•":
            for sub in f.split("/"):
                todas_frentes.add(sub.strip())

    nome_ref = (prof.apelido or prof.nome.split()[0]).lower()
    for frente in sorted(todas_frentes):
        chaves.append(f"{frente.lower()} - {nome_ref}")
        chaves.append(f"{disc} {frente.lower()} - {nome_ref}")

    return chaves


def gerar_mapa_professores_esqueleto() -> dict[str, int]:
    """
    Gera esqueleto do mapa_professores.json com todas as chaves possíveis.

    Os valores são 0 (placeholder) — devem ser preenchidos com IDs do iScholar
    obtidos via descobrir_ids_ischolar.py.
    """
    mapa: dict[str, int] = {}
    for prof in PROFESSORES:
        chaves = gerar_chaves_professor(prof)
        for chave in chaves:
            # Normaliza igual ao resolvedor
            norm = _normalizar_para_busca(chave)
            if norm and norm not in mapa:
                mapa[norm] = 0  # placeholder — preencher com ID real
    return dict(sorted(mapa.items()))


# ---------------------------------------------------------------------------
# Relatório de cobertura
# ---------------------------------------------------------------------------

def gerar_relatorio_cobertura() -> dict[str, Any]:
    """
    Gera relatório de cobertura do registro de professores.

    Útil para verificar quais disciplinas/turmas têm professor designado
    e quais estão descobertas.
    """
    cobertura: dict[str, dict[str, list[str]]] = {}

    for prof in PROFESSORES:
        disc = prof.disciplina_canonica or prof.materia_sigla
        if disc not in cobertura:
            cobertura[disc] = {"1a": {}, "2a": {}}

        for turma in prof.turmas_1a:
            cobertura[disc].setdefault("1a", {})
            cobertura[disc]["1a"].setdefault(turma, [])
            cobertura[disc]["1a"][turma].append(prof.nome_display)

        for turma in prof.turmas_2a:
            cobertura[disc].setdefault("2a", {})
            cobertura[disc]["2a"].setdefault(turma, [])
            cobertura[disc]["2a"][turma].append(prof.nome_display)

    return {
        "total_professores": len(PROFESSORES),
        "disciplinas_cobertas": len(cobertura),
        "cobertura_por_disciplina": cobertura,
    }


__all__ = [
    "ProfessorMadan",
    "PROFESSORES",
    "SIGLA_PARA_DISCIPLINA",
    "sigla_para_disciplina",
    "parece_chave_disciplina_frente",
    "buscar_por_apelido",
    "buscar_por_nome",
    "buscar_por_nome_ou_apelido",
    "buscar_por_disciplina",
    "buscar_professor_para_turma",
    "validar_professor_disciplina_turma",
    "extrair_professor_da_frente",
    "gerar_chaves_professor",
    "gerar_mapa_professores_esqueleto",
    "gerar_relatorio_cobertura",
]
