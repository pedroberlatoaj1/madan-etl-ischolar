# Checklist de Aceite — Go-Live Assistido

Projeto: Madan -> iScholar ETL
Data de preparacao: 2026-04-05
Ultima atualizacao: 2026-04-24
Status: **ACEITE CONCLUÍDO — SISTEMA EM PRODUÇÃO**

---

## O que foi provado

### Via CLI (terminal)
- [x] POST real em 4 disciplinas distintas (Arte, Ingles, Fisica A, Gramatica)
- [x] Dry-run com 30 itens, zero erros
- [x] Notas confirmadas visualmente no diario do iScholar
- [x] Idempotencia: reenvio do mesmo lote bloqueado antes de qualquer POST
- [x] Bug de mapeamento de disciplina diagnosticado e corrigido via audit DB

### Via Google Sheets — Apps Script direto ao iScholar (arquitetura final)
- [x] Gate de validacao: POST /webhook/notas → worker → polling → dialog (Execucao 004)
- [x] Autenticacao: sem secret → 401, com secret → 404 na rota protegida
- [x] Onda A: 3/3 enviados, notas confirmadas no diario (Execucao 005)
- [x] Onda B: 71/91 enviados, erros isolados, notas confirmadas por amostragem (Execucao 006)
- [x] snapshot_hash coerente entre validacao e aprovacao
- [x] Polling longo tratado corretamente (Mostrar Ultimo Status)
- [x] Fluxo completo executado sem intervencao do desenvolvedor
- [x] Dry run externo via Apps Script → iScholar validado (2026-04-21)
- [x] Envio real via Apps Script → iScholar validado para todas as 4 turmas (2026-04-21 a 2026-04-23)

### Cobertura de turmas — testes de producao completos (2026-04-21 a 2026-04-23)
- [x] **1A** — 21/21 combinacoes disciplina×frente enviadas + 44/44 alunos (Arte volume) ✅
- [x] **1B** — 21/21 combinacoes disciplina×frente enviadas + 41/41 alunos (Arte volume) ✅
- [x] **2B** — 21/21 combinacoes disciplina×frente enviadas + 45/45 alunos (Arte volume) ✅
- [x] **2A** — 21/21 combinacoes disciplina×frente enviadas + 45/45 alunos (Arte volume) ✅
- [x] Total: ~260 notas reais enviadas ao iScholar, 0 erros nao tratados

### Planilha oficial — matriz Madan 2026 (14 disciplinas)
- [x] `madan_2026_anual.xlsx` gerado com 12 abas (4 turmas x 3 trimestres)
- [x] 175 alunos reais em 4 turmas (1A=44, 1B=41, 2A=45, 2B=45)
- [x] Matriz de disciplinas corrigida e validada em producao:
  - Frente Unica: Arte, Literatura, Filosofia, Sociologia, Gramatica, Redacao, Educacao Fisica, Ingles
  - Frentes A+B: Geografia, Historia, Fisica, Quimica, Biologia
  - Frentes A+B+C: Matematica
- [x] `DISCIPLINAS_OFICIAIS_2026` como unica fonte de verdade em `gerador_planilhas.py`

### Correcoes de mapa aplicadas em producao
- [x] Band-aid `matematica c - luan → 57` adicionado em 2A e 2B (professor certo: Felipe de Castro)
- [x] Band-aid `matematica b - daniel → 71` adicionado em 2A (professor certo: Luan)
- [x] Band-aid `quimica b - leo → 70` adicionado em 2A (professor certo: Marcus Vinicius)
- [x] Band-aid `fisica b - cavaco → 108` adicionado em 2A (professor certo: Pezzin)
- [x] Todos os aliases validados em envio real com notas confirmadas no iScholar

### Infraestrutura operacional
- [x] VPS Hetzner (77.42.26.143) operacional — uptime 2+ dias
- [x] `madan-webhook.service` e `madan-worker.service` ativos via systemd
- [x] Backup automatico diario (cron 03:00 UTC) → Google Drive via rclone
- [x] Restore testado com PRAGMA integrity_check — 6 SQLite DBs OK
- [x] Health check `/status` respondendo com ok=true
- [x] `google_apps_script.gs` instalado na planilha oficial com menu Madan ETL

---

## Condicoes para go-live assistido

### Ja cumpridas
- [x] Pipeline validado com POST real em producao
- [x] Escala testada com turma completa (~44 alunos, 2 disciplinas)
- [x] Erros externos isolados sem bloquear envios validos
- [x] Documentacao tecnica e operacional consolidada
- [x] Runbook do operador criado

### Concluidas em sessao com operador (2026-04-22/23)
- [x] Handoff observado: Marina executou o fluxo validar → aprovar → conferir iScholar de forma autonoma
- [x] Operador demonstra capacidade de interpretar resultados (send_failed com sucesso parcial — caso real: 20/21 com 1 erro_resolucao diagnosticado e corrigido)
- [x] Operador sabe que NAO deve reenviar lote ja aprovado (idempotencia explicada e demonstrada)
- [x] Aceite tecnico declarado pelo desenvolvedor — sistema pronto para entrega (2026-04-24)

### Pendentes de admin iScholar (nao bloqueiam operacao)
- [ ] Correcao semantica em `professores_madan.py` para Felipe de Castro (turmas_2a deveria ser ["A","B"] com frente C, nao ["C"])
- [ ] Idem para Daniel (Mat A), Luan (Mat B), Leo (Quim A), Cavaco (Fis A) no 2o ano
- [ ] 4 alunos com matricula nao acessivel via API (ver `pendencias_admin_ischolar.md`)
- [ ] 6 alunos com grade curricular divergente (ver `pendencias_admin_ischolar.md`)

Os band-aids no `mapa_professores.json` garantem funcionamento correto em producao.
As correcoes semanticas em `professores_madan.py` sao melhorias pos-entrega.

---

## Responsabilidades apos go-live

### Operador / coordenacao
- Organizar lotes homogeneos por turma, trilha e sistema avaliativo
- Conferir notas no diario do iScholar apos cada envio
- Reportar erros sistematicos (nao reenviar indefinidamente)
- Manter as janelas do backend e worker abertas durante o uso

### Admin iScholar
- Resolver os 10 casos documentados em `pendencias_admin_ischolar.md`
- Confirmar permissoes do token de integracao para matriculas CURSANDO

### Desenvolvedor (suporte)
- Disponivel para suporte na primeira sessao de go-live assistido
- Nao e necessario para operacao normal apos handoff

---

## Aceite

| Campo | Valor |
|-------|-------|
| Data do aceite | 2026-04-24 |
| Decision owner | Pedro Berlato (desenvolvedor) |
| Operador | Marina Lima Monteiro |
| Condicao | Go-live assistido concluido — sistema entregue ao Madan em 2026-04-28 |
| Observacoes | ~260 notas reais enviadas em testes de producao. 4 turmas validadas (1A, 1B, 2A, 2B). 14 disciplinas × frentes cobertas. 0 erros nao tratados. Backup automatico diario operacional. Band-aids de professor aplicados e validados. Sistema pronto para uso em producao. |
