# Seleção de tier por sessão (substitui o classificador)

**Status (2026-10-17):** seleção inicial implementada nas features `0039-session-tier-selection` e `0040-session-tier-polish`; reavaliação periódica implementada, aprovada e integrada em `main` na feature `0041-periodic-tier-reevaluation` em 2026-10-03. Seleção estável implementada e aprovada no ticket 01 da feature 0053 em 2026-10-14; ver [ADR-0009](../../adrs/0009-stable-session-selection.md). Tiers, avaliador e seleção por Session foram removidos pela feature 0054 em 2026-10-16, substituídos pelo par Provider/modelo escolhido pelo usuário; este documento é inteiramente histórico. As decisões e questões abaixo são registros históricos; o [spec 0041](../../specs/0041-periodic-tier-reevaluation.md), [ADR-0007](../../adrs/0007-periodic-session-tier-reevaluation.md) descrevem a política histórica v1.

## Problema original (2026-10-02)

`src/personal_agent/routing/classifier.py` (15 linhas) escolhe o tier por palavras-chave em inglês (`refactor`, `architecture`, `prove`, `debug`, `design a system`) e contagem de palavras (>200 complex, >40 medium). Erra de forma previsível: tarefas em português, pedidos curtos e vagos ("crie um sistema de emissão de nota fiscal" → easy), "continue" sem contexto, textos longos e simples → complex. A Escalation acaba compensando o classificador, com custo maior. O usuário descartou medir o erro (o algoritmo é sabidamente fraco) e descartou Jev (exigiria avaliação de thresholds com dados reais, ver `2026-09-26-jev-routing.md`).

## Decisões originais de 0039 (amendadas por 0041)

1. **Remover o classificador heurístico.** `classifier.py` sai; o `route()` deixa de chamar `classify()`.
2. **Avaliação por LLM só no primeiro prompt da sessão.** O primeiro prompt do usuário é enviado ao tier **easy** para avaliar qual tier a sessão precisa; a resposta deve ser exatamente `easy`, `medium` ou `complex`.
3. **O tier escolhido vale para o resto da sessão.** Não há reavaliação automática depois (risco aceito: um primeiro prompt pouco representativo, como "oi", prende a sessão no tier escolhido; o aviso e o `/model` resolvem).
4. **Aviso visível.** Ex.: `Tier escolhido: medium (avaliado pela LLM). Use /model easy|medium|complex para trocar.`
5. **Troca pelo usuário via `/model`** (Tier Pin da sessão), não `/config` (que persiste modelos por tier no `.env`).
6. **Falha ou resposta inválida da avaliação:** usa `medium` e avisa ("avaliação indisponível").
7. **`/model` antes do primeiro prompt:** não avalia; usa o tier escolhido.
8. **Escalation removida.** Falha técnica após os retries vira erro visível; o usuário decide (`/model` + `/retry`). O gate do Budget Guardrail sobre Escalation (`BudgetGuardrail.allows_escalation`) deixa de ter uso. Isso altera a ADR-0001.
9. **Resume volta com o tier da sessão original** (não reavalia).
10. **Tiers continuam existindo** como slots de modelo configuráveis (`/config`); o easy continua sendo usado pela Compression.
11. **Documentação de identidade muda:** README, `CLAUDE.md` e `docs/CONTEXT.md` deixam de descrever "router by complexity".

## Questões históricas de discovery (resolvidas em 0039/0041)

- **Como persistir o tier da sessão para o Resume.** Opções: derivar do `tier` das entradas `attempt` ordinárias já gravadas no Call Log (sem mudar schema; considerar trocas via `/model` no meio da sessão e excluir Attempts de `/compress`), ou gravar um evento explícito quando o tier é escolhido/trocado. Sessão retomada sem nenhum Attempt ordinário: avaliar no primeiro prompt novo?
- O prompt de avaliação: instrução/rubrica, se inclui Memory/Skills ativas, limite de output, e se a chamada conta no Budget Guardrail e no Call Log como Attempt normal (provavelmente sim, como a Compression).
- Interação com `/retry`, `/undo`, `/clear` (o `/clear` reinicia a avaliação?) e com Agent Mode.
- O que fazer com `ladder_from`, `RouteResult.tier`, o Status Footer e o `/usage`.
- Tratamento da avaliação quando o primeiro "prompt" é um comando (`/compress`, `/skill`) — só tarefas roteadas disparam a avaliação.

## Melhoria originalmente adiada: reavaliação periódica (implementada em 0041)

**Concluída e integrada em `main` (2026-10-03):** discovery confirmada, implementação e revisão independente aprovadas na feature `0041-periodic-tier-reevaluation`. Ver [brief 0041](../../briefs/0041-periodic-tier-reevaluation.md), [spec 0041](../../specs/0041-periodic-tier-reevaluation.md) e [revisão do ticket](../../../tickets/0041-periodic-tier-reevaluation/01-durable-periodic-session-tier.review.md). As questões abaixo preservam a proposta histórica; foram resolvidas na discovery.

Proposta do usuário (2026-10-02): avaliar o tier 3 vezes na sessão, no 1º, 5º e 15º prompt, mandando ao avaliador só o que o usuário digitou (sem tools, skills ou histórico de respostas). Motivação: um primeiro prompt pouco representativo ("oi") prende a sessão em easy. Muda a decisão 3 acima e a ADR-0006, então exige discovery, brief e ADR nova (ou emenda) antes dos tickets.

Questões para a discovery:

- **Entrada do avaliador.** Hoje já vai só o texto da tarefa atual. Na 5ª e 15ª mensagem isso costuma ser "ok, continua" ou "roda os testes", que isolado vira easy. Proposta: enviar as últimas N mensagens do usuário (com limite de tamanho), sem respostas do modelo, tools ou skills.
- **Rebaixar ou só subir.** Descer de tier no meio da sessão pode cair num modelo com janela menor (disparando Compression) e perde cache de prompt. Opções: só subir nas reavaliações, ou permitir descer aceitando o custo.
- **`/model` manual.** Reavaliação não deve sobrescrever um tier escolhido pelo usuário; só reavaliar enquanto a origem for o avaliador.
- **O que conta como prompt.** Só tarefas roteadas; comandos locais (`/clear`, `/undo` etc.) e `/retry` (mesma tarefa) não contam.
- **Resume.** O contador precisa sobreviver ao Resume, derivado do Call Log, sem arquivo de estado novo.
- **Custo.** Até 3 chamadas do avaliador por sessão na rota easy, somadas ao gasto do Run.
