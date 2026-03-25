const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
        Header, Footer, AlignmentType, LevelFormat, HeadingLevel,
        BorderStyle, WidthType, ShadingType, PageNumber, PageBreak } = require("docx");

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const headerBorder = { style: BorderStyle.SINGLE, size: 1, color: "2E5090" };
const headerBorders = { top: headerBorder, bottom: headerBorder, left: headerBorder, right: headerBorder };

const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };

function headerCell(text, width) {
  return new TableCell({
    borders: headerBorders,
    width: { size: width, type: WidthType.DXA },
    shading: { fill: "2E5090", type: ShadingType.CLEAR },
    margins: cellMargins,
    verticalAlign: "center",
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, color: "FFFFFF", font: "Arial", size: 20 })] })]
  });
}

function cell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    margins: cellMargins,
    children: [new Paragraph({ children: [new TextRun({ text, font: "Arial", size: 20 })] })]
  });
}

function checkCell(text, width) {
  return new TableCell({
    borders,
    width: { size: width, type: WidthType.DXA },
    margins: cellMargins,
    children: [new Paragraph({ children: [
      new TextRun({ text: "\u2610 ", font: "Segoe UI Symbol", size: 20 }),
      new TextRun({ text, font: "Arial", size: 20 })
    ] })]
  });
}

function heading1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200 },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 32, color: "2E5090" })]
  });
}

function heading2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 160 },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 26, color: "2E5090" })]
  });
}

function heading3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 200, after: 120 },
    children: [new TextRun({ text, bold: true, font: "Arial", size: 22, color: "404040" })]
  });
}

function para(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 120 },
    children: [new TextRun({ text, font: "Arial", size: 20, ...opts })]
  });
}

function quote(text) {
  return new Paragraph({
    spacing: { after: 120 },
    indent: { left: 400 },
    border: { left: { style: BorderStyle.SINGLE, size: 8, color: "2E5090", space: 8 } },
    children: [new TextRun({ text, font: "Arial", size: 20, italics: true, color: "444444" })]
  });
}

function emptyLine() {
  return new Paragraph({ spacing: { after: 80 }, children: [] });
}

function separator() {
  return new Paragraph({
    spacing: { before: 200, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 4 } },
    children: []
  });
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: "2E5090" },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: "2E5090" },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, font: "Arial", color: "404040" },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 } },
    ]
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ] },
      { reference: "checks", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "\u2610", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ] },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1200, bottom: 1200, left: 1200 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "2E5090", space: 6 } },
          spacing: { after: 200 },
          children: [
            new TextRun({ text: "Roteiro de Reuniao \u2014 Pedagogico Madan", font: "Arial", size: 16, color: "888888" }),
          ]
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          border: { top: { style: BorderStyle.SINGLE, size: 2, color: "CCCCCC", space: 6 } },
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Pagina ", font: "Arial", size: 16, color: "888888" }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: "888888" }),
          ]
        })]
      })
    },
    children: [

      // ============================================================
      // CAPA
      // ============================================================
      emptyLine(), emptyLine(), emptyLine(), emptyLine(),

      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 120 },
        children: [new TextRun({ text: "ROTEIRO DE REUNIAO", font: "Arial", size: 44, bold: true, color: "2E5090" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 400 },
        children: [new TextRun({ text: "Pedagogico do Madan", font: "Arial", size: 36, color: "555555" })]
      }),

      separator(),

      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 80 },
        children: [new TextRun({ text: "Projeto: Pipeline Madan \u2192 iScholar", font: "Arial", size: 22, color: "444444" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 80 },
        children: [new TextRun({ text: "Fase: Homologacao", font: "Arial", size: 22, color: "444444" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 80 },
        children: [new TextRun({ text: "Duracao estimada: 35\u201345 minutos", font: "Arial", size: 22, color: "444444" })]
      }),

      emptyLine(), emptyLine(), emptyLine(),

      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 60 },
        children: [new TextRun({ text: "Objetivo:", font: "Arial", size: 22, bold: true, color: "2E5090" })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 200 },
        children: [new TextRun({
          text: "Fechar todas as pendencias que dependem exclusivamente do Madan para que o sistema entre em homologacao.",
          font: "Arial", size: 22, color: "444444"
        })]
      }),

      new PageBreak(),

      // ============================================================
      // ABERTURA
      // ============================================================
      heading1("Abertura (2 min)"),

      quote("O sistema de lancamento automatico de notas no iScholar esta com o desenvolvimento finalizado. O TI do iScholar ja liberou o ambiente de homologacao. O que falta para avancarmos sao definicoes do lado pedagogico de voces."),

      separator(),

      // ============================================================
      // BLOCO 1 - TEMPLATE
      // ============================================================
      heading1("Bloco 1 \u2014 Template da Planilha (10 min)"),

      heading2("O que explicar"),
      para("O sistema nao aceita planilhas livres. Existe um modelo fixo com colunas obrigatorias que voces vao preencher. Tudo que nao estiver nesse modelo sera rejeitado automaticamente."),

      heading2("Confirmar coluna por coluna"),

      new Table({
        width: { size: 9840, type: WidthType.DXA },
        columnWidths: [2400, 7440],
        rows: [
          new TableRow({ children: [headerCell("Coluna", 2400), headerCell("Pergunta para o Madan", 7440)] }),
          new TableRow({ children: [cell("Estudante", 2400), cell("O nome completo do aluno, certo? Exatamente como aparece no iScholar?", 7440)] }),
          new TableRow({ children: [cell("RA", 2400), cell("Todo aluno tem RA? Voces conseguem garantir que essa coluna vai estar preenchida em toda planilha?", 7440)] }),
          new TableRow({ children: [cell("Turma", 2400), cell("Qual formato voces usam? 2A, 3B, 1\u00BAA? Preciso saber para alinhar com o mapeamento.", 7440)] }),
          new TableRow({ children: [cell("Trimestre", 2400), cell("Sempre 1, 2 ou 3? Voces trabalham com algum outro periodo?", 7440)] }),
          new TableRow({ children: [cell("Disciplina", 2400), cell("Quais sao todas as disciplinas? Preciso da lista exata com os nomes que voces usam.", 7440)] }),
          new TableRow({ children: [cell("Frente - Professor", 2400), cell("Como voces preenchem isso hoje? Ex.: 'Matematica - Prof. Silva'? Sempre nesse formato?", 7440)] }),
        ]
      }),

      emptyLine(),
      heading3("O que precisa sair definido neste bloco"),

      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Madan aceita adotar o template fixo", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Madan confirma que todo aluno tem RA", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Lista completa de disciplinas com os nomes exatos", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Lista de frentes/professores com os nomes exatos", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Formato de turma padronizado", font: "Arial", size: 20 })] }),

      separator(),

      // ============================================================
      // BLOCO 2 - RA
      // ============================================================
      heading1("Bloco 2 \u2014 RA (5 min)"),

      heading2("O que explicar"),
      quote("O RA e o campo mais importante da planilha. E por ele que o sistema localiza o aluno no iScholar e encontra a matricula certa. Sem RA, o aluno simplesmente nao e processado."),

      heading2("Perguntas diretas"),

      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Todos os alunos de voces tem RA cadastrado no iScholar?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Existe alguma situacao em que o aluno nao tem RA? Aluno novo, transferencia, ouvinte?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Se existir aluno sem RA, qual e o procedimento? Bloqueia o lancamento dele ou voces querem algum tratamento diferente?", font: "Arial", size: 20 })] }),

      heading3("O que precisa sair definido neste bloco"),

      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "RA e sempre preenchido ou ha excecoes", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Procedimento para excecoes (se existirem)", font: "Arial", size: 20 })] }),

      separator(),

      // ============================================================
      // BLOCO 3 - REGRAS DE NOTAS
      // ============================================================
      heading1("Bloco 3 \u2014 Regras de Notas (10 min)"),

      para("Referencia: baseado no documento \"Sistema Avaliativo\" fornecido pelo Madan.", { italics: true }),

      // REGRAS JA CONFIRMADAS
      heading2("Regras ja implementadas (confirmar rapidamente)"),

      para("Mostrar ao Madan o que o sistema ja faz, baseado no PDF do Sistema Avaliativo:"),

      new Table({
        width: { size: 9840, type: WidthType.DXA },
        columnWidths: [2800, 7040],
        rows: [
          new TableRow({ children: [headerCell("Regra", 2800), headerCell("Como o sistema implementa", 7040)] }),
          new TableRow({ children: [cell("Pesos T1/T2 (sem AV3)", 2800), cell("AV1=12, AV2=15, Simulado=3 (total 30)", 7040)] }),
          new TableRow({ children: [cell("Pesos T1/T2 (com AV3)", 2800), cell("AV1=9, AV2=9, AV3=9, Simulado=3 (total 30)", 7040)] }),
          new TableRow({ children: [cell("Pesos T3 (sem AV3)", 2800), cell("AV1=16, AV2=18, Simulado=6 (total 40)", 7040)] }),
          new TableRow({ children: [cell("Pesos T3 (com AV3)", 2800), cell("AV1=12, AV2=12, AV3=12, Simulado=4 (total 40)", 7040)] }),
          new TableRow({ children: [cell("Calculo AV3", 2800), cell("70% listas + 30% avaliacao (0 a 10 cada)", 7040)] }),
          new TableRow({ children: [cell("Ponto Extra", 2800), cell("Somado na coluna AV1, teto de 10. Ignorado se avaliacao fechada.", 7040)] }),
          new TableRow({ children: [cell("Notas", 2800), cell("Digitadas de 0 a 10, pesos aplicados pelo iScholar", 7040)] }),
        ]
      }),

      emptyLine(),
      quote("Tudo isso esta implementado e testado. Quero so confirmar com voces que esta correto antes de ir para producao."),

      emptyLine(),

      // PERGUNTAS PENDENTES
      heading2("Perguntas que o PDF nao responde"),

      // AV1/AV2 OBJ+DISC
      heading3("1. AV1 e AV2 \u2014 Objetiva + Discursiva"),

      para("O que explicar:"),
      quote("O PDF diz que AV1 e AV2 tem peso, mas nao explica como a nota da objetiva e a da discursiva se combinam para formar a nota final da AV1 ou AV2. Hoje o sistema faz media simples. Exemplo: OBJ=7 e DISC=9, resultado=8."),

      para("Perguntas:", { bold: true }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "E media simples mesmo? Ou tem peso diferente entre objetiva e discursiva?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Se o aluno fez so a objetiva e nao fez a discursiva, o que vale? A objetiva sozinha? Ou e zero na discursiva?", font: "Arial", size: 20 })] }),

      emptyLine(),

      // RECUPERACAO
      heading3("2. Recuperacao"),

      para("O que explicar:"),
      quote("O PDF do Sistema Avaliativo nao menciona recuperacao. O sistema hoje preserva a nota mas nao a usa no calculo. Preciso saber como funciona."),

      para("Perguntas:", { bold: true }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Existe recuperacao no Madan? Se sim, como funciona?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Substitui a menor nota? Faz media com a nota anterior? Ou tem regra propria?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Se o aluno tirou 3 no trimestre e 7 na recuperacao, qual nota vai para o diario?", font: "Arial", size: 20 })] }),

      emptyLine(),

      // AVALIACAO FECHADA
      heading3("3. O que significa \"avaliacao fechada\"?"),

      para("O que explicar:"),
      quote("O PDF diz que o ponto extra nao se aplica se o aluno 'fechou' a avaliacao. Preciso entender quando uma avaliacao e considerada fechada para programar corretamente."),

      para("Perguntas:", { bold: true }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Fechar a avaliacao significa tirar 10? Ou tem outro criterio?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Essa informacao vem na planilha? Ou e algo que o sistema precisa calcular?", font: "Arial", size: 20 })] }),

      emptyLine(),

      // 3a SERIE
      heading3("4. Regras da 3\u00AA serie"),

      para("O que explicar:"),
      quote("O documento de regras que recebi cobre apenas 1\u00AA e 2\u00AA series. A 3\u00AA serie tem regras diferentes?"),

      para("Perguntas:", { bold: true }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "A 3\u00AA serie usa os mesmos pesos e regras? Ou tem algo diferente?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Existe algum documento de regras para a 3\u00AA serie que voces podem me enviar?", font: "Arial", size: 20 })] }),

      emptyLine(),
      heading3("O que precisa sair definido neste bloco"),

      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Confirmacao dos pesos e regras do PDF", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Consolidacao AV1/AV2: como OBJ + DISC viram uma nota so?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Recuperacao: existe? Como funciona?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Definicao de \"avaliacao fechada\" para ponto extra", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Regras da 3\u00AA serie (iguais ou diferentes?)", font: "Arial", size: 20 })] }),

      separator(),

      // ============================================================
      // BLOCO 4 - OPERACAO
      // ============================================================
      heading1("Bloco 4 \u2014 Operacao do Dia a Dia (5 min)"),

      heading2("Perguntas praticas"),

      new Table({
        width: { size: 9840, type: WidthType.DXA },
        columnWidths: [600, 9240],
        rows: [
          new TableRow({ children: [headerCell("#", 600), headerCell("Pergunta", 9240)] }),
          new TableRow({ children: [cell("1", 600), cell("Quem vai preencher a planilha? Uma pessoa so ou varios professores?", 9240)] }),
          new TableRow({ children: [cell("2", 600), cell("Com que frequencia voces vao enviar notas? Uma vez por trimestre? Semanalmente?", 9240)] }),
          new TableRow({ children: [cell("3", 600), cell("Quem vai aprovar o lote antes do envio? Coordenador? Diretor?", 9240)] }),
          new TableRow({ children: [cell("4", 600), cell("Voces querem que o primeiro envio real seja acompanhado por mim?", 9240)] }),
        ]
      }),

      emptyLine(),
      heading3("O que precisa sair definido neste bloco"),

      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Quem preenche a planilha", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Quem aprova o lote", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Frequencia de envio", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Acompanhamento no primeiro envio real", font: "Arial", size: 20 })] }),

      separator(),

      // ============================================================
      // BLOCO 5 - ACESSO AO ISCHOLAR
      // ============================================================
      heading1("Bloco 5 \u2014 Acesso ao iScholar (5 min)"),

      heading2("O que explicar"),
      quote("Para eu conseguir configurar e testar o sistema, preciso de acesso ao ambiente de homologacao do iScholar. O TI do iScholar ja criou o ambiente de testes, mas eu preciso que voces gerem um token de acesso para mim. Sem esse token, eu nao consigo avancar com nenhum teste real."),

      heading2("O que preciso de voces"),

      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Acesso a interface de homologacao: https://madan_homolog.ischolar.com.br/", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Gerar um token de API nessa interface (eu posso explicar o passo a passo, leva 2 minutos)", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Se voces ja tem login no iScholar, podemos fazer isso agora na reuniao", font: "Arial", size: 20 })] }),

      emptyLine(),

      para("Por que isso e importante:", { bold: true }),
      quote("O sistema esta 100% pronto no lado do codigo. Mas ele precisa se conectar ao iScholar para funcionar. O token e como a 'senha' que permite essa conexao. Sem ele, o sistema roda no vazio \u2014 consigo simular tudo, mas nao consigo validar com dados reais."),

      heading3("O que precisa sair definido neste bloco"),

      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Quem no Madan tem acesso administrativo ao iScholar", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Token de API gerado (ou prazo para gerar)", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Confirmacao de que posso usar o ambiente de homologacao livremente para testes", font: "Arial", size: 20 })] }),

      separator(),

      // ============================================================
      // BLOCO 6 - PILOTO
      // ============================================================
      heading1("Bloco 6 \u2014 Piloto Controlado (5 min)"),

      heading2("O que propor"),
      quote("Antes de enviar todas as notas, vamos fazer um piloto com 3\u20135 alunos de uma turma. Eu acompanho, a gente confere no diario do iScholar se bateu, e so depois abrimos para o lote completo."),

      heading2("Perguntas"),

      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Qual turma voces sugerem para o piloto?", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Quais alunos eu posso usar? Preciso dos RAs.", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Qual trimestre esta pronto para testar?", font: "Arial", size: 20 })] }),

      heading3("O que precisa sair definido neste bloco"),

      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Turma do piloto", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "3\u20135 RAs de alunos de teste", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Trimestre para o piloto", font: "Arial", size: 20 })] }),

      separator(),

      // ============================================================
      // FECHAMENTO
      // ============================================================
      heading1("Fechamento (3 min)"),

      para("Resumir o que ficou definido e o que ainda ficou pendente:"),

      quote("As regras de peso e calculo de AV3 e ponto extra ja estao implementadas com base no PDF de voces. O que falta para eu avancar: 1) Confirmacao do template; 2) Lista de disciplinas e frentes/professores; 3) Definicao de como OBJ+DISC viram uma nota; 4) Regras de recuperacao; 5) Token de acesso ao iScholar; 6) 3\u20135 RAs para o piloto. O token continua sendo o item mais urgente \u2014 sem ele nao consigo fazer nenhum teste real."),

      para("Combinar prazo:", { bold: true }),
      new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 80 },
        children: [new TextRun({ text: "Voces conseguem me mandar a lista de disciplinas e os RAs ate [data]?", font: "Arial", size: 20 })] }),

      new PageBreak(),

      // ============================================================
      // CHECKLIST FINAL
      // ============================================================
      heading1("Checklist Final \u2014 Levar para a Reuniao"),

      heading2("Levar"),

      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Template da planilha impresso ou no notebook", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Este roteiro impresso", font: "Arial", size: 20 })] }),
      new Paragraph({ numbering: { reference: "checks", level: 0 }, spacing: { after: 60 },
        children: [new TextRun({ text: "Papel/bloco para anotar as respostas", font: "Arial", size: 20 })] }),

      emptyLine(),
      heading2("Sair da reuniao com"),

      new Table({
        width: { size: 9840, type: WidthType.DXA },
        columnWidths: [600, 6640, 2600],
        rows: [
          new TableRow({ children: [
            headerCell("#", 600),
            headerCell("Item", 6640),
            headerCell("Resposta", 2600),
          ] }),
          new TableRow({ children: [cell("1", 600), cell("Template aprovado pelo Madan", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("2", 600), cell("Lista de disciplinas (nomes exatos)", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("3", 600), cell("Lista de frentes/professores (nomes exatos)", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("4", 600), cell("Formato de turma padronizado", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("5", 600), cell("Confirmacao pesos/AV3/ponto extra do PDF", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("6", 600), cell("Como OBJ + DISC combinam (AV1/AV2)", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("7", 600), cell("Definicao de \"avaliacao fechada\"", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("8", 600), cell("Regra de recuperacao", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("9", 600), cell("Confirmacao de RA obrigatorio", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("10", 600), cell("Token de acesso ao iScholar (homologacao)", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("11", 600), cell("Confirmacao de uso livre do ambiente de homologacao", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("12", 600), cell("3\u20135 RAs para piloto", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("13", 600), cell("Nome de quem preenche e quem aprova", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("14", 600), cell("Regras da 3\u00AA serie (iguais ou diferentes?)", 6640), cell("", 2600)] }),
          new TableRow({ children: [cell("15", 600), cell("Prazo para entrega das listas", 6640), cell("", 2600)] }),
        ]
      }),

    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  const outPath = "C:\\Users\\PICHAU\\Desktop\\Claude Cenario 2\\roteiro_reuniao_madan.docx";
  fs.writeFileSync(outPath, buffer);
  console.log("Documento criado: " + outPath);
});
