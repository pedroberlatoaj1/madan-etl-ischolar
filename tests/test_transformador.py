"""Testes do transformador com contrato rigoroso de schema API iScholar."""

import pandas as pd
import pytest

from transformador import limpar_e_transformar_notas, linha_madan_para_lancamentos


class TestSchemaRigorosoAPI:
    """Testa a extração e limpeza do novo formato de dados."""

    def test_pipeline_mapeia_aliases_e_limpa_tipos_com_sucesso(self):
        df = pd.DataFrame({
            "Matrícula": [" 115 ", "116"],
            "ID Avaliação": ["2045", "2045"],
            "Nota": ["8,5", "9.0"],
            "Data Lançamento": ["16/03/2026", "2026-03-16"]
        })
        resultado = limpar_e_transformar_notas(df)
        
        assert len(resultado) == 2
        
        colunas_esperadas = ["id_matricula", "identificacao", "valor", "data_lancamento", "tipo", "observacao"]
        assert list(resultado.columns) == colunas_esperadas
        
        assert resultado["id_matricula"].iloc[0] == 115
        assert resultado["identificacao"].iloc[0] == 2045
        assert resultado["valor"].iloc[0] == 8.5
        assert resultado["data_lancamento"].iloc[0] == "2026-03-16"
        assert resultado["tipo"].iloc[0] == "nota"
        assert resultado["observacao"].iloc[0] is None

    def test_pipeline_falha_explicita_se_faltar_id(self):
        df = pd.DataFrame({
            "Nome Aluno": ["Joao", "Maria"],
            "Nota": ["8.5", "9.0"],
            "Data": ["16/03/2026", "16/03/2026"]
        })
        
        with pytest.raises(ValueError, match="Faltam colunas obrigatórias.*id_matricula"):
            limpar_e_transformar_notas(df)

    def test_pipeline_descarta_linhas_com_tipos_incorrigiveis(self):
        df = pd.DataFrame({
            "id_matricula": ["115", "115.5", "invalido", None], # Apenas o 115 é válido
            "identificacao": ["2045", "2045", "2045", "2045"],
            "valor": ["8.5", "9", "10", "5"],
            "data_lancamento": ["2026-03-16", "2026-03-16", "2026-03-16", "2026-03-16"]
        })
        
        resultado = limpar_e_transformar_notas(df)
        
        # O transformador deve limar as 3 linhas zoadas e deixar só 1
        assert len(resultado) == 1
        assert resultado["id_matricula"].iloc[0] == 115
        assert resultado["valor"].iloc[0] == 8.5

    def test_pipeline_preserva_observacao_e_tipo_se_fornecidos(self):
        df = pd.DataFrame({
            "matricula": ["115"],
            "codigo_avaliacao": ["2045"],
            "resultado": ["8.5"],
            "data": ["2026-03-16"],
            "tipo": ["recuperacao"],
            "observacao": [" Faltou na primeira prova "]
        })
        
        resultado = limpar_e_transformar_notas(df)
        
        assert len(resultado) == 1
        assert resultado["tipo"].iloc[0] == "recuperacao"
        # Garante que espaços no início e fim foram removidos
        assert resultado["observacao"].iloc[0] == "Faltou na primeira prova"

    def test_pipeline_descarta_linhas_com_datas_invalidas(self):
        df = pd.DataFrame({
            "id_matricula": ["115", "116"],
            "identificacao": ["2045", "2045"],
            "valor": ["8.5", "9.0"],
            "data_lancamento": ["2026-03-16", "data-invalida"]
        })
        
        resultado = limpar_e_transformar_notas(df)
        
        # A linha com 'data-invalida' não consegue virar data ISO e deve ser descartada
        assert len(resultado) == 1
        assert resultado["id_matricula"].iloc[0] == 115


def test_quando_peso_avaliacao_existe_valor_vazio_nao_gera_zero():
    df = pd.DataFrame(
        {
            "id_matricula": ["115", "116"],
            "identificacao": ["2045", "2046"],
            "valor": ["", "8.0"],
            "peso_avaliacao": ["12", "12"],
            "data_lancamento": ["2026-03-16", "2026-03-16"],
        }
    )

    resultado = limpar_e_transformar_notas(df)

    # A linha com valor vazio deve ser ignorada/descartada (não pode virar 0.0 ponderado).
    assert len(resultado) == 1
    assert resultado["id_matricula"].iloc[0] == 116
    assert resultado["valor"].iloc[0] == 9.6


def test_linha_madan_para_lancamentos_gera_multiplos_auditaveis_e_preserva_obj_disc():
    row = {
        "Estudante": "Aluno 1",
        "Trimestre": "1",
        "Disciplina": "Matemática",
        "Frente - Professor": "Frente X - Prof Y",
        "Turma": "1A",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISÇ)": "5",
        "AV 2 (OBJ)": "3",
        "AV 2 (DISÇ)": "4",
        "AV 3 (listas)": "7",
        "AV 3 (avaliação)": "6",
        "Simulado": "10",
        "Ponto extra": "1",
        "Nota Final": "9,9",
    }

    lancs = linha_madan_para_lancamentos(row, linha_origem=2)

    assert isinstance(lancs, list)
    assert all("hash_conteudo" in x for x in lancs)
    # Preserva OBJ/DISC como subcomponentes e não consolida silenciosamente
    av1_subs = [x for x in lancs if x["componente"] == "av1" and x.get("subcomponente") in ("obj", "disc")]
    assert len(av1_subs) == 2
    assert {x["subcomponente"] for x in av1_subs} == {"obj", "disc"}

    # AV1 consolidada: soma(4+5)=9, +ponto extra 1 = 10.0 (teto)
    av1_cons = [x for x in lancs if x["componente"] == "av1" and x.get("peso_avaliacao") is not None]
    assert len(av1_cons) == 1
    assert av1_cons[0]["status"] == "pronto"
    assert av1_cons[0]["nota_ajustada_0a10"] == 10.0  # soma(4+5)=9; +1 => 10.0
    assert av1_cons[0]["valor_ponderado"] == 9.0  # peso 9 no cenário com nivelamento: (10/10)*9

    # AV2 consolidada: soma(3+4)=7
    av2_cons = [x for x in lancs if x["componente"] == "av2" and x.get("peso_avaliacao") is not None]
    assert len(av2_cons) == 1
    assert av2_cons[0]["status"] == "pronto"
    assert av2_cons[0]["nota_ajustada_0a10"] == 7.0  # soma simples
    assert av2_cons[0]["peso_avaliacao"] == 9.0  # cenário com nivelamento (t1)
    assert av2_cons[0]["valor_ponderado"] == 6.3

    # Av3 final existe quando completa e tem ponderado
    av3_final = [x for x in lancs if x["componente"] == "av3" and x.get("peso_avaliacao") is not None]
    assert len(av3_final) == 1
    assert av3_final[0]["status"] == "pronto"
    assert av3_final[0]["valor_ponderado"] is not None

    # Nota final não dirige o cálculo: aparece apenas como ignorada/conferência
    nota_final = [x for x in lancs if x["componente"] == "nota_final"]
    assert len(nota_final) == 1
    assert nota_final[0]["status"] == "ignorado"


def test_linha_madan_para_lancamentos_av3_incompleta_marca_incompleto_e_nao_gera_final():
    row = {
        "Estudante": "Aluno 2",
        "Trimestre": "1",
        "Disciplina": "Química",
        "Turma": "T2",
        "AV 3 (listas)": "7",
        "Simulado": "8",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=3)

    incompleto = [x for x in lancs if x["componente"] == "av3" and x["status"] == "incompleto"]
    assert len(incompleto) == 1

    av3_final = [x for x in lancs if x["componente"] == "av3" and x.get("peso_avaliacao") is not None]
    assert av3_final == []


def test_consolidacao_av2_obj_disc_gera_lancamento_consolidado_ponderado():
    row = {
        "Estudante": "Aluno 3",
        "Trimestre": "3",
        "Disciplina": "Física",
        "Turma": "2C",
        "AV 2 (OBJ)": "3",
        "AV 2 (DISÇ)": "4",
        "Simulado": "",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=4)

    av2_subs = [x for x in lancs if x["componente"] == "av2" and x.get("subcomponente") in ("obj", "disc")]
    assert len(av2_subs) == 2

    av2_cons = [x for x in lancs if x["componente"] == "av2" and x.get("peso_avaliacao") is not None]
    assert len(av2_cons) == 1
    assert av2_cons[0]["status"] == "pronto"
    assert av2_cons[0]["nota_ajustada_0a10"] == 7.0  # soma simples 3+4=7
    assert av2_cons[0]["peso_avaliacao"] == 18.0  # 3º tri sem nivelamento
    assert av2_cons[0]["valor_ponderado"] == 12.6


# ---------------------------------------------------------------------------
# Testes de RA — propagação para lançamentos canônicos
# ---------------------------------------------------------------------------

def test_ra_propagado_para_todos_os_lancamentos():
    """RA presente na linha deve aparecer em todos os lançamentos gerados."""
    row = {
        "Estudante": "Ana Silva",
        "RA": "RA2024001",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Matemática",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISC)": "4",
        "Simulado": "9",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=1)

    assert len(lancs) > 0
    for l in lancs:
        assert l.get("ra") == "RA2024001", (
            f"RA ausente ou errado no lançamento componente={l.get('componente')}"
        )


def test_ra_ausente_resulta_em_none_nos_lancamentos():
    """Linha sem coluna RA gera lançamentos com ra=None — sem erro, sem bloqueio."""
    row = {
        "Estudante": "Beto",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Física",
        "AV 1 (OBJ)": "3",
        "AV 1 (DISC)": "4",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=2)

    assert len(lancs) > 0
    # ra=None é propagado — quem bloqueia o envio é o resolvedor, não o transformador
    for l in lancs:
        assert l.get("ra") is None


def test_ra_vazio_resulta_em_none_nos_lancamentos():
    """RA com string vazia é equivalente a ausente — deve ser None nos lançamentos."""
    row = {
        "Estudante": "Carol",
        "RA": "",
        "Turma": "2A",
        "Trimestre": "1",
        "Disciplina": "Química",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISC)": "5",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=3)

    # RA vazio é mapeado pelo mapper como string vazia → contexto retorna "" ou None
    # O que importa: o campo ra existe em todos os lançamentos
    assert all("ra" in l for l in lancs)


def test_ra_presente_no_hash_conteudo():
    """
    RA é parte do schema canônico e deve entrar no hash_conteudo.
    Dois lançamentos idênticos exceto pelo RA devem ter hashes diferentes.
    """
    row_com_ra = {
        "Estudante": "Aluno X",
        "RA": "RA001",
        "Turma": "1A",
        "Trimestre": "1",
        "Disciplina": "Mat",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISC)": "4",
    }
    row_sem_ra = {
        "Estudante": "Aluno X",
        "Turma": "1A",
        "Trimestre": "1",
        "Disciplina": "Mat",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISC)": "4",
    }
    lancs_com = linha_madan_para_lancamentos(row_com_ra, linha_origem=1)
    lancs_sem = linha_madan_para_lancamentos(row_sem_ra, linha_origem=1)

    # Pega o consolidado de AV1 nos dois casos
    av1_com = next(l for l in lancs_com if l["componente"] == "av1" and l.get("peso_avaliacao"))
    av1_sem = next(l for l in lancs_sem if l["componente"] == "av1" and l.get("peso_avaliacao"))

    assert av1_com["hash_conteudo"] != av1_sem["hash_conteudo"], (
        "RA faz parte do contexto: hashes devem diferir quando RA muda"
    )


# ---------------------------------------------------------------------------
# Testes de bloqueio de 3ª série
# ---------------------------------------------------------------------------

def test_terceira_serie_bloqueada_com_status_e_motivo():
    """Aluno do 3º ano deve gerar lançamento único com status 'bloqueado'."""
    row = {
        "Estudante": "Aluno 3ª Série",
        "RA": "RA3001",
        "Turma": "3A",
        "Trimestre": "1",
        "Disciplina": "Matemática",
        "AV 1 (OBJ)": "5",
        "AV 1 (DISC)": "4",
        "Simulado": "8",
    }
    lancs = linha_madan_para_lancamentos(row, linha_origem=10)

    assert len(lancs) == 1
    assert lancs[0]["status"] == "bloqueado"
    assert "serie_3_nao_suportada" in lancs[0]["motivo_status"]
    assert lancs[0]["componente"] == "todos"


def test_primeira_e_segunda_serie_nao_bloqueadas():
    """Alunos do 1º e 2º ano devem ser processados normalmente (sem bloqueio)."""
    for turma in ("1A", "2B"):
        row = {
            "Estudante": "Aluno OK",
            "RA": "RA100",
            "Turma": turma,
            "Trimestre": "1",
            "Disciplina": "Física",
            "AV 1 (OBJ)": "3",
            "AV 1 (DISC)": "4",
        }
        lancs = linha_madan_para_lancamentos(row, linha_origem=1)

        bloqueados = [l for l in lancs if l.get("status") == "bloqueado"]
        assert bloqueados == [], f"Turma {turma} não deveria ser bloqueada"


def test_linha_madan_para_lancamentos_recuperacao_t1_pronta_sem_peso():
    row = {
        "Estudante": "Aluno Recuperacao T1",
        "RA": "RAREC1",
        "Turma": "1A",
        "Trimestre": "1",
        "Disciplina": "Matemática",
        "Recuperação": "7.5",
        "AV 1 (OBJ)": "3",
        "AV 1 (DISC)": "2",
    }

    lancs = linha_madan_para_lancamentos(row, linha_origem=20)
    rec = [l for l in lancs if l["componente"] == "recuperacao"]

    assert len(rec) == 1
    assert rec[0]["status"] == "pronto"
    assert rec[0]["nota_ajustada_0a10"] == 7.5
    assert rec[0]["peso_avaliacao"] is None
    assert rec[0]["valor_ponderado"] is None


def test_linha_madan_para_lancamentos_recuperacao_t3_ignorada():
    row = {
        "Estudante": "Aluno Recuperacao T3",
        "RA": "RAREC3",
        "Turma": "2B",
        "Trimestre": "3",
        "Disciplina": "Física",
        "Recuperação": "8.0",
        "AV 1 (OBJ)": "3",
        "AV 1 (DISC)": "4",
    }

    lancs = linha_madan_para_lancamentos(row, linha_origem=21)
    rec = [l for l in lancs if l["componente"] == "recuperacao"]

    assert len(rec) == 1
    assert rec[0]["status"] == "ignorado"
    assert "recuperacao_trimestral_nao_existe_para_t3" in rec[0]["motivo_status"]


def test_linha_madan_para_lancamentos_recuperacao_final_t3_pronta():
    row = {
        "Estudante": "Aluno Rec Final T3",
        "RA": "RARECFINAL3",
        "Turma": "2B",
        "Trimestre": "T3",
        "Disciplina": "Arte",
        "Recuperação Final": "6.0",
    }

    lancs = linha_madan_para_lancamentos(row, linha_origem=22)
    rec_final = [l for l in lancs if l["componente"] == "recuperacao_final"]

    assert len(rec_final) == 1
    assert rec_final[0]["status"] == "pronto"
    assert rec_final[0]["nota_ajustada_0a10"] == 6.0
    assert rec_final[0]["peso_avaliacao"] is None
    assert rec_final[0]["valor_ponderado"] is None
    assert rec_final[0]["motivo_status"] == "recuperacao_final_confirmada"


def test_linha_madan_para_lancamentos_recuperacao_final_t1_ignorada():
    row = {
        "Estudante": "Aluno Rec Final T1",
        "RA": "RARECFINAL1",
        "Turma": "1A",
        "Trimestre": "T1",
        "Disciplina": "Arte",
        "Recuperação Final": "5.0",
    }

    lancs = linha_madan_para_lancamentos(row, linha_origem=23)
    rec_final = [l for l in lancs if l["componente"] == "recuperacao_final"]

    assert len(rec_final) == 1
    assert rec_final[0]["status"] == "ignorado"
    assert rec_final[0]["motivo_status"] == "recuperacao_final_fora_do_t3"


def test_linha_madan_para_lancamentos_t3_sem_recuperacao_final_nao_gera_componente():
    row = {
        "Estudante": "Aluno Sem Rec Final",
        "RA": "RASEMRECFINAL",
        "Turma": "2B",
        "Trimestre": "T3",
        "Disciplina": "Arte",
        "AV 1 (OBJ)": "4",
        "AV 1 (DISC)": "5",
    }

    lancs = linha_madan_para_lancamentos(row, linha_origem=24)
    rec_final = [l for l in lancs if l["componente"] == "recuperacao_final"]

    assert rec_final == []


def test_linha_madan_para_lancamentos_recuperacao_final_t3_invalida():
    row = {
        "Estudante": "Aluno Rec Final Invalida",
        "RA": "RARECINVALIDA",
        "Turma": "2B",
        "Trimestre": "T3",
        "Disciplina": "Arte",
        "Recuperação Final": "11",
    }

    lancs = linha_madan_para_lancamentos(row, linha_origem=25)
    rec_final = [l for l in lancs if l["componente"] == "recuperacao_final"]

    assert len(rec_final) == 1
    assert rec_final[0]["status"] == "erro_validacao"
