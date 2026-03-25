"""
transformador.py — Limpeza, validação e transformação dos dados de notas.

Funções principais:
- limpar_e_transformar_notas(caminho_arquivo_ou_df)
  Aceita caminho de arquivo (CSV/XLSX/XLS) OU DataFrame já carregado.

Objetivo:
- aderir ao schema real da planilha pedagógica;
- ser tolerante a "sujeira" (nomes de colunas e formatos);
- devolver um DataFrame estritamente tipado no schema REST da API iScholar.
"""

from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Union

import pandas as pd

from logger import configurar_logger

log = configurar_logger("etl.transformador")

# ---------------------------------------------------------------------------
# Etapa 2: Planilha Madan (wide) -> lançamentos canônicos auditáveis
# ---------------------------------------------------------------------------


def _hash_conteudo(obj: Mapping[str, Any]) -> str:
    """
    Hash estável para audit/idempotência local (Etapa 2).
    Não depende de job_store/fila.
    """
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def linha_madan_para_lancamentos(
    row: Mapping[str, Any],
    *,
    linha_origem: Any = None,
) -> list[dict[str, Any]]:
    """
    Converte 1 linha wide da planilha Madan em uma lista de lançamentos canônicos auditáveis.
    Não envia nada e não depende de iScholar.
    """
    from avaliacao_rules import (
        AV1,
        AV2,
        AV3,
        AV3_AVALIACAO,
        AV3_LISTAS,
        PONTO_EXTRA,
        SIMULADO,
        aplicar_ponto_extra_em_av1,
        calcular_av3_nivelamento,
        calcular_nota_ponderada,
        consolidar_obj_disc,
        is_blank,
        obter_pesos,
        validar_nota_0_10,
    )
    from madan_planilha_mapper import (
        CAN_AV1_DISC,
        CAN_AV1_OBJ,
        CAN_AV2_DISC,
        CAN_AV2_OBJ,
        CAN_AV3_AVALIACAO,
        CAN_AV3_LISTAS,
        CAN_DISCIPLINA,
        CAN_ESTUDANTE,
        CAN_FRENTE_PROFESSOR,
        CAN_NOTA_COM_AV3,
        CAN_NOTA_FINAL,
        CAN_NOTA_SEM_AV3,
        CAN_OBS_PONTO_EXTRA,
        CAN_PONTO_EXTRA,
        CAN_RA,
        CAN_RECUPERACAO,
        CAN_SIMULADO,
        CAN_TRIMESTRE,
        CAN_TURMA,
        SERIES_SUPORTADAS,
        extrair_serie_da_turma,
        linha_wide_para_canonica,
    )

    canon = linha_wide_para_canonica(row)
    ctx = {
        "estudante": canon.contexto.get(CAN_ESTUDANTE),
        "ra": canon.contexto.get(CAN_RA),
        "turma": canon.contexto.get(CAN_TURMA),
        "disciplina": canon.contexto.get(CAN_DISCIPLINA),
        "frente_professor": canon.contexto.get(CAN_FRENTE_PROFESSOR),
        "trimestre": canon.contexto.get(CAN_TRIMESTRE),
        "tem_nivelamento": canon.tem_nivelamento,
    }

    # ──────────────────────────────────────────────────────────────
    # FILTRO DE SÉRIE: apenas 1ª e 2ª séries são processadas.
    # 3ª série possui regras diferentes (não documentadas) e deve
    # ser bloqueada com mensagem clara.
    # ──────────────────────────────────────────────────────────────
    serie = extrair_serie_da_turma(ctx["turma"])
    if serie is not None and serie not in SERIES_SUPORTADAS:
        return [{
            **ctx,
            "componente": "todos",
            "subcomponente": None,
            "nota_original": None,
            "nota_ajustada_0a10": None,
            "peso_avaliacao": None,
            "valor_ponderado": None,
            "status": "bloqueado",
            "motivo_status": (
                f"serie_{serie}_nao_suportada: "
                f"apenas séries {SERIES_SUPORTADAS} são processadas. "
                f"O 3º ano possui regras de cálculo diferentes que ainda não foram implementadas."
            ),
            "observacoes": {"serie_detectada": serie, "turma_original": ctx["turma"]},
            "linha_origem": linha_origem,
            "hash_conteudo": _hash_conteudo({
                "estudante": ctx["estudante"], "ra": ctx["ra"],
                "turma": ctx["turma"], "serie_bloqueada": serie,
            }),
        }]

    def base_lancamento(**kwargs: Any) -> dict[str, Any]:
        base = {
            **ctx,
            "componente": None,
            "subcomponente": None,
            "nota_original": None,
            "nota_ajustada_0a10": None,
            "peso_avaliacao": None,
            "valor_ponderado": None,
            "status": None,
            "motivo_status": None,
            "observacoes": None,
            "linha_origem": linha_origem,
        }
        base.update(kwargs)
        base["hash_conteudo"] = _hash_conteudo(
            {k: base.get(k) for k in base.keys() if k != "hash_conteudo"}
        )
        return base

    lancamentos: list[dict[str, Any]] = []

    # Pesos (dependem de trimestre + nivelamento). Se trimestre faltar/for inválido: marca erro em todos ponderáveis.
    pesos: dict[str, float] | None
    try:
        pesos = obter_pesos(ctx["trimestre"], canon.tem_nivelamento)
    except Exception as e:  # pragma: no cover (coberto indiretamente em testes de rules)
        pesos = None
        lancamentos.append(
            base_lancamento(
                componente="pesos",
                status="erro_validacao",
                motivo_status=f"trimestre/pesos inválidos: {e}",
            )
        )

    def _emit_conferencia(canon_key: str, componente_nome: str) -> None:
        raw = canon.componentes.get(canon_key)
        if is_blank(raw):
            return
        lancamentos.append(
            base_lancamento(
                componente=componente_nome,
                nota_original=raw,
                status="ignorado",
                motivo_status="campo_de_conferencia_apenas",
            )
        )

    # Campos de conferência (nunca fonte principal)
    _emit_conferencia(CAN_NOTA_SEM_AV3, "nota_sem_av3")
    _emit_conferencia(CAN_NOTA_COM_AV3, "nota_com_av3")
    _emit_conferencia(CAN_NOTA_FINAL, "nota_final")

    # ⚠️ Recuperação: PDF "Sistema Avaliativo.pdf" NÃO menciona recuperação.
    # Regras a definir na reunião. Preserva nota sem ponderar.
    raw_rec = canon.componentes.get(CAN_RECUPERACAO)
    if not is_blank(raw_rec):
        lancamentos.append(
            base_lancamento(
                componente="recuperacao",
                nota_original=raw_rec,
                status="pronto",
                motivo_status="preservado_regra_pendente_reuniao",
            )
        )

    # AV1/AV2 OBJ/DISC: preserva subcomponentes; consolidação fica explícita como pendência.
    def _emit_sub(nota_raw: Any, componente: str, sub: str) -> None:
        if is_blank(nota_raw):
            lancamentos.append(
                base_lancamento(componente=componente, subcomponente=sub, status="ignorado", motivo_status="em_branco")
            )
            return
        try:
            n = validar_nota_0_10(nota_raw, allow_blank=False)
            lancamentos.append(
                base_lancamento(
                    componente=componente,
                    subcomponente=sub,
                    nota_original=nota_raw,
                    nota_ajustada_0a10=n,
                    status="pronto",
                    motivo_status="subcomponente_preservado_sem_consolidacao",
                )
            )
        except Exception as e:
            lancamentos.append(
                base_lancamento(
                    componente=componente,
                    subcomponente=sub,
                    nota_original=nota_raw,
                    status="erro_validacao",
                    motivo_status=str(e),
                )
            )

    raw_av1_obj = canon.componentes.get(CAN_AV1_OBJ)
    raw_av1_disc = canon.componentes.get(CAN_AV1_DISC)
    raw_av2_obj = canon.componentes.get(CAN_AV2_OBJ)
    raw_av2_disc = canon.componentes.get(CAN_AV2_DISC)

    _emit_sub(raw_av1_obj, AV1, "obj")
    _emit_sub(raw_av1_disc, AV1, "disc")
    _emit_sub(raw_av2_obj, AV2, "obj")
    _emit_sub(raw_av2_disc, AV2, "disc")

    # ✅ CONFIRMADO pelo pedagógico do Madan:
    # AV1/AV2 = SOMA SIMPLES de OBJ + DISC, com restrição: soma ≤ 10.
    # Preserva subcomponentes originais (já emitidos) e registra a política.
    consolidacao_policy = "soma"

    def _emit_consolidado_av12(componente: str, raw_obj: Any, raw_disc: Any) -> None:
        if is_blank(raw_obj) and is_blank(raw_disc):
            lancamentos.append(
                base_lancamento(componente=componente, status="ignorado", motivo_status="em_branco")
            )
            return

        try:
            nota_base = consolidar_obj_disc(raw_obj, raw_disc, policy=consolidacao_policy, arredondar=2)
            if nota_base is None:
                lancamentos.append(
                    base_lancamento(componente=componente, status="ignorado", motivo_status="em_branco")
                )
                return

            nota_final_0a10 = nota_base
            obs: dict[str, Any] = {
                "policy_consolidacao": consolidacao_policy,
                "obj": raw_obj,
                "disc": raw_disc,
            }

            if componente == AV1:
                # Comportamento provisório explícito: assume avaliação NÃO fechada por padrão.
                raw_extra_local = canon.componentes.get(CAN_PONTO_EXTRA)
                if not is_blank(raw_extra_local):
                    nota_final_0a10 = aplicar_ponto_extra_em_av1(
                        nota_final_0a10,
                        raw_extra_local,
                        avaliacao_fechada=False,
                        arredondar=2,
                    )
                    obs["ponto_extra_aplicado_em_av1"] = True
                    obs["avaliacao_fechada_assumida"] = False
                else:
                    obs["ponto_extra_aplicado_em_av1"] = False

            peso = (pesos or {}).get(componente)
            if peso is None:
                lancamentos.append(
                    base_lancamento(
                        componente=componente,
                        nota_original={"obj": raw_obj, "disc": raw_disc},
                        nota_ajustada_0a10=nota_final_0a10,
                        status="erro_validacao",
                        motivo_status="peso_ausente_para_cenario",
                        observacoes=obs,
                    )
                )
                return

            lancamentos.append(
                base_lancamento(
                    componente=componente,
                    nota_original={"obj": raw_obj, "disc": raw_disc},
                    nota_ajustada_0a10=nota_final_0a10,
                    peso_avaliacao=peso,
                    valor_ponderado=calcular_nota_ponderada(nota_final_0a10, peso, arredondar=2),
                    status="pronto",
                    motivo_status="consolidado_obj_disc",
                    observacoes=obs,
                )
            )
        except Exception as e:
            lancamentos.append(
                base_lancamento(
                    componente=componente,
                    nota_original={"obj": raw_obj, "disc": raw_disc},
                    status="erro_validacao",
                    motivo_status=str(e),
                    observacoes={"policy_consolidacao": consolidacao_policy},
                )
            )

    _emit_consolidado_av12(AV1, raw_av1_obj, raw_av1_disc)
    _emit_consolidado_av12(AV2, raw_av2_obj, raw_av2_disc)

    # Simulado (ponderável e consolidado)
    raw_sim = canon.componentes.get(CAN_SIMULADO)
    if is_blank(raw_sim):
        lancamentos.append(
            base_lancamento(componente=SIMULADO, status="ignorado", motivo_status="em_branco")
        )
    else:
        try:
            n = validar_nota_0_10(raw_sim, allow_blank=False)
            peso = (pesos or {}).get(SIMULADO)
            if peso is None:
                lancamentos.append(
                    base_lancamento(
                        componente=SIMULADO,
                        nota_original=raw_sim,
                        nota_ajustada_0a10=n,
                        status="erro_validacao",
                        motivo_status="peso_simulado_ausente_para_cenario",
                    )
                )
            else:
                lancamentos.append(
                    base_lancamento(
                        componente=SIMULADO,
                        nota_original=raw_sim,
                        nota_ajustada_0a10=n,
                        peso_avaliacao=peso,
                        valor_ponderado=calcular_nota_ponderada(n, peso, arredondar=2),
                        status="pronto",
                        motivo_status="ok",
                    )
                )
        except Exception as e:
            lancamentos.append(
                base_lancamento(
                    componente=SIMULADO,
                    nota_original=raw_sim,
                    status="erro_validacao",
                    motivo_status=str(e),
                )
            )

    # Av3: subcomponentes + regra de completude
    raw_listas = canon.componentes.get(CAN_AV3_LISTAS)
    raw_aval = canon.componentes.get(CAN_AV3_AVALIACAO)

    def _emit_av3_sub(raw: Any, sub: str) -> None:
        if is_blank(raw):
            lancamentos.append(
                base_lancamento(componente=AV3, subcomponente=sub, status="ignorado", motivo_status="em_branco")
            )
            return
        try:
            n = validar_nota_0_10(raw, allow_blank=False)
            lancamentos.append(
                base_lancamento(
                    componente=AV3,
                    subcomponente=sub,
                    nota_original=raw,
                    nota_ajustada_0a10=n,
                    status="pronto",
                    motivo_status="subcomponente_preservado",
                )
            )
        except Exception as e:
            lancamentos.append(
                base_lancamento(
                    componente=AV3,
                    subcomponente=sub,
                    nota_original=raw,
                    status="erro_validacao",
                    motivo_status=str(e),
                )
            )

    _emit_av3_sub(raw_listas, "listas")
    _emit_av3_sub(raw_aval, "avaliacao")

    listas_present = not is_blank(raw_listas)
    aval_present = not is_blank(raw_aval)

    if listas_present and aval_present:
        try:
            av3_ajustada = calcular_av3_nivelamento(raw_listas, raw_aval, arredondar=2)
            peso_av3 = (pesos or {}).get(AV3)
            if peso_av3 is None:
                lancamentos.append(
                    base_lancamento(
                        componente=AV3,
                        nota_original={"listas": raw_listas, "avaliacao": raw_aval},
                        nota_ajustada_0a10=av3_ajustada,
                        status="erro_validacao",
                        motivo_status="peso_av3_ausente_para_cenario",
                    )
                )
            else:
                lancamentos.append(
                    base_lancamento(
                        componente=AV3,
                        nota_original={"listas": raw_listas, "avaliacao": raw_aval},
                        nota_ajustada_0a10=av3_ajustada,
                        peso_avaliacao=peso_av3,
                        valor_ponderado=calcular_nota_ponderada(av3_ajustada, peso_av3, arredondar=2),
                        status="pronto",
                        motivo_status="ok",
                    )
                )
        except Exception as e:
            lancamentos.append(
                base_lancamento(
                    componente=AV3,
                    nota_original={"listas": raw_listas, "avaliacao": raw_aval},
                    status="erro_validacao",
                    motivo_status=str(e),
                )
            )
    elif listas_present ^ aval_present:
        lancamentos.append(
            base_lancamento(
                componente=AV3,
                status="incompleto",
                motivo_status="av3_incompleta_precisa_listas_e_avaliacao",
                observacoes={"listas": raw_listas, "avaliacao": raw_aval},
            )
        )

    # ✅ Ponto extra CONFIRMADO pelo PDF: aplica na coluna AV1, teto 10.
    # ⚠️ Pendente: definição exata de "avaliação fechada" (reunião).
    raw_extra = canon.componentes.get(CAN_PONTO_EXTRA)
    raw_obs_extra = canon.componentes.get(CAN_OBS_PONTO_EXTRA)
    if is_blank(raw_extra):
        lancamentos.append(
            base_lancamento(componente=PONTO_EXTRA, status="ignorado", motivo_status="em_branco")
        )
    else:
        try:
            # Mantém valor como float sem impor teto 10 (é extra); valida não-negativo em avaliacao_rules
            # Aplicação em AV1 é registrada como pendência nesta etapa.
            _ = aplicar_ponto_extra_em_av1(0, raw_extra, avaliacao_fechada=False)  # valida extra >= 0
            lancamentos.append(
                base_lancamento(
                    componente=PONTO_EXTRA,
                    nota_original=raw_extra,
                    status="pronto",
                    motivo_status="preservado_aplicacao_em_av1_depende_de_contrato_avaliacao_fechada",
                    observacoes={"observacao_ponto_extra": raw_obs_extra} if not is_blank(raw_obs_extra) else None,
                )
            )
        except Exception as e:
            lancamentos.append(
                base_lancamento(
                    componente=PONTO_EXTRA,
                    nota_original=raw_extra,
                    status="erro_validacao",
                    motivo_status=str(e),
                    observacoes={"observacao_ponto_extra": raw_obs_extra} if not is_blank(raw_obs_extra) else None,
                )
            )

    # Enriquecimento opcional: peso/ponderado para AV1/AV2 consolidado ainda não existe (por falta de regra OBJ/DISC).
    # Mantemos apenas o "peso esperado" como metadado de conferência, se disponível.
    if pesos is not None:
        for comp in (AV1, AV2):
            peso = pesos.get(comp)
            if peso is None:
                continue
            lancamentos.append(
                base_lancamento(
                    componente=f"{comp}_peso_esperado",
                    status="ignorado",
                    motivo_status="metadado_de_conferencia",
                    observacoes={"peso_avaliacao": peso},
                )
            )

    return lancamentos


# ---------------------------------------------------------------------------
# Helpers internos de IO
# ---------------------------------------------------------------------------

def _carregar_arquivo(caminho: str) -> pd.DataFrame:
    """
    Lê CSV ou Excel e devolve um DataFrame bruto.
    Levanta exceção se o formato não for suportado.
    """
    ext = Path(caminho).suffix.lower()
    if ext == ".csv":
        return pd.read_csv(caminho, dtype=str)
    elif ext in (".xlsx", ".xls"):
        return pd.read_excel(caminho, dtype=str)
    else:
        raise ValueError(f"Extensão de arquivo não suportada: {ext}")


# ---------------------------------------------------------------------------
# Helpers de limpeza (Pipeline)
# ---------------------------------------------------------------------------

def _normalizar_strings(df: pd.DataFrame) -> pd.DataFrame:
    """Remove espaços em valores str e normaliza strings vazias para NaN."""
    # Aplica strip apenas em valores str para evitar problemas em colunas mistas (object/string heterogêneo).
    def _strip_misto(valor: object) -> object:
        if isinstance(valor, str):
            return valor.strip()
        return valor

    # Aplica por coluna para dtypes textuais (object/string)
    df = df.apply(
        lambda col: col.map(_strip_misto)
        if (col.dtype == "object" or str(col.dtype).startswith("string"))
        else col
    )
    # Converte strings vazias (após strip) para NA de forma vetorizada
    df = df.replace(r"^\s*$", pd.NA, regex=True)
    return df


def _normalizar_nomes_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Converte nomes de colunas para snake_case (minúsculas, sem acentos)."""
    import unicodedata

    def _limpar_nome(nome: str) -> str:
        n = str(nome).strip().lower()
        n = "".join(
            c for c in unicodedata.normalize("NFD", n)
            if unicodedata.category(c) != "Mn"
        )
        n = n.replace(" ", "_").replace("-", "_").replace("/", "_")
        # Remove caracteres que não sejam alfanuméricos ou underscore
        n = "".join(c for c in n if c.isalnum() or c == "_")
        return n

    df.columns = [_limpar_nome(c) for c in df.columns]
    return df


def _mapear_colunas_payload(df: pd.DataFrame) -> pd.DataFrame:
    """Mapeia aliases conhecidos de forma conservadora para o schema da API."""
    mapa = {
        "matricula": "id_matricula",
        "cod_matricula": "id_matricula",
        "codigo_matricula": "id_matricula",
        "id_avaliacao": "identificacao",
        "avaliacao_id": "identificacao",
        "cod_avaliacao": "identificacao",
        "codigo_avaliacao": "identificacao",
        "nota": "valor",
        "resultado": "valor",
        "data": "data_lancamento",
        "data_nota": "data_lancamento",
        "data_avaliacao": "data_lancamento"
    }
    return df.rename(columns=mapa)


def _aplicar_matematica_madan(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica a regra de negócio do cursinho Madan:
      Nota Final = (valor / 10) * peso_avaliacao

    - Se a coluna 'peso_avaliacao' existir, ajusta a coluna 'valor' para as linhas
      com peso numérico válido, arredondando para 2 casas decimais.
    - Se a coluna não existir, apenas loga um warning e retorna o DataFrame original.

    Importante: célula em branco deve ser IGNORADA, e não tratada como zero.
    """
    from avaliacao_rules import calcular_nota_ponderada
    if "peso_avaliacao" not in df.columns:
        log.warning(
            "Coluna 'peso_avaliacao' ausente. Mantendo 'valor' como nota bruta (fallback de segurança)."
        )
        return df

    # Trabalha em cópia para não surpreender chamadores que reutilizam o df original.
    df = df.copy()

    pesos_num = pd.to_numeric(df["peso_avaliacao"], errors="coerce")
    mask_peso_valid = pesos_num.notna()

    if not mask_peso_valid.any():
        log.warning(
            "Coluna 'peso_avaliacao' presente, mas nenhum peso numérico válido foi encontrado. "
            "Mantendo 'valor' como nota bruta."
        )
        return df

    # Converte para numérico aqui para:
    # - evitar atribuição de float em coluna dtype "str"
    # - garantir que vazios permaneçam NaN (e sejam descartados mais adiante)
    valores_num = pd.to_numeric(df["valor"], errors="coerce")
    df["valor"] = valores_num
    mask_valor_presente = valores_num.notna()
    mask_ajuste = mask_peso_valid & mask_valor_presente

    if mask_ajuste.any():
        df.loc[mask_ajuste, "valor"] = [
            calcular_nota_ponderada(nota, peso, arredondar=2)
            for nota, peso in zip(valores_num[mask_ajuste], pesos_num[mask_ajuste])
        ]

    linhas_ajustadas = int(mask_ajuste.sum())
    linhas_ignoradas_por_vazio = int((mask_peso_valid & ~mask_valor_presente).sum())
    if linhas_ajustadas > 0 or linhas_ignoradas_por_vazio > 0:
        log.info(
            "Aplicada matemática Madan em %d linha(s) usando coluna 'peso_avaliacao' (ignoradas %d por 'valor' vazio).",
            linhas_ajustadas,
            linhas_ignoradas_por_vazio,
        )

    return df


def _coerce_int_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Força coluna para inteiro numérico, descartando nulos ou decimais residuais."""
    tamanho_inicial = len(df)

    # Converte para float numérico, marcando não-numéricos como NaN
    df[col] = pd.to_numeric(df[col], errors="coerce")

    # Remove nulos
    df = df.dropna(subset=[col])

    # Mantém apenas valores que são inteiros exatos (ex.: 10.0 → OK, 10.5 → descartado)
    col_float = df[col].astype(float)
    mask_inteiro_exato = col_float == col_float.round(0)
    df = df[mask_inteiro_exato].copy()

    # Converte para int real após o filtro
    df[col] = col_float[mask_inteiro_exato].astype(int)

    descartadas = tamanho_inicial - len(df)
    if descartadas > 0:
        log.warning("Descartadas %d linhas por '%s' nulo ou inválido.", descartadas, col)
    return df


def _coerce_float_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Converte valores com vírgula para ponto e força para float numérico."""
    tamanho_inicial = len(df)
    # pandas 3 pode usar dtype "str" (além de object/string[python]/string[pyarrow]).
    # Precisamos tratar vírgula decimal em qualquer coluna textual.
    if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object:
        df[col] = df[col].astype(str).str.replace(",", ".", regex=False)
    df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=[col])
    
    descartadas = tamanho_inicial - len(df)
    if descartadas > 0:
        log.warning("Descartadas %d linhas por '%s' nulo ou inválido.", descartadas, col)
    return df


def _coerce_iso_date_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """
    Converte strings de data para formato ISO (YYYY-MM-DD).

    Estratégia em duas tentativas, ambas com formato explícito (sem dayfirst):
      1. Formato BR  : %d/%m/%Y   ex: 16/03/2026
      2. Formato ISO : %Y-%m-%d   ex: 2026-03-16
    Entradas que não parseiam em nenhum dos dois formatos são descartadas.
    """
    tamanho_inicial = len(df)

    # Tentativa 1: formato BR explícito
    parsed = pd.to_datetime(df[col], errors="coerce", format="%d/%m/%Y")
    mask_nat = parsed.isna()

    if mask_nat.any():
        # Tentativa 2: formato ISO explícito para as entradas ainda NaT
        parsed_iso = pd.to_datetime(df.loc[mask_nat, col], errors="coerce", format="%Y-%m-%d")
        parsed = pd.concat([parsed[~mask_nat], parsed_iso]).reindex(df.index)

    df = df.assign(**{col: parsed})
    df = df.dropna(subset=[col])
    df[col] = df[col].dt.strftime("%Y-%m-%d")

    descartadas = tamanho_inicial - len(df)
    if descartadas > 0:
        log.warning("Descartadas %d linhas por '%s' nulo ou inválido.", descartadas, col)
    return df


def _preparar_payload_ischolar(df: pd.DataFrame) -> pd.DataFrame:
    """Valida, limpa nulos e aplica tipagem estrita no DataFrame."""
    colunas_obrigatorias = {"id_matricula", "identificacao", "valor", "data_lancamento"}
    ausentes = colunas_obrigatorias - set(df.columns)
    
    # 1. Validação explícita de campos mínimos
    if ausentes:
        msg = f"Planilha não apta para envio. Faltam colunas obrigatórias após mapeamento: {ausentes}"
        log.error("❌ %s", msg)
        raise ValueError(msg)

    # 2. Tipagem consistente e remoção de inválidos/nulos com log detalhado em cascata
    df = _coerce_int_column(df, "id_matricula")
    df = _coerce_int_column(df, "identificacao")
    df = _coerce_float_column(df, "valor")
    df = _coerce_iso_date_column(df, "data_lancamento")

    # 3. Configurar opcionais (com limpeza robusta de resíduos textuais)
    if "tipo" not in df.columns:
        df["tipo"] = "nota"
    else:
        df["tipo"] = df["tipo"].astype(str).str.strip()
        df["tipo"] = df["tipo"].replace(["", "nan", "NaN", "None", "<NA>"], pd.NA)
        df["tipo"] = df["tipo"].fillna("nota")

    if "observacao" not in df.columns:
        df["observacao"] = None
    else:
        df["observacao"] = df["observacao"].apply(lambda x: str(x).strip() if pd.notna(x) and str(x).strip() else None)

    # 4. Entregar schema limpo e fechado (com deduplicação explícita no payload final)
    colunas_finais = ["id_matricula", "identificacao", "valor", "data_lancamento", "tipo", "observacao"]
    df = df[colunas_finais].copy()

    # Garante dtype float para o contrato de envio
    # (evita surprises com Float64/obj após concat/assign em pipelines externos)
    df["valor"] = df["valor"].astype(float)

    # Deduplicação defensiva: evita enviar linhas idênticas (mesma nota) mais de uma vez.
    # A dedup é aplicada após coerções/normalizações para colapsar representações equivalentes.
    tamanho_inicial = len(df)
    df = df.drop_duplicates(subset=colunas_finais, keep="last").reset_index(drop=True)
    removidas = tamanho_inicial - len(df)
    if removidas > 0:
        log.info("♻️ Deduplicação do payload: %d linha(s) duplicada(s) removida(s).", removidas)

    return df


def _pipeline_dataframe(df: pd.DataFrame, origem: str) -> pd.DataFrame:
    """Executa a sequência de limpeza até a entrega do payload."""
    log.info("Transformando dados de '%s' (%d linhas originais)...", origem, len(df))
    df = _normalizar_strings(df)
    df = _normalizar_nomes_colunas(df)
    df = _mapear_colunas_payload(df)
    # Aplica regra de negócio Madan (se peso_avaliacao estiver presente) ANTES da tipagem estrita.
    df = _aplicar_matematica_madan(df)
    df = _preparar_payload_ischolar(df)
    
    log.info("✔️ Transformação concluída: %d linhas válidas resultantes.", len(df))
    return df

# ---------------------------------------------------------------------------
# Interfaces públicas
# ---------------------------------------------------------------------------

def limpar_e_transformar_notas(
    entrada: Union[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Pipeline completo de limpeza e transformação das notas.

    Aceita:
      - caminho de arquivo (.csv, .xlsx, .xls); ou
      - DataFrame já carregado (por exemplo, vindo de webhook).

    Returns:
        DataFrame limpo, validado e enriquecido, pronto para envio à API.

    Raises:
        FileNotFoundError: Se o arquivo não existir.
        ValueError: Se colunas obrigatórias estiverem ausentes ou dados inválidos.
        Exception: Para erros inesperados de I/O ou parsing.
    """
    # Compatibilidade com chamadas antigas: se vier não-DataFrame, assume caminho
    if isinstance(entrada, pd.DataFrame):
        df_bruto = entrada.copy()
        origem = "dataframe"
    else:
        caminho_arquivo = str(entrada)
        if not os.path.exists(caminho_arquivo):
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho_arquivo}")
        df_bruto = _carregar_arquivo(caminho_arquivo)
        origem = caminho_arquivo

    return _pipeline_dataframe(df_bruto, origem=origem)


def limpar_e_transformar_notas_df(df: pd.DataFrame, origem: str = "dataframe") -> pd.DataFrame:
    """
    Versão explícita da função principal para DataFrames.

    Útil para cenários como Google Sheets/webhook, onde os dados já chegam em memória.
    """
    return _pipeline_dataframe(df.copy(), origem=origem)