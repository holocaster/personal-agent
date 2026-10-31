# personal-agent vs opencode — comparação de features

> **PENDENTE: extensibilidade por entry points** (plugins carregados de pacotes instalados, candidato 5). Não implementado; fora da feature 0055 por falta de um plugin concreto. Retomar quando houver um plugin real a carregar.

Snapshot original do OpenCode: 2026-09-23. Coluna `personal-agent` atualizada em 2026-10-04
até a feature 0041 (reavaliação periódica de tier), incluindo MCP Resources (0034), auditoria (0036), orçamento de contexto (0037) e seleção de tier por Session (0039). A comparação original veio da leitura direta de um fork local do OpenCode
(branch `dev`; caminho local omitido) e do código-fonte deste repositório. Nada foi
copiado; é um levantamento para decisão, não uma proposta fechada.

As capacidades do OpenCode preservam a pesquisa original; esta atualização não as revalida. No `personal-agent`, `plan`/`build` confirmam Network Tools e MCP Resources; `build` confirma Tools mutáveis. `auto` dispensa confirmação comum, mas mantém Strong Confirmation para comandos perigosos reconhecidos.

## Stack

| | personal-agent | opencode |
| --- | --- | --- |
| Linguagem | Python 3.12 + uv | TypeScript + Bun |
| Formato | pacote único, CLI/REPL | monorepo Turborepo (30+ packages) |
| Interfaces | terminal REPL | TUI, Web, Desktop, Slack, Console |
| Deploy | não aplicável (roda local) | SST |

## Comparação de capacidades

✅ = tem · ❌ = não tem · 🟡 = tem parcial/equivalente aproximado

### Tools de agente

| Tool (opencode) | personal-agent | Equivalente / nota |
| --- | :---: | --- |
| `read` | ✅ | `read_file` |
| `glob` | 🟡 | `list_files(pattern=...)`; glob case-sensitive, com semântica própria |
| `grep` | 🟡 | `search_text` é literal por padrão e aceita `regex: true` e filtro `glob` |
| `write` | ✅ | **feature 0016** (2026-09-24) — com Tool Confirmation, sem mkdir implícito |
| `edit` | ✅ | **feature 0016** (2026-09-24) — match exato, sem fuzzy matching |
| `apply_patch` | ✅ | **feature 0028** (2026-09-27) — formato OpenAI/Codex (add/update/delete, sem move), match exato, tudo-ou-nada, uma Tool Confirmation com diff combinado |
| `shell` | ✅ | **feature 0018** — ligado por padrão (`PA_ENABLE_SHELL=0` desliga), Tool Confirmation; **feature 0023** exige `yes` para regras perigosas conhecidas; encerra o process group ao fim da chamada |
| `lsp` | ❌ | |
| `webfetch` | ✅ | **feature 0022** — GET HTTP(S) sob Tool Confirmation; conteúdo é tratado como não confiável |
| `websearch` | ✅ | **feature 0027** — Tavily opt-in (`TAVILY_API_KEY`), busca básica com Tool Confirmation por consulta; títulos, URLs e trechos limitados |
| `task` (subagente) | ❌ | |
| `todo` | ✅ | **feature 0022** — checklist segue a Conversation, inclusive Compression e Resume |
| `plan` | ❌ | Tool específica do OpenCode; distinta do Agent Mode `/mode plan` |
| `question` | 🟡 | **feature 0026** — lote de até quatro perguntas, uma resposta por pergunta, escolhas opcionais e texto livre; exige Input Box interativo |
| `skill` | ✅ | **features 0031 e 0032** — modelo escolhe pelo nome/descrição e carrega até quatro skills efetivas sob demanda; não ativa `/skill` para o Run |
| `code-mode` | ❌ | |

### O que significam LSP, todo e code-mode

- **LSP** (*Language Server Protocol*): protocolo entre um editor/agente e um servidor de linguagem, que pode fornecer diagnósticos, definições, referências e símbolos. A linha da tabela se refere a essa integração de inteligência de código. O suporte varia por versão; a documentação atual do OpenCode V2 informa que ainda não há runtime LSP ativo.
- **todo**: ferramenta para criar e atualizar uma lista de tarefas da sessão, com estados como `pending`, `in_progress` e `completed`. No `personal-agent`, a feature 0022 adicionou `todo` e uma lista que acompanha a Conversation.
- **code-mode**: ambiente restrito para executar JavaScript que combina chamadas às ferramentas disponíveis. No OpenCode V2 ele só acessa o catálogo de ferramentas permitido; não tem acesso direto ao filesystem, imports ou `fetch`.

Referências: [OpenCode LSP](https://opencode.ai/v2/docs/lsp/), [OpenCode Tools e Code Mode](https://opencode.ai/v2/docs/tools/), [descrição da ferramenta TodoWrite](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/tool/todowrite.txt).

### Agentes / modos

| Feature (opencode) | personal-agent | Nota |
| --- | :---: | --- |
| Modo `build` (acesso completo, Tab) | 🟡 | `/mode build` é o padrão de cada Run; Tools de escrita e `shell` exigem Tool Confirmation. Troca por `/mode` ou Shift+Tab no Input Box |
| Modo `plan` (read-only, pede permissão) | 🟡 | `/mode plan` não oferece nem executa `write`, `edit`, `apply_patch` ou `shell`; `webfetch`, `websearch` e MCP Resources (quando configurados) continuam sob Tool Confirmation. Troca por `/mode` ou Shift+Tab no Input Box |
| Subagente `general` (`@general`) | ❌ | |

### Extensibilidade

| Feature (opencode) | personal-agent | Nota |
| --- | :---: | --- |
| Sistema de plugins | ❌ | |
| MCP (cliente) | ✅ parcial | Resources por stdio (feature 0034); sem Tools MCP |
| Sistema de skills | 🟡 | **features 0030–0032** — skills do workspace e do usuário, múltiplas ativas por Run ou carregadas sob demanda via `skill(name)`/`skill(names)`; sem instalação automática |
| Registrar tool externa sem tocar no core | ❌ | Tools são hardcoded em `tools/registry.py` |

### Sessão

| Feature (opencode) | personal-agent | Nota |
| --- | :---: | --- |
| Compaction automática (gatilho sozinho) | ✅ | **feature 0037** substituiu o gatilho pós-resposta de 0020: mede input completo antes de cada exchange; 80% do orçamento efetivo com turnos antigos elegíveis, alvo de 60% e teto obrigatório independente; continua o exchange pendente, sem Continuation Turn |
| "Context Epoch" | ❌ | |
| "Mid-Conversation System Messages" | ❌ | |
| System Context Registry (fontes plugáveis) | ❌ | |
| Resume de sessão | ✅ | |
| Replay a partir do log | ✅ | via Call Log JSONL |
| `/retry` e `/undo` de turno | ✅ | |
| Memória persistente entre sessões | ✅ | Memory Notes (`/remember`), não documentado no opencode nesta pesquisa |

### Providers / Models

| Feature | personal-agent | opencode |
| --- | :---: | :---: |
| Catálogo de modelos plugável | ❌ | ✅ |
| Roteamento automático por complexidade (Tier) | ✅ | ❌ |

O `personal-agent` configura três slots por ambiente ou `/config`, sem catálogo plugável. A feature 0041 avalia pedidos acumulados antes das tarefas 1/5/15 e só mantém/sobe o tier; `/model <tier>` suspende a avaliação e pode rebaixar. Retries ficam na rota selecionada; Escalation e o limite monetário foram removidos em 0039.

## O que não copiar

TUI rica, app desktop, integração Slack, LSP, "everything is a plugin", subagentes paralelos —
escopo de plataforma completa, incompatível com o objetivo do CLAUDE.md deste projeto (router
simples, sem overengineering).

## Candidatos a próximas features

| # | Candidato | Status | Nota |
| --- | --- | :---: | --- |
| 1 | Tool `edit`/`write` | ✅ feito | feature `0016-write-tools`, 2026-09-24. Ganhou Tool Confirmation (não previsto aqui originalmente); sem mkdir implícito e sem fuzzy matching (decisões deliberadas, ver `docs/CONTEXT.md`) |
| 2 | Tool `shell` com prompt de confirmação | ✅ feito | feature `0018-shell-tool`; ligado por padrão (`PA_ENABLE_SHELL=0` desliga). Feature `0023` adicionou Strong Confirmation para comandos reconhecidos como perigosos; nenhum deles é bloqueado automaticamente. Encerra o process group ao fim da chamada; um processo que escape com `setsid` pode continuar rodando |
| 3 | Auto-gatilho de `/compress` por turns/tokens | ✅ feito | 0020 entregou o gatilho inicial; 0037 o substituiu por Compression preventiva antes de cada exchange, orçamento configurável e recuperação de overflow na mesma rota. Sem Continuation Turn; comportamento atual em `docs/CONTEXT.md` |
| 4 | Modos `plan`/`build`/`auto` | ✅ feito | features `0025-plan-build-mode` e `0033-auto-mode`; Shift+Tab percorre os três modos. Cada Run começa em `build`; `plan` recusa Tools mutáveis, `build` confirma, `auto` dispensa confirmação comum mas mantém Strong Confirmation para comandos sinalizados |
| 5 | Extensibilidade — mínima (entry points) ou maior (cliente MCP) | ✅ MCP Resources implementado (`0034-mcp-resources`) | primeiro escopo: Resources por stdio; **entry points pendentes**: fora da feature 0055 (2026-10-17) por falta de um plugin concreto; **MCP Tools pendente**, adiado pelo usuário |
| 6 | Glob/regex em busca, `webfetch` e `todo` | ✅ feito | feature `0022-web-todo-search`, 2026-09-25 |
| 7 | Strong Confirmation, aviso de conteúdo buscado e remoção de HTML oculto | ✅ feito | feature `0023-shell-guardrails`, 2026-09-25 |
| 8 | Skills do workspace com ativação explícita | ✅ feito | feature `0030-workspace-skills`, 2026-09-28; feature `0031-skill-tool` adicionou carregamento sob demanda pelo modelo |
| 9 | Múltiplas skills ativas no mesmo Run | ✅ feito | feature `0032-complete-skills`, 2026-09-29; inclui skills globais do usuário, múltiplas ativas e Tool com seleção múltipla |
