# Context Window e capacidade por rota — pesquisa histórica

**Status (2026-10-04):** implementado na feature 0037. O corte fixo de 20 turnos,
o gatilho pós-resposta e o Continuation Turn foram substituídos por orçamento
total configurável, medição local de input completo, Compression preventiva e
uma recuperação de overflow na mesma rota. Ver [spec 0037](../../specs/0037-context-window.md),
[variáveis de contexto](../../ENV_VARS.md#context-capacity-overrides) e
[comportamento atual](../../USER_GUIDE.md#context-budgeting).
Os fatos locais, referências de linhas, fontes externas e perguntas abaixo
preservam a pesquisa de 2026-09-29; não descrevem decisões ainda pendentes.

## Estado observado neste repositório em 2026-09-29 (histórico)

- `HISTORY_WINDOW = 20`; antes de `route()`, o REPL usa
  `_flatten(turns[-HISTORY_WINDOW:])`. `turns` guarda a Conversation completa até
  Compression/Undo/Clear; `/usage` mostra turnos retidos e enviados. O corte é
  por turnos completos, não por tokens. [REPL: janela](../../../src/personal_agent/terminal/repl.py#L22-L24),
  [envio](../../../src/personal_agent/terminal/repl.py#L79-L150), [/usage](../../../src/personal_agent/terminal/repl.py#L267-L277)
- `cost.context_limit(provider, model)` consulta
  `litellm.get_model_info(...).get("max_input_tokens")`, com prefixo por Provider
  e fallback **128.000** se faltar metadado válido. Hoje esse valor serve ao
  gatilho de Auto-Compress; não determina quantos turnos entram em `history`.
  **128k é fallback atual, não recomendação de tamanho para a próxima feature.**
  [cost.py](../../../src/personal_agent/cost.py#L13-L37), [REPL](../../../src/personal_agent/terminal/repl.py#L187-L201)
- Auto-Compress verifica, **depois de um turno bem-sucedido**, se
  `prompt_tokens > 0,8 × context_limit`; se há mais de dois turnos, resume os
  anteriores aos dois últimos e pode enviar uma Continuation Turn. Uso ausente
  não dispara compressão. `/compress` usa o tier `easy` e envia os turnos
  substituídos para sumarização. [REPL](../../../src/personal_agent/terminal/repl.py#L166-L242), [router.compress](../../../src/personal_agent/routing/router.py#L192-L220)
- `route()` escolhe tier/modelo após receber o histórico; `_run_exchange()`
  envia `system` e `messages` ao Provider, inclusive em trocas adicionais após
  Tools. Escalation pode mudar tier/Provider antes da primeira resposta; após
  a primeira resposta, as trocas de Tool seguem a mesma rota. O histórico
  precisa caber junto com tarefa, System Prompt, esquema das Tools, resultados
  e espaço de saída na rota que efetivamente responder.
  [route](../../../src/personal_agent/routing/router.py#L114-L189), [Tool loop](../../../src/personal_agent/routing/router.py#L260-L333), [exchange](../../../src/personal_agent/routing/router.py#L388-L445)
- O OpenRouter local não fixa upstream no pedido (`provider.require_parameters`
  apenas quando há Tools); a consulta de upstream após a resposta é opcional
  e assíncrona. Seu `prompt_tokens` vem do uso retornado; `cached_tokens` e
  `cache_write_tokens` são campos separados de diagnóstico/custo, não uma
  autorização para aumentar a capacidade.
  [openrouter.py](../../../src/personal_agent/providers/openrouter.py#L23-L61), [consulta posterior](../../../src/personal_agent/routing/router.py#L490-L512)
- Amostra de um Attempt recente registrou **9.074 `prompt_tokens`**: há exemplo
  abaixo de 128k, mas isso não mede o pior caso futuro nem valida a janela
  fixa. Citação do contador apenas, sem reproduzir `task`, resposta ou payload
  do log. Fonte: Call Log local
  `~/.personal_agent/logs/pa_log-20260929T231044Z-c0rvgs.jsonl:33` (fora do repositório).

## Evidência externa (fontes primárias)

- O catálogo público `/api/v1/models` do OpenRouter lista `minimax/minimax-m3`
  com `context_length: 1048576`; a listagem de **endpoints do mesmo modelo**
  mostra CoreWeave com **262144** de contexto e **235929** de saída máxima,
  Venice com **524288** e **65536** respectivamente, além de outras capacidades.
  Logo, o número do catálogo do modelo não comprova a capacidade do upstream
  escolhido para cada pedido; os valores são um retrato da API nesta data.
  [catálogo](https://openrouter.ai/api/v1/models), [endpoints do modelo](https://openrouter.ai/api/v1/models/minimax/minimax-m3/endpoints)
- OpenCode carrega limites de modelo/provider do `models.dev` e aceita override
  de configuração; no cálculo de overflow, usa limite de input quando informado
  ou contexto menos reserva de saída (padrão de reserva até 20.000 quando há
  limite de input); a contagem inclui cache read/write. Trata a ocupação da
  janela e o custo de cache como questões diferentes.
  [modelos/override](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/provider/provider.ts#L1316-L1612), [overflow.ts](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/overflow.ts#L8-L34)
- Hermes resolve contexto por override, rota/provider, catálogo acessível,
  endpoint e fallbacks, incluindo consulta ao catálogo OpenRouter. Sua
  documentação expõe threshold de compressão padrão **0,50** e configuração
  da cauda preservada; é uma referência de comportamento, não uma calibração
  demonstrada para este projeto.
  [model_metadata.py](https://github.com/NousResearch/hermes-agent/blob/main/agent/model_metadata.py#L2176-L2309), [configuração Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)
- DeepSeek Harness atribui `contextWindow` à rota provider/model resolvida pelo
  adapter. `compaction-basic` usa threshold padrão **0,8**, headroom padrão
  **65536** e reserva de saída; limita a pressão pelo menor valor entre fração
  do contexto e capacidade restante, com overrides opcionais por rota. A
  documentação descreve compactação antes da etapa e reação a overflow.
  [LLM streaming](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/llm-streaming.md#L522-L529), [config.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/compaction/compaction-basic/src/config.ts#L19-L215), [compaction](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/compaction.md#L75-L101)

## Perguntas originais para o desenho (resolvidas em 0037)

1. O usuário escolhe um orçamento em tokens por Run/tier/rota, um limite máximo
   de turnos, ou ambos? Como exibir capacidade nominal versus orçamento
   efetivamente enviado, sem confundir os dois?
   [REPL](../../../src/personal_agent/terminal/repl.py#L128-L150), [/usage](../../../src/personal_agent/terminal/repl.py#L267-L277), [OpenRouter endpoints](https://openrouter.ai/api/v1/models/minimax/minimax-m3/endpoints)
2. Usar metadados locais (`litellm`), consulta dinâmica ao catálogo/endpoints,
   valor manual, ou combinação? Qual precedência, validade temporal e
   comportamento quando metadados falham — sem tratar automaticamente os
   atuais 128k como capacidade comprovada?
   [cost.py](../../../src/personal_agent/cost.py#L13-L37), [OpenRouter endpoints](https://openrouter.ai/api/v1/models/minimax/minimax-m3/endpoints)
3. Como definir elegibilidade quando o upstream OpenRouter ainda é desconhecido
   no momento do pedido, quando o Router escala entre tiers/Providers ou quando
   a resposta de uma Tool aumenta o prompt durante o turno? Haverá seleção de
   upstream, orçamento conservador, recuperação após erro, ou outra política?
   [openrouter.py](../../../src/personal_agent/providers/openrouter.py#L23-L45), [route/Tools](../../../src/personal_agent/routing/router.py#L145-L333)
4. Que margem reservar para saída e partes fora de `history` (System Prompt,
   skills, Tools, nova tarefa, resumo)? Como estimar tokens antes do envio e
   reconciliar estimativa com `prompt_tokens` real e métricas de cache sem
   considerar tokens em cache como espaço adicional?
   [system prompt/exchange](../../../src/personal_agent/routing/router.py#L35-L475), [OpenCode overflow](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/overflow.ts#L8-L34)
5. Ao exceder o orçamento, descartar turnos, comprimir antes do pedido, ou
   recuperar após overflow? Qual menor unidade segura preserva pares Tool
   call/result e estado de Resume/Call Log, inclusive quando um único turno já
   excede o limite? [REPL](../../../src/personal_agent/terminal/repl.py#L128-L242), [DeepSeek](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/compaction.md#L75-L101), [replay local](../../../src/personal_agent/call_log.py)
6. Qual retenção é necessária para qualidade das respostas e qual custo de
   reenviar contexto — mesmo com cache — vale aceitar? Medir em sessões
   representativas antes de fixar limiar ou algoritmo.
   [OpenRouter: métricas locais](../../../src/personal_agent/providers/openrouter.py#L47-L58), [REPL: uso](../../../src/personal_agent/terminal/repl.py#L385-L413), [OpenCode: cache na contagem](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/session/overflow.ts#L22-L33)
