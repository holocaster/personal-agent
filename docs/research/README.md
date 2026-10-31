# Estado das pesquisas

Revisado em **2026-10-27**, confrontando propostas com código, testes existentes e
registros de entrega. Este índice resume a situação atual; os documentos datados
preservam o que foi observado e proposto em cada pesquisa. `done/` significa
pesquisa arquivada, não que todas as sugestões tenham sido implementadas.

## Entregue

| Capacidade | Evidência local |
| --- | --- |
| Sessões persistentes, Resume, histórico e busca entre sessões | [Call Log](../../src/personal_agent/call_log.py), [session_logs](../../src/personal_agent/session_logs.py) |
| Configuração, seleção explícita de Provider/modelo e catálogo Models.dev | [runtime_config](../../src/personal_agent/routing/runtime_config.py), [model_catalog](../../src/personal_agent/model_catalog.py) |
| Orçamento de contexto, Compression preventiva e recuperação de overflow | [context_budget](../../src/personal_agent/context_budget.py), [router](../../src/personal_agent/routing/router.py) |
| Relatório de sessão, streaming e diagnóstico de rotas/cache | [session_report](../../src/personal_agent/session_report.py), [Providers](../../src/personal_agent/providers/) |
| Afinidade OpenRouter, prefixo estável, snapshots de prompt e custos de cache | [router](../../src/personal_agent/routing/router.py), [fixtures e testes](../../tests/README.md), [pesquisa de cache](done/2026-10-14-cache-and-session-routing.md) |
| Recuperação de arquivos, cache Claude, fork e jobs | [file_recovery](../../src/personal_agent/file_recovery.py), [Providers](../../src/personal_agent/providers/), [jobs](../../src/personal_agent/tools/jobs.py), [uso](../USER_GUIDE.md#commands) |
| Subagentes nativos, um por vez | [subagents](../../src/personal_agent/subagents/), [definições e limites](../USER_GUIDE.md#subagents) |
| ChatGPT por assinatura (0057) e reasoning configurável (0058) | [autenticação](../../src/personal_agent/chatgpt_auth.py), [Provider](../../src/personal_agent/providers/chatgpt.py), [revisão de integração](../../tickets/0057-chatgpt-subscription-provider/04-05-subagents-and-usage.review.md), [revisão e smoke](../../tickets/0058-chatgpt-reasoning/01-select-reasoning.review.md) |

## O que continua pendente

| Item | Situação e próximo passo |
| --- | --- |
| MCP Tools | Não implementado: o [catálogo atual](../../src/personal_agent/tools/registry.py) oferece apenas operações de MCP Resources. Foi adiado; escolher primeiro um servidor e uma operação úteis antes de abrir discovery. |
| Plugins de pacotes Python por entry points | Não implementado: [pyproject.toml](../../pyproject.toml) declara o comando CLI, sem mecanismo de descoberta de extensões no código. Retomar apenas com um plugin concreto; comparar com MCP antes de criar outro mecanismo. |
| Medição de ganho de cache, latência e custo por tarefa | As pesquisas registram diagnóstico histórico e verificações offline, sem benchmark comparativo live comprovando economia das mudanças. Se necessário, comparar tarefas equivalentes controlando modelo, host e aquecimento de cache. |
| Validação prática do workflow com subagentes | Usar uma tarefa real e observar conclusão, correções, custo e latência via `/report`. A leitura desta revisão não comprova esse resultado de uso. |

As duas primeiras linhas são expansões condicionais, não uma fila obrigatória.
As demais são avaliações de uso, não funcionalidades ausentes. Nenhuma delas
justifica automaticamente LSP, frontend, execução paralela ou uma plataforma de plugins.

## Arquivo e decisões superadas

| Pesquisa | Leitura atual |
| --- | --- |
| [Hermes/DeepSeek, 22/09](done/2026-09-22-hermes-deepseek-next-features.md) | Os sete candidatos tiveram entregas posteriores; tiers e regras antigas de contexto foram substituídos. |
| [Comparação OpenCode, 23/09](done/2026-09-23-opencode-feature-comparison.md) | Tabela histórica; subagentes já existem e roteamento por tier foi removido. MCP Tools e plugins permanecem condicionais. |
| [Jev, 26/09](done/2026-09-26-jev-routing.md) | Proposta rejeitada; sem integração. Não reabrir questões de thresholds como pendências do produto atual. |
| [Runtime config, 26/09](done/2026-09-26-runtime-config.md) | Entregue; a configuração por tier foi substituída pela seleção direta. |
| [Contexto, 29/09](done/2026-09-29-context-window-routing.md) | Entregue na 0037, com capacidades por campo ampliadas na 0054. |
| [Seleção de tier, 02/10](done/2026-10-02-session-tier-selection.md) | Foi entregue e depois removida pela 0054; não é trabalho pendente. |
| [Latência, 05/10](done/2026-10-05-session-latency.md) | Travessia de arquivos corrigida na 0048; preferência de host e streaming existem. Ganho live comparativo não foi medido. |
| [Oportunidades, 09/10](done/2026-10-09-feature-opportunities.md) | Relatório, streaming, checkpoints e jobs entregues; MCP Tools adiado. |
| [Cache, 14/10](done/2026-10-14-cache-and-session-routing.md) | Mudanças de afinidade, prompt, contabilização e cache Claude entregues; economia permanece não demonstrada. |
| [Referências, 14/10](done/2026-10-14-reference-opportunities.md) | Checkpoints, prefixo, snapshots e fork entregues; extensões condicionais acima. |
| [Catálogos, 15/10](done/2026-10-15-reference-model-catalogs.md) | Entregue na 0054 com Models.dev; recomendação inicial de catálogo LiteLLM foi superada. |
| [Próximos passos, 19/10](2026-10-19-next-steps.md) | Consolidado anterior à entrega de ChatGPT; consultar as pendências acima. |
| [Assinatura ChatGPT, 20/10](2026-10-20-chatgpt-subscription-provider.md) | Implementada nas 0057/0058; decisões de conta, saída, catálogo, custo e JWKS foram resolvidas. O spike permanece histórico. |

## Limites da revisão

Verificação documental e por leitura de fontes locais, sem repetir testes,
login, chamadas pagas ou benchmarks. Os reviews vinculados são evidência das
entregas anteriores, não verificações executadas nesta revisão. Fontes externas
e capacidades atuais dos projetos de referência não foram revalidadas.
