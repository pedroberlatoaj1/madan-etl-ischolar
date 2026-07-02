"""
Testes do gate de completude de colunas (completude_colunas.py).

Cobre a classe de erro do incidente 2026-06/07: coluna com cabeçalho fora do
padrão era descartada em silêncio. Também fixa a paridade da montagem de chave
de professor com o resolvedor do envio (chave por turma → fallback global).
"""

from __future__ import annotations

import pandas as pd

from completude_colunas import (
    CATEGORIA_DINAMICA_OK,
    CATEGORIA_DINAMICA_SEM_PROFESSOR,
    CATEGORIA_FIXA_RECONHECIDA,
    CATEGORIA_NAO_RECONHECIDA,
    COD_COLUNA_NAO_RECONHECIDA_COM_NOTAS,
    COD_COLUNA_NAO_RECONHECIDA_VAZIA,
    COD_COLUNA_PROFESSOR_SEM_MAPEAMENTO,
    avaliar_gate_completude,
    gerar_relatorio_colunas,
)


def _df_wide(colunas_extras: dict[str, list] | None = None, turma: str = "2B") -> pd.DataFrame:
    dados: dict[str, list] = {
        "Estudante": ["Ana Silva", "Beto Souza"],
        "RA": ["RA001", "RA002"],
        "Turma": [turma, turma],
        "Trimestre": ["2", "2"],
        "Matemática - Daniel (Frente A) - AV 1 Obj": ["4", "3"],
    }
    if colunas_extras:
        dados.update(colunas_extras)
    return pd.DataFrame(dados)


def _mapa() -> dict[str, int]:
    # Formato achatado de carregar_mapa_professores(): chaves já normalizadas
    # (minúsculas, sem acento, hífen vira espaço), globais + por turma.
    return {
        "matematica a daniel": 66,
        "geografia a carla": 72,
        "2b astronomia a": 92,
    }


class TestGerarRelatorioColunas:
    def test_colunas_fixas_reconhecidas(self):
        rel = gerar_relatorio_colunas(_df_wide(), mapa_professores=_mapa())
        por_coluna = {v.coluna: v for v in rel.colunas}
        for fixa in ("Estudante", "RA", "Turma", "Trimestre"):
            assert por_coluna[fixa].categoria == CATEGORIA_FIXA_RECONHECIDA
        assert rel.total_fixas == 4
        assert rel.turmas == ["2B"]

    def test_dinamica_ok_professor_embutido_via_chave_global(self):
        rel = gerar_relatorio_colunas(_df_wide(), mapa_professores=_mapa())
        v = next(c for c in rel.colunas if c.coluna.startswith("Matemática"))
        assert v.categoria == CATEGORIA_DINAMICA_OK
        assert v.id_professor == 66
        assert v.chave_professor == "matematica a daniel"

    def test_dinamica_ok_via_chave_por_turma(self):
        # Coluna LEGADA (sem professor no cabeçalho) de disciplina fora do
        # cadastro de professores_madan (sem qualificação por apelido): a chave
        # fica "astronomia a" e resolve APENAS pela chave por turma
        # "2b astronomia a" — paridade com a ordem do _resolver_professor
        # (turma antes do fallback global).
        df = _df_wide({"Astronomia - Frente A - AV 1 Obj": ["7", "8"]})
        rel = gerar_relatorio_colunas(df, mapa_professores=_mapa())
        v = next(c for c in rel.colunas if c.coluna.startswith("Astronomia"))
        assert v.categoria == CATEGORIA_DINAMICA_OK
        assert v.id_professor == 92
        assert v.chaves_turma == ["2b astronomia a"]

    def test_dinamica_sem_professor(self):
        df = _df_wide({"Geografia - Emerson (Frente A) - AV 1 Obj": ["6", "5"]})
        rel = gerar_relatorio_colunas(df, mapa_professores=_mapa())
        v = next(c for c in rel.colunas if c.coluna.startswith("Geografia"))
        assert v.categoria == CATEGORIA_DINAMICA_SEM_PROFESSOR
        assert v.chave_professor == "geografia a emerson"
        assert v.id_professor is None
        assert "2B" in (v.motivo or "")
        assert rel.total_dinamicas_sem_professor == 1

    def test_coluna_nao_reconhecida_com_notas_travessao(self):
        # Regressão da CLASSE do incidente: cabeçalho com travessão (em-dash)
        # não parseia e as notas seriam descartadas em silêncio.
        df = _df_wide({"Química — Caroline (Frente A) — AV 1 Obj": ["7", "8"]})
        rel = gerar_relatorio_colunas(df, mapa_professores=_mapa())
        v = next(c for c in rel.colunas if c.coluna.startswith("Química"))
        assert v.categoria == CATEGORIA_NAO_RECONHECIDA
        assert v.celulas_com_valor == 2
        assert rel.total_nao_reconhecidas == 1
        assert rel.total_nao_reconhecidas_com_valor == 1
        assert rel.celulas_com_valor_descartaveis == 2

    def test_coluna_nao_reconhecida_vazia(self):
        df = _df_wide({"Química — Caroline (Frente A) — AV 1 Obj": [None, ""]})
        rel = gerar_relatorio_colunas(df, mapa_professores=_mapa())
        v = next(c for c in rel.colunas if c.coluna.startswith("Química"))
        assert v.categoria == CATEGORIA_NAO_RECONHECIDA
        assert v.celulas_com_valor == 0
        assert rel.total_nao_reconhecidas_com_valor == 0
        assert rel.celulas_com_valor_descartaveis == 0

    def test_mapa_none_nao_gera_falso_bloqueio(self):
        df = _df_wide({"Geografia - Emerson (Frente A) - AV 1 Obj": ["6", "5"]})
        rel = gerar_relatorio_colunas(df, mapa_professores=None)
        assert rel.professor_verificado is False
        v = next(c for c in rel.colunas if c.coluna.startswith("Geografia"))
        assert v.categoria == CATEGORIA_DINAMICA_OK

    def test_contagem_celulas_reconhecidas(self):
        df = _df_wide({"Geografia - Carla (Frente A) - AV 1 Obj": ["6", None]})
        rel = gerar_relatorio_colunas(df, mapa_professores=_mapa())
        # Matemática: 2 células; Geografia: 1 célula.
        assert rel.celulas_com_valor_reconhecidas == 3

    def test_to_dict_serializavel(self):
        import json

        rel = gerar_relatorio_colunas(_df_wide(), mapa_professores=_mapa())
        assert json.dumps(rel.to_dict(), ensure_ascii=False)


class TestAvaliarGateCompletude:
    def _relatorio_com_problemas(self):
        df = _df_wide({
            "Química — Caroline (Frente A) — AV 1 Obj": ["7", "8"],
            "Geografia - Emerson (Frente A) - AV 1 Obj": ["6", "5"],
        })
        return gerar_relatorio_colunas(df, mapa_professores=_mapa())

    def test_default_nao_bloqueante(self):
        issues = avaliar_gate_completude(self._relatorio_com_problemas())
        por_codigo = {i.code: i for i in issues}

        perdida = por_codigo[COD_COLUNA_NAO_RECONHECIDA_COM_NOTAS]
        assert perdida.severity == "aviso"
        assert perdida.bloqueante is False
        assert "DESCARTADAS" in perdida.message
        assert perdida.details["origem"] == "gate_colunas"

        sem_prof = por_codigo[COD_COLUNA_PROFESSOR_SEM_MAPEAMENTO]
        assert sem_prof.severity == "pendencia"
        assert sem_prof.bloqueante is False

    def test_switches_bloqueantes(self):
        issues = avaliar_gate_completude(
            self._relatorio_com_problemas(),
            coluna_nao_reconhecida_bloqueante=True,
            professor_sem_mapeamento_bloqueante=True,
        )
        por_codigo = {i.code: i for i in issues}
        assert por_codigo[COD_COLUNA_NAO_RECONHECIDA_COM_NOTAS].severity == "erro"
        assert por_codigo[COD_COLUNA_NAO_RECONHECIDA_COM_NOTAS].bloqueante is True
        assert por_codigo[COD_COLUNA_PROFESSOR_SEM_MAPEAMENTO].bloqueante is True

    def test_coluna_vazia_sempre_aviso(self):
        df = _df_wide({"Coluna Estranha Qualquer": [None, None]})
        rel = gerar_relatorio_colunas(df, mapa_professores=_mapa())
        issues = avaliar_gate_completude(rel, coluna_nao_reconhecida_bloqueante=True)
        por_codigo = {i.code: i for i in issues}
        assert por_codigo[COD_COLUNA_NAO_RECONHECIDA_VAZIA].severity == "aviso"
        assert COD_COLUNA_NAO_RECONHECIDA_COM_NOTAS not in por_codigo

    def test_relatorio_limpo_zero_issues(self):
        rel = gerar_relatorio_colunas(_df_wide(), mapa_professores=_mapa())
        assert avaliar_gate_completude(rel) == []
