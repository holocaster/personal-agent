# Usar a assinatura ChatGPT/Codex no personal-agent

> **Atualização de 2026-10-27:** o Provider ChatGPT foi implementado na feature 0057; a seleção de reasoning foi entregue na 0058. Ver [autenticação](../../src/personal_agent/chatgpt_auth.py), [Provider](../../src/personal_agent/providers/chatgpt.py), [revisão de integração](../../tickets/0057-chatgpt-subscription-provider/04-05-subagents-and-usage.review.md) e [revisão/smoke de reasoning](../../tickets/0058-chatgpt-reasoning/01-select-reasoning.review.md). O texto abaixo preserva a pesquisa e o spike de 20/10, não uma fila de implementação. Uso atual: [guia](../USER_GUIDE.md#chatgpt-account-and-reasoning); pendências: [índice](README.md).

Pesquisa em **2026-10-20**, checkout `4a815833d70287e4f6c38538f7ff3cae75f3bb4f`. **Situação em 2026-10-20: proposta validada por spike real; ainda não implementada naquela data.** Context7, documentação oficial OpenAI e fontes do OpenCode, mais o spike descrito em [Resultados do spike](#resultados-do-spike-2026-10-20). Onde o spike contradiz a documentação, vale o comportamento observado, marcado como não documentado.

## Conclusão

**Existe um caminho oficial adequado a este projeto: Sign in with ChatGPT com permissão para usar o plano, chamando a Responses API pública.** A OpenAI documenta essa possibilidade para projetos open source e projetos pessoais locais; usuários Plus/Pro elegíveis autorizam o uso do plano. Não exige API key nem client secret. A disponibilidade de uma conta concreta depende do consentimento, elegibilidade e políticas do serviço; **a conta do usuário foi aceita sem aprovação adicional** e completou texto, Tools, reasoning e refresh. [Cookbook oficial, publicado em 28/09/2026](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt), [quickstart](https://developers.openai.com/siwc/quickstart).

Recomendação de engenharia: um provider **`chatgpt`**, distinto de `openai`, com OAuth próprio e adaptador Responses. Preservar o loop, as Tools e as permissões do personal-agent. Não é necessário transformar o projeto em cliente do agente Codex para aproveitar o plano.

Isso seria uma nova opção além das expansões listadas na [pesquisa de próximos passos](2026-10-19-next-steps.md). Não depende de implementar MCP Tools ou plugins primeiro. Naquele checkpoint, a última entrega era a 0056; a implementação proposta seguiria o fluxo SDD do projeto.

## O que o OpenCode faz

Há duas integrações diferentes nas fontes consultadas:

| Caminho | Autenticação e inferência | Implicação aqui |
| --- | --- | --- |
| Sign in with ChatGPT | Registro OAuth dinâmico, scope `chatgpt.tokens.use.direct`, recurso `https://api.openai.com/v1`. | Seguir o contrato oficial atual. |
| Codex legado | Client ID fixo do Codex, browser/device OAuth e `https://chatgpt.com/backend-api/codex`. O browser aparece rotulado como legacy. | Não é o contrato público recomendado para uma integração nova. |

Evidência: [provider ChatGPT](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/plugin/provider/chatgpt.ts) e [provider OpenAI/legado](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/plugin/provider/openai.ts). Histórico fixado: [introdução, commit 4d909079](https://github.com/anomalyco/opencode/commit/4d9090790b92d3f3074c5710cfaa8911d4be523c) e [correção, commit 0f830382](https://github.com/anomalyco/opencode/commit/0f830382531bff8ddf9b6946820402f40a6669c1), de 29/09/2026.

Esses commits não são o HEAD atual. Os aliases da branch `dev` retornaram snapshots divergentes; suas linhas não são uma referência imutável. No snapshot lido, o carregamento remoto de modelos estava desativado e existia fallback: não copiar essa lista como evidência de acesso. A recomendação acima se sustenta na documentação OpenAI, independentemente desses detalhes do OpenCode.

**Conferência adicional da v2.0.32:** a tag também contém os dois métodos: [openai.ts](https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/plugin/provider/openai.ts) registra `Codex browser (legacy)` e `Codex device code (legacy)`; [chatgpt.ts](https://github.com/anomalyco/opencode/blob/v2.0.32/packages/core/src/plugin/provider/chatgpt.ts) registra `Sign in with ChatGPT`. O método associado à credencial ativa determina qual integração se aplica; atualizar para v2 não significa migrar toda credencial Codex para token sharing. A [PR #52147](https://github.com/anomalyco/opencode/pull/52147), integrada à branch `v2`, declara explicitamente que preserva browser/headless existentes e adiciona token sharing separadamente. Manter compatibilidade é uma interpretação dessa decisão; não foi encontrada ali uma afirmação de que o legado seria tecnicamente superior.

## Contrato oficial necessário

### Login

Fluxo documentado de aplicação pública:

1. Persistir um `ext_agent_host_id` opaco por instalação; `urn:uuid:<UUIDv4>` é aceito. Reutilizá-lo entre execuções. [Host e client](https://developers.openai.com/siwc/token-sharing-open-source).
2. Iniciar callback em `http://127.0.0.1:<porta>/auth/callback`; gerar `state`, `nonce` e PKCE S256 novos por tentativa.
3. Abrir `https://auth.openai.com/api/accounts/authorize`. Primeiro registro: `client_id=dynamic_agent_client`, `agent_name_hint=personal-agent`, host ID e `resource=https://api.openai.com/v1`. Scopes: `openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`.
4. Validar `state`; trocar o código em `https://auth.openai.com/api/accounts/oauth/token` usando o client ID **emitido no callback**, PKCE e callback idêntico. Não trocar o código com `dynamic_agent_client`.
5. Validar assinatura/JWKS, issuer, audience, expiração e nonce do ID token. Só habilitar inferência quando o scope de uso do plano tiver sido concedido. Reautorização reutiliza o client ID salvo e rejeita um ID divergente. [Registro e sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in).

A aplicação deve guardar registros separados por client ID e identidade validada, permitir selecionar a conta e mostrar qual está ativa. Mesmo email não basta para identificar registros/workspaces. O refresh é serializado por sessão, substituindo o conjunto de tokens atomicamente; processos concorrentes não podem consumir o mesmo refresh token rotativo. Logout tenta revogar a sessão renovável, limpa os tokens e conserva o vínculo de registro. Falha transitória não justifica apagar credenciais. [Contas e sessões](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions).

O token response contém access/refresh/ID token, scopes, expiração e `earliest_refresh_at`. A documentação informa access token de uma hora e refresh token de 30 dias, renovado a cada refresh bem-sucedido. Não fixar a expiração no código quando o servidor fornece os campos. [Referência de tokens](https://developers.openai.com/siwc/token-sharing-open-source/token-reference).

### Inferência

Usar `Authorization: Bearer <access_token>` em **`POST https://api.openai.com/v1/responses`**. O guia manda usar esse endpoint público e evitar `backend-api`. Listar modelos da conta em `GET /v1/models`: a resposta deste fluxo possui `models`, com `slug`, `display_name` e `visibility`; não assumir o formato `data/id` da API key. Exibir `visibility=list` e usar o `slug` escolhido. Acesso só fica demonstrado para a requisição que efetivamente conclui. [Modelos e inferência](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).

Restrições relevantes da preview:

- `stream=true`, `store=false`, histórico necessário em `input` array e instruções via `instructions` ou mensagens developer.
- Não enviar `previous_response_id` por HTTP nem mensagens system explícitas.
- Não enviar `max_output_tokens`, `temperature`, `top_p`, `conversation`, `background`, `metadata` e outros campos da lista oficial. Spike: `temperature`, `top_p`, `metadata`, `truncation` e `previous_response_id` são recusados; `max_output_tokens` e mensagem `system` foram **aceitos e respeitados**, contrariando a lista (não documentado, pode mudar).
- Funções/custom tools devem estar em namespaces ou `additional_tools`. A execução local das funções continua na aplicação.
- Hosted MCP, `tool_search`, Code Interpreter, geração de imagem e computer use nativos não são suportados nesse fluxo. Isso não impede expor uma Tool local própria como função.

Essas regras também valem para o app-server configurado para esta rota. [Limitações oficiais](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

O adaptador deve transformar `ToolDef` em funções dentro de um namespace, correlacionar `function_call`/`function_call_output` por `call_id` e preservar a identificação do namespace ao receber chamadas. [Function calling](https://developers.openai.com/api/docs/guides/function-calling).

Reasoning não pode ser reduzido apenas ao texto mostrado ao usuário: preservar os itens replayáveis, inclusive `encrypted_content` e fase da mensagem, ao reconstruir a entrada. O guia atual informa que respostas sem armazenamento incluem reasoning criptografado por padrão. [Reasoning e replay](https://developers.openai.com/api/docs/guides/reasoning).

### Erros e uso do plano

Tratar falhas HTTP e eventos de erro depois de o stream começar. No spike, limite de uso e overflow de contexto chegaram como HTTP 200 seguido de evento `error` e `response.failed`, não como 429/400; só parâmetros recusados e autenticação falham no HTTP. Limite de uso deve interromper novas chamadas dessa rota; indisponibilidade transitória permite backoff limitado; capacidade não suportada exige corrigir o request. Não fazer fallback automático para API key. Preservar status, código e request ID, removendo segredos dos diagnósticos. [Erros e recuperação](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery).

Na interface, indicar uso do plano, confirmar isso no primeiro login e oferecer **Manage usage** apontando para `https://chatgpt.com/settings/usage`. A cota não é uma franquia independente criada pelo personal-agent. [Diretrizes de interface](https://developers.openai.com/siwc/ui-ux-guidelines).

## Por que o provider atual não serve apenas trocando a chave

O impedimento comprovado é de protocolo e integração local:

| Evidência local | Consequência para a feature |
| --- | --- |
| [openai.py:8](../../src/personal_agent/providers/openai.py#L8), [openai.py:38](../../src/personal_agent/providers/openai.py#L38) | Usa Chat Completions, mensagens desse protocolo e `max_completion_tokens`; precisa de adaptador Responses separado. |
| [registry.py:3](../../src/personal_agent/providers/registry.py#L3), [runtime_config.py:111](../../src/personal_agent/routing/runtime_config.py#L111) | Providers são fechados e todos exigem API key; OAuth precisa de validação própria. |
| [model_catalog.py:17](../../src/personal_agent/model_catalog.py#L17), [__main__.py:126](../../src/personal_agent/__main__.py#L126) | Admissão depende de Models.dev e de quatro providers. É preciso admitir a rota ChatGPT com catálogo da conta. |
| [repl.py:1213](../../src/personal_agent/terminal/repl.py#L1213) | `/model` também exige catálogo e API key; alterar só startup não resolve. |
| [router.py:519](../../src/personal_agent/routing/router.py#L519), [continuation.py:79](../../src/personal_agent/routing/continuation.py#L79) | Replay concluído/retomável só admite Gemini. Responses exige outro formato validado e persistência adequada. |
| [router.py:176](../../src/personal_agent/routing/router.py#L176), [router.py:618](../../src/personal_agent/routing/router.py#L618) | Redação de segredos parte de snapshots de API keys; tokens renovados precisam entrar na proteção durante a execução. |
| [subagents/__init__.py:30](../../src/personal_agent/subagents/__init__.py#L30) | Subagentes copiam config e usam outro processo; fixar registro de conta, sem congelar um access token expirável nem disputar refresh. |
| [http.py:125](../../src/personal_agent/providers/http.py#L125), [repl.py:561](../../src/personal_agent/terminal/repl.py#L561) | Usage atual estima preços API e footer mostra dólares. Isso não representa cobrança do plano. |
| [router.py:794](../../src/personal_agent/routing/router.py#L794), [context_budget.py:70](../../src/personal_agent/context_budget.py#L70) | Router passa reserva de saída. A documentação proíbe `max_output_tokens`, mas o spike mostrou que ele é aceito e imposto (`incomplete`, reason `max_output_tokens`). A spec deve decidir se depende desse comportamento não documentado. |

O transporte SSE já existe em [http.py:29](../../src/personal_agent/providers/http.py#L29), e o contrato comum já possui `AssistantMessage.replay`. Reutilizá-los, sem reaproveitar o parser de Chat Completions. Spike: o `response.completed` desta rota vem com `output: []`, então os itens precisam ser coletados de `response.output_item.done`; o maior evento observado numa saída de ~3k tokens foi 17 KB, dentro do limite atual de 256 KiB. A resposta SSE vem sem `Content-Type`.

Ambiente observado: Python requerido `>=3.12`, projeto `0.1.0`; `.venv` com LiteLLM `1.102.0`, MCP `2.2.0`, OpenAI `2.54.0`, PyJWT `2.15.1` e cryptography `50.0.1`. OpenAI/PyJWT são transitivos, não dependências diretas em [pyproject.toml](../../pyproject.toml). Para validar JWT, declarar `PyJWT[crypto]` diretamente se usado; não escrever criptografia própria. O [PyJWT 2.15.1](https://github.com/jpadilla/pyjwt/blob/2.15.1/docs/usage.rst) documenta JWKS, assinatura, issuer, audience e claims obrigatórios; o vínculo de nonce da tentativa também precisa ser conferido.

## Menor implementação completa proposta

Proposta, não comandos já existentes:

```text
personal-agent auth login chatgpt
personal-agent auth status chatgpt
personal-agent auth logout chatgpt
personal-agent --models chatgpt
```

No REPL, reutilizar `/model chatgpt <slug>` e `/models chatgpt`. O login precisa funcionar antes da validação normal que hoje exige configuração e chave. Para múltiplos registros, acrescentar seleção simples por identificador estável, conservando um registro ativo; nada de dashboard de contas.

Arquivos novos sugeridos: `chatgpt_auth.py` para OAuth/armazenamento e `providers/chatgpt.py` para serialização Responses/SSE. Só separar o parser quando o tamanho justificar. Credenciais em armazenamento global próprio, por exemplo `~/.personal_agent/chatgpt-auth.json`, com arquivo `0600`, diretório privado e escrita atômica. Host ID e registro permanecem estáveis; tokens nunca entram no `.env`, histórico ou conteúdo enviado ao modelo.

Nos pontos da tabela, integrar autenticação, catálogo, replay e relatórios. O catálogo da conta determina as opções da rota; Models.dev pode complementar metadados conhecidos pelo slug, sem ser apresentado como autorização. Rever filtros que hoje rejeitam reasoning intercalado e a procedência dos limites em `context_budget`. Se faltarem capacidades confiáveis, expor os limites assumidos ou manuais, sem inventar metadados. Separar cache por registro de conta e invalidar a seleção na troca de conta.

Guardar a referência estável do registro nos snapshots da tarefa/subagente; resolver tokens válidos no despacho com bloqueio entre processos e releitura dentro do bloqueio. Proteger também os tokens substituídos e URLs com `id_token_hint` nos logs. Não alterar conta no meio de uma tarefa.

Registrar tokens/cache observados e `cost=null` quando não houver custo monetário informado. Mostrar uso do plano e cobertura desconhecida no relatório/footer, em vez de converter consumo em preço API ou registrar `$0` como cobrança comprovada.

Para replay, completar serializer, validação, `/retry`, `/resume`, fork e compressão; preservar itens opacos compatíveis com a rota e não levá-los a outros providers. Antes do build, a spec deve decidir como reservar saída quando o servidor não aceita teto: manter o contrato atual de reserva de 16k como se fosse limite garantido seria incorreto. Interromper um stream localmente não equivale a impor um teto remoto de geração/cobrança.

### Comparação com embutir Codex

| Opção | Adequação |
| --- | --- |
| OAuth próprio + Responses | Recomendada: personal-agent continua dono de prompts, Tools, confirmação, auditoria e compressão. |
| Codex app-server/SDK | Adequado se o objetivo passar a ser delegar execução ao agente Codex, com seu histórico, ferramentas e eventos; exige conciliar dois ciclos de execução. |
| Copiar OAuth Codex legado e backend privado | Mais dependência de detalhes de compatibilidade; não usar como primeira implementação. |

O [app-server oficial](https://developers.openai.com/codex/app-server) permite integração em produtos e oferece autenticação/eventos. Há também uma [configuração específica para o plano via Responses público](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server), mas nela o host ainda renova os tokens e reinicia o processo. Portanto, não elimina o trabalho de OAuth desta proposta.

## Incrementos e comprovação futura

1. **OAuth e catálogo:** teste de callback/state, ID token inválido, scope ausente, reautorização, identidade selecionada e modelos da conta. Validar escrita privada/atômica e refresh concorrente, com servidor local e tokens fictícios.
2. **Responses e Tools:** fixture SSE com texto, função namespaced, resultado e resposta final; replay de reasoning; erro após deltas, stream cortado e evento grande. Consumir SSE mesmo sem callback de exibição. Só marcar sucesso após `response.completed`; tratar incomplete separadamente.
3. **Integração:** startup, `/model`, `/retry`, compressão, retomada/fork e subagente; conta fixa e access token renovado; nenhuma credencial nos logs; nenhum fallback de cobrança. Validar também a diferença entre reserva de saída e teto efetivo.
4. **Aceitação real:** feita no spike (ver resultados abaixo), fora do código do projeto. Repetir com o provider implementado.

Reaproveitar os testes em `test_provider.py`, `test_native_streaming.py`, `test_catalog_selection.py`, `test_runtime_config.py`, `test_direct_pair_config.py`, `test_compression.py`, `test_preventive_compression.py`, `test_call_log.py`, `test_session_report.py` e `test_subagents.py`, acrescentando fixtures do protocolo novo. Não alterar expectativas de providers existentes fora do impacto comprovado.

## Resultados do spike (2026-10-20)

Scripts descartáveis em Python stdlib (+ PyJWT do `.venv` para JWKS), guardados como referência em [2026-10-20-siwc-spike/](2026-10-20-siwc-spike/); nada do código do projeto foi alterado. Uso: `spike.py login|reauth|test`, depois `.venv/bin/python suite.py api [teste...]|refresh|reuse|logout`. Tokens ficam ao lado dos scripts e são ignorados pelo Git. Conta ChatGPT do usuário, modelo principal `gpt-6.1-sol`. As duas sessões do spike foram revogadas.

### OAuth e sessão

| Teste | Resultado |
| --- | --- |
| Registro com `dynamic_agent_client` | `client_id` emitido no callback (`oaiapp_...`); troca sem client secret. |
| Scopes | Os seis concedidos, incluindo `chatgpt.tokens.use.direct`. |
| ID token | Issuer, audience (lista com o `client_id`), nonce e exp ok; assinatura RS256 validada via `https://auth.openai.com/.well-known/jwks.json`. Access token também valida (aud `https://api.openai.com/v1`). |
| Token response | `access_token`, `refresh_token`, `id_token`, `expires_in=3600`, `earliest_refresh_at`, `scope`, `token_type`. |
| Refresh | `grant_type=refresh_token` + `client_id` + `refresh_token` + `resource`, sem `scope`. Rotaciona o refresh token e devolve novo ID token. |
| `earliest_refresh_at` | ~54 min após emissão, mas **apenas recomendação**: refresh 41 min antes foi aceito. |
| Reuso do refresh token rotacionado | **Aceito (200) logo após a rotação e de novo ~16 min depois**, sem revogar a família; o token atual seguiu válido. Não é janela curta de tolerância: tokens antigos continuam válidos até a revogação da sessão. Revogar o token atual invalida também os antigos (`refresh_token_invalidated`). |
| Reautorização | `client_id` salvo + `id_token_hint` + `login_hint`, sem `agent_name_hint`: mesmo `client_id` e `sub`, nova sessão (`sid` e refresh token diferentes). |
| Logout | `POST https://auth.openai.com/api/accounts/oauth/revoke` (`token`, `token_type_hint=refresh_token`, `client_id`): 200 vazio, idempotente. Refresh depois falha com `invalid_grant`/`refresh_token_invalidated`. **O access token também morre na hora (401).** Revogação é por sessão: a outra sessão do mesmo `client_id` seguiu válida. |
| Token inválido | `/models`: 401 `{"detail":{"error_code":"invalid_token"}}`; `/responses`: 401 no formato de erro da API. |

### Catálogo

`GET /v1/models` retorna `models[]` com 9 entradas (7 `visibility=list`). Cada entrada traz, entre outros, `slug`, `display_name`, `context_window` (500k no `gpt-6.1-sol`, 272k nos demais), `max_context_window` (872k), `supported_reasoning_levels`, `default_reasoning_level`, `supports_parallel_tool_calls`, `input_modalities` e um `instructions_template` do Codex (não usar). Uma entrada de 900.009 tokens foi aceita, acima de `max_context_window`; ~1,2M falhou com `context_length_exceeded`. Os limites do catálogo não são o teto rígido; usar `context_window` como limite conservador.

### Inferência

| Teste | Resultado |
| --- | --- |
| Texto em streaming | ok; request ID no header `x-oai-request-id`. |
| `instructions` e mensagem `developer` | ok. |
| Tool em namespace | `function_call` traz `namespace`, `name`, `call_id`, `arguments`; round trip com `function_call_output` ok. |
| Replay sem `id` dos itens | ok. |
| Tools paralelas | Duas chamadas no mesmo turno, resolvidas juntas. |
| Resultado de Tool com erro | Modelo trata e responde. |
| Reasoning | `effort` low/medium/xhigh e `summary` aceitos; default observado `medium`. Item `reasoning` com `encrypted_content` vem por padrão. |
| Replay de reasoning | Com os itens o modelo manteve o estado entre turnos; sem eles, perdeu (escolheu outro número). Preservar `encrypted_content` é necessário. |
| Outro modelo | `gpt-5.6-luna` ok. |
| Saída grande | ~3,1k tokens de saída; maior evento SSE 17 KB. |
| Usage | `input_tokens`, `output_tokens`, detalhes de cache/reasoning e um campo `attribution` por item. |

Eventos observados: `response.created`, `response.in_progress`, `response.metadata` (metadados de moderação), `response.output_item.added/done`, `response.content_part.added/done`, `response.output_text.delta/done`, `response.function_call_arguments.delta/done`, `response.completed`, `response.incomplete`, `response.failed`, `error`.

### Restrições e erros

| Caso | Resultado |
| --- | --- |
| `temperature`, `top_p`, `metadata`, `truncation`, `previous_response_id` | 400 `{"detail":"Unsupported parameter: <nome>"}`, sem `error.code`. |
| `store=true` / `stream=false` | 400 `Store must be set to false` / `Stream must be set to true`. |
| `max_output_tokens` | Aceito e imposto: `status=incomplete`, `incomplete_details.reason=max_output_tokens`. |
| Mensagem `system` | Aceita e respeitada. |
| `parallel_tool_calls`, `tool_choice`, função top-level fora de namespace, `text.verbosity` | Aceitos. |
| Overflow de contexto | HTTP 200, evento `error` (`context_length_exceeded`, `param=input`), depois `response.failed`. |
| Limite de uso | HTTP 200, evento `error` com `subscription_sharing_usage_limit_exceeded`, depois `response.failed` com o mesmo `error`; sem horário de reset. `/models` e refresh continuam funcionando. A mensagem sugere usar API key: não fazer fallback automático. |

### Consequências para a implementação

- Montar a lista de itens a partir de `response.output_item.done`; não confiar em `response.completed.output`.
- Tratar `error` e `response.failed` dentro do stream como caminho principal de erro (limite, overflow); mapear `context_length_exceeded` para `ContextOverflowError`.
- Replay deve guardar itens `reasoning` com `encrypted_content` e `function_call` com `namespace`; `id` é dispensável.
- Revogação mata o access token; o logout precisa limpar estado local antes de outras chamadas.
- Reuso tolerado do refresh token reduz o risco de corrida entre processos, mas não substitui o bloqueio: é comportamento não documentado. Também significa que um refresh token antigo vazado segue utilizável; o logout deve sempre revogar a sessão no servidor, não só apagar o arquivo local.
- O limite de uso é compartilhado com o uso interativo do ChatGPT/Codex. A janela de 5h, já perto do fim, foi atingida durante o spike; ~1,8M tokens de entrada vieram de duas sondas de overflow.

Não testado: erro 503 transitório, expiração natural do access token, imagens de entrada (o projeto não usa) e WebSocket (`prefer_websockets=true` no catálogo; HTTP SSE funcionou).

## Decisões originais da discovery (resolvidas na 0057)

Decisão final: uma conta conectada; reserva de saída local sem enviar `max_output_tokens`; catálogo da conta independente de Models.dev; custo do plano desconhecido; esgotamento exige ação explícita; validação JWKS com `PyJWT[crypto]`. Ver [ADR-0015](../adrs/0015-chatgpt-subscription-provider.md). As alternativas abaixo são o registro original.

1. **Contas:** uma conta ou várias com seleção. (Uma; troca por logout/login.)
2. **Teto de saída:** depender de `max_output_tokens`, aceito mas não documentado, ou tratar a reserva de 16k como estimativa local.
3. **Catálogo:** como o catálogo da conta (`/v1/models`) convive com ADR-0011/0012, que admitem o par via Models.dev; usar `context_window` da conta como limite.
4. **Custo e relatório:** como footer e Session Report mostram uso do plano com `cost=null`, sem converter em preço API.
5. **Limite de uso no meio de uma tarefa:** parar a tarefa e orientar o usuário (`/model` para outro provider ou esperar o reset), sem fallback automático.
6. **Escopo do JWKS:** manter validação de assinatura (`PyJWT[crypto]` como dependência direta) ou só nonce/state/PKCE/scope.

Pré-requisitos práticos: a aceitação exige novo login no navegador e cota de 5h disponível.

## Limites desta pesquisa

Nenhuma implementação, migração, alteração de regra canônica ou estado de feature. Nenhum commit/push. Context7 consultado para OpenCode, Codex e PyJWT; as regras de SIWC foram verificadas nas páginas oficiais específicas porque os resultados de Codex também misturavam autenticação antiga. Acesso da conta, Tools, reasoning, refresh e erros foram demonstrados no spike; economia frente à API não foi medida. A integração está documentada como preview e o spike encontrou divergências da documentação; rever os contratos antes de implementar.
