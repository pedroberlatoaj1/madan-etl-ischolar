/**
 * google_apps_script.gs — Webhook Google Sheets → Backend ETL iScholar
 *
 * Alinhado ao contrato do backend: POST /webhook/notas com spreadsheet_id, sheet_name, dados.
 *
 * Duas opções:
 *
 * — Versão A (apenas metadados): envia só spreadsheet_id, sheet_name e opcionalmente
 *   range/edit_info. O backend precisaria buscar os dados via Google Sheets API (OAuth/Service
 *   Account). Vantagens: payload mínimo; desvantagens: backend mais complexo, depende de API
 *   Google, latência e quotas. Não suportado pelo backend atual.
 *
 * — Versão B (dados estruturados): envia os dados da aba como lista de objetos (uma linha = um
 *   objeto). Vantagens: backend stateless, sem dependência de Google API, idempotência por hash
 *   no backend, pipeline atual (job → worker) já suporta. Desvantagens: payload maior em abas
 *   grandes. Recomendado para produção.
 *
 * Trigger recomendado: onChange (dispara em edição, colar, alteração de fórmula, etc.).
 * onEdit só dispara em edição manual célula a célula.
 */

// ============================================================
// CONFIGURAÇÕES — altere antes de implantar
// ============================================================
const WEBHOOK_URL = "https://sua-api.com/webhook/notas";
const WEBHOOK_SECRET = "troque_por_um_segredo_forte_em_producao";
const NOME_ABA_NOTAS = "Notas";

/** Debounce: não envia se o último envio foi há menos que este tempo (ms). */
const DEBOUNCE_MS = 5000;
const CHAVE_ULTIMO_ENVIO = "ultimo_envio_timestamp";

/** true = Versão B (dados completos, produção). false = Versão A (só metadados). */
const ENVIAR_DADOS_COMPLETOS = true;

// ============================================================
// Versão B — Envia dados da aba (contrato do backend atual)
// ============================================================

/**
 * Lê a aba e retorna lista de objetos: primeira linha = chaves (normalizadas snake_case).
 * Linhas vazias são ignoradas.
 */
function lerDadosDaAba(aba) {
  const intervalo = aba.getDataRange();
  const valores = intervalo.getValues();

  if (valores.length < 2) return [];

  const cabecalho = valores[0].map(function(cell) {
    return normalizarNomeColuna(cell);
  });

  const registros = [];
  for (let i = 1; i < valores.length; i++) {
    const linha = valores[i];
    if (linha.every(function(c) { return c === "" || c === null || c === undefined; })) continue;

    const obj = {};
    cabecalho.forEach(function(col, idx) {
      var val = linha[idx];
      obj[col] = (val !== "" && val !== null && val !== undefined) ? val : null;
    });
    registros.push(obj);
  }
  return registros;
}

/** Normaliza nome de coluna para snake_case (alinhado ao backend/transformador). */
function normalizarNomeColuna(str) {
  if (str === null || str === undefined) return "";
  return str.toString()
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "_")
    .replace(/[áàãâä]/g, "a")
    .replace(/[éèêë]/g, "e")
    .replace(/[íìîï]/g, "i")
    .replace(/[óòõôö]/g, "o")
    .replace(/[úùûü]/g, "u")
    .replace(/ç/g, "c")
    .replace(/[^a-z0-9_]/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

/**
 * Monta o payload no formato esperado pelo backend:
 * { spreadsheet_id, sheet_name, dados: [ { col1: val1, ... }, ... ] }
 */
function montarPayloadDados(ss, aba) {
  const dados = lerDadosDaAba(aba);
  return {
    spreadsheet_id: ss.getId(),
    sheet_name: aba.getName(),
    dados: dados
  };
}

/**
 * Envia payload completo ao webhook (Versão B).
 * Retorna objeto { ok: boolean, codigo: number, corpo: string }.
 */
function enviarPayload(payload) {
  const opcoes = {
    method: "post",
    contentType: "application/json",
    headers: {
      "X-Webhook-Secret": WEBHOOK_SECRET
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  const resposta = UrlFetchApp.fetch(WEBHOOK_URL, opcoes);
  const codigo = resposta.getResponseCode();
  const corpo = resposta.getContentText();
  return { ok: codigo >= 200 && codigo < 300, codigo: codigo, corpo: corpo };
}

/**
 * Aplica debounce global (por planilha) e envia dados da aba ao webhook.
 * Função principal chamada pelo trigger.
 */
function aoSalvarPlanilha(e) {
  const agora = Date.now();
  const props = PropertiesService.getScriptProperties();
  const ultimoEnvio = parseInt(props.getProperty(CHAVE_ULTIMO_ENVIO) || "0", 10);

  if (agora - ultimoEnvio < DEBOUNCE_MS) {
    Logger.log("Debounce ativo. Ignorando. Ultimo envio ha " + (agora - ultimoEnvio) + " ms.");
    return;
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const aba = ss.getSheetByName(NOME_ABA_NOTAS);

  if (!aba) {
    Logger.log("Aba '" + NOME_ABA_NOTAS + "' nao encontrada.");
    return;
  }

  if (ENVIAR_DADOS_COMPLETOS) {
    // Versão B: envia dados completos (produção)
    const payload = montarPayloadDados(ss, aba);
    if (!payload.dados || payload.dados.length === 0) {
      Logger.log("Nenhum dado na aba '" + NOME_ABA_NOTAS + "'. Nao enviado.");
      return;
    }
    props.setProperty(CHAVE_ULTIMO_ENVIO, agora.toString());
    Logger.log("Enviando " + payload.dados.length + " registros para webhook...");
    const resultado = enviarPayload(payload);
    if (resultado.ok) {
      Logger.log("Webhook OK | HTTP " + resultado.codigo + " | " + resultado.corpo);
    } else {
      Logger.log("Webhook erro | HTTP " + resultado.codigo + " | " + resultado.corpo);
    }
  } else {
    // Versão A: envia apenas metadados (backend precisaria buscar dados via API)
    props.setProperty(CHAVE_ULTIMO_ENVIO, agora.toString());
    const payload = {
      spreadsheet_id: ss.getId(),
      sheet_name: aba.getName(),
      edit_event: e ? { source: (e.source && e.source.getId()), authMode: e.authMode } : null
    };
    Logger.log("Enviando metadados (Versao A)...");
    const resultado = enviarPayload(payload);
    if (resultado.ok) {
      Logger.log("Webhook OK | HTTP " + resultado.codigo + " | " + resultado.corpo);
    } else {
      Logger.log("Webhook erro | HTTP " + resultado.codigo + " | " + resultado.corpo);
    }
  }
}

// ============================================================
// Versão A — Apenas metadados (para uso futuro com backend que busca dados via API)
// ============================================================

/**
 * Chamada explícita para enviar só metadados (sem dados da aba).
 * O backend atual espera "dados"; este payload retornará 200 com status "ignorado" (dados vazio).
 * Para Versão A real, o backend precisaria de um endpoint que receba spreadsheet_id + sheet_name
 * e busque os dados via Google Sheets API.
 */
function enviarApenasMetadados() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const aba = ss.getSheetByName(NOME_ABA_NOTAS);
  if (!aba) {
    Logger.log("Aba '" + NOME_ABA_NOTAS + "' nao encontrada.");
    return;
  }
  const payload = {
    spreadsheet_id: ss.getId(),
    sheet_name: aba.getName(),
    dados: []
  };
  const resultado = enviarPayload(payload);
  Logger.log("Metadados enviados | HTTP " + resultado.codigo + " | " + resultado.corpo);
  return resultado;
}

// ============================================================
// Triggers
// ============================================================

/**
 * Instala o trigger recomendado: onChange.
 * Execute uma vez manualmente (Executar > instalarTrigger).
 *
 * onChange: dispara em edição, colar, inserção de linhas/colunas, etc.
 * onEdit: dispara só quando o usuário edita uma célula (não em colar ou fórmulas em lote).
 */
function instalarTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger("aoSalvarPlanilha")
    .forSpreadsheet(SpreadsheetApp.getActive())
    .onChange()
    .create();

  Logger.log("Trigger 'onChange' instalado. Funcao: aoSalvarPlanilha");
}

/**
 * Alternativa: trigger onEdit (só edição célula a célula).
 * Use se quiser evitar disparos em colar ou alterações em lote.
 */
function instalarTriggerOnEdit() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger("aoSalvarPlanilha")
    .forSpreadsheet(SpreadsheetApp.getActive())
    .onEdit()
    .create();

  Logger.log("Trigger 'onEdit' instalado. Funcao: aoSalvarPlanilha");
}

// ============================================================
// INSTRUÇÕES DE CONFIGURAÇÃO
// ============================================================
//
// 1. Abra a planilha de notas no Google Sheets.
// 2. Extensões > Apps Script; cole todo este arquivo e salve (Ctrl+S).
// 3. No topo do script, altere:
//    - WEBHOOK_URL: URL pública do seu backend (ex.: https://api.seudominio.com/webhook/notas).
//    - WEBHOOK_SECRET: mesmo valor da variável WEBHOOK_SECRET no servidor Python (.env).
//    - NOME_ABA_NOTAS: nome exato da aba que contém as notas (ex.: "Notas").
//    - DEBOUNCE_MS: intervalo mínimo entre envios (5000 = 5 segundos).
//    - ENVIAR_DADOS_COMPLETOS: true para produção (Versão B); false para só metadados (Versão A).
// 4. Instale o trigger: no editor do Apps Script, selecione a função "instalarTrigger"
//    no dropdown e clique em Executar (play). Autorize o acesso quando solicitado.
// 5. Verifique em Editar > Acionadores do projeto que o acionador "aoSalvarPlanilha" com
//    evento "Ao alterar" (onChange) está ativo.
//
// Teste manual: altere uma célula na aba de notas e veja os logs em Execuções.
