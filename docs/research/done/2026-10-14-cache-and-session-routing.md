# Cache e seleção de modelo por sessão

**Status (2026-10-17, entregue):** feature 0053 concluída e verificada em 2026-10-15. Seleção estável (ticket 01), afinidade OpenRouter com `session_id` durável (ticket 02), ordem estável do prompt (ticket 03) e contabilização de cache nos Providers diretos (ticket 04) foram implementadas e aprovadas. A afinidade é best effort por modelo, sem garantir hit, sobrevivência ociosa ou reutilização entre modelos. A feature 0054 (2026-10-16) removeu tiers, avaliador e `/model auto`; propostas sobre checkpoints e trocas de tier são históricas. A ativação de `cache_control` da Anthropic foi entregue na feature 0055 (ticket 01, 2026-10-17): um marcador de nível de requisição, TTL padrão de cinco minutos, no Provider Anthropic direto e no OpenRouter com ids `anthropic/`; não garante hit nem economia. Escopo: roteamento, construção do prompt, adaptadores, contabilização e testes relacionados. A comparação com os projetos de referência está em [pesquisa complementar](2026-10-14-reference-opportunities.md).

Minha recomendação é retirar a reavaliação nos turnos 5 e 15 do comportamento padrão. Manter seleção inicial opcional e um modelo estável por sessão, com mudanças explícitas. Antes de automatizar novas trocas, medir qualidade e custo total de tarefas concluídas.

## Evidência histórica anterior à implementação

| Observação | Evidência local | Consequência |
| --- | --- | --- |
| Avaliações nas submissões 1, 5 e 15 | `routing/session.py:5,23–27`; `terminal/repl.py:222–247` | Uma decisão pode mudar a rota antes da tarefa do checkpoint. |
| O avaliador usa o tier easy e apenas solicitações acumuladas do usuário | `routing/router.py:28–35,236–256` | Classifica esforço solicitado; não mede qualidade de respostas ou sucesso de ferramentas. |
| Automação só mantém ou sobe tier | `routing/session.py:49–56` | Uma promoção continua nas tarefas simples posteriores, até intervenção manual. |
| Tier complex ainda passa por avaliações | `routing/session.py:23–27`; `tests/test_session_tier.py:46–63` | Há chamada paga sem possibilidade de promoção. |
| Não há checkpoints depois de 15 | `routing/session.py:33–34` | Uma tarefa difícil no turno 2 pode esperar até 5; após 15 não há nova adaptação agendada. |
| Cada tier resolve modelo/provedor configurados | `routing/router.py:190–192` | Tier não é uma identidade permanente de modelo: `/config` também pode mudar a rota. |

As configurações locais inspecionadas, sem expor credenciais, mapeiam easy para `minimax/minimax-m3`, medium para `z-ai/glm-5.3-flash` e complex para `z-ai/glm-5.3`, todos por OpenRouter. Portanto, promover tier nessa configuração troca de modelo. Não foi feito benchmark comparativo desses modelos.

O cache reaproveita estados de processamento do prefixo, não respostas prontas. Uma troca de modelo impede reutilizar os estados anteriores; não implica apagar o cache antigo. Avaliar e manter o mesmo modelo também não apaga esse cache. A documentação OpenAI explica correspondência do prefixo e influência do modelo. [OpenAI — prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

## Outros pontos que afetam cache

**Afinidade no OpenRouter (evidência histórica).** Antes do ticket 02, `providers/openrouter.py:39–40` não enviava `session_id`. OpenRouter oferece afinidade por modelo/conversa, aceita `session_id` explícito de até 256 caracteres e o usa na afinidade Z.AI. O ticket 02 reutiliza a identidade durável da sessão e distingue avaliação/compressão. Isso não compartilha cache entre modelos nem garante hit. Contrato reconfirmado via Context7 em 2026-10-14; nenhum `cache_control`, prewarm ou consulta de metadados foi acrescentado. [OpenRouter — prompt caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching).

O adaptador atual usa `sort: "price"`, não `"throughput"`, com preferência mínima de throughput de 85. A documentação descreve `sort: "price"` como uma forma de desativar Auto Exacto, cuja reordenação pode disputar com afinidade. Não há evidência para culpar esse sort pelo problema relatado. [OpenRouter — Auto Exacto](https://openrouter.ai/docs/guides/routing/auto-exacto).

**Prefixo variável (evidência histórica).** Antes do ticket 03, `_build_system_prompt()` punha memória antes das instruções básicas e resumo/todo antes das instruções do projeto (`routing/router.py:53–115` na revisão pesquisada). A reprodução local mudou um todo de pending para in_progress: a primeira diferença apareceu no caractere 86, antes das instruções estáveis do projeto. Isto prova alteração do prefixo, não um miss real. Z.AI recomenda system prompts estáveis; OpenAI exige correspondência do prefixo renderizado. [Z.AI — context caching](https://docs.z.ai/guides/capabilities/cache), [OpenAI — prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

**Implementado em 2026-10-14, feature 0053 ticket 03:** regras de aplicação/Tools/modo/idioma e Project Instructions precedem Memory, Skills ativos, Summary e Todo. Os [testes offline](../../../tests/test_prompt_surface.py) verificam bytes anteriores preservados no input preparado dos quatro Providers, orçamento completo, catálogos determinísticos e três fixtures reais isoladas. [Regeneração](../../../tests/README.md) produz diffs revisáveis. Não congela contexto, ativa cache nativo ou demonstra hits/economia; mudanças de projeto/modo/catálogo podem alterar o prefixo.

Proposta incremental: colocar conteúdo estável antes do variável, conservar ordem determinística das ferramentas e remover injeções redundantes, como reintroduzir todo já presente no resultado da ferramenta, quando preservar seu comportamento. Mudar somente a ordem preserva mais do início do prompt; não preserva todo o histórico quando o system muda. Uma solução posterior pode representar atualizações como contexto acrescentado à conversa, com prioridade e replay definidos. Não congelar memória, modo ou instruções a ponto de ignorar alterações legítimas. Compression e mudanças reais de ferramentas também alteram o contexto.

**Anthropic sem ativação de cache (evidência histórica, antes da feature 0055).** `providers/anthropic.py:74–78,225–227` não envia `cache_control`; o caminho OpenRouter também não adiciona esse campo para Claude. A API documenta ativação por campo superior ou breakpoints em blocos. Proposta: habilitar no adaptador compatível quando Claude for usado, respeitando mínimo de tokens, TTL e preço de escrita. Não é a causa imediata da configuração atual, que não usa Claude. [Anthropic — prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

## Medição antes de mais automação

O `/report` já existe e distingue execução, avaliação e compressão, com cobertura de métricas (`session_report.py:9–10,175–183`). Estender o relatório existente para mostrar sequência por tarefa/modelo e cache antes/depois de uma troca seria mais útil que criar outro dashboard. Calcular proporções apenas sobre chamadas com contadores compatíveis conhecidos; ausência não é zero. Eventos de upstream são diagnósticos opcionais e podem estar ausentes.

Há uma limitação adicional nos provedores diretos: `providers/http.py:100–113` estima custo Anthropic apenas pelos tokens não cacheados, omitindo preço de leitura/escrita. OpenAI direto estima pelos tokens totais, sem desconto. Contadores de cache são descartados nesse caminho não streaming; os caminhos streaming retêm contadores, mas usam a mesma estimativa incompleta. OpenRouter já conserva custo reportado e contadores (`http.py:93–99`), portanto essa limitação não afeta da mesma forma a configuração atual.

`cost.py:1–7` aceita somente modelo/input/output. LiteLLM **1.102.0**, fixada no lock e instalada, oferece `cache_read_input_tokens`, `cache_creation_input_tokens` e `usage_object`; confirmado no código instalado, `litellm/cost_calculator.py:323–342`. Context7 não oferece referência versionada 1.102.0; a assinatura local resolve essa lacuna. Proposta: transmitir usage de cache ao estimador e preservar os contadores também sem streaming; continuar identificando preços locais como estimados. [LiteLLM — cost calculator](https://github.com/berriai/litellm/blob/main/litellm/cost_calculator.py).

## Ordem sugerida

1. **Modelo estável por sessão:** remover checkpoints 5/15 do padrão, mantendo seleção inicial opcional e reavaliação explícita. Hoje `/model medium` ou outro tier escolhido já suspende avaliações; `/model auto` atualmente reativa checkpoints, portanto não corresponde à proposta de avaliação única. Preservar replay de logs antigos ao alterar a política: não basta editar `CHECKPOINTS`, que também participa da validação de persistência (`session.py:61–90`).
2. **Afinidade explícita OpenRouter e prefixo mais estável:** mudanças separadas, medidas individualmente. Afinidade não resolve mudança de modelo; estabilidade do modelo não resolve prefixo variável.
3. **Diagnóstico por troca no `/report`:** custo total, cache conhecido, tempo até primeiro texto, retries e resultado da tarefa. Corrigir estimativas dos provedores diretos antes de compará-las financeiramente.
4. **Checkpoint de arquivos:** oportunidade de produto com valor independente do cache; detalhada na pesquisa complementar. O `/undo` atual remove conversa, não alterações em arquivos.

O benefício da reavaliação periódica não está demonstrado pelos testes: eles usam respostas HTTP simuladas, inclusive a classificação (`tests/test_session_tier.py:46–63`). O problema original — começar com uma saudação e depois pedir trabalho complexo — é válido; contar turnos é um indicador fraco para detectá-lo.

Para avaliar a política, comparar sessões equivalentes com modelo fixo, seleção inicial única e checkpoints periódicos, usando critérios objetivos de tarefa concluída. Medir custo por tarefa aprovada, qualidade, correções necessárias, latência e cache; repetir e controlar aquecimento/expiração. Alterar uma variável por vez. Não inferir melhora de qualidade apenas porque o tier subiu, nem economia apenas porque o modelo tem menor preço nominal.

## Verificação realizada

- Teste isolado do agendamento e promoção: **1 passou**.
- `tests/test_session_tier.py`: **193 passaram**.
- `tests/test_session_report.py`: **21 passaram**; total das duas suítes: **214**.
- Reprodução com asserts e HTTP mockado confirmou avaliação inútil em complex, alteração precoce do system prompt, ausência de `session_id`/`cache_control` e omissão dos dados de cache no estimador direto.
- Fontes atuais consultadas via Context7, documentação oficial OpenAI e páginas oficiais dos provedores. As APIs são REST diretas; não há SDK OpenAI/Anthropic no caminho das chamadas.

Não há logs de sessão no diretório associado ao workspace atual. Sem a sessão exata relatada, não foi quantificado o custo real da troca nem provado que ela explica toda queda observada. Nenhuma chamada paga, alteração de código de produção, commit ou push foi realizada.

Para a próxima captura, o usuário informou que tentará uma sessão nova. Rodar `/report` depois das tarefas 4/5 e 14/15 permite guardar o ID e comparar subtotais; os registros individuais serão necessários para separar troca de modelo, prefixo, host e expiração. Uma avaliação que mantenha o modelo não reproduz necessariamente o sintoma relatado.

## Implemented accounting status — 2026-10-15

[Ticket 04](../../../tickets/0053-stable-sessions-and-recovery/04-task-routes-and-cache-accounting.md) adds bounded chronological execution/route evidence to `/report` and cache-aware direct-provider estimates. Earlier observations above remain historical; no paid cache-hit, latency or savings experiment was performed.

Verified against installed LiteLLM **1.102.0**, locked in `uv.lock`: `cost_calculator.py:cost_per_token` dispatches each direct Provider's `usage_object` to its calculator; `litellm_core_utils/llm_cost_calc/utils.py:generic_cost_per_token` subtracts read/write subsets from inclusive prompt totals, then prices each once. `calculate_cache_writing_cost` uses `prompt_tokens_details.cache_creation_token_details` for separate 5-minute/1-hour counts. The estimator uses that normalized object without Anthropic's additive argument path. `utils.py:_build_model_info` substitutes zero for absent base rates, so availability is checked against the original local `model_cost[info.key]`, before accepting an estimate.

Primary contracts checked through Context7 and official documentation:

- [Anthropic caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) and [official Usage schema](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/types/usage.py): input, reads and writes are disjoint; TTL defaults to five minutes unless a different duration is requested. This application sends no `cache_control`. Omitted cache categories can therefore be zero for the existing uncached calculation; supplied counters and TTL breakdowns are validated, not discarded. Absence remains unknown report coverage.
- [OpenAI caching](https://developers.openai.com/api/docs/guides/prompt-caching) and [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): read/write counts are prompt subsets. Current documentation distinguishes newer charged writes from older models, so no universal price multiplier or omitted-cache-zero assumption is used for OpenAI. Both cache categories must be supplied for an estimate; absence remains unavailable.
- [Gemini UsageMetadata](https://ai.google.dev/api/generate-content#UsageMetadata), [official protocol](https://github.com/googleapis/googleapis/blob/master/google/ai/generativelanguage/v1beta/generative_service.proto) and [ProtoJSON presence rules](https://protobuf.dev/programming-guides/json/#presence-and-default-values): cached input is a subset, and `cached_content_token_count` is an implicit-presence `int32` whose zero can be omitted. Calculation may use zero for that omitted field; coverage still records absence. This GenerateContent path creates no explicit cached-content resource or write/storage charge.

Offline fixed-price evidence: base input/output/read/write/1-hour-write rates `.01/.02/.001/.03/.05` yield Anthropic total prompt `60` from noncache `10`, reads `20`, writes `30`; writes split `10` at five minutes and `20` at one hour cost **$1.52** including output `5`. The equivalent unsplit default-write case and OpenAI inclusive prompt `60` cost **$1.12**; Gemini inclusive prompt `30` with reads `20` and output `5` costs **$0.22**. These are synthetic contracts, not production prices. Tests exercise the installed calculator, missing rates, malformed/partial usage, streaming/failure parity and one Run-spend charge per physical Attempt. OpenRouter's reported cost and legacy recorded costs are never recalculated.
