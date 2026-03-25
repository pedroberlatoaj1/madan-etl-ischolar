const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "Pipeline Madan-iScholar";
pres.title = "Pipeline Madan → iScholar — Apresentação Técnica";

// ── PALETTE ──
const C = {
  navy:     "1B2A4A",
  darkBlue: "2E4057",
  teal:     "048A81",
  mint:     "54C6EB",
  light:    "F0F4F8",
  white:    "FFFFFF",
  offWhite: "F7F9FC",
  gray:     "64748B",
  darkGray: "334155",
  accent:   "F59E0B",
  green:    "10B981",
  red:      "EF4444",
  orange:   "F97316",
};

// ── HELPERS ──
const mkShadow = () => ({ type: "outer", blur: 4, offset: 2, angle: 135, color: "000000", opacity: 0.10 });

function addCard(slide, x, y, w, h, opts = {}) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: opts.fill || C.white },
    shadow: mkShadow(),
    line: opts.border ? { color: opts.border, width: 1.2 } : undefined,
  });
  if (opts.accentColor) {
    slide.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.06, h,
      fill: { color: opts.accentColor },
    });
  }
}

function addSectionNumber(slide, x, y, num, color) {
  slide.addShape(pres.shapes.OVAL, {
    x, y, w: 0.45, h: 0.45,
    fill: { color: color || C.teal },
  });
  slide.addText(String(num), {
    x, y, w: 0.45, h: 0.45,
    fontSize: 16, fontFace: "Arial", bold: true,
    color: C.white, align: "center", valign: "middle", margin: 0,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 1 — CAPA
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };

  // Decorative bar top
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });

  // Decorative diagonal shape
  s.addShape(pres.shapes.RECTANGLE, {
    x: 6.5, y: 0, w: 4, h: 5.625,
    fill: { color: C.darkBlue, transparency: 40 },
  });

  s.addText("Pipeline Madan → iScholar", {
    x: 0.8, y: 1.2, w: 7, h: 1.2,
    fontSize: 38, fontFace: "Calibri", bold: true,
    color: C.white, margin: 0,
  });

  s.addText("Sistema de Lancamento Automatizado de Notas", {
    x: 0.8, y: 2.4, w: 6, h: 0.6,
    fontSize: 18, fontFace: "Calibri",
    color: C.mint, margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 3.2, w: 1.5, h: 0.04, fill: { color: C.teal } });

  s.addText("Apresentacao Tecnica para o Madan", {
    x: 0.8, y: 3.5, w: 5, h: 0.5,
    fontSize: 14, fontFace: "Calibri",
    color: C.gray, margin: 0,
  });

  // Stats on the right
  const stats = [
    { num: "265", label: "Testes passando" },
    { num: "7", label: "Endpoints integrados" },
    { num: "15+", label: "Modulos de codigo" },
  ];
  stats.forEach((st, i) => {
    const sy = 1.4 + i * 1.2;
    s.addText(st.num, {
      x: 7.2, y: sy, w: 2, h: 0.5,
      fontSize: 32, fontFace: "Calibri", bold: true,
      color: C.accent, align: "center", margin: 0,
    });
    s.addText(st.label, {
      x: 7.2, y: sy + 0.45, w: 2, h: 0.35,
      fontSize: 11, fontFace: "Calibri",
      color: C.gray, align: "center", margin: 0,
    });
  });

  // Bottom bar
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.325, w: 10, h: 0.3, fill: { color: C.teal, transparency: 70 } });
}

// ════════════════════════════════════════════════════════════
// SLIDE 2 — O PROBLEMA
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("O Problema que Resolvemos", {
    x: 0.6, y: 0.3, w: 9, h: 0.7,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  // BEFORE card
  addCard(s, 0.5, 1.2, 4.2, 3.6, { accentColor: C.red });
  s.addText("ANTES — Manual", {
    x: 0.8, y: 1.35, w: 3.5, h: 0.4,
    fontSize: 16, fontFace: "Calibri", bold: true,
    color: C.red, margin: 0,
  });
  s.addText([
    { text: "Professor preenche planilha", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Coordenador confere manualmente", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Secretario digita nota por nota no iScholar", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Erros de digitacao passam despercebidos", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Sem rastreabilidade do que foi lancado", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Processo repetido 3x por ano (trimestres)", options: { bullet: true, fontSize: 13 } },
  ], {
    x: 0.8, y: 1.85, w: 3.7, h: 2.8,
    fontFace: "Calibri", color: C.darkGray, paraSpaceAfter: 6, margin: 0,
  });

  // Arrow
  s.addText("→", {
    x: 4.5, y: 2.5, w: 0.8, h: 0.6,
    fontSize: 36, fontFace: "Calibri", bold: true,
    color: C.teal, align: "center", valign: "middle", margin: 0,
  });

  // AFTER card
  addCard(s, 5.3, 1.2, 4.2, 3.6, { accentColor: C.green });
  s.addText("DEPOIS — Automatizado", {
    x: 5.6, y: 1.35, w: 3.5, h: 0.4,
    fontSize: 16, fontFace: "Calibri", bold: true,
    color: C.green, margin: 0,
  });
  s.addText([
    { text: "Planilha padrao com validacao automatica", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Regras pedagogicas aplicadas pelo sistema", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Envio direto ao iScholar via API", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Erros bloqueados antes do envio", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Auditoria completa por item enviado", options: { bullet: true, breakLine: true, fontSize: 13 } },
    { text: "Aprovacao obrigatoria antes de qualquer envio", options: { bullet: true, fontSize: 13 } },
  ], {
    x: 5.6, y: 1.85, w: 3.7, h: 2.8,
    fontFace: "Calibri", color: C.darkGray, paraSpaceAfter: 6, margin: 0,
  });

  // Bottom summary
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 5.0, w: 9, h: 0.04, fill: { color: C.teal, transparency: 60 } });
  s.addText("Objetivo: eliminar erro humano, garantir rastreabilidade e acelerar o lancamento de notas.", {
    x: 0.5, y: 5.1, w: 9, h: 0.4,
    fontSize: 12, fontFace: "Calibri", italic: true,
    color: C.gray, margin: 0,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 3 — VISAO GERAL DA ARQUITETURA
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Arquitetura do Pipeline — Visao Geral", {
    x: 0.6, y: 0.3, w: 9, h: 0.7,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  const stages = [
    { label: "Planilha\nFixa",          color: C.navy },
    { label: "Transformacao\nCanonica",  color: C.darkBlue },
    { label: "Validacao\nPre-envio",     color: C.teal },
    { label: "Preflight\nTecnico",       color: "0E7490" },
    { label: "Aprovacao\ndo Lote",       color: C.accent },
    { label: "Resolucao\nde IDs",        color: "7C3AED" },
    { label: "Envio\nao iScholar",       color: C.green },
    { label: "Auditoria\npor Item",      color: "059669" },
  ];

  // Draw flow with arrows
  const startX = 0.3;
  const boxW = 1.05;
  const gap = 0.1;
  const row1Y = 1.4;
  const row2Y = 3.4;

  stages.forEach((st, i) => {
    let x, y;
    if (i < 4) {
      x = startX + i * (boxW + gap + 0.08);
      y = row1Y;
    } else {
      // Second row, right to left visually but positioned left to right
      x = startX + (7 - i) * (boxW + gap + 0.08);
      y = row2Y;
    }

    // Box
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: boxW, h: 1.3,
      fill: { color: st.color },
      shadow: mkShadow(),
    });

    // Number circle
    s.addShape(pres.shapes.OVAL, {
      x: x + 0.02, y: y + 0.05, w: 0.3, h: 0.3,
      fill: { color: C.white, transparency: 25 },
    });
    s.addText(String(i + 1), {
      x: x + 0.02, y: y + 0.05, w: 0.3, h: 0.3,
      fontSize: 12, fontFace: "Calibri", bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0,
    });

    // Label
    s.addText(st.label, {
      x, y: y + 0.35, w: boxW, h: 0.85,
      fontSize: 11, fontFace: "Calibri", bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0,
    });

    // Arrows between boxes (row 1: right arrows, between rows: down arrow)
    if (i < 3) {
      const arrowX = x + boxW;
      s.addText("→", {
        x: arrowX, y: row1Y + 0.35, w: gap + 0.08, h: 0.5,
        fontSize: 18, fontFace: "Calibri", bold: true,
        color: C.gray, align: "center", valign: "middle", margin: 0,
      });
    }
    if (i >= 5 && i < 7) {
      const arrowX = x + boxW;
      s.addText("→", {
        x: arrowX, y: row2Y + 0.35, w: gap + 0.08, h: 0.5,
        fontSize: 18, fontFace: "Calibri", bold: true,
        color: C.gray, align: "center", valign: "middle", margin: 0,
      });
    }
  });

  // Down arrow between rows (from stage 4 to stage 5)
  s.addText("↓", {
    x: 3.7, y: 2.7, w: 0.5, h: 0.7,
    fontSize: 24, fontFace: "Calibri", bold: true,
    color: C.gray, align: "center", valign: "middle", margin: 0,
  });

  // Bottom note
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 5.0, w: 9, h: 0.04, fill: { color: C.teal, transparency: 60 } });
  s.addText("Cada etapa e independente, testavel e auditavel. Nenhuma etapa pode ser pulada.", {
    x: 0.5, y: 5.1, w: 9, h: 0.4,
    fontSize: 12, fontFace: "Calibri", italic: true,
    color: C.gray, margin: 0,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 4 — TEMPLATE DA PLANILHA
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Template Oficial da Planilha", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  s.addText("A planilha segue um modelo fixo. Qualquer coluna faltando bloqueia o processo.", {
    x: 0.6, y: 0.85, w: 8, h: 0.35,
    fontSize: 13, fontFace: "Calibri", color: C.gray, margin: 0,
  });

  // Table with columns
  const headerOpts = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 10, fontFace: "Calibri", align: "center", valign: "middle" };
  const cellOpts = { fontSize: 10, fontFace: "Calibri", color: C.darkGray, align: "center", valign: "middle" };
  const reqOpts = { ...cellOpts, fill: { color: "DCFCE7" } };
  const noteOpts = { ...cellOpts, fill: { color: "FEF3C7" } };
  const confOpts = { ...cellOpts, fill: { color: "EDE9FE" } };

  s.addTable([
    [
      { text: "Tipo", options: headerOpts },
      { text: "Coluna", options: headerOpts },
      { text: "Obrigatoria", options: headerOpts },
      { text: "Descricao", options: headerOpts },
    ],
    [{ text: "Contexto", options: reqOpts }, { text: "Estudante", options: reqOpts }, { text: "Sim", options: reqOpts }, { text: "Nome completo do aluno", options: reqOpts }],
    [{ text: "Contexto", options: reqOpts }, { text: "RA", options: reqOpts }, { text: "Sim", options: reqOpts }, { text: "Registro do Aluno (identifica no iScholar)", options: reqOpts }],
    [{ text: "Contexto", options: reqOpts }, { text: "Turma", options: reqOpts }, { text: "Sim", options: reqOpts }, { text: "Ex: 1A, 2B", options: reqOpts }],
    [{ text: "Contexto", options: reqOpts }, { text: "Trimestre", options: reqOpts }, { text: "Sim", options: reqOpts }, { text: "1, 2 ou 3", options: reqOpts }],
    [{ text: "Contexto", options: reqOpts }, { text: "Disciplina", options: reqOpts }, { text: "Sim", options: reqOpts }, { text: "Nome da disciplina", options: reqOpts }],
    [{ text: "Contexto", options: reqOpts }, { text: "Frente - Professor", options: reqOpts }, { text: "Sim", options: reqOpts }, { text: "Ex: Matematica - Prof. Silva", options: reqOpts }],
    [{ text: "Nota", options: noteOpts }, { text: "AV1 OBJ / AV1 DISC", options: noteOpts }, { text: "—", options: noteOpts }, { text: "Nota 0-10 (vazio = nao se aplica)", options: noteOpts }],
    [{ text: "Nota", options: noteOpts }, { text: "AV2 OBJ / AV2 DISC", options: noteOpts }, { text: "—", options: noteOpts }, { text: "Nota 0-10", options: noteOpts }],
    [{ text: "Nota", options: noteOpts }, { text: "AV3 listas / AV3 aval.", options: noteOpts }, { text: "—", options: noteOpts }, { text: "Apenas alunos com nivelamento", options: noteOpts }],
    [{ text: "Nota", options: noteOpts }, { text: "Simulado / Pt. Extra / Rec.", options: noteOpts }, { text: "—", options: noteOpts }, { text: "Componentes adicionais", options: noteOpts }],
    [{ text: "Conferencia", options: confOpts }, { text: "Nota Final / c/ AV3 / s/ AV3", options: confOpts }, { text: "Nao", options: confOpts }, { text: "Auxiliar — nao afeta o envio", options: confOpts }],
  ], {
    x: 0.4, y: 1.3, w: 9.2,
    colW: [1.2, 2.5, 1.2, 4.3],
    border: { pt: 0.5, color: "CBD5E1" },
    rowH: [0.32, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3],
  });

  // Legend
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 5.0, w: 0.25, h: 0.2, fill: { color: "DCFCE7" } });
  s.addText("Obrigatoria", { x: 0.8, y: 5.0, w: 1.2, h: 0.2, fontSize: 9, fontFace: "Calibri", color: C.darkGray, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 2.2, y: 5.0, w: 0.25, h: 0.2, fill: { color: "FEF3C7" } });
  s.addText("Nota", { x: 2.5, y: 5.0, w: 0.8, h: 0.2, fontSize: 9, fontFace: "Calibri", color: C.darkGray, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 3.5, y: 5.0, w: 0.25, h: 0.2, fill: { color: "EDE9FE" } });
  s.addText("Conferencia (opcional)", { x: 3.8, y: 5.0, w: 2, h: 0.2, fontSize: 9, fontFace: "Calibri", color: C.darkGray, margin: 0 });
}

// ════════════════════════════════════════════════════════════
// SLIDE 5 — REGRAS PEDAGOGICAS
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Regras Pedagogicas Implementadas", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  s.addText("Fonte oficial: \"Sistema Avaliativo.pdf\" — confirmado para 1a e 2a series.", {
    x: 0.6, y: 0.85, w: 8, h: 0.3,
    fontSize: 12, fontFace: "Calibri", italic: true, color: C.gray, margin: 0,
  });

  // Weight tables
  const hOpts = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 10, fontFace: "Calibri", align: "center", valign: "middle" };
  const cOpts = { fontSize: 10, fontFace: "Calibri", color: C.darkGray, align: "center", valign: "middle" };
  const totOpts = { ...cOpts, bold: true, fill: { color: "F0FDF4" } };

  s.addText("Tabela de Pesos por Trimestre", {
    x: 0.5, y: 1.25, w: 4, h: 0.35,
    fontSize: 14, fontFace: "Calibri", bold: true, color: C.darkBlue, margin: 0,
  });

  s.addTable([
    [{ text: "Periodo", options: hOpts }, { text: "AV1", options: hOpts }, { text: "AV2", options: hOpts }, { text: "AV3", options: hOpts }, { text: "Sim.", options: hOpts }, { text: "Total", options: hOpts }],
    [{ text: "T1/T2 sem AV3", options: cOpts }, { text: "12", options: cOpts }, { text: "15", options: cOpts }, { text: "—", options: cOpts }, { text: "3", options: cOpts }, { text: "30", options: totOpts }],
    [{ text: "T1/T2 com AV3", options: cOpts }, { text: "9", options: cOpts }, { text: "9", options: cOpts }, { text: "9", options: cOpts }, { text: "3", options: cOpts }, { text: "30", options: totOpts }],
    [{ text: "T3 sem AV3", options: cOpts }, { text: "16", options: cOpts }, { text: "18", options: cOpts }, { text: "—", options: cOpts }, { text: "6", options: cOpts }, { text: "40", options: totOpts }],
    [{ text: "T3 com AV3", options: cOpts }, { text: "12", options: cOpts }, { text: "12", options: cOpts }, { text: "12", options: cOpts }, { text: "4", options: cOpts }, { text: "40", options: totOpts }],
  ], {
    x: 0.3, y: 1.65, w: 4.5,
    colW: [1.3, 0.6, 0.6, 0.6, 0.6, 0.8],
    border: { pt: 0.5, color: "CBD5E1" },
    rowH: [0.3, 0.28, 0.28, 0.28, 0.28],
  });

  // Rules cards on the right
  const rules = [
    { title: "AV3 (Nivelamento)", desc: "70% listas + 30% avaliacao\nSo para alunos com nivelamento", color: C.teal },
    { title: "Ponto Extra", desc: "Somado na coluna AV1\nTeto de 10 (nunca ultrapassa)", color: C.accent },
    { title: "Notas 0 a 10", desc: "Pesos aplicados pelo iScholar\nPipeline envia nota bruta", color: C.green },
  ];

  rules.forEach((r, i) => {
    const ry = 1.3 + i * 1.15;
    addCard(s, 5.2, ry, 4.3, 1.0, { accentColor: r.color });
    s.addText(r.title, {
      x: 5.5, y: ry + 0.1, w: 3.8, h: 0.3,
      fontSize: 13, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
    });
    s.addText(r.desc, {
      x: 5.5, y: ry + 0.4, w: 3.8, h: 0.5,
      fontSize: 11, fontFace: "Calibri", color: C.darkGray, margin: 0,
    });
  });

  // Pending items
  addCard(s, 0.3, 4.15, 9.4, 1.1, { fill: "FFF7ED", border: C.orange });
  s.addText("Pendente — A confirmar na reuniao", {
    x: 0.6, y: 4.25, w: 4, h: 0.3,
    fontSize: 13, fontFace: "Calibri", bold: true, color: C.orange, margin: 0,
  });
  s.addText([
    { text: "Como OBJ + DISC se combinam em AV1/AV2 (media simples? ponderada?)", options: { bullet: true, breakLine: true, fontSize: 11 } },
    { text: "Regras de recuperacao (nao mencionada no PDF)", options: { bullet: true, breakLine: true, fontSize: 11 } },
    { text: "O que significa \"avaliacao fechada\" para ponto extra", options: { bullet: true, breakLine: true, fontSize: 11 } },
    { text: "Regras da 3a serie (PDF cobre apenas 1a e 2a)", options: { bullet: true, fontSize: 11 } },
  ], {
    x: 0.6, y: 4.55, w: 8.8, h: 0.65,
    fontFace: "Calibri", color: C.darkGray, margin: 0, paraSpaceAfter: 2,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 6 — INTEGRACAO COM iSCHOLAR
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Integracao com a API iScholar", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  s.addText("7 endpoints integrados — autenticados via token + codigo da escola", {
    x: 0.6, y: 0.85, w: 8, h: 0.3,
    fontSize: 12, fontFace: "Calibri", italic: true, color: C.gray, margin: 0,
  });

  const hOpts = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 10, fontFace: "Calibri", valign: "middle" };
  const cOpts = { fontSize: 10, fontFace: "Calibri", color: C.darkGray, valign: "middle" };
  const getOpts = { ...cOpts, fill: { color: "DBEAFE" }, bold: true, align: "center" };
  const postOpts = { ...cOpts, fill: { color: "FEF3C7" }, bold: true, align: "center" };

  s.addTable([
    [
      { text: "Metodo", options: hOpts },
      { text: "Endpoint", options: hOpts },
      { text: "Funcao no Sistema", options: hOpts },
    ],
    [{ text: "GET", options: getOpts }, { text: "/aluno/busca", options: cOpts }, { text: "Localiza aluno por RA ou CPF → retorna id_aluno", options: cOpts }],
    [{ text: "GET", options: getOpts }, { text: "/matricula/listar", options: cOpts }, { text: "Lista matriculas de um aluno → retorna id_matricula", options: cOpts }],
    [{ text: "GET", options: getOpts }, { text: "/matricula/pega_alunos", options: cOpts }, { text: "Fallback: busca alunos por turma com RA + IDs juntos", options: cOpts }],
    [{ text: "GET", options: getOpts }, { text: "/disciplinas", options: cOpts }, { text: "Lista todas as disciplinas cadastradas na escola", options: cOpts }],
    [{ text: "GET", options: getOpts }, { text: "/funcionarios/professores", options: cOpts }, { text: "Lista todos os professores cadastrados", options: cOpts }],
    [{ text: "GET", options: getOpts }, { text: "/diario/notas", options: cOpts }, { text: "Consulta notas ja lancadas (reconciliacao/auditoria)", options: cOpts }],
    [{ text: "POST", options: postOpts }, { text: "/notas/lanca_nota", options: cOpts }, { text: "Lancamento principal de nota (idempotente)", options: cOpts }],
  ], {
    x: 0.3, y: 1.3, w: 9.4,
    colW: [0.9, 2.5, 6.0],
    border: { pt: 0.5, color: "CBD5E1" },
    rowH: [0.32, 0.35, 0.35, 0.35, 0.35, 0.35, 0.35, 0.35],
  });

  // Envelope pattern
  addCard(s, 0.3, 4.35, 4.5, 1.1, { accentColor: C.teal });
  s.addText("Envelope Padrao da API", {
    x: 0.6, y: 4.45, w: 3.5, h: 0.3,
    fontSize: 13, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
  });
  s.addText('{ "status": "sucesso",\n  "mensagem": "...",\n  "dados": ... }', {
    x: 0.6, y: 4.75, w: 3.5, h: 0.6,
    fontSize: 10, fontFace: "Consolas", color: C.darkGray, margin: 0,
  });

  // Auth info
  addCard(s, 5.1, 4.35, 4.6, 1.1, { accentColor: C.accent });
  s.addText("Autenticacao", {
    x: 5.4, y: 4.45, w: 4, h: 0.3,
    fontSize: 13, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
  });
  s.addText([
    { text: "X-Autorizacao: ", options: { bold: true, fontSize: 10, fontFace: "Consolas" } },
    { text: "token da escola", options: { fontSize: 10, fontFace: "Calibri", breakLine: true } },
    { text: "X-Codigo-Escola: ", options: { bold: true, fontSize: 10, fontFace: "Consolas" } },
    { text: "madan_homolog", options: { fontSize: 10, fontFace: "Calibri" } },
  ], {
    x: 5.4, y: 4.75, w: 4.1, h: 0.6,
    color: C.darkGray, margin: 0,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 7 — RESOLUCAO DE IDs
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Estrategia de Resolucao de IDs", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  s.addText("Postura fail-closed: na duvida, bloqueia. Nunca infere, nunca adivinha.", {
    x: 0.6, y: 0.85, w: 8, h: 0.3,
    fontSize: 12, fontFace: "Calibri", italic: true, color: C.gray, margin: 0,
  });

  // Flow diagram - main path
  const flowBoxes = [
    { x: 0.3, y: 1.4, w: 2.0, label: "buscar_aluno\n(RA)", color: C.navy },
    { x: 2.8, y: 1.4, w: 2.0, label: "id_aluno\nextraido?", color: C.teal },
    { x: 5.3, y: 1.4, w: 2.0, label: "listar_matriculas\n(id_aluno)", color: C.darkBlue },
    { x: 7.8, y: 1.4, w: 1.8, label: "id_matricula\nresolvido", color: C.green },
  ];

  flowBoxes.forEach(b => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: b.x, y: b.y, w: b.w, h: 0.9,
      fill: { color: b.color }, shadow: mkShadow(),
    });
    s.addText(b.label, {
      x: b.x, y: b.y, w: b.w, h: 0.9,
      fontSize: 11, fontFace: "Calibri", bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0,
    });
  });

  // Arrows
  s.addText("→", { x: 2.2, y: 1.6, w: 0.6, h: 0.4, fontSize: 18, fontFace: "Calibri", bold: true, color: C.gray, align: "center", margin: 0 });
  s.addText("Sim →", { x: 4.65, y: 1.55, w: 0.7, h: 0.4, fontSize: 11, fontFace: "Calibri", bold: true, color: C.green, align: "center", margin: 0 });
  s.addText("→", { x: 7.2, y: 1.6, w: 0.6, h: 0.4, fontSize: 18, fontFace: "Calibri", bold: true, color: C.gray, align: "center", margin: 0 });

  // Fallback path
  s.addText("Nao ↓", { x: 3.3, y: 2.3, w: 1.0, h: 0.35, fontSize: 11, fontFace: "Calibri", bold: true, color: C.red, align: "center", margin: 0 });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 2.3, y: 2.7, w: 2.5, h: 0.8,
    fill: { color: "7C3AED" }, shadow: mkShadow(),
  });
  s.addText("pega_alunos\n(fallback por turma)", {
    x: 2.3, y: 2.7, w: 2.5, h: 0.8,
    fontSize: 11, fontFace: "Calibri", bold: true,
    color: C.white, align: "center", valign: "middle", margin: 0,
  });

  s.addText("→", { x: 4.7, y: 2.85, w: 0.6, h: 0.4, fontSize: 18, fontFace: "Calibri", bold: true, color: C.gray, align: "center", margin: 0 });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 5.2, y: 2.7, w: 2.2, h: 0.8,
    fill: { color: C.accent }, shadow: mkShadow(),
  });
  s.addText("encontrar_por_ra\n(match exato)", {
    x: 5.2, y: 2.7, w: 2.2, h: 0.8,
    fontSize: 11, fontFace: "Calibri", bold: true,
    color: C.white, align: "center", valign: "middle", margin: 0,
  });

  // DE-PARA cards
  const depara = [
    { label: "id_disciplina", source: "mapa_disciplinas.json\n(ou GET /disciplinas)", x: 0.3 },
    { label: "id_avaliacao", source: "mapa_avaliacoes.json\n(manual)", x: 3.5 },
    { label: "id_professor", source: "mapa_professores.json\n(ou GET /professores)", x: 6.7 },
  ];

  depara.forEach(d => {
    addCard(s, d.x, 3.9, 2.8, 0.95, { accentColor: "7C3AED" });
    s.addText(d.label, {
      x: d.x + 0.2, y: 3.98, w: 2.4, h: 0.28,
      fontSize: 12, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
    });
    s.addText(d.source, {
      x: d.x + 0.2, y: 4.28, w: 2.4, h: 0.5,
      fontSize: 10, fontFace: "Calibri", color: C.darkGray, margin: 0,
    });
  });

  // Bottom: posture
  s.addShape(pres.shapes.RECTANGLE, { x: 0.3, y: 5.05, w: 9.4, h: 0.45, fill: { color: "FEF2F2" }, shadow: mkShadow() });
  s.addText("POSTURA: matricula ambigua → BLOQUEIA | disciplina sem mapa → BLOQUEIA | multiplos matches → BLOQUEIA", {
    x: 0.6, y: 5.05, w: 9, h: 0.45,
    fontSize: 11, fontFace: "Calibri", bold: true, color: C.red, valign: "middle", margin: 0,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 8 — BANCO DE DADOS E PERSISTENCIA
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Banco de Dados e Persistencia", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  s.addText("3 bancos SQLite independentes — leves, portateis, sem servidor externo", {
    x: 0.6, y: 0.85, w: 8, h: 0.3,
    fontSize: 12, fontFace: "Calibri", italic: true, color: C.gray, margin: 0,
  });

  // Three DB cards
  const dbs = [
    {
      title: "aprovacoes_lote.db",
      desc: "Estado de cada lote:\n- ID do lote + hash\n- Status (aguardando / aprovado / rejeitado)\n- Quem aprovou e quando\n- Snapshot congelado do resumo",
      color: C.teal,
      icon: "APROVACAO",
    },
    {
      title: "lote_itens.db",
      desc: "Itens aprovados para envio:\n- Lista exata de lancamentos\n- Hash de integridade\n- Garante que so o que foi aprovado\n  e enviado (sem injecao)",
      color: C.accent,
      icon: "ITENS",
    },
    {
      title: "envio_lote_audit.db",
      desc: "Auditoria do envio:\n- Resultado por item (sucesso/erro)\n- Payload montado\n- Resposta da API\n- Erros transitorios marcados",
      color: C.green,
      icon: "AUDITORIA",
    },
  ];

  dbs.forEach((db, i) => {
    const x = 0.3 + i * 3.2;
    addCard(s, x, 1.3, 2.95, 3.2, { accentColor: db.color });

    // Icon circle
    s.addShape(pres.shapes.OVAL, {
      x: x + 1.05, y: 1.45, w: 0.7, h: 0.7,
      fill: { color: db.color },
    });
    s.addText(db.icon.substring(0, 2), {
      x: x + 1.05, y: 1.45, w: 0.7, h: 0.7,
      fontSize: 16, fontFace: "Calibri", bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0,
    });

    s.addText(db.title, {
      x: x + 0.2, y: 2.25, w: 2.55, h: 0.35,
      fontSize: 12, fontFace: "Consolas", bold: true, color: C.navy, align: "center", margin: 0,
    });

    s.addText(db.desc, {
      x: x + 0.2, y: 2.65, w: 2.55, h: 1.7,
      fontSize: 10, fontFace: "Calibri", color: C.darkGray, margin: 0,
    });
  });

  // Design decisions
  addCard(s, 0.3, 4.7, 9.4, 0.75, { fill: "F0F9FF", accentColor: C.navy });
  s.addText("Decisoes de Design:", {
    x: 0.6, y: 4.78, w: 2.5, h: 0.25,
    fontSize: 11, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
  });
  s.addText("WAL mode ativado | Foreign keys habilitadas | Suporte a :memory: para testes | UPSERT com ON CONFLICT | Hash de integridade em todos os stores", {
    x: 0.6, y: 5.05, w: 8.8, h: 0.3,
    fontSize: 10, fontFace: "Calibri", color: C.darkGray, margin: 0,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 9 — DECISOES TECNICAS
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Decisoes Tecnicas e Filosofia do Projeto", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  const decisions = [
    { title: "Fail-Closed (nunca adivinha)", desc: "Quando ha duvida, o sistema bloqueia e reporta. Nunca infere IDs, nunca desempata automaticamente, nunca assume que a nota esta certa se o mapeamento nao existe.", color: C.red },
    { title: "Auditavel por Item", desc: "Cada nota enviada tem rastreabilidade completa: de qual linha da planilha veio, qual ID foi resolvido, qual payload foi montado, qual foi a resposta da API.", color: C.teal },
    { title: "Aprovacao Humana Obrigatoria", desc: "Nenhuma nota e enviada sem aprovacao explicita do operador. O lote inteiro precisa ser revisado e aprovado antes de qualquer POST ao iScholar.", color: C.accent },
    { title: "Idempotencia no Envio", desc: "O endpoint /notas/lanca_nota e idempotente por contrato. Reenviar o mesmo lancamento nao duplica a nota. O sistema verifica via hash de conteudo.", color: C.green },
    { title: "Separacao Clara: Regras vs Codigo", desc: "Regras pedagogicas ficam em avaliacao_rules.py, isoladas do HTTP, do banco e da CLI. Podem ser testadas e alteradas independentemente.", color: "7C3AED" },
    { title: "Dry-Run antes de Tudo", desc: "O operador pode rodar o pipeline inteiro sem enviar nada ao iScholar. Valida planilha, resolve IDs, monta payloads — mas nao faz POST real.", color: C.darkBlue },
  ];

  decisions.forEach((d, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.3 + col * 4.85;
    const y = 1.1 + row * 1.4;

    addCard(s, x, y, 4.55, 1.25, { accentColor: d.color });
    s.addText(d.title, {
      x: x + 0.25, y: y + 0.1, w: 4.1, h: 0.3,
      fontSize: 13, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
    });
    s.addText(d.desc, {
      x: x + 0.25, y: y + 0.4, w: 4.1, h: 0.75,
      fontSize: 10, fontFace: "Calibri", color: C.darkGray, margin: 0,
    });
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 10 — COMO FUNCIONA O CODIGO (MODULOS)
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Estrutura do Codigo — 15+ Modulos", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  const modules = [
    { name: "cli_envio.py", role: "Orquestrador principal (entrypoint)", group: "Nucleo" },
    { name: "madan_planilha_mapper.py", role: "Normalizacao de colunas e template", group: "Nucleo" },
    { name: "avaliacao_rules.py", role: "Regras pedagogicas isoladas", group: "Nucleo" },
    { name: "transformador.py", role: "Planilha wide → lancamentos canonicos", group: "Nucleo" },
    { name: "validacao_pre_envio.py", role: "Qualificacao pre-envio com issues", group: "Nucleo" },
    { name: "aprovacao_lote.py", role: "Resumo, elegibilidade, aprovacao", group: "Controle" },
    { name: "aprovacao_lote_store.py", role: "Persistencia do estado do lote", group: "Controle" },
    { name: "lote_itens_store.py", role: "Persistencia dos itens aprovados", group: "Controle" },
    { name: "resolvedor_ids_ischolar.py", role: "Resolucao hibrida: API + DE-PARA", group: "Integracao" },
    { name: "ischolar_client.py", role: "Cliente HTTP (7 endpoints, 7 dataclasses)", group: "Integracao" },
    { name: "envio_lote.py", role: "Envio item a item com rastreabilidade", group: "Integracao" },
    { name: "envio_lote_audit_store.py", role: "Auditoria por item (SQLite)", group: "Integracao" },
  ];

  const groupColors = { "Nucleo": C.teal, "Controle": C.accent, "Integracao": "7C3AED" };

  const hOpts = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 10, fontFace: "Calibri", valign: "middle" };

  const rows = modules.map(m => {
    const gColor = groupColors[m.group];
    return [
      { text: m.group, options: { fontSize: 9, fontFace: "Calibri", bold: true, color: gColor, align: "center", valign: "middle", fill: { color: C.white } } },
      { text: m.name, options: { fontSize: 10, fontFace: "Consolas", color: C.navy, valign: "middle" } },
      { text: m.role, options: { fontSize: 10, fontFace: "Calibri", color: C.darkGray, valign: "middle" } },
    ];
  });

  s.addTable([
    [{ text: "Camada", options: hOpts }, { text: "Arquivo", options: hOpts }, { text: "Responsabilidade", options: hOpts }],
    ...rows,
  ], {
    x: 0.3, y: 1.0, w: 9.4,
    colW: [1.0, 3.0, 5.4],
    border: { pt: 0.5, color: "CBD5E1" },
    rowH: [0.3, ...Array(12).fill(0.32)],
  });

  s.addText("+ alertas.py, logger.py, descobrir_ids_ischolar.py, .env.example, mapas JSON", {
    x: 0.5, y: 5.15, w: 9, h: 0.3,
    fontSize: 10, fontFace: "Calibri", italic: true, color: C.gray, margin: 0,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 11 — TESTES E QUALIDADE
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Cobertura de Testes — 265 Testes Automatizados", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  // Big stat
  s.addShape(pres.shapes.OVAL, {
    x: 0.5, y: 1.2, w: 2.0, h: 2.0,
    fill: { color: C.green }, shadow: mkShadow(),
  });
  s.addText("265", {
    x: 0.5, y: 1.35, w: 2.0, h: 1.0,
    fontSize: 48, fontFace: "Calibri", bold: true,
    color: C.white, align: "center", valign: "middle", margin: 0,
  });
  s.addText("PASSANDO", {
    x: 0.5, y: 2.25, w: 2.0, h: 0.5,
    fontSize: 12, fontFace: "Calibri", bold: true,
    color: C.white, align: "center", valign: "middle", margin: 0,
  });

  s.addText("0 falhas", {
    x: 0.5, y: 2.75, w: 2.0, h: 0.3,
    fontSize: 14, fontFace: "Calibri", bold: true,
    color: C.white, align: "center", margin: 0,
  });

  // Test suites
  const hOpts = { fill: { color: C.navy }, color: C.white, bold: true, fontSize: 9, fontFace: "Calibri", valign: "middle" };
  const cOpts = { fontSize: 9, fontFace: "Calibri", color: C.darkGray, valign: "middle" };

  const suites = [
    ["test_resolvedor_ids_ischolar", "63", "Resolucao de IDs, mapas, fail-closed"],
    ["teste_envio_lote", "44", "Envio, auditoria, dry-run, aprovacao"],
    ["test_novos_endpoints", "37", "Novos endpoints, envelope, coercao"],
    ["test_avaliacao_rules", "36", "Regras pedagogicas, pesos, notas"],
    ["test_validacao_pre_envio", "25", "Validacao pre-envio, duplicidade"],
    ["test_madan_planilha_mapper", "18", "Template, colunas, aliases, RA"],
    ["test_worker_retry", "12", "Worker legado (compatibilidade)"],
    ["test_transformador", "12", "Transformacao canonica, RA"],
    ["test_cli_envio", "8", "CLI completo, exit codes"],
    ["Outros (5 suites)", "10", "Alertas, snapshots, jobs, client"],
  ];

  const rows = suites.map(([name, count, desc]) => [
    { text: name, options: { ...cOpts, fontFace: "Consolas", fontSize: 8 } },
    { text: count, options: { ...cOpts, align: "center", bold: true } },
    { text: desc, options: cOpts },
  ]);

  s.addTable([
    [{ text: "Suite", options: hOpts }, { text: "Qtd", options: { ...hOpts, align: "center" } }, { text: "O que testa", options: hOpts }],
    ...rows,
  ], {
    x: 2.8, y: 1.2, w: 6.8,
    colW: [2.4, 0.5, 3.9],
    border: { pt: 0.5, color: "CBD5E1" },
    rowH: [0.3, ...Array(10).fill(0.28)],
  });

  // What's tested
  s.addText("O que os testes cobrem:", {
    x: 0.5, y: 4.5, w: 2.5, h: 0.3,
    fontSize: 12, fontFace: "Calibri", bold: true, color: C.navy, margin: 0,
  });

  const coverage = [
    "RA obrigatorio no template e schema",
    "Resolucao e fallback de id_matricula",
    "Envelope 'dados' da API",
    "Exit codes do CLI",
    "Aprovacao e rejeicao de lote",
    "Dry-run sem POST real",
  ];

  s.addText(coverage.map((c, i) => ({
    text: c,
    options: { bullet: true, breakLine: i < coverage.length - 1, fontSize: 10 },
  })), {
    x: 0.5, y: 4.8, w: 9, h: 0.7,
    fontFace: "Calibri", color: C.darkGray, margin: 0, paraSpaceAfter: 2,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 12 — FLUXO OPERACIONAL
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Fluxo Operacional — Como Usar o Sistema", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  const steps = [
    { num: "1", title: "Preencher Planilha", desc: "Usar o template oficial com todas\nas colunas obrigatorias", color: C.navy },
    { num: "2", title: "Dry-Run", desc: "Rodar cli_envio.py --dry-run\npara validar tudo sem enviar", color: C.darkBlue },
    { num: "3", title: "Corrigir Erros", desc: "Sistema mostra exatamente o que\nesta errado e onde", color: C.teal },
    { num: "4", title: "Aprovar Lote", desc: "Operador revisa resumo e\naprova explicitamente", color: C.accent },
    { num: "5", title: "Enviar", desc: "Sistema envia nota por nota\nao iScholar via API", color: C.green },
    { num: "6", title: "Conferir", desc: "Auditoria completa disponivel\npor item enviado", color: "059669" },
  ];

  steps.forEach((st, i) => {
    const col = i % 3;
    const row = Math.floor(i / 3);
    const x = 0.3 + col * 3.2;
    const y = 1.2 + row * 2.1;

    addCard(s, x, y, 2.95, 1.8, {});

    // Number circle
    s.addShape(pres.shapes.OVAL, {
      x: x + 1.1, y: y + 0.15, w: 0.65, h: 0.65,
      fill: { color: st.color },
    });
    s.addText(st.num, {
      x: x + 1.1, y: y + 0.15, w: 0.65, h: 0.65,
      fontSize: 22, fontFace: "Calibri", bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0,
    });

    s.addText(st.title, {
      x: x + 0.15, y: y + 0.9, w: 2.65, h: 0.3,
      fontSize: 14, fontFace: "Calibri", bold: true,
      color: C.navy, align: "center", margin: 0,
    });

    s.addText(st.desc, {
      x: x + 0.15, y: y + 1.2, w: 2.65, h: 0.5,
      fontSize: 10, fontFace: "Calibri",
      color: C.darkGray, align: "center", margin: 0,
    });
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 13 — STATUS ATUAL
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.offWhite };

  s.addText("Status Atual do Projeto", {
    x: 0.6, y: 0.3, w: 9, h: 0.6,
    fontSize: 28, fontFace: "Calibri", bold: true,
    color: C.navy, margin: 0,
  });

  // Progress bar
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.05, w: 9, h: 0.35, fill: { color: "E2E8F0" } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.05, w: 7.8, h: 0.35, fill: { color: C.green } });
  s.addText("~87% concluido", {
    x: 0.5, y: 1.05, w: 9, h: 0.35,
    fontSize: 12, fontFace: "Calibri", bold: true,
    color: C.white, align: "center", valign: "middle", margin: 0,
  });

  // Done column
  addCard(s, 0.3, 1.65, 5.8, 3.6, { accentColor: C.green });
  s.addText("Pronto e Testado", {
    x: 0.55, y: 1.75, w: 3, h: 0.3,
    fontSize: 14, fontFace: "Calibri", bold: true, color: C.green, margin: 0,
  });

  const done = [
    "Template fixo com validacao automatica",
    "Transformacao canonica com RA no schema",
    "Regras pedagogicas (pesos, AV3, ponto extra)",
    "Validacao pre-envio com issues bloqueantes",
    "Aprovacao manual do lote com snapshot",
    "Client iScholar com 7 endpoints + dataclasses",
    "Resolucao hibrida de IDs com fallback",
    "Envio por item com dry-run",
    "3 stores SQLite endurecidos",
    "Auditoria por item enviado",
    "Script de discovery de IDs",
    "Autopreenchimento de mapas via API",
    "265 testes automatizados passando",
  ];

  s.addText(done.map((d, i) => ({
    text: d,
    options: { bullet: true, breakLine: i < done.length - 1, fontSize: 10 },
  })), {
    x: 0.55, y: 2.1, w: 5.3, h: 3.0,
    fontFace: "Calibri", color: C.darkGray, margin: 0, paraSpaceAfter: 2,
  });

  // Pending column
  addCard(s, 6.3, 1.65, 3.4, 3.6, { accentColor: C.orange });
  s.addText("Falta (externo)", {
    x: 6.55, y: 1.75, w: 3, h: 0.3,
    fontSize: 14, fontFace: "Calibri", bold: true, color: C.orange, margin: 0,
  });

  const pending = [
    "Token de acesso ao iScholar",
    "Regra OBJ + DISC",
    "Regra de recuperacao",
    "Definicao de 'fechada'",
    "Regras da 3a serie",
    "Piloto controlado",
    "Teste com dados reais",
    "Validacao do shape da API",
  ];

  s.addText(pending.map((p, i) => ({
    text: p,
    options: { bullet: true, breakLine: i < pending.length - 1, fontSize: 10 },
  })), {
    x: 6.55, y: 2.1, w: 2.9, h: 3.0,
    fontFace: "Calibri", color: C.darkGray, margin: 0, paraSpaceAfter: 2,
  });
}

// ════════════════════════════════════════════════════════════
// SLIDE 14 — PROXIMOS PASSOS
// ════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.navy };

  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });

  s.addText("Proximos Passos", {
    x: 0.6, y: 0.3, w: 9, h: 0.7,
    fontSize: 32, fontFace: "Calibri", bold: true,
    color: C.white, margin: 0,
  });

  s.addText("O que precisamos de voces para entrar em homologacao", {
    x: 0.6, y: 0.95, w: 8, h: 0.3,
    fontSize: 14, fontFace: "Calibri", color: C.mint, margin: 0,
  });

  const nextSteps = [
    { num: "1", title: "Token do iScholar", desc: "Gerar o token de acesso no ambiente de homologacao. Sem ele, nao conseguimos testar nada com dados reais.", urgent: true },
    { num: "2", title: "Definicoes Pedagogicas", desc: "Como OBJ + DISC combinam? Recuperacao existe? O que e 'avaliacao fechada'? Regras da 3a serie?", urgent: false },
    { num: "3", title: "Template Aprovado", desc: "Confirmar que o modelo da planilha esta OK. Lista de disciplinas e professores com nomes exatos.", urgent: false },
    { num: "4", title: "Piloto Controlado", desc: "Escolher 3-5 alunos de uma turma para o primeiro teste real. Acompanhar o lancamento juntos.", urgent: false },
  ];

  nextSteps.forEach((ns, i) => {
    const y = 1.5 + i * 0.95;
    const cardColor = ns.urgent ? "1E3A5F" : C.darkBlue;

    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y, w: 9, h: 0.8,
      fill: { color: cardColor },
      shadow: mkShadow(),
    });

    // Number
    s.addShape(pres.shapes.OVAL, {
      x: 0.7, y: y + 0.12, w: 0.55, h: 0.55,
      fill: { color: ns.urgent ? C.accent : C.teal },
    });
    s.addText(ns.num, {
      x: 0.7, y: y + 0.12, w: 0.55, h: 0.55,
      fontSize: 20, fontFace: "Calibri", bold: true,
      color: C.white, align: "center", valign: "middle", margin: 0,
    });

    s.addText(ns.title + (ns.urgent ? "  ← MAIS URGENTE" : ""), {
      x: 1.5, y: y + 0.05, w: 7.5, h: 0.3,
      fontSize: 15, fontFace: "Calibri", bold: true,
      color: ns.urgent ? C.accent : C.white, margin: 0,
    });

    s.addText(ns.desc, {
      x: 1.5, y: y + 0.38, w: 7.5, h: 0.35,
      fontSize: 11, fontFace: "Calibri",
      color: C.gray, margin: 0,
    });
  });

  // Bottom bar
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.325, w: 10, h: 0.3, fill: { color: C.teal, transparency: 70 } });
  s.addText("Com o token + definicoes, entramos em homologacao em menos de 1 semana.", {
    x: 0.5, y: 5.33, w: 9, h: 0.25,
    fontSize: 12, fontFace: "Calibri", bold: true,
    color: C.white, align: "center", margin: 0,
  });
}

// ════════════════════════════════════════════════════════════
// SAVE
// ════════════════════════════════════════════════════════════
const outPath = "C:\\Users\\PICHAU\\Desktop\\Claude Cenario 2\\apresentacao_madan_ischolar.pptx";
pres.writeFile({ fileName: outPath }).then(() => {
  console.log("Apresentacao criada: " + outPath);
}).catch(err => {
  console.error("Erro:", err);
});
