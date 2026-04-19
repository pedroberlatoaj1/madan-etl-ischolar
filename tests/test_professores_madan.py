"""
test_professores_madan.py — Testes do registro de professores Madan 2026.

Cobertura:
  - Sigla → disciplina canônica
  - Busca por apelido, nome, disciplina
  - Validação cruzada professor ↔ disciplina ↔ turma
  - Extração de nome do campo "Frente - Professor"
  - Geração de chaves para mapa_professores.json
"""

import pytest

from professores_madan import (
    PROFESSORES,
    SIGLA_PARA_DISCIPLINA,
    ProfessorMadan,
    buscar_por_apelido,
    buscar_por_disciplina,
    buscar_por_nome,
    buscar_por_nome_ou_apelido,
    buscar_professor_para_turma,
    extrair_professor_da_frente,
    gerar_chaves_professor,
    gerar_mapa_professores_esqueleto,
    gerar_relatorio_cobertura,
    parece_chave_disciplina_frente,
    sigla_para_disciplina,
    validar_professor_disciplina_turma,
)


# ---------------------------------------------------------------------------
# Siglas
# ---------------------------------------------------------------------------

class TestSiglaParaDisciplina:
    def test_siglas_basicas(self):
        assert sigla_para_disciplina("MAT") == "matematica"
        assert sigla_para_disciplina("HIS") == "historia"
        assert sigla_para_disciplina("FÍS") == "fisica"
        assert sigla_para_disciplina("GEO") == "geografia"
        assert sigla_para_disciplina("BIO") == "biologia"
        assert sigla_para_disciplina("QUÍ") == "quimica"

    def test_sigla_sem_acento(self):
        assert sigla_para_disciplina("FIS") == "fisica"
        assert sigla_para_disciplina("QUI") == "quimica"

    def test_sigla_case_insensitive(self):
        assert sigla_para_disciplina("mat") == "matematica"
        assert sigla_para_disciplina("His") == "historia"

    def test_sigla_composta(self):
        assert sigla_para_disciplina("SOC/FIL/HIS") == "sociologia"

    def test_sigla_desconhecida_retorna_none(self):
        assert sigla_para_disciplina("XXX") is None


# ---------------------------------------------------------------------------
# Busca por apelido/nome
# ---------------------------------------------------------------------------

class TestBuscaProfessor:
    def test_busca_por_apelido_exato(self):
        prof = buscar_por_apelido("Carioca")
        assert prof is not None
        assert "FELIPE" in prof.nome
        assert prof.materia_sigla == "MAT"

    def test_busca_por_apelido_case_insensitive(self):
        prof = buscar_por_apelido("pezzin")
        assert prof is not None
        assert "DIEGO" in prof.nome

    def test_busca_por_apelido_com_acento(self):
        prof = buscar_por_apelido("Varejão")
        assert prof is not None
        assert prof.materia_sigla == "GEO"

    def test_busca_por_nome_completo(self):
        prof = buscar_por_nome("DANIEL ROJAS NASCIMENTO")
        assert prof is not None
        assert prof.materia_sigla == "MAT"

    def test_busca_por_nome_ou_apelido_prioriza_apelido(self):
        prof = buscar_por_nome_ou_apelido("Cavaco")
        assert prof is not None
        assert "THIAGO HENRIQUE" in prof.nome

    def test_busca_inexistente_retorna_none(self):
        assert buscar_por_apelido("Professor Inexistente") is None
        assert buscar_por_nome("Nome Que Não Existe") is None

    def test_busca_por_disciplina(self):
        profs_mat = buscar_por_disciplina("matematica")
        assert len(profs_mat) >= 3  # Daniel, Carioca, Luan, Frika, Filipe
        nomes = [p.nome for p in profs_mat]
        assert any("DANIEL" in n for n in nomes)
        assert any("FELIPE" in n for n in nomes)

    def test_busca_professor_para_turma(self):
        profs = buscar_professor_para_turma("matematica", 1, "A")
        assert len(profs) >= 1
        # Luan Schunck leciona MAT 1ª A
        assert any("LUAN" in p.nome for p in profs)

    def test_busca_professor_para_turma_biologia_2a_pdf(self):
        profs = buscar_professor_para_turma("biologia", 2, "A")
        nomes = [p.nome for p in profs]
        assert any("PERRONE" in n for n in nomes)
        assert not any("JAMINE" in n for n in nomes)

    def test_busca_professor_para_turma_redacao_2a_pdf(self):
        profs = buscar_professor_para_turma("redacao", 2, "A")
        nomes = [p.nome for p in profs]
        assert any("GOMES DA SILVA JUNIOR" in n for n in nomes)
        assert not any("EMANUELLY" in n for n in nomes)

    def test_busca_professor_para_turma_literatura_2a_pdf(self):
        profs = buscar_professor_para_turma("literatura", 2, "A")
        nomes = [p.nome for p in profs]
        assert any("IANA" in n for n in nomes)
        assert not any("JANAINA" in n for n in nomes)

    def test_busca_professor_para_turma_filosofia_1a_pdf(self):
        profs = buscar_professor_para_turma("filosofia", 1, "A")
        nomes = [p.nome for p in profs]
        assert any("EZIMAR BRAVIN" in n for n in nomes)


# ---------------------------------------------------------------------------
# ProfessorMadan — métodos
# ---------------------------------------------------------------------------

class TestProfessorMadan:
    def test_disciplina_canonica(self):
        prof = buscar_por_apelido("Carioca")
        assert prof.disciplina_canonica == "matematica"

    def test_nome_display_com_apelido(self):
        prof = buscar_por_apelido("Carioca")
        assert prof.nome_display == "Carioca"

    def test_nome_display_sem_apelido(self):
        prof = buscar_por_nome("DANIEL ROJAS NASCIMENTO")
        assert prof.nome_display == "DANIEL NASCIMENTO"  # primeiro + último

    def test_leciona_em_turma(self):
        prof = buscar_por_apelido("Carioca")
        assert prof.leciona_em_turma(1, "B") is True   # 1ª B
        assert prof.leciona_em_turma(2, "C") is True   # 2ª C
        assert prof.leciona_em_turma(1, "A") is False   # não leciona 1ª A

    def test_leciona_em_turma_bullet_todas(self):
        # Cristina de Arruda Bravim leciona ING em todas as turmas
        prof = buscar_por_nome("CRISTINA DE ARRUDA BRAVIM")
        assert prof.leciona_em_turma(1, "A") is True
        assert prof.leciona_em_turma(1, "B") is True
        assert prof.leciona_em_turma(2, "C") is True

    def test_leciona_em_frente(self):
        prof = buscar_por_apelido("Pezzin")
        assert prof.leciona_em_frente("F1") is True
        assert prof.leciona_em_frente("F2") is True   # F1/F2 no EXT
        assert prof.leciona_em_frente("F5") is False


# ---------------------------------------------------------------------------
# Validação cruzada
# ---------------------------------------------------------------------------

class TestValidacaoCruzada:
    def test_professor_disciplina_turma_validos(self):
        res = validar_professor_disciplina_turma("Carioca", "matematica", 1, "B")
        assert res["professor_encontrado"] is True
        assert res["disciplina_compativel"] is True
        assert res["turma_compativel"] is True
        assert res["problemas"] == []

    def test_professor_disciplina_errada(self):
        res = validar_professor_disciplina_turma("Carioca", "historia", 1, "B")
        assert res["professor_encontrado"] is True
        assert res["disciplina_compativel"] is False
        assert len(res["problemas"]) >= 1

    def test_professor_turma_errada(self):
        res = validar_professor_disciplina_turma("Carioca", "matematica", 1, "A")
        assert res["professor_encontrado"] is True
        assert res["disciplina_compativel"] is True
        assert res["turma_compativel"] is False
        assert len(res["problemas"]) >= 1

    def test_professor_nao_encontrado(self):
        res = validar_professor_disciplina_turma("Prof Inexistente", "matematica", 1, "A")
        assert res["professor_encontrado"] is False
        assert len(res["problemas"]) >= 1

    def test_professor_materia_composta_bravin(self):
        """Bravin leciona SOC/FIL/HIS — deve ser compatível com qualquer das 3."""
        for disc in ("sociologia", "filosofia", "historia"):
            res = validar_professor_disciplina_turma("Bravin", disc, 1, "A")
            assert res["professor_encontrado"] is True
            assert res["disciplina_compativel"] is True, f"Bravin deveria ser compatível com {disc}"

    def test_professor_disciplina_turma_perrone_2a_pdf(self):
        res = validar_professor_disciplina_turma("Perrone", "biologia", 2, "A")
        assert res["professor_encontrado"] is True
        assert res["disciplina_compativel"] is True
        assert res["turma_compativel"] is True

    def test_professor_disciplina_turma_sergio_2a_pdf(self):
        res = validar_professor_disciplina_turma("Sergio", "redacao", 2, "A")
        assert res["professor_encontrado"] is True
        assert res["disciplina_compativel"] is True
        assert res["turma_compativel"] is True


# ---------------------------------------------------------------------------
# Extração de professor do campo "Frente - Professor"
# ---------------------------------------------------------------------------

class TestExtrairProfessorDaFrente:
    def test_formato_frente_separador(self):
        assert extrair_professor_da_frente("Mat - Carioca") == "Carioca"
        assert extrair_professor_da_frente("F1 - Pezzin") == "Pezzin"
        assert extrair_professor_da_frente("Frente X - Prof Y") == "Y"

    def test_formato_sem_separador(self):
        assert extrair_professor_da_frente("Carioca") == "Carioca"

    def test_formato_com_prof_prefix(self):
        assert extrair_professor_da_frente("Mat - Prof Silva") == "Silva"
        assert extrair_professor_da_frente("Mat - Profa Lima") == "Lima"

    def test_vazio_retorna_none(self):
        assert extrair_professor_da_frente("") is None
        assert extrair_professor_da_frente(None) is None


# ---------------------------------------------------------------------------
# Geração de chaves e esqueleto
# ---------------------------------------------------------------------------

class TestGeracaoChaves:
    def test_gerar_chaves_professor_com_apelido(self):
        prof = buscar_por_apelido("Carioca")
        chaves = gerar_chaves_professor(prof)
        assert "carioca" in chaves
        assert "matematica - carioca" in chaves

    def test_gerar_mapa_esqueleto_nao_vazio(self):
        mapa = gerar_mapa_professores_esqueleto()
        assert len(mapa) > 0
        # Todas as chaves devem ter valor 0 (placeholder)
        assert all(v == 0 for v in mapa.values())
        # Deve conter chaves para professores conhecidos
        assert "carioca" in mapa
        assert "pezzin" in mapa

    def test_relatorio_cobertura(self):
        relatorio = gerar_relatorio_cobertura()
        assert relatorio["total_professores"] == len(PROFESSORES)
        assert relatorio["disciplinas_cobertas"] > 0
        assert "cobertura_por_disciplina" in relatorio


# ---------------------------------------------------------------------------
# Integridade do registro
# ---------------------------------------------------------------------------

class TestIntegridadeRegistro:
    def test_total_professores_minimo(self):
        """O PDF tem 37 professores — o registro deve ter pelo menos esse número."""
        assert len(PROFESSORES) >= 37

    def test_todos_tem_materia(self):
        for prof in PROFESSORES:
            assert prof.materia_sigla, f"{prof.nome} sem matéria definida"

    def test_todos_tem_nome(self):
        for prof in PROFESSORES:
            assert prof.nome.strip(), f"Professor sem nome"

    def test_emails_formato_valido(self):
        for prof in PROFESSORES:
            if prof.email:
                assert "@" in prof.email, f"Email inválido: {prof.email} ({prof.nome})"

    def test_disciplina_canonica_resolve_para_todos(self):
        """Todo professor deve ter uma disciplina canônica reconhecida."""
        for prof in PROFESSORES:
            disc = prof.disciplina_canonica
            assert disc is not None, (
                f"{prof.nome} ({prof.materia_sigla}) não tem disciplina canônica"
            )


# ---------------------------------------------------------------------------
# parece_chave_disciplina_frente — distinguir alias de disciplina/frente de nome
# ---------------------------------------------------------------------------

class TestPareceChaveDisciplinaFrente:
    """
    Garante que parece_chave_disciplina_frente() identifica corretamente
    aliases de disciplina/frente (produzidos pelo wide_format_adapter) e não
    os confunde com nomes de professor.

    Regressão dos warnings PROFESSOR_NAO_ENCONTRADO_REGISTRO falsos detectados
    em 2026-04-01 durante homologação assistida.
    """

    # --- chaves que DEVEM ser reconhecidas como alias disciplina/frente ---

    def test_frente_unica_arte(self):
        """'arte' é alias de Frente Única de Arte — não nome de pessoa."""
        assert parece_chave_disciplina_frente("arte") is True

    def test_frente_unica_biologia(self):
        assert parece_chave_disciplina_frente("biologia") is True

    def test_frente_unica_ingles(self):
        assert parece_chave_disciplina_frente("ingles") is True

    def test_frente_unica_gramatica(self):
        assert parece_chave_disciplina_frente("gramatica") is True

    def test_frente_multipla_fisica_a(self):
        """'fisica a' é alias de Física Frente A — não nome de pessoa."""
        assert parece_chave_disciplina_frente("fisica a") is True

    def test_frente_multipla_fisica_b(self):
        assert parece_chave_disciplina_frente("fisica b") is True

    def test_frente_multipla_fisica_c(self):
        assert parece_chave_disciplina_frente("fisica c") is True

    def test_frente_multipla_matematica_a(self):
        assert parece_chave_disciplina_frente("matematica a") is True

    def test_frente_multipla_matematica_b(self):
        assert parece_chave_disciplina_frente("matematica b") is True

    def test_acento_normalizado(self):
        """Chaves com acento devem ser reconhecidas após normalização."""
        assert parece_chave_disciplina_frente("Física A") is True
        assert parece_chave_disciplina_frente("Inglês") is True

    # --- valores que NÃO devem ser reconhecidos como alias ---

    def test_apelido_professor_puro_nao_e_alias(self):
        """'cavaco' é apelido de professor — deve ir para lookup normal."""
        assert parece_chave_disciplina_frente("cavaco") is False

    def test_apelido_carioca_nao_e_alias(self):
        assert parece_chave_disciplina_frente("carioca") is False

    def test_formato_com_separador_nao_e_alias(self):
        """Presença de ' - ' indica nome explícito — não é chave pura."""
        assert parece_chave_disciplina_frente("arte - lenice") is False
        assert parece_chave_disciplina_frente("fisica - cavaco") is False
        assert parece_chave_disciplina_frente("biologia - jamine") is False

    def test_nome_professor_inexistente_nao_e_alias(self):
        assert parece_chave_disciplina_frente("professor inexistente") is False

    def test_string_vazia_nao_e_alias(self):
        assert parece_chave_disciplina_frente("") is False

    def test_identificador_frente_com_digito_nao_e_alias(self):
        """Frentes numéricas (ex.: 'fisica 1') não são o padrão do pipeline — não suprimir."""
        # O pipeline produz "fisica a", "fisica b" — nunca "fisica 1"
        # Esta regra garante que não suprimimos formatos inesperados.
        assert parece_chave_disciplina_frente("fisica 1") is False
