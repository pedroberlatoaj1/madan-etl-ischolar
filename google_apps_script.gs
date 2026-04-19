/**
 * google_apps_script.gs - Cliente fino Google Sheets -> backend ETL iScholar.
 *
 * Fluxo operacional suportado:
 * 1. Validar Lote
 * 2. Aprovar e Enviar
 * 3. Simular (Dry Run)
 * 4. Consultar ultimo status
 *
 * Este script nao implementa regra de negocio.
 * Ele apenas:
 * - le a aba configurada;
 * - chama os endpoints HTTP;
 * - faz polling simples;
 * - mostra dialogs textuais para o operador;
 * - guarda lote_id / snapshot_hash localmente entre validacao e aprovacao.
 */

// ---------------------------------------------------------------------------
// ATENÇÃO — diferença entre arquivo versionado e instância implantada:
//
// Este arquivo mantém PLACEHOLDERS por segurança.
// Os valores reais são inseridos manualmente na instância implantada no Google Sheets
// (Extensões > Apps Script) a cada sessão de uso.
//
// Campos que devem ser preenchidos manualmente na instância implantada:
//   API_BASE_URL    → URL pública HTTPS do túnel ngrok (muda a cada reinício)
//   WEBHOOK_SECRET  → valor do campo WEBHOOK_SECRET no arquivo .env do backend
//
// Nota — Plano B (workbook anual multi-aba):
//   O script usa SEMPRE a aba ativa no momento do clique. Não há mais constante
//   NOME_ABA_NOTAS. Navegue até a aba desejada (ex: "2A_T1") ANTES de clicar
//   em "Validar Lote", "Dry Run" ou "Aprovar e Enviar".
//   Um diálogo de confirmação exibe o nome da aba a processar antes de prosseguir.
//
// Qualquer mudança ESTRUTURAL neste arquivo (nova função, novo endpoint, nova lógica)
// deve ser refletida no repositório. Valores sensíveis nunca devem ser commitados.
// ---------------------------------------------------------------------------
const API_BASE_URL = "https://sua-api.com";
const WEBHOOK_SECRET = "troque_por_um_segredo_forte_em_producao";
const ISCHOLAR_API_BASE_URL = "https://api.ischolar.app";
const ISCHOLAR_CODIGO_ESCOLA = "madan";
const PROP_ISCHOLAR_TOKEN = "ISCHOLAR_TOKEN";
const ISCHOLAR_TAMANHO_LOTE_POST = 25;
const ISCHOLAR_TEMPO_MAX_MS = 4 * 60 * 1000;
const ISCHOLAR_MAX_PAGINAS_ALUNOS = 20;
const EMAIL_NOTIFICACOES = "marina@madan.com.br";
const EMAIL_BCC = "pedroberlatoaj1@gmail.com";
const EMAIL_ALERTA_TOKEN_ISCHOLAR = "pedroberlatoaj1@gmail.com";
const HABILITAR_NOTIFICACOES = true;

// Padrão reconhecido como aba trimestral Plano B: ex. "2A_T1", "1B_T3"
var REGEX_ABA_PLANO_B = /^([1-9][A-Za-z])_(T[123])$/i;

const POLL_INTERVAL_MS = 5000;
const POLL_TENTATIVAS_VALIDACAO = 8;
const POLL_TENTATIVAS_ENVIO = 12;

const PROP_LOTE_ID = "etl_ischolar_lote_id";
const PROP_SNAPSHOT_HASH = "etl_ischolar_snapshot_hash";
const PROP_VALIDACAO_JOB_ID = "etl_ischolar_validacao_job_id";
const PROP_APROVACAO_JOB_ID = "etl_ischolar_aprovacao_job_id";
const PROP_ULTIMO_STATUS = "etl_ischolar_ultimo_status";
const PROP_ULTIMA_ABA = "etl_ischolar_ultima_aba";
const PROP_NOTIFICACAO_PREFIX = "etl_ischolar_notificado";
const PROP_ALERTA_TOKEN_ISCHOLAR_DIA = "etl_ischolar_token_alerta_dia";
const TRIGGER_VERIFICACAO_TOKEN_ISCHOLAR = "verificarTokenIScholar_";

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("iScholar ETL")
    .addItem("Validar Lote", "menuValidarLote")
    .addItem("Aprovar e Enviar", "menuAprovarEEnviar")
    .addItem("Simular (Dry Run)", "menuSimularDryRun")
    .addSeparator()
    .addItem("Simular via Apps Script", "menuSimularViaAppsScript")
    .addItem("Aprovar e Enviar (Apps Script)", "menuAprovarEEnviarViaAppsScript")
    .addSeparator()
    .addItem("Mostrar Ultimo Status", "menuMostrarUltimoStatus")
    .addItem("Limpar Estado Local", "menuLimparEstadoLocal")
    .addToUi();
}

function menuValidarLote() {
  executarFluxoValidacao_();
}

function executarFluxoValidacao_() {
  executarAcaoComTratamento_(function() {
    garantirBackendDisponivel_("validar o lote");
    var aba = obterAbaAtiva_();
    confirmarProcessamentoAba_(aba);
    var payload = montarPayloadValidacao_(aba);
    var resposta = chamarApi_("post", "/webhook/notas", payload);

    if (resposta.statusCode !== 202) {
      throw new Error(extrairMensagemErro_(resposta));
    }

    var body = resposta.json || {};
    salvarEstadoLocal_({
      lote_id: body.lote_id || payload.lote_id,
      snapshot_hash: body.snapshot_hash || "",
      validacao_job_id: body.job_id || "",
      aprovacao_job_id: "",
      ultimo_status: body.status || "",
      ultima_aba: aba.getName()
    });

    var validacao = aguardarValidacao_(body.lote_id || payload.lote_id, body.job_id || "");
    salvarEstadoLocal_({
      lote_id: validacao.lote_id,
      snapshot_hash: validacao.snapshot_hash || body.snapshot_hash || "",
      ultimo_status: validacao.status || ""
    });

    var infoAba = _interpretarNomeAba_(aba.getName());
    var turmaTrimestre = infoAba ? (infoAba.turma + "_" + infoAba.trimestre) : aba.getName();
    var resumoValidacao = validacao.resumo || {};
    var assuntoValidacao =
      "[Madan ETL] Lote " +
      turmaTrimestre +
      " validado \u2014 " +
      valorOuZero_(resumoValidacao.total_sendaveis) +
      " envios prontos";
    var corpoValidacao = montarHtmlNotificacaoValidacao_(validacao, aba);
    notificarEventoLote_(
      validacao.lote_id || payload.lote_id || "",
      "validacao_concluida",
      assuntoValidacao,
      corpoValidacao
    );

    mostrarDialogoTexto_(
      "Resultado da Validacao",
      montarTextoValidacao_(validacao)
    );
  });
}

function menuAprovarEEnviar() {
  executarFluxoAprovacao_(false);
}

function menuSimularDryRun() {
  executarFluxoAprovacao_(true);
}

function menuSimularViaAppsScript() {
  executarFluxoAppsScript_(true);
}

function menuAprovarEEnviarViaAppsScript() {
  executarFluxoAppsScript_(false);
}

function menuMostrarUltimoStatus() {
  executarAcaoComTratamento_(function() {
    var estado = carregarEstadoLocal_();
    if (!estado.lote_id) {
      throw new Error("Nenhum lote local foi registrado ainda. Rode 'Validar Lote' primeiro.");
    }

    var texto = ["Lote: " + estado.lote_id];
    var validacao = consultarValidacaoAtual_(estado.lote_id, true);
    if (validacao) {
      texto.push("");
      texto.push("=== VALIDACAO ===");
      texto.push(montarTextoValidacao_(validacao));
    }

    var envio = consultarResultadoEnvioAtual_(estado.lote_id, true);
    if (envio) {
      texto.push("");
      texto.push("=== RESULTADO DO ENVIO ===");
      texto.push(montarTextoResultadoEnvio_(envio));
    }

    var jobId = estado.aprovacao_job_id || estado.validacao_job_id;
    var job = jobId ? consultarJobAtual_(jobId, true) : null;
    if (job) {
      texto.push("");
      texto.push("=== JOB ASSINCRONO ===");
      texto.push(montarTextoJob_(job));
    }

    mostrarDialogoTexto_("Ultimo Status", texto.join("\n"));
  });
}

function menuLimparEstadoLocal() {
  obterArmazenamentoEstado_().deleteAllProperties();
  SpreadsheetApp.getUi().alert("Estado local limpo.", SpreadsheetApp.getUi().ButtonSet.OK);
}

function executarFluxoAprovacao_(dryRun) {
  executarAcaoComTratamento_(function() {
    garantirBackendDisponivel_(dryRun ? "simular o envio" : "aprovar e enviar");
    var estado = carregarEstadoLocal_();
    if (!estado.lote_id) {
      throw new Error("Nenhum lote validado localmente. Rode 'Validar Lote' antes de aprovar.");
    }

    var validacao = consultarValidacaoAtual_(estado.lote_id, false);
    if (!validacao) {
      throw new Error("Nao foi possivel localizar a validacao atual do lote.");
    }
    if (!validacao.pode_aprovar) {
      throw new Error(validacao.mensagem || "O lote nao esta apto para aprovacao.");
    }

    salvarEstadoLocal_({
      lote_id: validacao.lote_id,
      snapshot_hash: validacao.snapshot_hash || "",
      ultimo_status: validacao.status || ""
    });

    var aprovador = solicitarIdentidadeAprovador_(dryRun);
    if (!aprovador) {
      return;
    }

    confirmarAcao_(
      dryRun ? "Simular envio?" : "Aprovar e enviar?",
      [
        "Lote: " + validacao.lote_id,
        "Snapshot: " + validacao.snapshot_hash,
        "Aprovador: " + aprovador.aprovado_por,
        (aprovador.aprovador_email ? "Email de sessao: " + aprovador.aprovador_email : "Email de sessao: indisponivel"),
        dryRun ? "Modo: simulacao (dry run)" : "Modo: envio real"
      ].join("\n")
    );

    var resposta = chamarApi_(
      "post",
      "/lote/" + encodeURIComponent(validacao.lote_id) + "/aprovar",
      {
        snapshot_hash: validacao.snapshot_hash,
        aprovador: aprovador.aprovado_por,
        aprovador_nome_informado: aprovador.aprovador_nome_informado,
        aprovador_email: aprovador.aprovador_email,
        aprovador_origem: aprovador.aprovador_origem,
        dry_run: dryRun
      }
    );

    if (resposta.statusCode !== 202) {
      throw new Error(extrairMensagemErro_(resposta));
    }

    var body = resposta.json || {};
    salvarEstadoLocal_({
      lote_id: body.lote_id || validacao.lote_id,
      snapshot_hash: body.snapshot_hash || validacao.snapshot_hash,
      aprovacao_job_id: body.job_id || "",
      ultimo_status: body.status || ""
    });

    notificarEventoLote_(
      body.lote_id || validacao.lote_id || "",
      dryRun ? "aprovacao_iniciada_dry_run" : "aprovacao_iniciada_envio_real",
      "[Madan ETL] Lote aprovado \u2014 iniciando envio",
      montarHtmlNotificacaoAprovacao_(body.lote_id || validacao.lote_id || "", aprovador, dryRun)
    );

    var resultado = aguardarResultadoEnvio_(body.lote_id || validacao.lote_id, body.job_id || "");
    salvarEstadoLocal_({
      ultimo_status: resultado.status || ""
    });
    reportarResultados_(resultado, {
      dry_run: dryRun,
      aprovador: aprovador.aprovado_por
    });

    mostrarDialogoTexto_(
      dryRun ? "Resultado da Simulacao" : "Resultado do Envio",
      montarTextoResultadoEnvio_(resultado)
    );
  });
}

function executarFluxoAppsScript_(dryRun) {
  executarAcaoComTratamento_(function() {
    garantirBackendDisponivel_(dryRun ? "simular via Apps Script" : "aprovar e enviar via Apps Script");
    garantirTokenIScholar_();

    var estado = carregarEstadoLocal_();
    if (!estado.lote_id) {
      throw new Error("Nenhum lote validado localmente. Rode 'Validar Lote' antes de aprovar.");
    }

    var validacao = consultarValidacaoAtual_(estado.lote_id, false);
    if (!validacao) {
      throw new Error("Nao foi possivel localizar a validacao atual do lote.");
    }
    var statusValidacao = String(validacao.status || "");
    var podeRecuperarEnvioAnterior = (
      validacao.apto_para_aprovacao &&
      ["send_failed", "dry_run_completed", "aguardando_execucao_externa"].indexOf(statusValidacao) >= 0
    );
    if (!validacao.pode_aprovar && !podeRecuperarEnvioAnterior) {
      throw new Error(validacao.mensagem || "O lote nao esta apto para aprovacao.");
    }

    var aprovador = solicitarIdentidadeAprovador_(dryRun);
    if (!aprovador) {
      return;
    }

    confirmarAcao_(
      dryRun ? "Simular via Apps Script?" : "Aprovar e enviar via Apps Script?",
      [
        "Lote: " + validacao.lote_id,
        "Snapshot: " + validacao.snapshot_hash,
        "Aprovador: " + aprovador.aprovado_por,
        "Modo: " + (dryRun ? "simulacao via Apps Script" : "envio real via Apps Script"),
        "",
        "A VPS continuara validando e auditando. Apenas a chamada final ao iScholar sairá pelo Apps Script."
      ].join("\n")
    );

    var aprovacao = chamarApi_(
      "post",
      "/lote/" + encodeURIComponent(validacao.lote_id) + "/aprovar",
      {
        snapshot_hash: validacao.snapshot_hash,
        aprovador: aprovador.aprovado_por,
        aprovador_nome_informado: aprovador.aprovador_nome_informado,
        aprovador_email: aprovador.aprovador_email,
        aprovador_origem: aprovador.aprovador_origem,
        dry_run: dryRun,
        modo_execucao: "apps_script"
      }
    );
    if (aprovacao.statusCode !== 202) {
      throw new Error(extrairMensagemErro_(aprovacao));
    }
    notificarEventoLote_(
      validacao.lote_id || "",
      dryRun ? "aprovacao_apps_script_iniciada_dry_run" : "aprovacao_apps_script_iniciada_envio_real",
      "[Madan ETL] Lote aprovado \u2014 iniciando envio",
      montarHtmlNotificacaoAprovacao_(validacao.lote_id || "", aprovador, dryRun)
    );

    var pacote = obterPacoteExecucao_(validacao.lote_id, dryRun);
    var mapaMatriculas = resolverMatriculasPorTurma_(pacote.turma.id_turma);
    var resultados = executarLancamentosIScholar_(pacote, mapaMatriculas, dryRun);
    var registro = reportarResultadoExecucao_(pacote, resultados, aprovador, dryRun);
    var resultadoFinal = consultarResultadoEnvioAtual_(pacote.lote_id, false) || (registro.send_result || registro);

    salvarEstadoLocal_({
      lote_id: pacote.lote_id,
      snapshot_hash: pacote.snapshot_hash,
      aprovacao_job_id: "",
      ultimo_status: resultadoFinal.status || ""
    });
    reportarResultados_(resultadoFinal, {
      dry_run: dryRun,
      aprovador: aprovador.aprovado_por
    });

    mostrarDialogoTexto_(
      dryRun ? "Resultado da Simulacao via Apps Script" : "Resultado do Envio via Apps Script",
      montarTextoResultadoEnvio_(resultadoFinal)
    );
  });
}

function executarAcaoComTratamento_(fn) {
  try {
    fn();
  } catch (err) {
    SpreadsheetApp.getUi().alert("Falha", mensagemErroHumana_(err), SpreadsheetApp.getUi().ButtonSet.OK);
  }
}

function obterAbaAtiva_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var aba = ss.getActiveSheet();
  if (!aba) {
    throw new Error(
      "Nao foi possivel determinar a aba ativa. " +
      "Clique em uma aba da planilha antes de usar o menu iScholar ETL."
    );
  }
  return aba;
}

/**
 * Interpreta o nome da aba como aba trimestral Plano B.
 * Retorna { turma, trimestre } se o nome seguir o padrao, null caso contrario.
 * Ex: "2A_T1" -> { turma: "2A", trimestre: "T1" }
 */
function _interpretarNomeAba_(nomeAba) {
  var m = REGEX_ABA_PLANO_B.exec((nomeAba || "").trim());
  if (!m) { return null; }
  return { turma: m[1].toUpperCase(), trimestre: m[2].toUpperCase() };
}

/**
 * Exibe dialogo de confirmacao mostrando qual aba sera processada.
 * Para abas Plano B exibe turma e trimestre explicitamente.
 * O operador pode cancelar se estiver na aba errada.
 */
function confirmarProcessamentoAba_(aba) {
  var nomeAba = aba.getName();
  var info = _interpretarNomeAba_(nomeAba);
  var linhas;
  if (info) {
    linhas = [
      "Aba:       " + nomeAba,
      "Turma:     " + info.turma,
      "Trimestre: " + info.trimestre,
      "",
      "Prosseguir com esta aba?"
    ];
  } else {
    linhas = [
      "Aba: " + nomeAba,
      "",
      "Esta aba nao segue o padrao Plano B (ex: 2A_T1).",
      "Verifique se voce esta na aba correta.",
      "",
      "Prosseguir mesmo assim?"
    ];
  }
  confirmarAcao_("Confirmar aba a processar", linhas.join("\n"));
}

function montarPayloadValidacao_(aba) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  return {
    spreadsheet_id: ss.getId(),
    sheet_name: aba.getName(),
    lote_id: construirLoteId_(ss, aba),
    dados: lerDadosDaAba_(aba)
  };
}

function construirLoteId_(ss, aba) {
  return ss.getId() + "/" + aba.getName();
}

function lerDadosDaAba_(aba) {
  var valores = aba.getDataRange().getDisplayValues();
  if (valores.length < 2) {
    throw new Error("A aba nao possui linhas de dados para validar.");
  }

  var cabecalho = valores[0].map(function(cell) {
    return (cell || "").toString().trim();
  });

  if (cabecalho.every(function(col) { return !col; })) {
    throw new Error("A primeira linha da aba precisa conter o cabecalho da planilha.");
  }

  var registros = [];
  for (var i = 1; i < valores.length; i++) {
    var linha = valores[i];
    if (linha.every(function(c) { return c === "" || c === null || c === undefined; })) {
      continue;
    }

    var obj = {};
    for (var j = 0; j < cabecalho.length; j++) {
      if (!cabecalho[j]) {
        continue;
      }
      var valor = linha[j];
      obj[cabecalho[j]] = valor === "" ? null : valor;
    }
    registros.push(obj);
  }

  if (!registros.length) {
    throw new Error("Nenhuma linha preenchida foi encontrada na aba.");
  }
  return registros;
}

function chamarApi_(method, path, body) {
  var url = API_BASE_URL.replace(/\/$/, "") + path;
  Logger.log("[chamarApi_] " + String(method || "get").toUpperCase() + " " + path);
  var headers = {
    "X-Webhook-Secret": WEBHOOK_SECRET,
    "X-Webhook-Timestamp": String(Math.floor(Date.now() / 1000)),
    "X-Webhook-Nonce": Utilities.getUuid(),
    "ngrok-skip-browser-warning": "true"
  };

  var opcoes = {
    method: method,
    contentType: "application/json",
    headers: headers,
    muteHttpExceptions: true
  };

  if (body !== undefined && body !== null) {
    opcoes.payload = JSON.stringify(body);
  }

  var resposta;
  try {
    resposta = UrlFetchApp.fetch(url, opcoes);
  } catch (err) {
    throw new Error("Nao foi possivel conectar ao backend. Verifique a URL, o segredo e se o servidor esta no ar.");
  }

  var texto = resposta.getContentText() || "";
  var json = null;
  try {
    json = texto ? JSON.parse(texto) : null;
  } catch (err2) {
    json = null;
  }

  Logger.log(
    "[chamarApi_] status=" + resposta.getResponseCode() +
    " | path=" + path
  );

  return {
    statusCode: resposta.getResponseCode(),
    text: texto,
    json: json
  };
}

function obterPacoteExecucao_(loteId, dryRun) {
  var path = "/lote/" + encodeURIComponent(loteId) + "/pacote-execucao?dry_run=" + (dryRun ? "true" : "false");
  var resposta = chamarApi_("get", path);
  if (resposta.statusCode !== 200) {
    throw new Error(extrairMensagemErro_(resposta));
  }
  var pacote = resposta.json || {};
  if (!pacote.turma || !pacote.turma.id_turma) {
    throw new Error("Pacote de execucao sem id_turma. Preencha mapa_turmas.json na VPS.");
  }
  return pacote;
}

function chamarIScholar_(method, path, body, queryParams) {
  var token = garantirTokenIScholar_();
  var url = ISCHOLAR_API_BASE_URL.replace(/\/$/, "") + path;
  var query = montarQueryString_(queryParams || {});
  if (query) {
    url += "?" + query;
  }

  var opcoes = {
    method: method,
    contentType: "application/json",
    headers: {
      "X-Codigo-Escola": ISCHOLAR_CODIGO_ESCOLA,
      "X-Autorizacao": token,
      "Accept": "application/json"
    },
    muteHttpExceptions: true
  };
  if (body !== undefined && body !== null) {
    opcoes.payload = JSON.stringify(body);
  }

  var resposta = UrlFetchApp.fetch(url, opcoes);
  var texto = resposta.getContentText() || "";
  var json = null;
  try {
    json = texto ? JSON.parse(texto) : null;
  } catch (err) {
    json = null;
  }
  return {
    statusCode: resposta.getResponseCode(),
    text: texto,
    json: json
  };
}

function garantirTokenIScholar_() {
  var token = PropertiesService.getScriptProperties().getProperty(PROP_ISCHOLAR_TOKEN);
  token = (token || "").toString().trim();
  if (!token) {
    throw new Error("ISCHOLAR_TOKEN ausente em Script Properties. Configure antes de usar o modo Apps Script.");
  }
  return token;
}

function montarQueryString_(params) {
  var partes = [];
  Object.keys(params || {}).forEach(function(chave) {
    var valor = params[chave];
    if (valor === undefined || valor === null || valor === "") {
      return;
    }
    partes.push(encodeURIComponent(chave) + "=" + encodeURIComponent(String(valor)));
  });
  return partes.join("&");
}

function resolverMatriculasPorTurma_(idTurma) {
  var mapa = {};
  for (var pagina = 1; pagina <= ISCHOLAR_MAX_PAGINAS_ALUNOS; pagina++) {
    var resposta = chamarIScholar_("get", "/matricula/listar", null, {
      id_turma: idTurma,
      pagina: pagina
    });
    if (resposta.statusCode < 200 || resposta.statusCode >= 300) {
      throw new Error("Falha ao listar alunos da turma no iScholar: HTTP " + resposta.statusCode + ".");
    }

    var alunos = extrairListaAlunos_(resposta.json || {});
    if (!alunos.length) {
      break;
    }
    alunos.forEach(function(aluno) {
      var ra = extrairRaAluno_(aluno);
      var idMatricula = extrairIdMatricula_(aluno);
      if (ra && idMatricula) {
        mapa[String(ra).trim()] = idMatricula;
      }
    });

    var body = resposta.json || {};
    if (body.tem_mais === false || body.tem_mais === undefined) {
      break;
    }
  }
  return mapa;
}

function extrairListaAlunos_(body) {
  if (Array.isArray(body)) return body;
  if (Array.isArray(body.dados)) return body.dados;
  if (body.dados && Array.isArray(body.dados.alunos)) return body.dados.alunos;
  if (body.dados && Array.isArray(body.dados.matriculas)) return body.dados.matriculas;
  if (Array.isArray(body.alunos)) return body.alunos;
  if (Array.isArray(body.matriculas)) return body.matriculas;
  return [];
}

function extrairRaAluno_(aluno) {
  var candidatos = [
    aluno.ra,
    aluno.numero_re,
    aluno.re,
    aluno.codigo_aluno,
    aluno.aluno && aluno.aluno.ra,
    aluno.aluno && aluno.aluno.numero_re
  ];
  for (var i = 0; i < candidatos.length; i++) {
    if (candidatos[i] !== undefined && candidatos[i] !== null && String(candidatos[i]).trim()) {
      return String(candidatos[i]).trim();
    }
  }
  return null;
}

function extrairIdMatricula_(aluno) {
  var candidatos = [
    aluno.id_matricula,
    aluno.id_matricula_aluno,
    aluno.matricula_id,
    aluno.matricula && aluno.matricula.id_matricula,
    aluno.matricula && aluno.matricula.id_matricula_aluno,
    aluno.matricula && aluno.matricula.matricula_id
  ];
  for (var i = 0; i < candidatos.length; i++) {
    if (candidatos[i] !== undefined && candidatos[i] !== null && String(candidatos[i]).trim()) {
      return Number(candidatos[i]);
    }
  }
  return null;
}

function executarLancamentosIScholar_(pacote, mapaMatriculas, dryRun) {
  var inicio = Date.now();
  var resultados = [];
  var pendentes = [];
  var lancamentos = pacote.lancamentos || [];
  (pacote.itens_com_erro_local || []).forEach(function(item) {
    resultados.push(resultadoErroResolucao_(item, (item.erros || []).join("; ") || "Item com erro local no pacote de execucao."));
  });

  lancamentos.forEach(function(item) {
    var idMatricula = mapaMatriculas[String(item.ra || "").trim()];
    if (!idMatricula) {
      resultados.push(resultadoErroResolucao_(item, "RA nao encontrado via pega_alunos."));
      return;
    }
    if (dryRun) {
      resultados.push(resultadoDryRun_(item, idMatricula));
      return;
    }
    pendentes.push({ item: item, id_matricula: idMatricula });
  });

  for (var i = 0; i < pendentes.length; i += ISCHOLAR_TAMANHO_LOTE_POST) {
    if ((Date.now() - inicio) > ISCHOLAR_TEMPO_MAX_MS) {
      for (var restante = i; restante < pendentes.length; restante++) {
        resultados.push(resultadoErroEnvio_(pendentes[restante].item, pendentes[restante].id_matricula, 0, "Tempo limite do Apps Script atingido.", true, null));
      }
      break;
    }

    var lote = pendentes.slice(i, i + ISCHOLAR_TAMANHO_LOTE_POST);
    var requests = lote.map(function(entry) {
      return montarRequestLancamento_(entry.item, entry.id_matricula);
    });

    var responses;
    try {
      responses = UrlFetchApp.fetchAll(requests);
    } catch (err) {
      lote.forEach(function(entry) {
        resultados.push(resultadoErroEnvio_(entry.item, entry.id_matricula, 0, "Falha em fetchAll: " + err.message, true, null));
      });
      continue;
    }

    for (var r = 0; r < responses.length; r++) {
      var resposta = responses[r];
      var entry = lote[r];
      var statusCode = resposta.getResponseCode();
      var texto = resposta.getContentText() || "";
      var sucesso = statusCode >= 200 && statusCode < 300;
      if (sucesso) {
        resultados.push(resultadoEnviado_(entry.item, entry.id_matricula, statusCode, texto));
      } else {
        resultados.push(resultadoErroEnvio_(entry.item, entry.id_matricula, statusCode, texto, statusCode === 429 || statusCode >= 500, texto));
      }
    }
  }
  return resultados;
}

function montarRequestLancamento_(item, idMatricula) {
  var token = garantirTokenIScholar_();
  var payload = montarPayloadLancamentoIScholar_(item, idMatricula);
  return {
    url: ISCHOLAR_API_BASE_URL.replace(/\/$/, "") + "/notas/lanca_nota",
    method: "post",
    contentType: "application/json",
    headers: {
      "X-Codigo-Escola": ISCHOLAR_CODIGO_ESCOLA,
      "X-Autorizacao": token,
      "Accept": "application/json"
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };
}

function montarPayloadLancamentoIScholar_(item, idMatricula) {
  return {
    id_matricula: idMatricula,
    id_disciplina: item.id_disciplina,
    id_avaliacao: item.id_avaliacao,
    id_professor: item.id_professor,
    valor: item.valor
  };
}

function reportarResultadoExecucao_(pacote, resultados, aprovador, dryRun) {
  var resposta = chamarApi_(
    "post",
    "/lote/" + encodeURIComponent(pacote.lote_id) + "/resultado-execucao",
    {
      snapshot_hash: pacote.snapshot_hash,
      dry_run: dryRun,
      aprovador: aprovador.aprovado_por,
      aprovador_nome_informado: aprovador.aprovador_nome_informado,
      aprovador_email: aprovador.aprovador_email,
      aprovador_origem: aprovador.aprovador_origem,
      resultados: resultados
    }
  );
  if (resposta.statusCode !== 200) {
    throw new Error(extrairMensagemErro_(resposta));
  }
  return resposta.json || {};
}

function notificar_(assunto, corpoHtml) {
  Logger.log("[notificar_] preparando envio | assunto=" + (assunto || "(sem assunto)"));

  if (!HABILITAR_NOTIFICACOES) {
    Logger.log("[notificar_] notificacoes desabilitadas por HABILITAR_NOTIFICACOES=false.");
    return false;
  }

  var destinatario = String(EMAIL_NOTIFICACOES || "").trim();
  if (!destinatario) {
    Logger.log("[notificar_] EMAIL_NOTIFICACOES vazio. Notificacao ignorada.");
    return false;
  }

  var assuntoFinal = String(assunto || "[Madan ETL] Notificacao");
  var htmlBody = String(corpoHtml || "<p>Sem conteudo.</p>");
  var opcoes = {
    htmlBody: htmlBody
  };
  var bcc = String(EMAIL_BCC || "").trim();
  if (bcc) {
    opcoes.bcc = bcc;
  }

  try {
    GmailApp.sendEmail(destinatario, assuntoFinal, htmlParaTexto_(htmlBody), opcoes);
    Logger.log(
      "[notificar_] email enviado | para=" + destinatario +
      " | bcc=" + (bcc || "-") +
      " | assunto=" + assuntoFinal
    );
    return true;
  } catch (err) {
    Logger.log("[notificar_] falha no envio de email: " + mensagemErroHumana_(err));
    return false;
  }
}

function notificarEventoLote_(loteId, evento, assunto, corpoHtml) {
  var loteSeguro = String(loteId || "sem_lote").trim() || "sem_lote";
  var eventoSeguro = String(evento || "evento").trim() || "evento";
  var chave = PROP_NOTIFICACAO_PREFIX + ":" + encodeURIComponent(loteSeguro) + ":" + encodeURIComponent(eventoSeguro);
  var props = PropertiesService.getScriptProperties();

  try {
    var jaNotificado = props.getProperty(chave);
    if (jaNotificado) {
      Logger.log("[notificarEventoLote_] dedupe ativo. Ignorando envio repetido | chave=" + chave);
      return;
    }
  } catch (errDedupeLeitura) {
    Logger.log("[notificarEventoLote_] falha ao ler dedupe: " + mensagemErroHumana_(errDedupeLeitura));
  }

  var enviado = notificar_(assunto, corpoHtml);
  if (!enviado) {
    Logger.log("[notificarEventoLote_] email nao enviado (toggle/erro). chave=" + chave);
    return;
  }

  try {
    props.setProperty(chave, new Date().toISOString());
    Logger.log("[notificarEventoLote_] dedupe registrado com sucesso | chave=" + chave);
  } catch (errDedupeGravacao) {
    Logger.log("[notificarEventoLote_] falha ao gravar dedupe: " + mensagemErroHumana_(errDedupeGravacao));
  }
}

function reportarResultados_(resultado, contexto) {
  try {
    var dados = resultado || {};
    var ctx = contexto || {};
    var dryRun = !!ctx.dry_run;
    var loteId = String(dados.lote_id || ctx.lote_id || "").trim();
    var total = valorOuZero_(dados.total_sendaveis);
    var enviados = valorOuZero_(dados.quantidade_enviada);
    var errosHttp = extrairErrosHttpEnvio_(dados);

    var assuntoBase = "[Madan ETL] Envio conclu\u00eddo \u2014 " + enviados + "/" + total;
    var assunto = errosHttp.length ? ("\u26A0\uFE0F " + assuntoBase) : assuntoBase;
    var corpo = montarHtmlNotificacaoEnvio_(dados, ctx, errosHttp);

    notificarEventoLote_(
      loteId || "sem_lote",
      dryRun ? "envio_concluido_dry_run" : "envio_concluido_envio_real",
      assunto,
      corpo
    );
  } catch (err) {
    Logger.log("[reportarResultados_] falha ao montar/enviar notificacao: " + mensagemErroHumana_(err));
  }
}

function montarHtmlNotificacaoValidacao_(validacao, aba) {
  var dados = validacao || {};
  var resumo = dados.resumo || {};
  var linkAba = montarLinkAba_(aba);
  var tabela = montarTabelaHtmlNotificacao_([
    ["Linhas", valorOuZero_(resumo.total_linhas)],
    ["Sendaveis", valorOuZero_(resumo.total_sendaveis)],
    ["Avisos", valorOuZero_(resumo.total_avisos)],
    ["Erros", valorOuZero_(resumo.total_erros)]
  ]);

  return [
    '<div style="font-family:Arial,sans-serif;font-size:13px;color:#202124;">',
    "<p>Validacao concluida para o lote <b>" + escaparHtml_(dados.lote_id || "-") + "</b>.</p>",
    tabela,
    (linkAba
      ? '<p><a href="' + escaparHtmlAtributo_(linkAba) + '">Abrir aba da planilha</a></p>'
      : ""),
    "</div>"
  ].join("");
}

function montarHtmlNotificacaoAprovacao_(loteId, aprovador, dryRun) {
  var nomeAprovador = (aprovador && aprovador.aprovado_por) ? aprovador.aprovado_por : "-";
  var tabela = montarTabelaHtmlNotificacao_([
    ["Lote", loteId || "-"],
    ["Aprovador", nomeAprovador],
    ["Dry run", boolSimNao_(dryRun)]
  ]);
  return [
    '<div style="font-family:Arial,sans-serif;font-size:13px;color:#202124;">',
    "<p>O lote foi aprovado e o envio foi iniciado.</p>",
    tabela,
    "</div>"
  ].join("");
}

function montarHtmlNotificacaoEnvio_(resultado, contexto, errosHttp) {
  var dados = resultado || {};
  var ctx = contexto || {};
  var total = valorOuZero_(dados.total_sendaveis);
  var enviados = valorOuZero_(dados.quantidade_enviada);
  var linkAudit = montarLinkAuditResultado_(dados.lote_id || ctx.lote_id || "");
  var tabela = montarTabelaHtmlNotificacao_([
    ["Lote", dados.lote_id || ctx.lote_id || "-"],
    ["Status", dados.status || "-"],
    ["Enviados", enviados],
    ["Total", total],
    ["Com erro", valorOuZero_(dados.quantidade_com_erro)],
    ["Erros de envio", valorOuZero_(dados.total_erros_envio)]
  ]);

  var blocoErros = "";
  if (errosHttp && errosHttp.length) {
    var top5 = errosHttp.slice(0, 5);
    var itens = top5.map(function(item) {
      return "<li>" + escaparHtml_(item) + "</li>";
    }).join("");
    blocoErros =
      "<p><b>Primeiros erros HTTP (4xx/5xx):</b></p>" +
      "<ol>" + itens + "</ol>";
  }

  return [
    '<div style="font-family:Arial,sans-serif;font-size:13px;color:#202124;">',
    "<p>Processamento de envio concluido.</p>",
    tabela,
    blocoErros,
    (linkAudit
      ? '<p><a href="' + escaparHtmlAtributo_(linkAudit) + '">Abrir audit do lote</a></p>'
      : ""),
    "</div>"
  ].join("");
}

function montarTabelaHtmlNotificacao_(linhas) {
  var rows = (linhas || []).map(function(linha) {
    return (
      '<tr>' +
      '<td style="border:1px solid #dadce0;padding:6px 8px;background:#f8f9fa;"><b>' + escaparHtml_(linha[0]) + "</b></td>" +
      '<td style="border:1px solid #dadce0;padding:6px 8px;">' + escaparHtml_(String(linha[1])) + "</td>" +
      "</tr>"
    );
  }).join("");

  return (
    '<table style="border-collapse:collapse;margin:8px 0 12px 0;">' +
    rows +
    "</table>"
  );
}

function montarLinkAba_(aba) {
  if (!aba) {
    return "";
  }
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    return ss.getUrl() + "#gid=" + aba.getSheetId();
  } catch (err) {
    Logger.log("[montarLinkAba_] nao foi possivel montar link da aba: " + mensagemErroHumana_(err));
    return "";
  }
}

function montarLinkAuditResultado_(loteId) {
  var lote = String(loteId || "").trim();
  if (!lote) {
    return "";
  }
  return API_BASE_URL.replace(/\/$/, "") + "/lote/" + encodeURIComponent(lote) + "/resultado-envio";
}

function extrairErrosHttpEnvio_(resultado) {
  var erros = [];
  var dados = resultado || {};
  var resumo = dados.resumo || {};
  var itens = [];

  if (Array.isArray(resumo.itens)) {
    itens = resumo.itens;
  } else if (Array.isArray(dados.itens)) {
    itens = dados.itens;
  }

  for (var i = 0; i < itens.length; i++) {
    var item = itens[i] || {};
    var statusCode = extrairCodigoHttp_(item.status_code);
    if (!(statusCode >= 400 && statusCode < 600)) {
      statusCode = extrairCodigoHttp_(item.mensagem);
    }
    if (!(statusCode >= 400 && statusCode < 600)) {
      statusCode = extrairCodigoHttp_(item.resposta_api);
    }
    if (statusCode >= 400 && statusCode < 600) {
      erros.push(formatarLinhaErroEnvio_(item, statusCode));
    }
  }

  var colecoesErros = [];
  if (Array.isArray(resumo.erros)) colecoesErros.push(resumo.erros);
  if (Array.isArray(dados.erros)) colecoesErros.push(dados.erros);
  for (var c = 0; c < colecoesErros.length; c++) {
    var colecao = colecoesErros[c];
    for (var j = 0; j < colecao.length; j++) {
      var itemErro = colecao[j] || {};
      var statusErro = extrairCodigoHttp_(itemErro.status_code);
      if (!(statusErro >= 400 && statusErro < 600)) {
        statusErro = extrairCodigoHttp_(itemErro.mensagem || itemErro.erro || itemErro.descricao);
      }
      if (statusErro >= 400 && statusErro < 600) {
        erros.push(formatarLinhaErroEnvio_(itemErro, statusErro));
      }
    }
  }

  if (!erros.length) {
    var statusTopo = extrairCodigoHttp_(dados.mensagem);
    if (statusTopo >= 400 && statusTopo < 600) {
      erros.push("HTTP " + statusTopo + " - " + limitarTexto_(String(dados.mensagem || ""), 220));
    }
  }

  if (!erros.length && (valorOuZero_(dados.total_erros_envio) > 0 || valorOuZero_(dados.quantidade_com_erro) > 0)) {
    var statusResumo = extrairCodigoHttp_(resumo);
    if (statusResumo >= 400 && statusResumo < 600) {
      erros.push("HTTP " + statusResumo + " - Erro detectado no resumo do envio.");
    }
  }

  if (erros.length > 1) {
    var vistos = {};
    erros = erros.filter(function(erroTxt) {
      if (vistos[erroTxt]) return false;
      vistos[erroTxt] = true;
      return true;
    });
  }

  Logger.log("[extrairErrosHttpEnvio_] erros_http_detectados=" + erros.length);
  return erros;
}

function extrairCodigoHttp_(valor) {
  if (valor === null || valor === undefined) {
    return null;
  }

  var numero = Number(valor);
  if (!isNaN(numero) && numero >= 400 && numero < 600) {
    return Math.floor(numero);
  }

  if (typeof valor === "object") {
    if (valor.status_code !== undefined && valor.status_code !== null) {
      var sc = extrairCodigoHttp_(valor.status_code);
      if (sc) return sc;
    }
    try {
      valor = JSON.stringify(valor);
    } catch (errJson) {
      valor = String(valor);
    }
  }

  var texto = String(valor || "");
  var match = texto.match(/\b(?:HTTP\D*)?([45][0-9]{2})\b/i);
  if (match && match[1]) {
    return Number(match[1]);
  }
  return null;
}

function formatarLinhaErroEnvio_(item, statusCode) {
  var partes = [];
  if (item.estudante) partes.push(item.estudante);
  if (item.ra) partes.push("RA " + item.ra);
  if (item.componente) partes.push(item.componente);
  if (item.disciplina && !item.componente) partes.push(item.disciplina);
  if (!partes.length && item.item_key) partes.push("item_key " + item.item_key);

  var mensagem = item.mensagem || item.erro || item.resposta_api || "";
  if (typeof mensagem === "object") {
    try {
      mensagem = JSON.stringify(mensagem);
    } catch (errJson) {
      mensagem = String(mensagem);
    }
  }
  mensagem = limitarTexto_(String(mensagem || ""), 220);

  return "HTTP " + statusCode + " - " + (partes.join(" | ") || "item sem contexto") + (mensagem ? (" -> " + mensagem) : "");
}

function limitarTexto_(texto, limite) {
  var t = String(texto || "");
  if (t.length <= limite) {
    return t;
  }
  return t.substring(0, limite - 3) + "...";
}

function htmlParaTexto_(html) {
  var texto = String(html || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<\/tr>/gi, "\n")
    .replace(/<li>/gi, "- ")
    .replace(/<\/li>/gi, "\n")
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, "\"")
    .replace(/&#39;/gi, "'");

  texto = texto.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  return texto || "Notificacao Madan ETL.";
}

function boolSimNao_(flag) {
  return flag ? "sim" : "nao";
}

function resultadoBase_(item, idMatricula) {
  return {
    item_key: item.item_key,
    estudante: item.estudante,
    ra: item.ra,
    componente: item.componente,
    disciplina: item.disciplina,
    trimestre: item.trimestre,
    valor: item.valor,
    id_matricula: idMatricula || null,
    id_disciplina: item.id_disciplina,
    id_avaliacao: item.id_avaliacao,
    id_professor: item.id_professor,
    rastreabilidade: item.rastreabilidade || {}
  };
}

function resultadoDryRun_(item, idMatricula) {
  var res = resultadoBase_(item, idMatricula);
  res.status = "dry_run";
  res.mensagem = "Dry run: payload montado no Apps Script, sem POST no iScholar.";
  res.payload_enviado = montarPayloadLancamentoIScholar_(item, idMatricula);
  return res;
}

function resultadoEnviado_(item, idMatricula, statusCode, texto) {
  var res = resultadoBase_(item, idMatricula);
  res.status = "enviado";
  res.status_code = statusCode;
  res.mensagem = "Nota enviada ao iScholar.";
  res.resposta_api = texto;
  res.payload_enviado = montarPayloadLancamentoIScholar_(item, idMatricula);
  return res;
}

function resultadoErroResolucao_(item, mensagem) {
  var res = resultadoBase_(item, null);
  res.status = "erro_resolucao";
  res.mensagem = mensagem;
  res.erros_resolucao = [mensagem];
  return res;
}

function resultadoErroEnvio_(item, idMatricula, statusCode, mensagem, transitorio, respostaApi) {
  var res = resultadoBase_(item, idMatricula);
  res.status = "erro_envio";
  res.status_code = statusCode;
  res.mensagem = mensagem;
  res.transitorio = !!transitorio;
  res.resposta_api = respostaApi;
  res.payload_enviado = montarPayloadLancamentoIScholar_(item, idMatricula);
  return res;
}

function utilListarTurmas_() {
  executarAcaoComTratamento_(function() {
    var resposta = chamarIScholar_("get", "/turma/lista", null, null);
    mostrarDialogoTexto_("Turmas iScholar", "HTTP " + resposta.statusCode + "\n\n" + JSON.stringify(resposta.json || resposta.text, null, 2));
  });
}

function utilListarTurmas() {
  utilListarTurmas_();
}

function garantirBackendDisponivel_(acao) {
  var resposta;
  try {
    resposta = chamarApi_("get", "/health");
  } catch (err) {
    throw new Error("Nao foi possivel contatar o backend para " + acao + ". Verifique se o servidor esta no ar e tente novamente.");
  }
  if (resposta.statusCode !== 200) {
    throw new Error("O backend nao respondeu ao health check. Nao foi possivel " + acao + ".");
  }
  var body = resposta.json || {};
  if ((body.status || "").toString().toLowerCase() !== "online") {
    throw new Error("O backend respondeu ao health check, mas nao esta operacional no momento.");
  }
}

function aguardarValidacao_(loteId, jobId) {
  var ultimo = null;
  for (var tentativa = 0; tentativa < POLL_TENTATIVAS_VALIDACAO; tentativa++) {
    ultimo = consultarValidacaoAtual_(loteId, true);
    if (ultimo && ultimo.finalizado) {
      return ultimo;
    }
    Utilities.sleep(POLL_INTERVAL_MS);
  }

  if (ultimo) {
    var job = jobId ? consultarJobAtual_(jobId, true) : null;
    throw new Error(
      "A validacao ainda nao terminou. O job foi criado, mas o worker pode estar ocupado.\n\n" +
      (job && job.mensagem ? "Status atual do job: " + job.mensagem + "\n\n" : "") +
      "Use o menu 'Mostrar Ultimo Status' em alguns instantes."
    );
  }

  throw new Error("Nao foi possivel obter o resultado da validacao no tempo esperado.");
}

function aguardarResultadoEnvio_(loteId, jobId) {
  var ultimo = null;
  for (var tentativa = 0; tentativa < POLL_TENTATIVAS_ENVIO; tentativa++) {
    ultimo = consultarResultadoEnvioAtual_(loteId, true);
    if (ultimo && ultimo.finalizado) {
      return ultimo;
    }
    Utilities.sleep(POLL_INTERVAL_MS);
  }

  if (ultimo) {
    var job = jobId ? consultarJobAtual_(jobId, true) : null;
    throw new Error(
      "O envio ainda nao terminou. A solicitacao foi aceita e segue em background.\n\n" +
      (job && job.mensagem ? "Status atual do job: " + job.mensagem + "\n\n" : "") +
      "Use o menu 'Mostrar Ultimo Status' para consultar novamente."
    );
  }

  if (jobId) {
    var jobFallback = consultarJobAtual_(jobId, true);
    if (jobFallback) {
      throw new Error(
        "O envio ainda nao publicou um resultado consolidado.\n\n" +
        "Status atual do job: " + (jobFallback.mensagem || jobFallback.status || "desconhecido") + "\n\n" +
        "Use o menu 'Mostrar Ultimo Status' para consultar novamente."
      );
    }
  }

  throw new Error("Nao foi possivel obter o resultado do envio no tempo esperado.");
}

function consultarValidacaoAtual_(loteId, aceitarNaoEncontrado) {
  var resposta = chamarApi_("get", "/lote/" + encodeURIComponent(loteId) + "/validacao");
  if (resposta.statusCode === 404 && aceitarNaoEncontrado) {
    return null;
  }
  if (resposta.statusCode !== 200) {
    throw new Error(extrairMensagemErro_(resposta));
  }
  return resposta.json || {};
}

function consultarResultadoEnvioAtual_(loteId, aceitarNaoEncontrado) {
  var resposta = chamarApi_("get", "/lote/" + encodeURIComponent(loteId) + "/resultado-envio");
  if (resposta.statusCode === 404 && aceitarNaoEncontrado) {
    return null;
  }
  if (resposta.statusCode !== 200) {
    throw new Error(extrairMensagemErro_(resposta));
  }
  return resposta.json || {};
}

function consultarJobAtual_(jobId, aceitarNaoEncontrado) {
  var resposta = chamarApi_("get", "/job/" + encodeURIComponent(jobId) + "/status");
  if (resposta.statusCode === 404 && aceitarNaoEncontrado) {
    return null;
  }
  if (resposta.statusCode !== 200) {
    throw new Error(extrairMensagemErro_(resposta));
  }
  return resposta.json || {};
}

function solicitarIdentidadeAprovador_(dryRun) {
  var emailSessao = Session.getActiveUser().getEmail() || "";
  var prompt = SpreadsheetApp.getUi().prompt(
    dryRun ? "Simular lote" : "Aprovar lote",
    "Informe o nome ou identificador do aprovador:" + (emailSessao ? "\nEmail da sessao detectado: " + emailSessao : ""),
    SpreadsheetApp.getUi().ButtonSet.OK_CANCEL
  );

  if (prompt.getSelectedButton() !== SpreadsheetApp.getUi().Button.OK) {
    return null;
  }

  var valor = (prompt.getResponseText() || "").toString().trim();
  if (!valor && emailSessao) {
    valor = emailSessao;
  }
  if (!valor) {
    throw new Error("O aprovador e obrigatorio para continuar.");
  }
  var emailInformado = (!emailSessao && /@/.test(valor)) ? valor : null;
  return {
    aprovado_por: valor,
    aprovador_nome_informado: valor,
    aprovador_email: emailSessao || emailInformado || null,
    aprovador_origem: emailSessao ? "google_apps_script_session" : (emailInformado ? "google_apps_script_manual_email" : "google_apps_script_manual")
  };
}

function confirmarAcao_(titulo, mensagem) {
  var resposta = SpreadsheetApp.getUi().alert(titulo, mensagem, SpreadsheetApp.getUi().ButtonSet.OK_CANCEL);
  if (resposta !== SpreadsheetApp.getUi().Button.OK) {
    throw new Error("Operacao cancelada pelo operador.");
  }
}

function montarTextoValidacao_(validacao) {
  var resumo = validacao.resumo || {};
  var linhas = [
    validacao.mensagem || "Resultado de validacao disponivel.",
    "",
    "Lote: " + (validacao.lote_id || "-"),
    "Snapshot: " + (validacao.snapshot_hash || "-"),
    "Status: " + (validacao.status || "-"),
    "Apto para aprovacao: " + (validacao.apto_para_aprovacao ? "sim" : "nao")
  ];

  if (Object.keys(resumo).length) {
    linhas.push("");
    linhas.push("Resumo:");
    linhas.push("- Linhas: " + valorOuZero_(resumo.total_linhas));
    linhas.push("- Lancamentos: " + valorOuZero_(resumo.total_lancamentos));
    linhas.push("- Sendaveis: " + valorOuZero_(resumo.total_sendaveis));
    linhas.push("- Bloqueados: " + valorOuZero_(resumo.total_bloqueados));
    linhas.push("- Avisos: " + valorOuZero_(resumo.total_avisos));
    linhas.push("- Pendencias: " + valorOuZero_(resumo.total_pendencias));
    linhas.push("- Erros: " + valorOuZero_(resumo.total_erros));
  }

  anexarListaLimitada_(linhas, "Avisos", validacao.avisos, 8);
  anexarListaLimitada_(linhas, "Pendencias", validacao.pendencias, 8);
  anexarListaLimitada_(linhas, "Erros", validacao.erros, 8);

  if (!validacao.finalizado) {
    linhas.push("");
    linhas.push("A validacao ainda esta em andamento.");
  }
  return linhas.join("\n");
}

function montarTextoResultadoEnvio_(resultado) {
  var linhas = [
    resultado.mensagem || "Resultado de envio disponivel.",
    "",
    "Lote: " + (resultado.lote_id || "-"),
    "Snapshot: " + (resultado.snapshot_hash || "-"),
    "Status: " + (resultado.status || "-"),
    "Quantidade enviada: " + valorOuZero_(resultado.quantidade_enviada),
    "Quantidade com erro: " + valorOuZero_(resultado.quantidade_com_erro),
    "Total sendaveis: " + valorOuZero_(resultado.total_sendaveis),
    "Total dry run: " + valorOuZero_(resultado.total_dry_run),
    "Erros de resolucao: " + valorOuZero_(resultado.total_erros_resolucao),
    "Erros de envio: " + valorOuZero_(resultado.total_erros_envio)
  ];

  if (resultado.aprovador) {
    linhas.push("Aprovador: " + (resultado.aprovado_por || "-"));
    linhas.push("Identidade: " + (resultado.aprovador.identity_strength || "desconhecida"));
    if (resultado.aprovador.email) {
      linhas.push("Email: " + resultado.aprovador.email);
    }
  }

  var auditoria = resultado.auditoria_resumo || {};
  var chaves = Object.keys(auditoria);
  if (chaves.length) {
    linhas.push("");
    linhas.push("Auditoria por item:");
    chaves.forEach(function(chave) {
      linhas.push("- " + chave + ": " + auditoria[chave]);
    });
  }

  if (!resultado.finalizado) {
    linhas.push("");
    linhas.push("O processamento ainda nao terminou.");
  }
  return linhas.join("\n");
}

function montarTextoJob_(job) {
  return [
    "Job ID: " + (job.job_id || "-"),
    "Tipo: " + (job.job_type || "-"),
    "Status: " + (job.status || "-"),
    "Tentativas: " + valorOuZero_(job.attempt_count) + "/" + valorOuZero_(job.max_attempts),
    "Mensagem: " + (job.mensagem || "-"),
    (job.next_retry_at ? "Proximo retry: " + job.next_retry_at : null)
  ].filter(function(item) { return !!item; }).join("\n");
}

function anexarListaLimitada_(linhas, titulo, itens, limite) {
  if (!itens || !itens.length) {
    return;
  }
  linhas.push("");
  linhas.push(titulo + ":");

  var quantidade = Math.min(itens.length, limite);
  for (var i = 0; i < quantidade; i++) {
    linhas.push("- " + formatarItemOperacional_(itens[i]));
  }
  if (itens.length > limite) {
    linhas.push("- ... e mais " + (itens.length - limite) + " item(ns)");
  }
}

function formatarItemOperacional_(item) {
  if (!item) {
    return "(item vazio)";
  }
  if (typeof item === "string") {
    return item;
  }

  var partes = [];
  if (item.linha_origem) partes.push("linha " + item.linha_origem);
  if (item.estudante) partes.push(item.estudante);
  if (item.componente) partes.push(item.componente);
  if (item.disciplina && !item.componente) partes.push(item.disciplina);

  var mensagem = item.mensagem || item.erro || item.descricao || item.tipo || JSON.stringify(item);
  if (partes.length) {
    return partes.join(" | ") + " -> " + mensagem;
  }
  return mensagem;
}

function mostrarDialogoTexto_(titulo, texto) {
  var html = HtmlService.createHtmlOutput(
    '<div style="font-family:Arial,sans-serif;padding:12px;">' +
      '<pre style="white-space:pre-wrap;font-family:Consolas,monospace;font-size:12px;line-height:1.45;">' +
      escaparHtml_(texto) +
      "</pre>" +
    "</div>"
  )
    .setWidth(720)
    .setHeight(520);

  SpreadsheetApp.getUi().showModalDialog(html, titulo);
}

function escaparHtml_(texto) {
  return String(texto || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escaparHtmlAtributo_(texto) {
  return escaparHtml_(texto).replace(/"/g, "&quot;");
}

function extrairMensagemErro_(resposta) {
  var body = resposta.json || {};
  return body.erro || body.mensagem || ("Erro HTTP " + resposta.statusCode + ".");
}

function mensagemErroHumana_(err) {
  if (!err) {
    return "Falha desconhecida.";
  }
  var mensagem = err.message || err.toString();
  if (mensagem === "Operacao cancelada pelo operador.") {
    return "Operacao cancelada.";
  }
  return mensagem;
}

function valorOuZero_(valor) {
  return valor || valor === 0 ? valor : 0;
}

function decodificarExpiracaoJwt_(token) {
  try {
    var partes = String(token || "").trim().split(".");
    if (partes.length < 2) {
      return null;
    }

    var payloadBase64 = String(partes[1] || "").trim();
    if (!payloadBase64) {
      return null;
    }

    // JWT usa base64url no payload; converter para base64 padrao com padding.
    payloadBase64 = payloadBase64.replace(/-/g, "+").replace(/_/g, "/");
    while (payloadBase64.length % 4 !== 0) {
      payloadBase64 += "=";
    }

    var payloadBytes = Utilities.base64Decode(payloadBase64);
    var payloadJson = Utilities.newBlob(payloadBytes).getDataAsString("UTF-8");
    var payload = JSON.parse(payloadJson);
    var expSegundos = Number(payload && payload.exp);
    if (!isFinite(expSegundos) || expSegundos <= 0) {
      return null;
    }
    return new Date(expSegundos * 1000);
  } catch (err) {
    Logger.log("[decodificarExpiracaoJwt_] parse de exp falhou: " + mensagemErroHumana_(err));
    return null;
  }
}

function verificarTokenIScholar_() {
  var agora = new Date();
  var msDia = 24 * 60 * 60 * 1000;
  var timezone = Session.getScriptTimeZone() || "America/Sao_Paulo";
  var props = PropertiesService.getScriptProperties();
  var token = "";

  try {
    token = garantirTokenIScholar_();
  } catch (errToken) {
    token = "";
    Logger.log("[verificarTokenIScholar_] token ausente: " + mensagemErroHumana_(errToken));
  }

  var expiracao = decodificarExpiracaoJwt_(token);
  var assunto = "";
  var statusResumo = "";
  var diasRestantes = null;
  var expiracaoFormatada = "";

  if (!token) {
    assunto = "\uD83D\uDEA8 EXPIRADO \u2014 Token iScholar inv\u00E1lido";
    statusResumo = "Token ausente em Script Properties (ISCHOLAR_TOKEN).";
  } else if (!expiracao) {
    assunto = "[Madan ETL] \u26A0\uFE0F N\u00E3o foi poss\u00EDvel ler expira\u00E7\u00E3o do token iScholar";
    statusResumo = "Formato do JWT inesperado, sem campo exp valido.";
  } else {
    var diffMs = expiracao.getTime() - agora.getTime();
    expiracaoFormatada = Utilities.formatDate(expiracao, timezone, "dd/MM/yyyy HH:mm:ss") + " (" + timezone + ")";

    if (diffMs <= 0) {
      diasRestantes = 0;
      assunto = "\uD83D\uDEA8 EXPIRADO \u2014 Token iScholar inv\u00E1lido";
      statusResumo = "Token expirado.";
    } else {
      diasRestantes = Math.max(1, Math.floor(diffMs / msDia));
      if (diffMs < 7 * msDia) {
        assunto = "\uD83D\uDEA8 URGENTE \u2014 Token iScholar expira em " + diasRestantes + " dias";
        statusResumo = "Token perto do vencimento.";
      } else if (diffMs < 30 * msDia) {
        assunto = "[Madan ETL] \u26A0\uFE0F Token iScholar expira em " + diasRestantes + " dias";
        statusResumo = "Token em janela de alerta (menos de 30 dias).";
      } else {
        Logger.log(
          "[verificarTokenIScholar_] token dentro da validade: expira em " +
            diasRestantes +
            " dias (sem alerta)."
        );
        return {
          alerta_enviado: false,
          motivo: "fora_da_janela",
          dias_restantes: diasRestantes,
          expiracao: expiracao
        };
      }
    }
  }

  var diaHoje = Utilities.formatDate(agora, timezone, "yyyy-MM-dd");
  var ultimoDiaEnviado = String(props.getProperty(PROP_ALERTA_TOKEN_ISCHOLAR_DIA) || "");
  if (ultimoDiaEnviado === diaHoje) {
    Logger.log("[verificarTokenIScholar_] alerta ja enviado hoje (" + diaHoje + "). Dedupe aplicado.");
    return {
      alerta_enviado: false,
      motivo: "dedupe_diario",
      assunto: assunto
    };
  }

  var corpoHtml = montarHtmlAlertaTokenIScholar_({
    status: statusResumo,
    expiracao: expiracaoFormatada,
    diasRestantes: diasRestantes
  });
  var enviado = enviarAlertaTokenIScholar_(assunto, corpoHtml);
  if (!enviado) {
    return {
      alerta_enviado: false,
      motivo: "falha_envio",
      assunto: assunto
    };
  }

  props.setProperty(PROP_ALERTA_TOKEN_ISCHOLAR_DIA, diaHoje);
  Logger.log("[verificarTokenIScholar_] alerta enviado e dedupe diario registrado.");
  return {
    alerta_enviado: true,
    assunto: assunto,
    expiracao: expiracao
  };
}

function montarHtmlAlertaTokenIScholar_(dados) {
  var info = dados || {};
  var status = String(info.status || "Token em estado de atencao.");
  var expiracao = String(info.expiracao || "Nao foi possivel determinar.");
  var diasRestantes = info.diasRestantes;
  var diasTexto = "-";
  if (diasRestantes === 0 || diasRestantes) {
    diasTexto = String(diasRestantes);
  }

  var linhas = [];
  linhas.push("<p><strong>Alerta automatico do monitor de token iScholar.</strong></p>");
  linhas.push("<p><strong>Status:</strong> " + escaparHtml_(status) + "</p>");
  linhas.push("<p><strong>Expiracao:</strong> " + escaparHtml_(expiracao) + "</p>");
  linhas.push("<p><strong>Dias restantes:</strong> " + escaparHtml_(diasTexto) + "</p>");
  linhas.push("<p><strong>Passo a passo para renovar:</strong></p>");
  linhas.push("<ol>");
  linhas.push("<li>Acesse o iScholar com usuario autorizado para integracoes.</li>");
  linhas.push("<li>Gere um novo JWT para a escola/codigo <code>madan</code>.</li>");
  linhas.push("<li>No Google Sheets, abra <code>Extensoes &gt; Apps Script</code>.</li>");
  linhas.push("<li>Em <code>Project Settings &gt; Script properties</code>, atualize a chave <code>ISCHOLAR_TOKEN</code>.</li>");
  linhas.push("<li>Salve e execute <code>verificarTokenIScholar_()</code> para confirmar a nova expiracao.</li>");
  linhas.push("<li>Teste sem afetar producao com <code>Validar Lote</code> + <code>Simular via Apps Script</code>.</li>");
  linhas.push("</ol>");
  linhas.push("<p>Importante: nao compartilhe o token em chats, logs ou screenshots.</p>");
  return linhas.join("");
}

function enviarAlertaTokenIScholar_(assunto, corpoHtml) {
  if (!HABILITAR_NOTIFICACOES) {
    Logger.log("[enviarAlertaTokenIScholar_] notificacoes desabilitadas.");
    return false;
  }

  var destinatario = String(EMAIL_ALERTA_TOKEN_ISCHOLAR || "").trim();
  if (!destinatario) {
    Logger.log("[enviarAlertaTokenIScholar_] destinatario vazio. Email nao enviado.");
    return false;
  }

  try {
    GmailApp.sendEmail(destinatario, String(assunto || "[Madan ETL] Alerta token iScholar"), htmlParaTexto_(corpoHtml), {
      htmlBody: String(corpoHtml || "<p>Sem conteudo.</p>")
    });
    Logger.log("[enviarAlertaTokenIScholar_] alerta enviado para " + destinatario + ".");
    return true;
  } catch (err) {
    Logger.log("[enviarAlertaTokenIScholar_] falha no envio: " + mensagemErroHumana_(err));
    return false;
  }
}

function criarTriggerVerificacaoToken_() {
  var removidos = 0;
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction && trigger.getHandlerFunction() === TRIGGER_VERIFICACAO_TOKEN_ISCHOLAR) {
      ScriptApp.deleteTrigger(trigger);
      removidos += 1;
    }
  });

  ScriptApp.newTrigger(TRIGGER_VERIFICACAO_TOKEN_ISCHOLAR)
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(9)
    .create();

  Logger.log(
    "[criarTriggerVerificacaoToken_] trigger semanal criado/atualizado para segunda-feira as 9h. Removidos=" +
      removidos
  );
  return {
    triggers_removidos: removidos,
    funcao: TRIGGER_VERIFICACAO_TOKEN_ISCHOLAR
  };
}

function carregarEstadoLocal_() {
  var props = obterArmazenamentoEstado_();
  return {
    lote_id: props.getProperty(PROP_LOTE_ID),
    snapshot_hash: props.getProperty(PROP_SNAPSHOT_HASH),
    validacao_job_id: props.getProperty(PROP_VALIDACAO_JOB_ID),
    aprovacao_job_id: props.getProperty(PROP_APROVACAO_JOB_ID),
    ultimo_status: props.getProperty(PROP_ULTIMO_STATUS),
    ultima_aba: props.getProperty(PROP_ULTIMA_ABA)
  };
}

function salvarEstadoLocal_(estado) {
  var props = obterArmazenamentoEstado_();
  if (estado.lote_id !== undefined) props.setProperty(PROP_LOTE_ID, String(estado.lote_id || ""));
  if (estado.snapshot_hash !== undefined) props.setProperty(PROP_SNAPSHOT_HASH, String(estado.snapshot_hash || ""));
  if (estado.validacao_job_id !== undefined) props.setProperty(PROP_VALIDACAO_JOB_ID, String(estado.validacao_job_id || ""));
  if (estado.aprovacao_job_id !== undefined) props.setProperty(PROP_APROVACAO_JOB_ID, String(estado.aprovacao_job_id || ""));
  if (estado.ultimo_status !== undefined) props.setProperty(PROP_ULTIMO_STATUS, String(estado.ultimo_status || ""));
  if (estado.ultima_aba !== undefined) props.setProperty(PROP_ULTIMA_ABA, String(estado.ultima_aba || ""));
}

function obterArmazenamentoEstado_() {
  // UserProperties evita falhas de DocumentProperties em arquivos recém-convertidos do XLSX.
  return PropertiesService.getUserProperties();
}

// ---------------------------------------------------------------------------
// Wrappers públicos (aparecem no dropdown do editor do Apps Script)
// O Apps Script esconde funções terminadas em "_" — então criamos versões
// sem underscore para que possam ser executadas manualmente do editor.
// ---------------------------------------------------------------------------

function setupTriggerVerificacaoToken() {
  return criarTriggerVerificacaoToken_();
}

function rodarVerificacaoTokenAgora() {
  return verificarTokenIScholar_();
}
