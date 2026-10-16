"""prompt_strategies — real LLM call routed to Anthropic OR OpenAI (P3.1).

The ``direct`` variant loads a prompt template, renders it with the
retrieved documents + the user request, and calls whichever provider
matches the model id picked by the route stage:

  - ``claude-*`` / ``anthropic-*``  → Anthropic SDK
  - ``deepseek-*``                  → OpenAI SDK (OpenAI-compatible API)
  - ``gpt-*`` / ``o1-*`` / ``o3-*`` → OpenAI SDK
  - ``ollama/*``                    → local Ollama OpenAI-compatible API

Token usage is stashed in ``ctx.state["llm_usage"]`` so the executor
can compute exact cost instead of the char-based estimate it falls
back to.

BYOK (P3.1): the key is resolved through ``runtime.agents.secrets``:
  1) ``agents/<active_id>/secrets.env`` (operator's per-agent key)
  2) ``os.environ`` (global ``.env`` from server startup)
  3) None → offline marker, response still non-empty, tests still pass

Offline path is intact for the cold-clone case: missing key / missing
SDK package → clearly-marked response, no crash. Same shape the rest
of the pipeline expects.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from runtime.protocols import BaseTechnique, Context, Document, Stage


logger = logging.getLogger("techniques.prompt_strategies")

_DEFAULT_MODEL = "claude-haiku-4-5"
_DEFAULT_SYSTEM = (
    "You are a helpful assistant. Answer based on the provided context. "
    "If the context does not contain the answer, say so explicitly."
)


class _Direct:
    def __init__(self, knobs: dict[str, Any]) -> None:
        self.prompt_path: str = str(knobs.get("prompt", "../prompts/system.md"))
        self.max_tokens: int = int(knobs.get("max_tokens", 2048))
        self.temperature: float = float(knobs.get("temperature", 0.3))
        self.max_tool_iterations: int = int(knobs.get("max_tool_iterations", 8))

    def execute(self, context: Context) -> Context:
        from runtime.agent_context import get_active
        from runtime.agents.secrets import get_secret, provider_for_model

        model = (
            context.routing.model
            if context.routing and context.routing.model
            else _DEFAULT_MODEL
        )
        system = _load_system_prompt(self.prompt_path)
        user_msg = _render_user_message(context.documents, context.request)

        provider = provider_for_model(model) or "anthropic"
        agent_id = get_active()
        is_ollama = provider == "ollama"
        api_key = "ollama" if is_ollama else get_secret(provider, agent_id=agent_id)

        if not api_key:
            context.response = (
                f"[offline] No {provider} API key set for agent {agent_id!r} — "
                f"would have called {model} with {len(context.documents)} doc(s). "
                f"Request: {context.request!r}"
            )
            return context

        tools: list[Any] = []
        try:
            from runtime.mcp.client import list_tools_for_agent
            tools = list_tools_for_agent(agent_id)
        except Exception as e:
            logger.warning("mcp discovery failed for %s (%s); proceeding tool-free", agent_id, e)
            tools = []

        try:
            if provider in ("openai", "deepseek", "ollama"):
                base_url = None
                if provider == "deepseek":
                    base_url = os.environ.get(
                        "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
                    )
                request_model = model
                if provider == "ollama":
                    base_url = (
                        os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
                        .rstrip("/")
                        + "/v1"
                    )
                    configured_model = os.environ.get("OLLAMA_MODEL", "").strip()
                    requested_model = model.removeprefix("ollama/").strip()
                    request_model = (
                        configured_model
                        if requested_model in ("", "local", "default")
                        else requested_model
                    )
                    if not request_model:
                        raise ValueError(
                            "OLLAMA_MODEL is required when using ollama/local"
                        )
                if is_ollama:
                    text, usage, tool_calls = _run_ollama_native(
                        model=request_model,
                        system=system,
                        user=user_msg,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                    )
                else:
                    text, usage, tool_calls = _run_openai_loop(
                        model=request_model,
                        system=system,
                        user=user_msg,
                        api_key=api_key,
                        base_url=base_url,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        tools=tools,
                        agent_id=agent_id,
                        max_iterations=self.max_tool_iterations,
                    )
            else:
                text, usage, tool_calls = _run_anthropic_loop(
                    model=model,
                    system=system,
                    user=user_msg,
                    api_key=api_key,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    tools=tools,
                    agent_id=agent_id,
                    max_iterations=self.max_tool_iterations,
                )
        except _SdkUnavailable as e:
            logger.warning("%s SDK unavailable: %s", provider, e)
            context.response = (
                f"[offline] {provider} SDK not installed — would have called "
                f"{model}. Request: {context.request!r}"
            )
            return context
        except Exception as e:
            logger.warning("%s call failed (%s); returning error marker", provider, e)
            context.response = (
                f"[error] LLM call failed: {type(e).__name__}: {e}. "
                f"Request: {context.request!r}"
            )
            return context

        context.response = text or "(empty response)"
        if usage:
            context.state["llm_usage"] = {**usage, "model": model, "provider": provider}
        if tool_calls:
            context.state["tool_calls"] = tool_calls
        return context


class _SdkUnavailable(RuntimeError):
    """Raised when the provider's SDK isn't importable."""


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


def _run_anthropic_loop(
    *,
    model: str,
    system: str,
    user: str,
    api_key: str,
    max_tokens: int,
    temperature: float,
    tools: list[Any],
    agent_id: str,
    max_iterations: int,
) -> tuple[str, Optional[dict], list[dict[str, Any]]]:
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise _SdkUnavailable("anthropic") from e
    from runtime.mcp.client import call_tool as mcp_call

    client = Anthropic(api_key=api_key)
    anthropic_tools = [t.to_anthropic_tool() for t in tools] if tools else None
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    total_in = 0
    total_out = 0
    tool_calls: list[dict[str, Any]] = []
    final_text = ""

    for it in range(max_iterations + 1):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": messages,
        }
        if anthropic_tools and it < max_iterations:
            kwargs["tools"] = anthropic_tools

        resp = client.messages.create(**kwargs)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            total_in += int(getattr(usage, "input_tokens", 0) or 0)
            total_out += int(getattr(usage, "output_tokens", 0) or 0)

        text_parts: list[str] = []
        tool_use_blocks: list[Any] = []
        for block in (resp.content or []):
            btype = getattr(block, "type", None)
            if btype == "tool_use":
                tool_use_blocks.append(block)
                continue
            t = getattr(block, "text", None)
            if isinstance(t, str) and t:
                text_parts.append(t)

        if not tool_use_blocks:
            final_text = "".join(text_parts)
            break

        messages.append({"role": "assistant", "content": resp.content})

        result_blocks: list[dict[str, Any]] = []
        for tu in tool_use_blocks:
            qname = getattr(tu, "name", "")
            args = getattr(tu, "input", {}) or {}
            tu_id = getattr(tu, "id", "")
            tool_calls.append({"name": qname, "input": args, "id": tu_id})
            try:
                result_text = mcp_call(agent_id, qname, args)
                is_error = False
            except Exception as e:
                logger.warning("mcp tool %s failed: %s", qname, e)
                result_text = f"Tool error: {type(e).__name__}: {e}"
                is_error = True
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tu_id,
                "content": result_text,
            }
            if is_error:
                block["is_error"] = True
            result_blocks.append(block)

        messages.append({"role": "user", "content": result_blocks})

    usage_dict: Optional[dict] = None
    if total_in or total_out:
        usage_dict = {"input_tokens": total_in, "output_tokens": total_out}
    return final_text, usage_dict, tool_calls


# ---------------------------------------------------------------------------
# Ollama native
# ---------------------------------------------------------------------------

def _run_ollama_native(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, Optional[dict], list[dict[str, Any]]]:
    import json
    import urllib.error
    import urllib.request

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    if base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/")[:-3]
    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": "10m",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": temperature,
            "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX", "4096")),
            "num_predict": max_tokens,
        },
    }
    if "TAREFA_SYSTEMOS_ANALISE_TECNICA_V1" in user:
        payload["format"] = "json"
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    timeout = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "180"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    message = body.get("message") if isinstance(body, dict) else None
    text = message.get("content", "") if isinstance(message, dict) else ""
    usage = {
        "input_tokens": int(body.get("prompt_eval_count", 0) or 0),
        "output_tokens": int(body.get("eval_count", 0) or 0),
    }
    return text, usage, []


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


def _run_openai_loop(
    *,
    model: str,
    system: str,
    user: str,
    api_key: str,
    base_url: Optional[str] = None,
    max_tokens: int,
    temperature: float,
    tools: list[Any],
    agent_id: str,
    max_iterations: int,
) -> tuple[str, Optional[dict], list[dict[str, Any]]]:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise _SdkUnavailable("openai") from e
    from runtime.mcp.client import call_tool as mcp_call

    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)

    openai_tools = [t.to_openai_tool() for t in tools] if tools else None
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    total_in = 0
    total_out = 0
    tool_calls: list[dict[str, Any]] = []
    final_text = ""

    for it in range(max_iterations + 1):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if openai_tools and it < max_iterations:
            kwargs["tools"] = openai_tools
        resp = client.chat.completions.create(**kwargs)
        usage_obj = getattr(resp, "usage", None)
        if usage_obj is not None:
            total_in += int(getattr(usage_obj, "prompt_tokens", 0) or 0)
            total_out += int(getattr(usage_obj, "completion_tokens", 0) or 0)

        if not resp.choices:
            break
        choice = resp.choices[0]
        msg = choice.message

        calls = getattr(msg, "tool_calls", None) or []
        if not calls:
            final_text = msg.content or ""
            break

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in calls
            ],
        })

        for tc in calls:
            qname = tc.function.name
            try:
                import json as _json
                args = _json.loads(tc.function.arguments) if tc.function.arguments else {}
            except Exception:
                args = {}
            tool_calls.append({"name": qname, "input": args, "id": tc.id})
            try:
                result_text = mcp_call(agent_id, qname, args)
            except Exception as e:
                logger.warning("mcp tool %s failed: %s", qname, e)
                result_text = f"Tool error: {type(e).__name__}: {e}"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_text,
            })

    usage_dict: Optional[dict] = None
    if total_in or total_out:
        usage_dict = {"input_tokens": total_in, "output_tokens": total_out}
    return final_text, usage_dict, tool_calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_system_prompt(path: str) -> str:
    """Resolve the prompt path against a few likely roots; fall back to default.
    Replaces {{CURRENT_DATE}} and {{CURRENT_TIME}} with the current UTC date/time.
    """
    from datetime import datetime, timezone

    candidates = [
        Path(path),
        Path("agent/pipeline") / path,
        Path("agent") / path,
        Path.cwd() / path,
    ]
    prompt = _DEFAULT_SYSTEM
    for p in candidates:
        try:
            resolved = p.resolve()
            if resolved.is_file():
                prompt = resolved.read_text(encoding="utf-8").strip()
                break
        except OSError:
            continue

    now = datetime.now(timezone.utc)
    prompt = prompt.replace("{{CURRENT_DATE}}", now.strftime("%Y-%m-%d"))
    prompt = prompt.replace("{{CURRENT_TIME}}", now.strftime("%H:%M:%S"))
    return prompt


def _render_user_message(documents: list[Document], request: str) -> str:
    if not documents:
        return request
    blocks = []
    for i, doc in enumerate(documents, 1):
        metadata = doc.metadata or {}
        source = metadata.get("source") or metadata.get("documento_id") or ""
        fabricante = metadata.get("fabricante") or metadata.get("manufacturer") or ""
        modelo = metadata.get("modelo") or metadata.get("model") or ""
        tipo = metadata.get("tipo") or metadata.get("document_type") or ""
        header_parts = [f"[{i}]"]
        if source:
            header_parts.append(f"Fonte: {source}")
        details = []
        if fabricante:
            details.append(f"fabricante={fabricante}")
        if modelo:
            details.append(f"modelo={modelo}")
        if tipo:
            details.append(f"tipo={tipo}")
        if details:
            header_parts.append("(" + ", ".join(details) + ")")
        blocks.append(f"{' '.join(header_parts)}\n{doc.content}")
    context_str = "\n\n".join(blocks)
    instructions = (
        "Use somente o contexto abaixo como base factual quando houver contexto. "
        "Quando o usuario pedir para listar todos, todos os modelos, todos os "
        "clientes, todos os motores ou um inventario completo, percorra todas as "
        "fontes do contexto antes de responder. Nao resuma para apenas dois "
        "exemplos. Se a lista estiver limitada ao contexto recuperado, diga isso "
        "explicitamente."
    )
    return (
        f"Instrucoes de uso do contexto:\n{instructions}\n\n"
        f"Context:\n{context_str}\n\nQuestion: {request}"
    )


class _ClaudeCode:
    def __init__(self, knobs: dict[str, Any]) -> None:
        self.timeout_s: int = int(knobs.get("timeout", 300))

    def execute(self, context: Context) -> Context:
        from runtime.agent_context import get_active
        from runtime.agents.secrets import get_secret
        from runtime.sandbox import SandboxRun
        from runtime.workspaces import get_workspace

        agent_id = get_active()
        api_key = get_secret("anthropic", agent_id=agent_id)
        if not api_key:
            raise RuntimeError(
                f"claude_code: no Anthropic BYOK for agent {agent_id!r} — "
                "set the per-agent key before chatting"
            )

        workspace = get_workspace(agent_id)
        workspace.ensure()
        system_prompt = workspace.read_system_prompt()
        tar_in = workspace.to_tar_bytes()

        model = (
            context.routing.model
            if context.routing and context.routing.model
            else _DEFAULT_MODEL
        )

        response_chunks: list[str] = []
        try:
            with SandboxRun(
                anthropic_key=api_key,
                timeout_s=self.timeout_s,
            ) as sb:
                sb.upload_workspace_tar(tar_in)
                for evt in sb.run_claude(
                    context.request,
                    system=system_prompt,
                    model=model,
                ):
                    kind = evt.get("type")
                    if kind == "stdout":
                        response_chunks.append(evt.get("data") or "")
                    elif kind == "stderr":
                        logger.info("claude_code stderr: %s", evt.get("data"))
                    elif kind == "error":
                        logger.warning("claude_code sandbox error: %s", evt.get("detail"))
                        break
                    elif kind == "done":
                        break

                try:
                    tar_out = sb.snapshot_workspace_tar()
                    workspace.from_tar_bytes(tar_out)
                except Exception as exc:
                    logger.warning("claude_code: snapshot back failed: %s", exc)
        except Exception as exc:
            logger.warning("claude_code: sandbox lifetime failed: %s", exc, exc_info=True)
            raise

        context.response = "".join(response_chunks).strip()
        return context


class PromptStrategiesTechnique(BaseTechnique):
    name = "prompt_strategies"
    variants = ("direct", "claude_code")

    def compile(self, variant: str, knobs: dict[str, Any]) -> Stage:
        if variant not in self.variants:
            raise ValueError(
                f"prompt_strategies: unknown variant {variant!r}; expected one of {self.variants}"
            )
        if variant == "claude_code":
            return _ClaudeCode(knobs)
        return _Direct(knobs)
