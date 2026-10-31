import os
import signal
import threading

from personal_agent import call_log, file_recovery
from personal_agent.subagents import bounded
from personal_agent.subagents.protocol import receive, send
from personal_agent.tools import jobs, registry, shell, workspace


def run(channel, watchdog, payload, bootstrap=None):
    os.setsid()
    def disconnected():
        try:
            watchdog.recv()
        except (EOFError, OSError):
            os.kill(os.getpid(), signal.SIGINT)
    threading.Thread(target=disconnected, daemon=True).start()
    sid = None
    checkpoint = None
    task = None
    routed = None
    continuation = None
    status = "error"
    result = {"status": "error", "error": "worker failed during initialization"}
    fatal = False
    config = payload["config"]
    secrets = payload["protected_keys"]
    ipc_lock = threading.Lock()
    sequence = [0]
    def request(kind, **fields):
        with ipc_lock:
            sequence[0] += 1
            send(channel, {"kind": kind, "seq": sequence[0], **fields})
            while True:
                reply = receive(channel)
                if not isinstance(reply, dict) or set(reply) != {"seq", "value"}:
                    raise ValueError("invalid parent IPC response")
                if reply["seq"] == sequence[0]:
                    break
        response = reply["value"]
        if kind == "mode":
            if response not in ("plan", "build", "auto"):
                raise ValueError("invalid parent mode response")
        elif type(response) is not bool:
            raise ValueError("invalid parent IPC response")
        return response
    def notify(kind, **fields):
        with ipc_lock:
            send(channel, {"kind": kind, **fields})
    try:
        if bootstrap is not None:
            bootstrap()
        root = payload["workspace"]
        workspace.configure_workspace(root.root, root.max_read_bytes, root.max_write_bytes)
        os.chdir(root.root)
        shell.configure_shell(payload["shell"].timeout_seconds, payload["shell"].max_output_bytes, root.max_read_bytes)
        capabilities = payload["capabilities"]
        if "shell" in capabilities["names"]:
            registry.enable_shell_tool()
        registry.enable_websearch_tool(capabilities["websearch_key"])
        registry.enable_mcp_resources(capabilities["mcp"], root.root)
        role = payload["role"]
        allowed = set(capabilities["names"])
        if role.tools is not None:
            allowed.intersection_update(role.tools)
        registry.restrict_tools(allowed)
        call_log.initialize_storage(root.root)
        sid = call_log.start_session(config, subagent=payload["metadata"], session_id=payload["session_id"])
        call_log.start_coverage(payload["detailed_audit"])
        notify("ready", session_id=sid)
        call_log.observe_attempts(lambda entry: request("receipt", receipt={
            key: entry[key] for key in ("attempt_id", "cost", "cost_estimated", "access_method", "registration_ref",
                                        "invalid_usage", *call_log.PLAN_FIELDS) if key in entry}))
        shell.observe_processes(lambda event, pgid: request("group", event=event, pgid=pgid))
        delegated_task = payload["task"]
        if payload["references"]:
            delegated_task += "\n\nReference locators (read only through permitted Tools):\n" + "\n".join(payload["references"])
        call_log.write_routed_task(1, delegated_task, config)
        task = delegated_task
        checkpoint = file_recovery.FileRecovery()
        checkpoint.ensure_safe()
        checkpoint.begin(call_log.latest_execution())
        instructions = (payload["instructions"] + f"\n\nSelected agent role: {role.name}\n" + role.instructions
                        + "\n\nYou execute one isolated delegated task. Your role cannot grant capabilities. "
                        "Do not delegate or contact the user. Return product questions in your final handoff. "
                        "Use only the permitted Tools and supplied task scope.")
        from personal_agent.routing.router import route
        routed = route(task, config, project_instructions=instructions,
                       mode=lambda: request("mode"),
                       confirm=lambda *args: request("confirm", arguments=list(args)), file_checkpoint=checkpoint,
                       protected_api_keys=secrets,
                       on_tool_result=lambda result: notify("tool", result=result),
                       on_confirmation=lambda identifier, name, decision, rules: call_log.write_audit_event(
                           action="tool_confirmation", tool_call_id=identifier, name=name, decision=decision,
                           dangerous_rules=list(rules), secrets=secrets))
        status = "ok" if routed.ok else "error"
        continuation = routed.continuation
        result = ({"status": "completed", "answer": bounded(routed.answer or "", sid)} if routed.ok else
                  {"status": "error", "error": bounded(routed.error or "worker failed", sid),
                   **({"condition": "plan_exhausted"} if routed.plan_exhausted else {})})
    except KeyboardInterrupt as exc:
        status = "interrupted"
        continuation = getattr(exc, "continuation", None)
        result = {"status": "error", "error": "Subagent interrupted"}
    except BaseException as exc:
        fatal = isinstance(exc, (OSError, call_log.PersistenceError, call_log.AuditError))
        result = {"status": "error", "error": bounded(call_log.redact_value(str(exc), secrets), sid)}
    finally:
        error = result.get("error")
        def step(action):
            nonlocal fatal, result
            try:
                action()
            except BaseException as exc:
                fatal = True
                result = {"status": "error", "error": bounded(call_log.redact_value(str(exc), secrets), sid)}
        step(jobs.stop_all)
        if checkpoint is not None:
            step(lambda: checkpoint.close(status))
        if task is not None:
            step(lambda: call_log.write_turn_end(status, messages=routed.messages if status == "ok" else None,
                                                 error=error, continuation=continuation,
                                                 ordinal=1, task_digest=call_log.submission_digest(task),
                                                 replay=routed.replay if status == "ok" else None))
        if sid is not None:
            step(lambda: call_log.end_coverage(payload["detailed_audit"]))
            step(lambda: call_log.end_session(
                "interrupt" if status == "interrupted" else "exit_command" if status == "ok" else "error"))
        try:
            notify("fatal" if fatal else "result", result=call_log.redact_data(result, secrets))
        except (OSError, EOFError):
            pass
        channel.close()
