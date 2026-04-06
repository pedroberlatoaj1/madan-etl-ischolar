# Checklist de Aceite — Go-Live Assistido

Projeto: Madan -> iScholar ETL
Data de preparacao: 2026-04-05
Status: **PENDENTE DE ACEITE**

---

## O que foi provado

### Via CLI (terminal)
- [x] POST real em 4 disciplinas distintas (Arte, Ingles, Fisica A, Gramatica)
- [x] Dry-run com 30 itens, zero erros
- [x] Notas confirmadas visualmente no diario do iScholar
- [x] Idempotencia: reenvio do mesmo lote bloqueado antes de qualquer POST
- [x] Bug de mapeamento de disciplina diagnosticado e corrigido via audit DB

### Via Google Sheets (sem terminal)
- [x] Gate de validacao: POST /webhook/notas → worker → polling → dialog (Execucao 004)
- [x] Autenticacao: sem secret → 401, com secret → 404 na rota protegida
- [x] Onda A: 3/3 enviados, notas confirmadas no diario (Execucao 005)
- [x] Onda B: 71/91 enviados, erros isolados, notas confirmadas por amostragem (Execucao 006)
- [x] snapshot_hash coerente entre validacao e aprovacao
- [x] Polling longo tratado corretamente (Mostrar Ultimo Status)
- [x] Fluxo completo executado sem intervencao do desenvolvedor

### Infraestrutura operacional
- [x] `iniciar_servicos.bat` testado — sobe backend + worker
- [x] `parar_servicos.bat` testado — encerra processos
- [x] `subir_tunel.bat` testado — expoe backend via ngrok
- [x] `google_apps_script.gs` versionado com placeholders seguros

---

## Condicoes para go-live assistido

### Ja cumpridas
- [x] Pipeline validado com POST real em producao
- [x] Escala testada com turma completa (~44 alunos, 2 disciplinas)
- [x] Erros externos isolados sem bloquear envios validos
- [x] Documentacao tecnica e operacional consolidada
- [x] Runbook do operador criado

### Pendentes de sessao com operador
- [ ] Handoff observado: operador executa o fluxo sozinho ao menos uma vez
- [ ] Operador demonstra capacidade de interpretar resultados (send_failed com sucesso parcial)
- [ ] Operador sabe que NAO deve reenviar lote ja aprovado
- [ ] Aceite formal declarado

### Pendentes de admin iScholar
- [ ] 4 alunos com matricula nao acessivel via API (ver `pendencias_admin_ischolar.md`)
- [ ] 6 alunos com grade curricular divergente (ver `pendencias_admin_ischolar.md`)

As pendencias do iScholar NAO bloqueiam o go-live assistido.
O pipeline isola esses alunos automaticamente.

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
| Data do aceite | _(pendente)_ |
| Decision owner | _(pendente)_ |
| Operador | _(pendente)_ |
| Condicao | Go-live assistido com acompanhamento do dev na primeira sessao |
| Observacoes | _(pendente)_ |
