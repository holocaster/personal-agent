import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from personal_agent import call_log, chatgpt_auth, memory, model_catalog, project_instructions
from personal_agent.dotenv import load_dotenv
from personal_agent.routing import runtime_config
from personal_agent.terminal.input_box import InputBox
from personal_agent.terminal.tty import sanitize_control_chars
from personal_agent.terminal.repl import COMMANDS, run_repl
from personal_agent.tools import registry as tools_registry, shell as shell_tool, workspace, mcp_resources


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="personal-agent")
    parser.add_argument("--resume", default=None, help="Session Id, or 'last', to resume")
    parser.add_argument("--models", metavar="PROVIDER", help="List API catalog or chatgpt account models and exit")
    parser.add_argument("--search", metavar="TEXT", help="Filter --models by ID or name")
    parser.add_argument("--refresh-models", action="store_true", help="Refresh the Models.dev catalog cache and exit")
    args = parser.parse_args([] if argv is None else argv)
    if args.search is not None and args.models is None:
        parser.error("--search requires --models <provider>")
    if args.resume is not None and (args.models is not None or args.refresh_models):
        parser.error("--resume cannot be combined with --models or --refresh-models")
    return args


def _catalog_command(args: argparse.Namespace) -> None:
    def fail(message: str) -> None:
        print(sanitize_control_chars(message, multiline=False), file=sys.stderr)
        sys.exit(1)

    try:
        provider = ("chatgpt" if args.models and args.models.strip().lower() == "chatgpt"
                    else model_catalog.normalize_provider(args.models) if args.models is not None else None)
    except model_catalog.CatalogError as exc:
        fail(str(exc))
    if provider == "chatgpt":
        try:
            auth = chatgpt_auth.ChatGPTAuth()
            status = auth.status()
            if not status.connected:
                raise chatgpt_auth.AuthError("Connect in a local interactive REPL with /connect chatgpt")
            if not status.acknowledged:
                raise chatgpt_auth.AuthError("Acknowledge plan use in an interactive /connect chatgpt")
            choices = auth.models(status.binding)
            query = (args.search or "").casefold()
            print("ChatGPT account models; listing does not prove inference access:")
            for model in choices:
                if query in model.id.casefold() or query in model.name.casefold():
                    print(chatgpt_auth.safe(f"  {model.id}  {model.name}"))
        except chatgpt_auth.AuthError as exc:
            fail(chatgpt_auth.safe(str(exc)))
        return
    if args.refresh_models:
        try:
            catalog = model_catalog.refresh()
        except model_catalog.CatalogError as exc:
            fail(f"Models.dev catalog refresh failed: {exc}. Existing cache and settings kept; "
                 f"retry with {model_catalog.REFRESH_COMMAND}.")
        counts = ", ".join(f"{name} {len(catalog.search(name))}" for name in model_catalog.PROVIDERS)
        print(f"Models.dev catalog refreshed at {catalog.fetched_at}; eligible models: {counts}.")
    else:
        try:
            catalog = model_catalog.load()
        except model_catalog.CatalogError as exc:
            fail(str(exc))
    if provider is not None:
        print(model_catalog.render(catalog, provider, args.search or ""))


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.models is not None or args.refresh_models:
        _catalog_command(args)
        return
    workspace_root = Path.cwd().resolve()
    call_log.initialize_storage(workspace_root)
    managed_env_vars = runtime_config.MANAGED_ENV_VARS
    exported_managed_vars = managed_env_vars.intersection(os.environ)
    load_dotenv()
    cwd_dotenv_vars = managed_env_vars.intersection(os.environ).difference(exported_managed_vars)
    before_home_dotenv_vars = managed_env_vars.intersection(os.environ)
    load_dotenv(os.path.expanduser("~/.personal_agent/.env"))
    if os.environ.get("PA_DETAILED_AUDIT") not in (None, "0", "1"):
        print("Configuration error: PA_DETAILED_AUDIT must be 0, 1, or unset", file=sys.stderr)
        sys.exit(1)
    tools_registry.enable_websearch_tool(os.environ.get("TAVILY_API_KEY"))
    home_dotenv_vars = managed_env_vars.intersection(os.environ).difference(before_home_dotenv_vars)
    config_sources = {variable: "exported environment" for variable in exported_managed_vars}
    config_sources.update({variable: "current-directory .env" for variable in cwd_dotenv_vars})
    config_sources.update({variable: "home .env" for variable in home_dotenv_vars})
    try:
        workspace_config = workspace.configure_workspace(
            workspace_root,
            os.environ.get("PA_MAX_READ_BYTES"),
            os.environ.get("PA_MAX_WRITE_BYTES"),
        )
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        mcp_config = mcp_resources.parse_config(os.environ.get("PA_MCP_SERVER"))
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
    tools_registry.enable_mcp_resources(mcp_config, workspace_config.root)

    shell_enable_value = os.environ.get("PA_ENABLE_SHELL")
    if shell_enable_value not in (None, "", "0", "1"):
        print(
            f"Configuration error: PA_ENABLE_SHELL must be 1, 0, or unset: {shell_enable_value}",
            file=sys.stderr,
        )
        sys.exit(1)
    if shell_enable_value != "0":
        try:
            shell_tool.configure_shell(
                os.environ.get("PA_SHELL_TIMEOUT_SECONDS"),
                os.environ.get("PA_SHELL_MAX_OUTPUT_BYTES"),
                workspace_config.max_read_bytes,
            )
        except ValueError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            sys.exit(1)
        tools_registry.enable_shell_tool()

    try:
        config = runtime_config.load()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)
    problems = runtime_config.validate(config)
    if problems:
        print("Configuration error:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)

    catalog = None
    try:
        if config.provider != "chatgpt":
            catalog = model_catalog.load()
        if not problems and config.provider != "chatgpt":
            config = replace(config, offering=catalog.lookup(config.provider, config.model))
    except model_catalog.CatalogError as exc:
        print(f"Configuration error: {sanitize_control_chars(str(exc), multiline=False)}", file=sys.stderr)
        print(f"List eligible models with personal-agent --models {config.provider}; refresh with "
              f"{model_catalog.REFRESH_COMMAND}.", file=sys.stderr)
        problems.append(str(exc))
    if config.provider == "chatgpt" and not problems:
        try:
            config = runtime_config.admit_chatgpt(config)
        except chatgpt_auth.AuthError as exc:
            problems.append(chatgpt_auth.safe(str(exc)))
    config = replace(config, readiness_error="; ".join(problems) if problems else None)

    try:
        memory_notes = memory.load()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    resumed = None
    if args.resume is not None:
        try:
            session_id = call_log.resolve_resume_session(args.resume)
            turns, summary, todo_baseline, submissions = call_log.load_conversation(session_id)
        except call_log.ResumeError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        resumed = (session_id, turns, summary, todo_baseline, submissions)

    input_box = InputBox(COMMANDS) if sys.stdin.isatty() and sys.stdout.isatty() else None
    try:
        run_repl(
            config,
            input_box=input_box,
            resumed=resumed,
            memory_notes=memory_notes,
            config_sources=config_sources,
            workspace_root=workspace_config.root,
            catalog=catalog,
        )
    except project_instructions.LoadError as exc:
        print(f"Project instructions error: {sanitize_control_chars(str(exc), multiline=False)}", file=sys.stderr)
        sys.exit(1)
    except call_log.AuditError as exc:
        print(f"Fatal audit error: {exc}", file=sys.stderr)
        sys.exit(1)
    except call_log.ResumeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except (call_log.PersistenceError, OSError) as exc:
        print(f"Fatal persistence error: {exc}", file=sys.stderr)
        sys.exit(1)


def cli() -> None:
    main(sys.argv[1:])


if __name__ == "__main__":
    cli()
