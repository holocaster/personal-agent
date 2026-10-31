# Próximos passos após a feature 0056 — histórico de 2026-10-19

> Consolidado histórico. Para entregas e pendências verificadas em 2026-10-27, consulte o [índice atual](README.md).

Leitura em **2026-10-19**, checkout `cd3eebd`. Escopo: confrontar os research mais recentes com README, código e specs 0053–0056. Fontes primárias locais e contratos oficiais de MCP/entry points reconfirmados pelo agente orquestrador via Context7/fontes oficiais; sem revalidar capacidades atuais dos projetos de referência, executar modelos, instalar pacotes ou alterar implementação.

Pesquisas anteriores: [done/](done/). As pendências identificadas em 2026-10-19 estão consolidadas neste arquivo; os documentos arquivados preservam também propostas superadas ou adiadas.

**Conclusão:** os research deixam somente duas expansões explicitamente pendentes: **MCP Tools** e **plugins de pacotes instalados por entry points**. Ambas foram adiadas por falta de uma integração concreta. Não há uma fila de features recentes obrigatórias ainda por fazer. Naquele checkpoint, a última entrega era a 0056; o [estado do projeto](../../.ai/PROJECT_STATE.md) acompanha entregas posteriores.

## O que já está entregue

| Proposta dos research | Situação comprovada |
| --- | --- |
| Relatório e streaming | Entregues; [README](../../README.md), [relatório atual](../../src/personal_agent/session_report.py). |
| Prefixo estável, snapshots de prompt e custos de cache | Entregues na [0053](../specs/0053-stable-sessions-and-recovery.md), com implementação em [router](../../src/personal_agent/routing/router.py) e [testes de superfície](../../tests/test_prompt_surface.py). |
| Recuperação de arquivos | `/recover`, entregue na [0053](../specs/0053-stable-sessions-and-recovery.md), [implementação](../../src/personal_agent/file_recovery.py). |
| Catálogo e seleção direta de Provider/modelo | Entregues na [0054](../specs/0054-direct-provider-model-selection.md); o [README](../../README.md) descreve Models.dev e `/model <provider> <model-id>`. Tiers e avaliador foram removidos. |
| Cache Claude, fork e jobs | Entregues na [0055](../specs/0055-fork-jobs-claude-cache.md); [Anthropic](../../src/personal_agent/providers/anthropic.py), [OpenRouter](../../src/personal_agent/providers/openrouter.py), [jobs](../../src/personal_agent/tools/jobs.py). |
| Subagentes | Entregues na [0056](../specs/0056-isolated-subagents.md); [implementação](../../src/personal_agent/subagents/__init__.py), [descoberta](../../src/personal_agent/subagents/definitions.py). A tabela antiga de setembro ainda marca ausência. |
| Diagnóstico de rota/cache por tarefa | Já existe: [session_report.py](../../src/personal_agent/session_report.py) renderiza execuções cronológicas, métricas por rota, cobertura e `[observed Provider/model change]`. Não propor novamente como se o relatório fosse apenas um agregado. |

## Opções priorizadas

Prioridade é julgamento de engenharia. A opção 2 é acompanhamento, não uma feature pendente prometida pelos research.

1. **MCP Tools, se houver um servidor que o usuário realmente queira usar.** É a expansão funcional ainda pendente nos [research de 09/10](done/2026-10-09-feature-opportunities.md) e [14/10](done/2026-10-14-reference-opportunities.md). Mínimo já proposto: um servidor stdio, Tools selecionadas explicitamente, validação, confirmação, timeout e resultados limitados. Escolher primeiro uma operação útil e seu servidor; não juntar OAuth, HTTP remoto ou marketplace. A [especificação oficial](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) foi reconfirmada pelo agente orquestrador em 19/10; a pesquisa específica do SDK fica separada deste levantamento.

2. **Validar o workflow entregue antes de acrescentar automação.** Aplicar o fluxo SDD com subagentes a uma tarefa real; usar `/report` para observar conclusão, correções, latência, custo delegado e cache com sua cobertura. O mínimo é um pequeno registro comparável de sessões, com o modelo e as condições anotados; nenhum dashboard ou nova política de roteamento. A [pesquisa de cache](done/2026-10-14-cache-and-session-routing.md) já recomenda medição; a [0055](../specs/0055-fork-jobs-claude-cache.md) não mediu hits ou economia live. Não confundir fixture offline com melhoria de custo demonstrada. Nenhum experimento pago foi executado aqui.

3. **Entry points somente quando existir um plugin concreto.** Continua pendente no [candidato 5 de 23/09](done/2026-09-23-opencode-feature-comparison.md) e foi excluído da [0055](../specs/0055-fork-jobs-claude-cache.md). Aqui “entry points” significa carregar extensões de pacotes Python instalados, conforme o [guia oficial de plugins Python](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/), reconfirmado pelo agente orquestrador em 19/10; não significa novos comandos de CLI. A [configuração do pacote](../../pyproject.toml) só declara o comando `personal-agent`, e o [registro de Tools](../../src/personal_agent/tools/registry.py) monta o catálogo interno; não há descoberta de plugins. Escopo mínimo futuro: uma extensão opt-in comprovadamente necessária, reutilizando validação, permissões e auditoria. Se a necessidade for apenas chamar um serviço externo, comparar primeiro com a integração MCP para evitar dois mecanismos equivalentes. Sem plugin identificado, adiar.

LSP, frontend adicional, execução paralela, instalação automática e uma plataforma geral de plugins não ganham prioridade apenas por aparecerem nos projetos de referência. A [comparação histórica](done/2026-09-23-opencode-feature-comparison.md) já os excluía por escopo; não foi demonstrada uma necessidade atual que justifique reverter isso.

## Limites

Verificação por leitura de fontes locais e contratos oficiais, sem testar servidor MCP/plugin concreto, suíte de testes, benchmark ou chamadas pagas. As propostas acima não comprovam economia, qualidade de modelos ou compatibilidade de qualquer plugin futuro. Nenhuma alteração de código, regra canônica ou estado da feature foi feita.
