"""
descobrir_ids_ischolar.py — Script de discovery para o ambiente de homologacao.

Chama os endpoints oficiais da API iScholar de forma read-only para:
  1. Validar conectividade e credenciais
  2. Descobrir o shape real das respostas de /aluno/busca
  3. Descobrir o shape real de /matricula/listar
  4. Listar notas existentes para descobrir IDs de disciplina/avaliacao/professor
  5. (Opcional) Gerar esqueletos dos mapas JSON no formato esperado pelo pipeline

Uso:
  # Discovery basico com um RA de teste:
  python descobrir_ids_ischolar.py --ra 12345

  # Pular busca de aluno (se ja souber o id_aluno):
  python descobrir_ids_ischolar.py --id-aluno 42

  # Pular busca de aluno e matricula (se ja souber o id_matricula):
  python descobrir_ids_ischolar.py --id-matricula 999

  # Gerar esqueletos de mapas JSON a partir dos dados descobertos:
  python descobrir_ids_ischolar.py --ra 12345 --gerar-mapas

  # Ver respostas brutas da API:
  python descobrir_ids_ischolar.py --ra 12345 --verbose

IMPORTANTE: Este script NAO modifica nenhum arquivo. Saida apenas em stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ischolar_client import IScholarClient


# ---------------------------------------------------------------------------
# Helpers de exibicao
# ---------------------------------------------------------------------------

def _sep(char: str = "─", n: int = 60) -> None:
    print(char * n)


def _titulo(texto: str) -> None:
    _sep()
    print(f"  {texto}")
    _sep()


def _ok(msg: str) -> None:
    print(f"  OK   {msg}")


def _erro(msg: str) -> None:
    print(f"  ERRO {msg}")


def _info(msg: str) -> None:
    print(f"       {msg}")


def _json_pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def _mostrar_shape(dados: Any, label: str = "resposta") -> None:
    """Mostra a estrutura de uma resposta da API de forma resumida."""
    if dados is None:
        _info(f"Shape de {label}: None")
        return

    if isinstance(dados, dict):
        _info(f"Shape de {label}: dict com {len(dados)} chave(s)")
        for k, v in dados.items():
            tipo = type(v).__name__
            if isinstance(v, list):
                _info(f"  '{k}': list[{len(v)} item(ns)]")
            elif isinstance(v, dict):
                _info(f"  '{k}': dict com {len(v)} chave(s)")
            else:
                _info(f"  '{k}': {tipo} = {v!r}")
    elif isinstance(dados, list):
        _info(f"Shape de {label}: list com {len(dados)} item(ns)")
        if dados and isinstance(dados[0], dict):
            _info(f"  Chaves do primeiro item: {list(dados[0].keys())}")
    else:
        _info(f"Shape de {label}: {type(dados).__name__}")


def _classificar_erro_http(status_code: Optional[int], mensagem: str) -> str:
    """Retorna orientacao para o operador baseada no status HTTP."""
    if status_code == 401:
        return (
            "Token rejeitado (401). Gere um novo token em "
            "https://madan_homolog.ischolar.com.br/ seguindo as instrucoes de "
            "https://ajuda.ischolar.com.br/pt-BR/articles/5680701-acessando-a-api-do-ischolar"
        )
    if status_code == 403:
        return (
            "Acesso negado (403). Verifique se ISCHOLAR_CODIGO_ESCOLA "
            "corresponde ao token configurado."
        )
    if status_code == 404:
        return (
            "Endpoint nao encontrado (404). Verifique ISCHOLAR_BASE_URL no .env."
        )
    if status_code == 422:
        return (
            "Parametros rejeitados pela API (422). Verifique se o RA ou ID informado esta correto."
        )
    if status_code is not None and status_code >= 500:
        return (
            f"Erro no servidor iScholar ({status_code}) — transitorio. Tente novamente em alguns minutos."
        )
    if "rede" in mensagem.lower() or "timeout" in mensagem.lower() or "connection" in mensagem.lower():
        return "Sem resposta da API. Verifique sua conexao de rede/firewall."
    return f"Erro: {mensagem}"


# ---------------------------------------------------------------------------
# Etapas de discovery
# ---------------------------------------------------------------------------

def etapa_1_conectividade(cliente: IScholarClient) -> bool:
    """Valida que token e codigo escola estao configurados."""
    _titulo("ETAPA 1 — Conectividade")

    try:
        headers = cliente._get_headers()
        _ok(f"Credenciais configuradas")
        _info(f"Base URL       : {cliente.base_url}")
        _info(f"Codigo escola  : {cliente.codigo_escola}")
        _info(f"Token presente : {'Sim' if cliente.token else 'Nao'}")
        _info(f"Token (inicio) : {cliente.token[:8]}..." if len(cliente.token) > 8 else "")
        return True
    except ValueError as exc:
        _erro(str(exc))
        _info("Preencha ISCHOLAR_API_TOKEN e ISCHOLAR_CODIGO_ESCOLA no arquivo .env")
        _info("Copie .env.example para .env e preencha os valores.")
        return False


def etapa_2_buscar_aluno(
    cliente: IScholarClient,
    ra: str,
    verbose: bool = False,
) -> Optional[int]:
    """Chama /aluno/busca e mostra shape da resposta."""
    _titulo(f"ETAPA 2 — Buscar aluno (RA={ra})")

    resultado = cliente.buscar_aluno(ra=ra)

    if not resultado.sucesso:
        _erro(f"buscar_aluno falhou: {resultado.mensagem}")
        orientacao = _classificar_erro_http(resultado.status_code, resultado.mensagem)
        _info(orientacao)
        return None

    _ok(f"buscar_aluno retornou sucesso (HTTP {resultado.status_code})")
    _mostrar_shape(resultado.dados, "/aluno/busca")

    if verbose and resultado.dados is not None:
        print()
        _info("Resposta bruta:")
        print(_json_pretty(resultado.dados))

    # Tenta extrair id_aluno
    from resolvedor_ids_ischolar import _extrair_id_aluno_da_resposta
    id_aluno = _extrair_id_aluno_da_resposta(resultado.dados)

    if id_aluno is not None:
        _ok(f"id_aluno extraido: {id_aluno}")
    else:
        _erro(
            "Nao foi possivel extrair id_aluno da resposta. "
            "O shape pode ser diferente do esperado pelo resolvedor."
        )
        _info("Revise a resposta acima e compare com _extrair_id_aluno_da_resposta().")

    return id_aluno


def etapa_3_listar_matriculas(
    cliente: IScholarClient,
    id_aluno: int,
    verbose: bool = False,
) -> tuple[Optional[int], Any]:
    """Chama /matricula/listar e mostra shape da resposta."""
    _titulo(f"ETAPA 3 — Listar matriculas (id_aluno={id_aluno})")

    resultado = cliente.listar_matriculas(id_aluno=id_aluno, resolver_id_matricula=True)

    if not resultado.sucesso:
        _erro(f"listar_matriculas falhou: {resultado.mensagem}")
        orientacao = _classificar_erro_http(resultado.status_code, resultado.mensagem)
        _info(orientacao)
        return None, None

    _ok(f"listar_matriculas retornou sucesso (HTTP {resultado.status_code})")
    _mostrar_shape(resultado.dados, "/matricula/listar")

    if verbose and resultado.dados is not None:
        print()
        _info("Resposta bruta:")
        print(_json_pretty(resultado.dados))

    if resultado.id_matricula_resolvido is not None:
        _ok(f"id_matricula resolvido: {resultado.id_matricula_resolvido}")
    else:
        _erro("Nao foi possivel resolver id_matricula inequivoco.")
        if resultado.rastreabilidade:
            ids = resultado.rastreabilidade.get("id_matriculas_extraiados", [])
            if len(ids) > 1:
                _info(f"IDs encontrados (ambiguos): {ids}")
            elif not ids:
                _info("Nenhum id_matricula encontrado nos itens retornados.")

    return resultado.id_matricula_resolvido, resultado.dados


def etapa_4_listar_notas(
    cliente: IScholarClient,
    id_matricula: int,
    verbose: bool = False,
) -> Any:
    """Chama /diario/notas para descobrir IDs de disciplina/avaliacao/professor."""
    _titulo(f"ETAPA 4 — Listar notas (id_matricula={id_matricula})")

    resultado = cliente.listar_notas(id_matricula=id_matricula)

    if not resultado.sucesso:
        _erro(f"listar_notas falhou: {resultado.mensagem}")
        orientacao = _classificar_erro_http(resultado.status_code, resultado.mensagem)
        _info(orientacao)
        return None

    _ok(f"listar_notas retornou sucesso (HTTP {resultado.status_code})")
    _mostrar_shape(resultado.dados, "/diario/notas")

    if verbose and resultado.dados is not None:
        print()
        _info("Resposta bruta:")
        print(_json_pretty(resultado.dados))

    # Tenta extrair IDs unicos de disciplina/avaliacao/professor
    notas = resultado.dados
    if isinstance(notas, dict):
        # Tenta desembrulhar envelope
        for k in ("notas", "items", "data", "dados"):
            if isinstance(notas.get(k), list):
                notas = notas[k]
                break

    if isinstance(notas, list) and notas:
        _ok(f"{len(notas)} nota(s) encontrada(s)")

        # Coleta IDs unicos
        disciplinas: dict[str, int] = {}
        avaliacoes: dict[str, int] = {}
        professores: dict[str, int] = {}

        campos_disc = ("id_disciplina", "idDisciplina", "disciplina_id")
        campos_aval = ("id_avaliacao", "idAvaliacao", "avaliacao_id", "identificacao")
        campos_prof = ("id_professor", "idProfessor", "professor_id")
        campos_nome_disc = ("disciplina", "nome_disciplina", "nomeDisciplina")
        campos_nome_aval = ("avaliacao", "nome_avaliacao", "nomeAvaliacao", "componente")
        campos_nome_prof = ("professor", "nome_professor", "nomeProfessor")

        for nota in notas:
            if not isinstance(nota, dict):
                continue

            # Disciplina
            for campo in campos_disc:
                val = nota.get(campo)
                if val is not None:
                    nome = None
                    for cn in campos_nome_disc:
                        nome = nota.get(cn)
                        if nome:
                            break
                    label = str(nome) if nome else f"id_{val}"
                    disciplinas[label] = int(val)
                    break

            # Avaliacao
            for campo in campos_aval:
                val = nota.get(campo)
                if val is not None:
                    nome = None
                    for cn in campos_nome_aval:
                        nome = nota.get(cn)
                        if nome:
                            break
                    label = str(nome) if nome else f"id_{val}"
                    avaliacoes[label] = int(val)
                    break

            # Professor
            for campo in campos_prof:
                val = nota.get(campo)
                if val is not None:
                    nome = None
                    for cn in campos_nome_prof:
                        nome = nota.get(cn)
                        if nome:
                            break
                    label = str(nome) if nome else f"id_{val}"
                    professores[label] = int(val)
                    break

        print()
        if disciplinas:
            _info(f"Disciplinas encontradas ({len(disciplinas)}):")
            for nome, id_d in sorted(disciplinas.items(), key=lambda x: x[1]):
                _info(f"  {nome} -> id_disciplina={id_d}")
        else:
            _info("Nenhum id_disciplina encontrado nas notas.")

        if avaliacoes:
            _info(f"Avaliacoes encontradas ({len(avaliacoes)}):")
            for nome, id_a in sorted(avaliacoes.items(), key=lambda x: x[1]):
                _info(f"  {nome} -> id_avaliacao={id_a}")
        else:
            _info("Nenhum id_avaliacao encontrado nas notas.")

        if professores:
            _info(f"Professores encontrados ({len(professores)}):")
            for nome, id_p in sorted(professores.items(), key=lambda x: x[1]):
                _info(f"  {nome} -> id_professor={id_p}")
        else:
            _info("Nenhum id_professor encontrado nas notas (pode ser opcional).")

        return {
            "notas_raw": notas,
            "disciplinas": disciplinas,
            "avaliacoes": avaliacoes,
            "professores": professores,
        }

    elif isinstance(notas, list) and not notas:
        _info("Nenhuma nota encontrada para esta matricula.")
        _info("Tente com um aluno que ja tenha notas lancadas no iScholar.")
        return {"notas_raw": [], "disciplinas": {}, "avaliacoes": {}, "professores": {}}

    else:
        _info("Formato inesperado da resposta de /diario/notas.")
        _info("Revise a resposta bruta com --verbose.")
        return None


def etapa_5_gerar_esqueletos(dados_notas: dict[str, Any]) -> None:
    """Gera esqueletos dos mapas JSON a partir dos IDs descobertos."""
    _titulo("ETAPA 5 — Esqueletos de mapas JSON")

    disciplinas = dados_notas.get("disciplinas", {})
    avaliacoes = dados_notas.get("avaliacoes", {})
    professores = dados_notas.get("professores", {})

    _info("ATENCAO: Estes esqueletos sao baseados nos dados de UMA matricula.")
    _info("Para cobertura completa, rode o script com alunos de diferentes")
    _info("disciplinas ou consulte a interface web do iScholar.")
    print()

    # mapa_disciplinas.json
    disc_mapa: dict[str, int] = {}
    for nome, id_d in disciplinas.items():
        chave = nome.lower().strip()
        disc_mapa[chave] = id_d

    disc_json = {
        "_schema": "mapa_disciplinas_v1",
        "_descricao": "Mapa disciplina -> id_disciplina (gerado por descobrir_ids_ischolar.py)",
        "disciplinas": disc_mapa if disc_mapa else {"PREENCHER_NOME_NORMALIZADO": 0},
    }
    _info("=== mapa_disciplinas.json ===")
    print(_json_pretty(disc_json))
    print()

    # mapa_avaliacoes.json
    aval_entries: list[dict[str, Any]] = []
    for nome, id_a in avaliacoes.items():
        entry: dict[str, Any] = {
            "componente": nome.lower().strip(),
            "id_avaliacao": id_a,
            "_comentario": "REVISE: componente deve ser av1/av2/av3/simulado/recuperacao. Adicione 'trimestre' se variar.",
        }
        aval_entries.append(entry)

    if not aval_entries:
        aval_entries = [{"componente": "PREENCHER", "trimestre": "1", "id_avaliacao": 0}]

    aval_json = {
        "_schema": "mapa_avaliacoes_v1",
        "_descricao": "Mapa componente+trimestre -> id_avaliacao (gerado por descobrir_ids_ischolar.py)",
        "avaliacoes": aval_entries,
    }
    _info("=== mapa_avaliacoes.json ===")
    print(_json_pretty(aval_json))
    print()

    # mapa_professores.json
    prof_mapa: dict[str, int] = {}
    for nome, id_p in professores.items():
        chave = nome.lower().strip()
        prof_mapa[chave] = id_p

    prof_json = {
        "_schema": "mapa_professores_v1",
        "_descricao": "Mapa frente_professor -> id_professor (gerado por descobrir_ids_ischolar.py)",
        "professores": prof_mapa if prof_mapa else {"PREENCHER_FRENTE_PROFESSOR": 0},
    }
    _info("=== mapa_professores.json ===")
    print(_json_pretty(prof_json))

    print()
    _info("Copie os JSONs acima para os respectivos arquivos de mapa.")
    _info("Revise os nomes normalizados e adicione entradas faltantes.")


# ---------------------------------------------------------------------------
# Resumo final
# ---------------------------------------------------------------------------

def _resumo_final(resultados: dict[str, bool]) -> None:
    _titulo("RESUMO DA DISCOVERY")

    for etapa, passou in resultados.items():
        status = "OK" if passou else "FALHOU"
        print(f"  {etapa}: {status}")

    print()
    todas_ok = all(resultados.values())
    if todas_ok:
        _ok("Todas as etapas passaram.")
        _info("Proximo passo: preencha os mapas JSON com os IDs descobertos")
        _info("e rode o dry-run do pipeline:")
        _info("")
        _info("  python cli_envio.py --planilha <planilha> --lote-id <id> --dry-run --aprovador <nome>")
    else:
        _erro("Algumas etapas falharam. Corrija os problemas acima antes de prosseguir.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _parsear_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discovery de IDs no ambiente iScholar (read-only, nao modifica arquivos)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python descobrir_ids_ischolar.py --ra 12345
  python descobrir_ids_ischolar.py --ra 12345 --gerar-mapas
  python descobrir_ids_ischolar.py --id-aluno 42
  python descobrir_ids_ischolar.py --id-matricula 999 --verbose
        """,
    )
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument(
        "--ra",
        help="RA de um aluno de teste para iniciar a discovery.",
    )
    grupo.add_argument(
        "--id-aluno",
        type=int,
        dest="id_aluno",
        help="id_aluno conhecido (pula etapa 2 — buscar_aluno).",
    )
    grupo.add_argument(
        "--id-matricula",
        type=int,
        dest="id_matricula",
        help="id_matricula conhecido (pula etapas 2 e 3).",
    )
    parser.add_argument(
        "--gerar-mapas",
        action="store_true",
        dest="gerar_mapas",
        help="Gera esqueletos dos mapas JSON a partir dos dados descobertos.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Mostra as respostas brutas (JSON completo) da API.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parsear_args()
    resultados: dict[str, bool] = {}

    print()
    _titulo("DISCOVERY DE IDS — iScholar")
    _info("Este script NAO modifica nenhum arquivo.")
    _info("Apenas chama endpoints GET da API iScholar.")
    print()

    # Inicializa o client
    try:
        cliente = IScholarClient()
    except Exception as exc:
        _erro(f"Falha ao criar IScholarClient: {exc}")
        _info("Verifique o .env e tente novamente.")
        sys.exit(5)

    # Etapa 1: Conectividade
    ok = etapa_1_conectividade(cliente)
    resultados["Etapa 1 - Conectividade"] = ok
    if not ok:
        _resumo_final(resultados)
        cliente.close()
        sys.exit(5)

    # Etapa 2: Buscar aluno (se necessario)
    id_aluno: Optional[int] = args.id_aluno
    id_matricula: Optional[int] = args.id_matricula

    if id_matricula is not None:
        _info(f"Pulando etapas 2 e 3 (id_matricula={id_matricula} fornecido).")
        resultados["Etapa 2 - Buscar aluno"] = True
        resultados["Etapa 3 - Listar matriculas"] = True
    elif id_aluno is not None:
        _info(f"Pulando etapa 2 (id_aluno={id_aluno} fornecido).")
        resultados["Etapa 2 - Buscar aluno"] = True
    else:
        id_aluno = etapa_2_buscar_aluno(cliente, args.ra, verbose=args.verbose)
        resultados["Etapa 2 - Buscar aluno"] = id_aluno is not None
        if id_aluno is None:
            _resumo_final(resultados)
            cliente.close()
            sys.exit(1)

    # Etapa 3: Listar matriculas (se necessario)
    if id_matricula is None:
        id_matricula, dados_mat = etapa_3_listar_matriculas(
            cliente, id_aluno, verbose=args.verbose
        )
        resultados["Etapa 3 - Listar matriculas"] = id_matricula is not None
        if id_matricula is None:
            _resumo_final(resultados)
            cliente.close()
            sys.exit(1)

    # Etapa 4: Listar notas
    dados_notas = etapa_4_listar_notas(cliente, id_matricula, verbose=args.verbose)
    resultados["Etapa 4 - Listar notas"] = dados_notas is not None

    # Etapa 5: Gerar esqueletos (opcional)
    if args.gerar_mapas and dados_notas is not None:
        etapa_5_gerar_esqueletos(dados_notas)
        resultados["Etapa 5 - Gerar esqueletos"] = True

    # Resumo
    _resumo_final(resultados)
    cliente.close()

    if all(resultados.values()):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
