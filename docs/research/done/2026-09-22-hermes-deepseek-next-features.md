# Próximas features inspiradas por Hermes e DeepSeek Harness

Data: 2026-09-22. Escopo: pesquisa nos repositórios oficiais [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) e [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness). Não há código copiado, dependência proposta, nem afirmação baseada em fontes secundárias.

**Status em 2026-10-04:** todos os itens 1-7 foram implementados (ver coluna Status), com MCP Resources por stdio em 0034. As features 0022 (`webfetch`, `todo`, glob/regex), 0023 (shell guardrails), 0025/0033 (modos), 0037 (orçamento de contexto) e 0039/0041 (tier por Session) também foram entregues. Este documento preserva a pesquisa de 2026-09-22; propostas, fontes externas e o ponto de partida abaixo são históricos. Ver [CONTEXT](../../CONTEXT.md) e a [comparação de features](2026-09-23-opencode-feature-comparison.md) para as capacidades atuais.

## Ponto de partida (histórico, 2026-09-22)

O `model-router` já tem quatro Providers, três Complexity Tiers, retries, Escalation por falha técnica, Budget Guardrail, Call Log JSONL por Session, Conversation em memória limitada às 20 últimas turns completas, Input Box e um Tool Registry seguro. Os únicos Tools são `calculator` e `current_time`. Por decisão explícita, Conversation não persiste além do processo e Tools não recebem acesso arbitrário ao shell ou ao filesystem. Portanto, estas são extensões candidatas; não são lacunas acidentais.

## Prioridades

| Ordem | Feature | Impacto | Esforço | Aderência | Base | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Toolset de workspace somente leitura | Alto | Médio | Muito alta | Evidência direta + adaptação restrita | ✅ feito — `0009-workspace-tools` |
| 2 | Sessões persistentes, listáveis e retomáveis | Alto | Médio | Alta | Evidência direta | ✅ feito — `0012-session-resume` (desenho diferente do MVP, ver nota) |
| 3 | `/usage` para tokens, contexto e custo | Médio | Baixo | Muito alta | Evidência direta | ✅ feito — commit `9c76758`, 2026-09-24 |
| 4 | Controles de recuperação: `/retry` e `/undo` | Médio | Baixo | Alta | Evidência direta | ✅ feito — `0014-turn-controls` |
| 5 | Override explícito de Tier por turno | Médio | Baixo | Muito alta | Inferência do problema do Router | ✅ feito — `0014-turn-controls` (`/model`) |
| 6 | `/compact` explícito para contexto longo | Alto | Médio | Média | Evidência direta, mas conflita com decisão atual se for automático | ✅ feito — `0020-auto-compress`, **decisão revertida** (ver nota) |
| 7 | Integração MCP mínima, começando por Resources | Alto | Alto | Média | Evidência direta | ✅ implementado (`0034-mcp-resources`, Resources por stdio) — candidato 5 em `2026-09-23-opencode-feature-comparison.md` |

### 1. Toolset de workspace somente leitura

**MVP.** Adicionar apenas `list_files`, `read_file` e `search_text`, todos confinados a um `ROUTER_WORKSPACE` absoluto e existente. Limitar profundidade, tamanho de arquivo e número de resultados; negar symlinks que escapem da raiz; nunca expor variáveis de ambiente, comandos, escrita ou patch nesta feature. Assim o modelo pode inspecionar um projeto antes de responder sem transformar o Router em um agente com execução arbitrária.

**Por que primeiro.** Hoje o loop de Tool calling já está pronto e auditável, mas os dois Tools não permitem resolver uma tarefa sobre o projeto do usuário. O Hermes anuncia Toolsets e o DeepSeek documenta um catálogo de Tools model-facing com JSON Schema. Mais importante: o DeepSeek adverte que execução de código, plugins e acesso a arquivos/credenciais têm risco real, e recomenda menor privilégio. A conclusão é uma adaptação deliberadamente pequena e segura, não a cópia de um terminal Tool.

**Evidência direta.** [Hermes README: Tools & Toolsets](https://github.com/NousResearch/hermes-agent/blob/main/README.md#documentation), [DeepSeek Tool Schema Catalog](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/tool-catalog.md), [DeepSeek Safety](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md).

### 2. Sessões persistentes, listáveis e retomáveis

**MVP.** Persistir um Transcript de turns concluídas separado do Call Log: `/sessions`, `/resume <id>` e `/forget <id>`. Cada registro deve preservar papéis e resultados de Tools suficientes para remontar a Conversation; o Call Log continua sendo o registro de Attempts/custos, não vira uma fonte de estado por acidente. Começar sem memória semântica, perfil de usuário ou busca por IA.

**Por que agora.** A Session atual perde a Conversation ao encerrar; o JSONL existente registra Provider exchanges, mas não foi desenhado como transcript canônico. Hermes persiste e pesquisa sessões; DeepSeek separa fatos duráveis em `session/event` de estado ao vivo de `agent/*`. Isso confirma o desenho de separar replay persistente da UI/loop corrente.

**Decisão pendente.** Esta feature muda a decisão atual de Conversation efêmera. Antes de implementá-la, definir retenção, local do arquivo, se o default é opt-in e a semântica de `/forget`.

**Evidência direta.** [Hermes: armazenamento de estado](https://github.com/NousResearch/hermes-agent/blob/main/hermes_state_dbfile.py), [Hermes: busca de sessões](https://github.com/NousResearch/hermes-agent/blob/main/hermes_state_search.py), [DeepSeek: lifecycle e replay durável](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/agent-lifecycle.md).

**Nota de implementação (`0012-session-resume`, 2026-09-24).** O desenho final não usa `/sessions`/`/resume <id>`/`/forget <id>` como comandos de REPL. Em vez disso: o Call Log JSONL vira o transcript canônico (Turn End entries), e um flag de startup `--resume <session-id>` (ou `--resume last`) reconstrói a Conversation a partir dele. `/forget` acabou reaproveitado depois pela feature `0015-persistent-memory` para outra coisa (remover uma Memory Note por índice) — não tem relação com sessões.

### 3. `/usage`: transparência de contexto e custo

**MVP.** Um comando local que mostra, sem chamada ao Provider: Tier/modelo da última resposta, custo da Session, custo estimado versus reportado, número de turns retidas/enviadas e contagem de tokens disponível por Attempt. O Footer permanece compacto; `/usage` mostra os detalhes.

**Por que vale o pequeno diff.** O projeto já captura usage e custo, e já informa spend no Footer; falta tornar compreensível o que o Context Window está descartando e quanto foi consumido. Hermes expõe `/usage`; DeepSeek mantém um `token-meter` como capability separada. Esta é uma inferência de produto pequena apoiada nessas capacidades, não a importação da arquitetura deles.

**Evidência direta.** [Hermes README: `/usage`](https://github.com/NousResearch/hermes-agent/blob/main/README.md#cli-vs-messaging-quick-reference), [DeepSeek capability seams: `token-meter`](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/capability-seams.md).

### 4. Recuperação local: `/retry` e `/undo`

**MVP.** `/retry` reenvia o último task do usuário mantendo a Conversation anterior; `/undo` remove a última turn concluída apenas da Conversation ativa. O Call Log continua append-only e registra a nova Attempt normalmente. Não confundir `/retry` com retry técnico automático nem fazer rollback de custo.

**Por que vale o pequeno diff.** A pessoa pode corrigir uma resposta ruim sem copiar a pergunta e pode retirar um desvio de contexto sem reiniciar tudo. O Hermes expõe esses dois comandos em CLI e mensageria. A aplicabilidade ao Router é uma inferência direta de UX.

**Evidência direta.** [Hermes README: `/retry` e `/undo`](https://github.com/NousResearch/hermes-agent/blob/main/README.md#cli-vs-messaging-quick-reference).

### 5. Override explícito de Tier por turno

**MVP.** Um prefixo ou comando inequívoco, por exemplo `/tier complex <task>`, que ignora o Classifier somente naquele task e ainda usa o Tier Config, retry, Budget Guardrail e Call Log já existentes. Exibir no resultado que a seleção foi manual. Não adicionar um seletor de modelo livre nem configuração nova.

**Por que vale o pequeno diff.** O Classifier usa sinais superficiais; o usuário sabe quando uma pergunta curta requer raciocínio caro ou quando uma longa é trivial. Hermes oferece troca explícita de modelo; aplicar o mesmo princípio ao contrato local de Tiers é uma **inferência**, não uma feature literalmente presente nas fontes.

**Evidência direta e limite da evidência.** [Hermes README: `/model`](https://github.com/NousResearch/hermes-agent/blob/main/README.md#cli-vs-messaging-quick-reference) prova o controle explícito de escolha. A sintaxe `/tier` e seu mapeamento para `easy`/`medium`/`complex` são proposta deste projeto.

**Atualização de implementação (0039/0041).** `/model <tier>` agora escolhe o tier durável da Session e suspende avaliação; `/model auto` preserva tier/progresso e pede avaliação na próxima execução. Sessions novas avaliam pedidos acumulados antes das tarefas 1/5/15. Não há Tier Pin por Run, Classifier, Escalation ou teto monetário.

### 6. `/compact` explícito, não compactação silenciosa

**MVP.** Quando a Conversation ficar grande, `/compact` salva o transcript bruto e pede uma única síntese estruturada, substituindo apenas o contexto ativo. A saída deve informar claramente que houve compactação e quantas turns foram resumidas. Não rodar em segundo plano e não persistir a síntese como memória de usuário.

**Por que não é prioridade maior.** Hermes fornece `/compress`, e DeepSeek tem compaction para pressão de contexto e overflow. Porém, o projeto decidiu não resumir silenciosamente; automatizar isso contrariaria essa decisão e pode deformar detalhes de Tool calls. O comando explícito preserva a escolha do usuário, mas deve esperar a decisão sobre sessões persistentes.

**Evidência direta.** [Hermes README: `/compress`](https://github.com/NousResearch/hermes-agent/blob/main/README.md#cli-vs-messaging-quick-reference), [DeepSeek lifecycle: compaction](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/agent-lifecycle.md).

**Nota de implementação (`0020-auto-compress`, 2026-09-24).** Esta seção recomendava só o `/compress` explícito e alertava que automatizar contrariaria a decisão de não resumir silenciosamente. A decisão foi revertida deliberadamente: `0020` manteve `/compress` manual e **acrescentou** um gatilho automático por tokens (80% do limite de contexto do modelo respondente, via `litellm.get_model_info`), seguido de um Continuation Turn sintético (não reenvia a tarefa original), com trava de 1 ciclo por tarefa digitada. Ver `docs/CONTEXT.md` para o racional da reversão.

**Atualização de implementação (0037).** O gatilho pós-resposta e o Continuation Turn de 0020 foram substituídos por Compression preventiva, medindo o input completo antes de cada exchange. O alvo de 60% é best-effort; o teto de input é obrigatório. A execução continua o exchange pendente, sem tarefa sintética. Ver [spec 0037](../../specs/0037-context-window.md).

### 7. MCP mínimo para Resources, não um ecossistema de plugins

**MVP.** Suportar configuração opt-in de um servidor MCP e somente as operações de Resources (`list templates`, `list`, `read`). Exigir allowlist de servidor e mostrar a origem na linha de Tool. Deixar Tools MCP de escrita, instalação de plugins e OAuth para uma etapa posterior.

**Por que depois.** MCP abre serviços externos e é a expansão natural de um Tool Registry; Hermes e DeepSeek têm integrações MCP. Mas é uma fronteira de segurança e configuração, não uma melhoria pequena do Router. O próprio DeepSeek descreve uma pipeline com policy, approval, sandbox e guards; seu aviso de segurança deixa claro que essa fronteira não pode ser adicionada como um simples novo Tool.

**Evidência direta.** [Hermes README: integração MCP](https://github.com/NousResearch/hermes-agent/blob/main/README.md#documentation), [DeepSeek Tool Catalog: MCP Resources](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/tool-catalog.md), [DeepSeek Tool Execution Pipeline](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/tool-execution-pipeline.md), [DeepSeek Safety](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md).

## Limites da recomendação original (2026-09-22)

- Na entrega inicial do Toolset, não juntar shell, escrita, browser, mensagens, subagents ou cron. Essas capacidades foram avaliadas separadamente; shell e escrita chegaram em features posteriores.
- Não copiar a arquitetura “everything is a plugin” do DeepSeek: o repositório pesquisado dizia estar em developer preview e sujeito a quebras de compatibilidade. É excesso para um Router pequeno.
- Naquele momento, não implementar memória autônoma/autoaprendizado antes de sessões explícitas e política de retenção. Sessões e notas persistentes foram decididas e entregues depois.

## Recomendação original de sequência (2026-09-22)

O plano recomendava implementar **1 (Toolset somente leitura)**, depois **3 (`/usage`)** e **4 (`/retry`, `/undo`)**, decidir a política de **2 (sessões persistentes)** e só então escolher como **6 (`/compact`)** funcionaria. Todos os sete itens foram concluídos, incluindo MCP Resources em 0034; Tools MCP, instalação de plugins e OAuth continuam fora do escopo entregue.
