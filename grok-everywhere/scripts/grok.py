#!/usr/bin/env python3
"""Cross-platform xAI CLI for text, search, speech, images, and video."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from http.client import RemoteDisconnected
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


VERSION = "0.2.0"
PUBLIC_API = "https://api.x.ai/v1"
SESSION_PROXY = "https://cli-chat-proxy.grok.com/v1"
GROK_CLIENT_VERSION = "0.2.114"
COST_TICK_DIVISOR = 10_000_000_000
DEPTHS = {
    "quick": (1, "low"),
    "balanced": (3, "low"),
    "deep": (8, "medium"),
}
MAX_TTS_CHARACTERS = 60_000
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_AUDIO_BYTES = 100 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024


class GrokError(RuntimeError):
    """Expected user-facing failure."""


@dataclass(frozen=True)
class Credential:
    token: str
    kind: str
    source: str
    expires_at: Optional[str] = None


@dataclass(frozen=True)
class RunContext:
    run_id: str
    directory: Path


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def parse_iso_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "date must use YYYY-MM-DD: {}".format(value)
        ) from exc
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError(
            "date must be zero-padded YYYY-MM-DD: {}".format(value)
        )
    return parsed


def parse_expiry(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_expired(value: Optional[str]) -> bool:
    parsed = parse_expiry(value)
    return bool(parsed and datetime.now(timezone.utc) >= parsed)


def read_auth_store(auth_file: Path) -> Dict[str, Any]:
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise GrokError("Cannot read auth file {}: {}".format(auth_file, exc)) from exc
    if not isinstance(data, dict):
        raise GrokError("Auth file must contain a JSON object: {}".format(auth_file))
    return data


def api_key_from_store(store: Dict[str, Any]) -> Optional[Credential]:
    entry = store.get("xai::api_key")
    if isinstance(entry, dict) and str(entry.get("key", "")).strip():
        return Credential(
            token=str(entry["key"]).strip(),
            kind="api_key",
            source="Grok auth.json API key",
            expires_at=entry.get("expires_at"),
        )
    return None


def session_from_store(store: Dict[str, Any]) -> Optional[Credential]:
    candidates = [
        value
        for value in store.values()
        if isinstance(value, dict)
        and str(value.get("key", "")).strip()
        and value.get("auth_mode") in {"oidc", "external"}
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("expires_at", "")), reverse=True)
    entry = candidates[0]
    return Credential(
        token=str(entry["key"]).strip(),
        kind="session",
        source="Grok auth.json session token",
        expires_at=entry.get("expires_at"),
    )


def load_credential(auth_mode: str, auth_file: Path) -> Credential:
    store: Optional[Dict[str, Any]] = None

    def get_store() -> Dict[str, Any]:
        nonlocal store
        if store is None:
            store = read_auth_store(auth_file)
        return store

    if auth_mode in {"auto", "api-key"}:
        for env_name in ("XAI_API_KEY", "GROK_API_KEY"):
            value = os.environ.get(env_name, "").strip()
            if value:
                return Credential(value, "api_key", "environment {}".format(env_name))
        stored_key = api_key_from_store(get_store())
        if stored_key:
            if is_expired(stored_key.expires_at):
                raise GrokError("The API key recorded in auth.json is expired.")
            return stored_key
        if auth_mode == "api-key":
            raise GrokError(
                "No API key found. Set XAI_API_KEY or add xai::api_key to {}.".format(
                    auth_file
                )
            )

    if auth_mode in {"auto", "session"}:
        session = session_from_store(get_store())
        if session:
            if is_expired(session.expires_at):
                raise GrokError(
                    "The Grok session token is expired. Run `grok login` and retry."
                )
            return session

    raise GrokError(
        "No xAI credential found. Set XAI_API_KEY, or optionally sign in with "
        "Grok CLI so {} contains a session token.".format(auth_file)
    )


def auth_status(auth_mode: str, auth_file: Path) -> Dict[str, Any]:
    try:
        credential = load_credential(auth_mode, auth_file)
    except GrokError as exc:
        return {
            "available": False,
            "requested_mode": auth_mode,
            "auth_file": str(auth_file),
            "message": str(exc),
        }
    return {
        "available": True,
        "requested_mode": auth_mode,
        "kind": credential.kind,
        "source": credential.source,
        "expires_at": credential.expires_at,
        "expired": is_expired(credential.expires_at),
        "auth_file": str(auth_file),
    }


def default_cache_root() -> Path:
    configured = os.environ.get("GROK_EVERYWHERE_CACHE", "").strip()
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if os.name == "nt" and local_app_data:
        return Path(local_app_data) / "grok-everywhere"
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        return Path(xdg_cache).expanduser() / "grok-everywhere"
    return Path.home() / ".cache" / "grok-everywhere"


def create_run(cache_root: Path, label: str) -> RunContext:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = "{}-{}-{}".format(timestamp, label, uuid.uuid4().hex[:8])
    directory = cache_root.expanduser().resolve() / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return RunContext(run_id, directory)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def sanitize(value: Any) -> Any:
    secret_keys = {
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "key",
    }
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in secret_keys:
                result[key] = "[REDACTED]"
            else:
                result[key] = sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str) and value.startswith("data:"):
        prefix = value.split(",", 1)[0]
        return "{};[base64 omitted]".format(prefix)
    return value


def cost_from_usage(usage: Any) -> Optional[float]:
    if not isinstance(usage, dict):
        return None
    ticks = usage.get("cost_in_usd_ticks")
    if isinstance(ticks, (int, float)):
        return ticks / COST_TICK_DIVISOR
    return None


def ensure_output_path(
    requested: Optional[Path], fallback: Path, overwrite: bool
) -> Path:
    path = (requested.expanduser() if requested else fallback).resolve()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GrokError("Cannot prepare output directory {}: {}".format(path.parent, exc)) from exc
    if path.is_dir():
        raise GrokError("Output path is a directory: {}".format(path))
    if path.exists() and not overwrite:
        raise GrokError(
            "Output exists: {}. Pass --overwrite to replace it.".format(path)
        )
    return path


def emit(value: Dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def success(
    ctx: Optional[RunContext],
    module: str,
    operation: str,
    started: float,
    artifacts: Sequence[Path] = (),
    cost_usd: Optional[float] = None,
    warnings: Sequence[str] = (),
    **extra: Any
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "ok": True,
        "module": module,
        "operation": operation,
        "run_id": ctx.run_id if ctx else None,
        "result_path": str(ctx.directory) if ctx else None,
        "artifacts": [str(path.resolve()) for path in artifacts],
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "cost_usd": cost_usd,
        "warnings": list(warnings),
    }
    result.update(extra)
    if ctx:
        write_json(ctx.directory / "result.json", sanitize(result))
    return result


def credential_endpoint(credential: Credential, responses_api: bool = False) -> str:
    if responses_api and credential.kind == "session":
        return SESSION_PROXY
    return PUBLIC_API


def request_headers(
    credential: Credential,
    model: Optional[str] = None,
    content_type: Optional[str] = "application/json",
    accept: str = "application/json",
    responses_api: bool = False,
) -> Dict[str, str]:
    headers = {
        "Authorization": "Bearer {}".format(credential.token),
        "Accept": accept,
        "User-Agent": "grok-everywhere/{}".format(VERSION),
    }
    if content_type:
        headers["Content-Type"] = content_type
    if responses_api and credential.kind == "session":
        request_id = str(uuid.uuid4())
        headers.update(
            {
                "X-XAI-Token-Auth": "xai-grok-cli",
                "x-authenticateresponse": "authenticate-response",
                "x-grok-client-mode": "headless",
                "x-grok-client-version": GROK_CLIENT_VERSION,
                "x-grok-client-identifier": "grok-everywhere",
                "x-grok-conv-id": str(uuid.uuid4()),
                "x-grok-req-id": request_id,
                "x-grok-session-id": request_id,
                "x-grok-agent-id": "grok-everywhere",
            }
        )
        if model:
            headers["x-grok-model-override"] = model
    return headers


def redact_error(message: str, token: Optional[str] = None) -> str:
    message = str(message)
    if token:
        message = message.replace(token, "[REDACTED]")
    message = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", message)
    message = re.sub(r"\bxai-[A-Za-z0-9_-]{10,}\b", "[REDACTED]", message)
    message = re.sub(r"data:[^,;\s]+(?:;[^,\s]+)*;base64,[A-Za-z0-9+/=]+", "data:[base64 omitted]", message)
    return message


def api_error(exc: HTTPError, token: Optional[str] = None) -> GrokError:
    body = exc.read().decode("utf-8", errors="replace")
    try:
        parsed = sanitize(json.loads(body))
        error = parsed.get("error", parsed) if isinstance(parsed, dict) else parsed
        if isinstance(error, dict):
            message = error.get("message") or json.dumps(error, ensure_ascii=False)
        else:
            message = str(error)
    except json.JSONDecodeError:
        message = body
    return GrokError("xAI API returned HTTP {}: {}".format(exc.code, redact_error(message, token)[:1200]))


def open_request(request: Request, timeout: int) -> Any:
    try:
        return urlopen(request, timeout=timeout)
    except HTTPError as exc:
        authorization = request.get_header("Authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else None
        raise api_error(exc, token or None) from exc
    except URLError as exc:
        raise GrokError("Cannot reach xAI API: {}".format(exc.reason)) from exc
    except (RemoteDisconnected, ConnectionResetError, TimeoutError) as exc:
        raise GrokError(
            "The connection ended before a response arrived. This command does not "
            "auto-retry paid POST requests."
        ) from exc


def http_json(
    method: str,
    path: str,
    credential: Credential,
    timeout: int,
    payload: Optional[Dict[str, Any]] = None,
    responses_api: bool = False,
) -> Dict[str, Any]:
    body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    model = str(payload.get("model")) if payload and payload.get("model") else None
    request = Request(
        "{}/{}".format(
            credential_endpoint(credential, responses_api).rstrip("/"),
            path.lstrip("/"),
        ),
        data=body,
        headers=request_headers(
            credential, model=model, responses_api=responses_api
        ),
        method=method,
    )
    with open_request(request, timeout) as response:
        raw = response.read()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GrokError("xAI API returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise GrokError("xAI API response must be a JSON object.")
    return value


def http_raw_json_post(
    path: str,
    credential: Credential,
    payload: Dict[str, Any],
    timeout: int,
    accept: str,
) -> Tuple[bytes, str]:
    request = Request(
        "{}/{}".format(PUBLIC_API, path.lstrip("/")),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers(credential, accept=accept),
        method="POST",
    )
    with open_request(request, timeout) as response:
        content_type = response.headers.get_content_type()
        return response.read(), content_type


def multipart_body(
    fields: Dict[str, Any], file_field: str, file_path: Path
) -> Tuple[bytes, str]:
    if not file_path.is_file():
        raise GrokError("Input file does not exist: {}".format(file_path))
    size = file_path.stat().st_size
    if size > MAX_AUDIO_BYTES:
        raise GrokError(
            "Audio file is larger than the {} MiB local safety limit.".format(
                MAX_AUDIO_BYTES // 1024 // 1024
            )
        )
    boundary = "----codexgrok{}".format(uuid.uuid4().hex)
    chunks: List[bytes] = []
    for name, raw_value in fields.items():
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        for value in values:
            chunks.extend(
                [
                    "--{}\r\n".format(boundary).encode("ascii"),
                    (
                        'Content-Disposition: form-data; name="{}"\r\n\r\n'.format(
                            name
                        )
                    ).encode("utf-8"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.extend(
        [
            "--{}\r\n".format(boundary).encode("ascii"),
            (
                'Content-Disposition: form-data; name="{}"; filename="{}"\r\n'.format(
                    file_field, file_path.name.replace('"', "_")
                )
            ).encode("utf-8"),
            "Content-Type: {}\r\n\r\n".format(mime).encode("ascii"),
            file_path.read_bytes(),
            b"\r\n",
            "--{}--\r\n".format(boundary).encode("ascii"),
        ]
    )
    return b"".join(chunks), "multipart/form-data; boundary={}".format(boundary)


def http_multipart(
    path: str,
    credential: Credential,
    fields: Dict[str, Any],
    file_path: Path,
    timeout: int,
) -> Dict[str, Any]:
    body, content_type = multipart_body(fields, "file", file_path)
    request = Request(
        "{}/{}".format(PUBLIC_API, path.lstrip("/")),
        data=body,
        headers=request_headers(credential, content_type=content_type),
        method="POST",
    )
    with open_request(request, timeout) as response:
        raw = response.read()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GrokError("xAI STT returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise GrokError("xAI STT response must be a JSON object.")
    return value


def local_media_uri(value: str, max_bytes: int) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "data"}:
        return value
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise GrokError("Media input does not exist: {}".format(path))
    size = path.stat().st_size
    if size > max_bytes:
        raise GrokError(
            "Media file is larger than the {} MiB local safety limit: {}".format(
                max_bytes // 1024 // 1024, path
            )
        )
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:{};base64,{}".format(mime, encoded)


def download_url(url: str, destination: Path, timeout: int) -> Path:
    request = Request(
        url, headers={"User-Agent": "grok-everywhere/{}".format(VERSION)}
    )
    with open_request(request, timeout) as response:
        data = response.read(MAX_VIDEO_BYTES + 1)
    if len(data) > MAX_VIDEO_BYTES:
        raise GrokError("Downloaded media exceeded the 200 MiB safety limit.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination


def parse_sse_response(
    lines: Iterable[bytes], search_enabled: bool = True, token: Optional[str] = None
) -> Dict[str, Any]:
    completed: Optional[Dict[str, Any]] = None
    data_lines: List[str] = []
    seen_calls = set()
    answer_started = False

    def consume() -> None:
        nonlocal completed, answer_started
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        data_lines.clear()
        if raw == "[DONE]":
            return
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GrokError("xAI returned an invalid SSE event.") from exc
        event_type = event.get("type")
        if event_type in {"error", "response.failed"}:
            error = event.get("error") or event.get("response", {}).get("error")
            raise GrokError("xAI streaming request failed: {}".format(redact_error(str(sanitize(error or event)), token)))
        if event_type in {"response.output_item.added", "response.output_item.done"}:
            item = event.get("item")
            if isinstance(item, dict) and (
                item.get("type") in {
                    "custom_tool_call",
                    "x_search_call",
                    "web_search_call",
                }
                or str(item.get("name", "")).startswith(("x_", "web_"))
            ):
                call_id = str(item.get("id") or item.get("call_id") or len(seen_calls))
                if call_id not in seen_calls:
                    seen_calls.add(call_id)
                    log("→ search tool call {}".format(len(seen_calls)))
        if event_type == "response.output_text.delta" and not answer_started:
            answer_started = True
            log(
                "→ search completed; composing answer"
                if search_enabled
                else "→ response started"
            )
        if event_type in {"response.completed", "response.incomplete"} and isinstance(
            event.get("response"), dict
        ):
            completed = event["response"]
            completed.setdefault("status", event_type.split(".", 1)[1])

    for raw_line in lines:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            consume()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    consume()
    if completed is None:
        raise GrokError("The SSE connection ended without a completed/incomplete response. No automatic retry was made.")
    return completed


def call_responses(
    credential: Credential, payload: Dict[str, Any], timeout: int
) -> Dict[str, Any]:
    model = str(payload["model"])
    search_enabled = any(
        isinstance(tool, dict)
        and tool.get("type") in {"web_search", "x_search"}
        for tool in payload.get("tools", [])
    )
    request = Request(
        "{}/responses".format(
            credential_endpoint(credential, responses_api=True).rstrip("/")
        ),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers(
            credential,
            model=model,
            accept="text/event-stream",
            responses_api=True,
        ),
        method="POST",
    )
    with open_request(request, timeout) as response:
        if response.headers.get_content_type() == "text/event-stream":
            log(
                "→ connected to xAI; searching"
                if search_enabled
                else "→ connected to xAI; waiting for response"
            )
            return parse_sse_response(response, search_enabled=search_enabled, token=credential.token)
        try:
            value = json.loads(response.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GrokError("xAI Responses API returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise GrokError("xAI Responses API response must be a JSON object.")
    return value


def comma_values(values: Optional[List[str]]) -> List[str]:
    result: List[str] = []
    for value in values or []:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return list(dict.fromkeys(result))


def build_search_tool(args: argparse.Namespace) -> Dict[str, Any]:
    if args.search_kind == "x":
        allowed = [value.lstrip("@") for value in comma_values(args.allow)]
        excluded = [value.lstrip("@") for value in comma_values(args.exclude)]
        if len(allowed) > 20 or len(excluded) > 20:
            raise GrokError("X Search allows at most 20 handles per filter.")
        if allowed and excluded:
            raise GrokError("--allow and --exclude cannot be used together.")
        if args.from_date and args.to_date and args.from_date > args.to_date:
            raise GrokError("--from-date cannot be later than --to-date.")
        tool: Dict[str, Any] = {"type": "x_search"}
        if allowed:
            tool["allowed_x_handles"] = allowed
        if excluded:
            tool["excluded_x_handles"] = excluded
        if args.from_date:
            tool["from_date"] = args.from_date.isoformat()
        if args.to_date:
            tool["to_date"] = args.to_date.isoformat()
        if args.media in {"image", "both"}:
            tool["enable_image_understanding"] = True
        if args.media in {"video", "both"}:
            tool["enable_video_understanding"] = True
        return tool

    allowed_domains = comma_values(args.allow_domain)
    excluded_domains = comma_values(args.exclude_domain)
    if allowed_domains and excluded_domains:
        raise GrokError("--allow-domain and --exclude-domain cannot be used together.")
    if len(allowed_domains) > 5 or len(excluded_domains) > 5:
        raise GrokError("Web Search allows at most 5 domains per filter.")
    tool = {"type": "web_search"}
    filters: Dict[str, Any] = {}
    if allowed_domains:
        filters["allowed_domains"] = allowed_domains
    if excluded_domains:
        filters["excluded_domains"] = excluded_domains
    if filters:
        tool["filters"] = filters
    for option in ("enable_image_search", "enable_image_understanding"):
        if getattr(args, option, False):
            tool[option] = True
    return tool


def build_search_prompt(args: argparse.Namespace) -> str:
    source = "X" if args.search_kind == "x" else "the public web"
    depth_rules = {
        "quick": "Make one direct search and answer; do not add broad synonym searches.",
        "balanced": "Start with one direct search; add one refinement only if evidence is weak.",
        "deep": "Cross-check with multiple focused searches when that materially improves confidence.",
    }
    scope_notes: List[str] = []
    if args.search_kind == "x":
        if args.from_date or args.to_date:
            scope_notes.append(
                "Evidence window: {} through {}. Discard clearly out-of-window posts.".format(
                    args.from_date.isoformat() if args.from_date else "unbounded",
                    args.to_date.isoformat() if args.to_date else "unbounded",
                )
            )
        allowed = comma_values(args.allow)
        if allowed:
            scope_notes.append(
                "The caller has already selected these account handles: {}.".format(
                    ", ".join("@{}".format(value.lstrip("@")) for value in allowed)
                )
            )
    else:
        allowed_domains = comma_values(args.allow_domain)
        if allowed_domains:
            scope_notes.append(
                "Prefer only these caller-selected domains: {}.".format(
                    ", ".join(allowed_domains)
                )
            )
    scope = "\n".join(scope_notes) or "No additional source scope was requested."
    return """Research this question using {source}:
{query}

Current date: {today}.
Mode: {depth}. {depth_rule}
Scope: {scope}

Requirements:
1. You must use the supplied search tool; do not present memory as a search result.
2. Prefer direct and primary sources. Separate source claims, public opinion, and inference.
3. Keep the answer compact and attach clickable source links to material claims.
4. State gaps, uncertainty, or weak evidence plainly.
""".format(
        source=source,
        query=args.query,
        today=date.today().isoformat(),
        depth=args.depth,
        depth_rule=depth_rules[args.depth],
        scope=scope,
    )


def build_search_payload(
    args: argparse.Namespace, tool: Dict[str, Any]
) -> Dict[str, Any]:
    max_turns, effort = DEPTHS[args.depth]
    return {
        "model": args.model,
        "input": [{"role": "user", "content": build_search_prompt(args)}],
        "tools": [tool],
        "tool_choice": "required",
        "max_turns": max_turns,
        "parallel_tool_calls": True,
        "reasoning": {"effort": getattr(args, "reasoning_effort", None) or effort},
        "store": False,
        "stream": True,
    }


def summarize_response(response: Dict[str, Any]) -> Dict[str, Any]:
    texts: List[str] = []
    citations: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type in {"custom_tool_call", "x_search_call", "web_search_call"}:
            calls.append(
                {
                    "name": item.get("name") or item_type,
                    "arguments": item.get("arguments") or item.get("action"),
                    "status": item.get("status"),
                }
            )
        if item_type != "message":
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict) or content.get("type") != "output_text":
                continue
            text_value = content.get("text")
            if isinstance(text_value, str) and text_value.strip():
                texts.append(text_value.strip())
            for annotation in content.get("annotations", []):
                if isinstance(annotation, dict) and annotation.get("url"):
                    citations.append(annotation)
    unique_citations: List[Dict[str, Any]] = []
    seen = set()
    for citation in citations:
        url = str(citation["url"])
        if url not in seen:
            seen.add(url)
            unique_citations.append(citation)
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    return {
        "id": response.get("id"),
        "status": response.get("status"),
        "model": response.get("model"),
        "text": "\n\n".join(texts),
        "tool_calls": calls,
        "tool_call_counts": dict(
            Counter(str(call["name"]) for call in calls)
        ),
        "citations": unique_citations,
        "usage": usage,
        "search_items": usage.get("server_side_tool_usage_details", {}),
        "incomplete_details": response.get("incomplete_details"),
        "warnings": (["xAI returned an incomplete response; partial answer and usage were preserved. No retry was made."] if response.get("status") == "incomplete" else []),
        "cost_usd": cost_from_usage(usage),
    }


def build_text_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": args.model,
        "input": args.prompt,
        "reasoning": {"effort": getattr(args, "reasoning_effort", None) or "low"},
        "store": False,
        "stream": True,
    }
    if getattr(args, "image", None):
        content = [{"type": "input_text", "text": args.prompt}]
        content.extend({"type": "input_image", "image_url": local_media_uri(value, MAX_IMAGE_BYTES)} for value in args.image)
        payload["input"] = [{"role": "user", "content": content}]
    if not args.no_search:
        payload.update(
            {
                "tools": [{"type": "web_search"}],
                "tool_choice": "auto",
                "max_turns": 1,
                "parallel_tool_calls": True,
            }
        )
    return payload


def command_text(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    payload = build_text_payload(args)
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "text",
            "operation": "generate",
            "request": sanitize(payload),
        }
    ctx = create_run(args.cache_dir, "text")
    write_json(ctx.directory / "request.json", sanitize(payload))
    credential = load_credential(args.auth, args.auth_file)
    response = call_responses(credential, payload, args.timeout)
    write_json(ctx.directory / "raw-response.json", sanitize(response))
    summary = summarize_response(response)
    markdown_path = ctx.directory / "result.md"
    write_text(markdown_path, summary["text"] or "(No answer text returned.)")
    return success(
        ctx,
        "text",
        "generate",
        started,
        [markdown_path, ctx.directory / "raw-response.json"],
        summary["cost_usd"],
        answer=summary["text"],
        model=summary["model"],
        requested_model=args.model,
        response_id=summary["id"],
        citations=summary["citations"],
        tool_call_counts=summary["tool_call_counts"],
        usage=summary["usage"],
        response_status=summary["status"],
        incomplete_details=summary["incomplete_details"],
        search_items=summary["search_items"],
        warnings=summary["warnings"],
        auth_kind=credential.kind,
        web_search_enabled=not args.no_search,
    )


def command_search(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    tool = build_search_tool(args)
    payload = build_search_payload(args, tool)
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "search",
            "operation": args.search_kind,
            "request": sanitize(payload),
        }
    ctx = create_run(args.cache_dir, "search-{}".format(args.search_kind))
    write_json(ctx.directory / "request.json", sanitize(payload))
    credential = load_credential(args.auth, args.auth_file)
    response = call_responses(credential, payload, args.timeout)
    write_json(ctx.directory / "raw-response.json", sanitize(response))
    summary = summarize_response(response)
    markdown_path = ctx.directory / "result.md"
    write_text(markdown_path, summary["text"] or "(No answer text returned.)")
    return success(
        ctx,
        "search",
        args.search_kind,
        started,
        [markdown_path, ctx.directory / "raw-response.json"],
        summary["cost_usd"],
        answer=summary["text"],
        citations=summary["citations"],
        tool_call_counts=summary["tool_call_counts"],
        usage=summary["usage"],
        model=summary["model"],
        requested_model=args.model,
        response_id=summary["id"],
        response_status=summary["status"],
        incomplete_details=summary["incomplete_details"],
        search_items=summary["search_items"],
        warnings=summary["warnings"],
        auth_kind=credential.kind,
        depth=args.depth,
    )


def command_models(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "system",
            "operation": "models",
            "request": {"method": "GET", "path": "/v1/models"},
        }
    credential = load_credential(args.auth, args.auth_file)
    response = http_json("GET", "models", credential, args.timeout)
    return success(
        None,
        "system",
        "models",
        started,
        models=response.get("data", response),
        auth_kind=credential.kind,
    )


def command_voices(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "system",
            "operation": "voices",
            "request": {"method": "GET", "path": "/v1/tts/voices"},
        }
    credential = load_credential(args.auth, args.auth_file)
    response = http_json("GET", "tts/voices", credential, args.timeout)
    return success(
        None,
        "system",
        "voices",
        started,
        voices=response.get("voices", response.get("data", response)),
        auth_kind=credential.kind,
    )


def extension_for_content_type(content_type: str, fallback: str) -> str:
    return {
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/ogg": ".ogg",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
    }.get(content_type, fallback)


def parse_audio_replacements(values: Optional[Sequence[str]]) -> Dict[str, str]:
    replacements: Dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise GrokError("Each --replace value must use PHRASE=PRONUNCIATION.")
        phrase, pronunciation = item.split("=", 1)
        if len(phrase) > 100 or len(pronunciation) > 128:
            raise GrokError(
                "TTS --replace phrases must be at most 100 characters and "
                "pronunciations at most 128 characters."
            )
        replacements[phrase] = pronunciation
    if len(replacements) > 200:
        raise GrokError("TTS accepts at most 200 --replace entries.")
    return replacements


def audio_tts_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if not args.text:
        raise GrokError("TTS text must not be empty.")
    if len(args.text) > MAX_TTS_CHARACTERS:
        raise GrokError(
            "TTS text exceeds the {} character limit.".format(MAX_TTS_CHARACTERS)
        )
    payload: Dict[str, Any] = {
        "text": args.text,
        "voice_id": args.voice,
        "language": args.language,
    }
    codec = getattr(args, "codec", None)
    sample_rate = getattr(args, "sample_rate", None)
    bit_rate = getattr(args, "bit_rate", None)
    if bit_rate is not None and codec not in (None, "mp3"):
        raise GrokError("TTS --bit-rate is only supported with the mp3 codec.")
    output_format: Dict[str, Any] = {}
    if codec:
        output_format["codec"] = "mulaw" if codec == "ulaw" else codec
    if sample_rate is not None:
        output_format["sample_rate"] = sample_rate
    if bit_rate is not None:
        output_format["bit_rate"] = bit_rate
        output_format.setdefault("codec", "mp3")
    if output_format:
        payload["output_format"] = output_format

    speed = getattr(args, "speed", None)
    if speed is not None:
        if not 0.7 <= speed <= 1.5:
            raise GrokError("TTS --speed must be between 0.7 and 1.5.")
        payload["speed"] = speed
    latency = getattr(args, "optimize_streaming_latency", None)
    if latency is not None:
        payload["optimize_streaming_latency"] = latency
    text_normalization = getattr(args, "text_normalization", None)
    if text_normalization is not None:
        payload["text_normalization"] = text_normalization
    if getattr(args, "with_timestamps", False):
        payload["with_timestamps"] = True
    replacements = parse_audio_replacements(getattr(args, "replace", None))
    if replacements:
        payload["replace"] = replacements
    return payload


def audio_extension_for_content_type(content_type: str) -> str:
    return {
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/pcm": ".pcm",
        "audio/basic": ".ulaw",
        "audio/alaw": ".alaw",
        "audio/ogg": ".ogg",
    }.get(content_type, ".bin")


def audio_accept_for_payload(payload: Dict[str, Any]) -> str:
    if payload.get("with_timestamps"):
        return "application/json"
    codec = payload.get("output_format", {}).get("codec", "mp3")
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
        "mulaw": "audio/basic",
        "alaw": "audio/alaw",
    }.get(codec, "audio/mpeg")


def decode_audio_tts_response(
    body: bytes, content_type: str, with_timestamps: bool
) -> Tuple[bytes, Optional[Dict[str, Any]], str]:
    if not with_timestamps:
        return body, None, content_type
    if content_type != "application/json":
        raise GrokError("Timestamped TTS response must be a JSON envelope.")
    try:
        response = json.loads(body.decode("utf-8"))
        if not isinstance(response, dict):
            raise TypeError("response is not an object")
        audio = base64.b64decode(response["audio"], validate=True)
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise GrokError("xAI TTS returned an invalid timestamped audio response.") from exc
    audio_type = response.get("content_type")
    timing = response.get("audio_timestamps")
    if not isinstance(audio_type, str) or not audio_type.startswith("audio/"):
        raise GrokError("xAI TTS timestamped response has no audio content type.")
    if not isinstance(timing, dict):
        raise GrokError("xAI TTS timestamped response has no character timings.")
    chars = timing.get("graph_chars")
    times = timing.get("graph_times")
    if (
        not isinstance(chars, list)
        or not all(isinstance(char, str) for char in chars)
        or not isinstance(times, list)
        or len(chars) != len(times)
        or any(
            not isinstance(pair, list)
            or len(pair) != 2
            or any(not isinstance(value, (int, float)) for value in pair)
            for pair in times
        )
    ):
        raise GrokError("xAI TTS character timing arrays are invalid.")
    metadata = {key: value for key, value in response.items() if key != "audio"}
    return audio, metadata, audio_type


def command_tts(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    payload = audio_tts_payload(args)
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "audio",
            "operation": "tts",
            "request": sanitize(payload),
        }
    ctx = create_run(args.cache_dir, "audio-tts")
    write_json(ctx.directory / "request.json", payload)
    requested_output = None
    if args.output:
        requested_output = ensure_output_path(
            args.output, ctx.directory / "speech.mp3", args.overwrite
        )
    credential = load_credential(args.auth, args.auth_file)
    log("→ synthesizing speech with voice {}".format(args.voice))
    body, response_type = http_raw_json_post(
        "tts",
        credential,
        payload,
        args.timeout,
        audio_accept_for_payload(payload),
    )
    audio, timestamp_metadata, content_type = decode_audio_tts_response(
        body, response_type, bool(payload.get("with_timestamps"))
    )
    output = requested_output or ensure_output_path(
        None,
        ctx.directory / "speech{}".format(audio_extension_for_content_type(content_type)),
        args.overwrite,
    )
    output.write_bytes(audio)
    artifacts = [output]
    timestamp_path = None
    if timestamp_metadata is not None:
        timestamp_path = ctx.directory / "speech-timestamps.json"
        write_json(timestamp_path, timestamp_metadata)
        artifacts.append(timestamp_path)
    return success(
        ctx,
        "audio",
        "tts",
        started,
        artifacts,
        voice=args.voice,
        language=args.language,
        content_type=content_type,
        duration=(timestamp_metadata or {}).get("duration"),
        timestamps_path=str(timestamp_path) if timestamp_path else None,
        auth_kind=credential.kind,
    )


def join_tokens(tokens: Sequence[str]) -> str:
    result = ""
    cjk_or_punct = re.compile(
        r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]"
    )
    no_space_before = set("，。！？；：、,.!?;:)]}）】》」』")
    no_space_after = set("([{（【《「『")
    for raw in tokens:
        token = str(raw)
        if not token:
            continue
        if not result:
            result = token
        elif (
            token[0] in no_space_before
            or result[-1] in no_space_after
            or cjk_or_punct.match(token[0])
            or cjk_or_punct.match(result[-1])
        ):
            result += token
        else:
            result += " " + token
    return result


def audio_stt_fields(args: argparse.Namespace) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    stt_model = getattr(args, "stt_model", None)
    if stt_model:
        fields["model"] = stt_model
    audio_format = getattr(args, "audio_format", None)
    sample_rate = getattr(args, "sample_rate", None)
    if bool(audio_format) != (sample_rate is not None):
        raise GrokError("STT --audio-format and --sample-rate must be used together.")
    if audio_format:
        fields["audio_format"] = audio_format
        fields["sample_rate"] = sample_rate

    language = getattr(args, "language", None)
    if language == "auto":
        language = None
    format_text = getattr(args, "format_text", False)
    if format_text and not language:
        raise GrokError("STT --format requires an explicit --language.")
    if language:
        fields["language"] = language
    if format_text:
        fields["format"] = "true"

    multichannel = getattr(args, "multichannel", False)
    channels = getattr(args, "channels", None)
    if channels is not None and not multichannel:
        raise GrokError("STT --channels requires --multichannel.")
    if multichannel and audio_format and channels is None:
        raise GrokError("STT multichannel raw audio requires --channels.")
    if channels is not None and not 2 <= channels <= 8:
        raise GrokError("STT --channels must be between 2 and 8.")
    if multichannel:
        fields["multichannel"] = "true"
    if channels is not None:
        fields["channels"] = channels

    if getattr(args, "diarize", False):
        fields["diarize"] = "true"
    if getattr(args, "filler_words", False):
        fields["filler_words"] = "true"
    keyterms = getattr(args, "keyterm", None) or []
    if len(keyterms) > 100:
        raise GrokError("STT accepts at most 100 --keyterm values.")
    if any(len(value) > 50 for value in keyterms):
        raise GrokError("Each STT --keyterm must be at most 50 characters.")
    if keyterms:
        fields["keyterm"] = keyterms
    vad_threshold = getattr(args, "vad_threshold", None)
    if vad_threshold is not None:
        if not 0.0 <= vad_threshold <= 1.0:
            raise GrokError("STT --vad-threshold must be between 0 and 1.")
        fields["vad_threshold"] = vad_threshold
    return fields


def transcript_turns(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    words = response.get("words")
    if not isinstance(words, list):
        return []
    turns: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for word in words:
        if not isinstance(word, dict):
            continue
        speaker = word.get("speaker")
        token = word.get("word", word.get("text", ""))
        if current is None or current["speaker"] != speaker:
            current = {
                "speaker": speaker,
                "start": word.get("start"),
                "end": word.get("end"),
                "tokens": [token],
            }
            turns.append(current)
        else:
            current["tokens"].append(token)
            current["end"] = word.get("end", current.get("end"))
    for turn in turns:
        turn["text"] = join_tokens(turn.pop("tokens"))
    return turns


def format_timestamp(value: Any) -> str:
    try:
        total = max(0.0, float(value))
    except (TypeError, ValueError):
        return "--:--"
    minutes = int(total // 60)
    seconds = total - minutes * 60
    return "{:02d}:{:05.2f}".format(minutes, seconds)


def append_audio_transcript_turns(
    lines: List[str], turns: Sequence[Dict[str, Any]]
) -> None:
    for turn in turns:
        speaker = turn.get("speaker")
        label = "Speaker {}".format(speaker) if speaker is not None else "Transcript"
        lines.append(
            "**{label}** `{start}–{end}`  ".format(
                label=label,
                start=format_timestamp(turn.get("start")),
                end=format_timestamp(turn.get("end")),
            )
        )
        lines.extend([turn["text"], ""])


def render_transcript(response: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    lines = ["# Transcript", ""]
    channels = response.get("channels")
    if isinstance(channels, list):
        all_turns: List[Dict[str, Any]] = []
        for channel_number, channel in enumerate(channels):
            if not isinstance(channel, dict):
                continue
            channel_label = channel.get("index")
            if channel_label is None:
                channel_label = channel_number
            lines.extend(["## Channel {}".format(channel_label), ""])
            channel_turns = transcript_turns(
                {"words": channel.get("words", [])}
            )
            for turn in channel_turns:
                turn["channel"] = channel_label
            if channel_turns:
                append_audio_transcript_turns(lines, channel_turns)
            else:
                lines.extend([str(channel.get("text", "")), ""])
            all_turns.extend(channel_turns)
        return "\n".join(lines), all_turns

    turns = transcript_turns(response)
    if turns:
        append_audio_transcript_turns(lines, turns)
    else:
        lines.extend([str(response.get("text", "")), ""])
    return "\n".join(lines), turns


def transcribe(
    args: argparse.Namespace, credential: Credential, ctx: RunContext
) -> Tuple[Dict[str, Any], List[Path]]:
    audio_path = args.file.expanduser().resolve()
    fields = audio_stt_fields(args)
    log("→ transcribing {}".format(audio_path.name))
    response = http_multipart("stt", credential, fields, audio_path, args.timeout)
    raw_path = ctx.directory / "transcript.json"
    markdown_path = ctx.directory / "transcript.md"
    write_json(raw_path, response)
    markdown, turns = render_transcript(response)
    write_text(markdown_path, markdown)
    response["_grok_everywhere_turns"] = turns
    artifacts = [raw_path, markdown_path]
    if args.audio_operation == "transcribe" and args.output:
        output = ensure_output_path(args.output, markdown_path, args.overwrite)
        if output != markdown_path:
            write_text(output, markdown)
            artifacts.append(output)
    return response, artifacts


def command_transcribe(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    fields = audio_stt_fields(args)
    request_preview = {
        "file": str(args.file),
        "fields": fields,
    }
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "audio",
            "operation": "transcribe",
            "request": request_preview,
        }
    ctx = create_run(args.cache_dir, "audio-stt")
    write_json(ctx.directory / "request.json", request_preview)
    if args.output:
        ensure_output_path(args.output, ctx.directory / "output-preflight", args.overwrite)
    credential = load_credential(args.auth, args.auth_file)
    response, artifacts = transcribe(args, credential, ctx)
    turns = response.pop("_grok_everywhere_turns")
    speaker_keys = {
        (
            str(turn["channel"]) if turn.get("channel") is not None else None,
            str(turn["speaker"]),
        )
        for turn in turns
        if turn.get("speaker") is not None
    }
    channels = response.get("channels")
    return success(
        ctx,
        "audio",
        "transcribe",
        started,
        artifacts,
        transcript=response.get("text"),
        language=response.get("language"),
        duration=response.get("duration"),
        speaker_count=len(speaker_keys),
        channel_count=len(channels) if isinstance(channels, list) else 0,
        turn_count=len(turns),
        auth_kind=credential.kind,
    )


def minutes_prompt(transcript_markdown: str) -> str:
    return """Create rigorous meeting minutes from the transcript below.

Rules:
- Do not invent speaker identities, facts, owners, deadlines, or decisions.
- Preserve uncertainty and flag suspected transcription errors.
- Separate confirmed decisions from proposals or open questions.
- Use these headings: Meeting summary, Decisions, Action items, Risks,
  Open questions, Transcript caveats.
- For each action item, include owner and deadline only when explicitly supported.
- Write in the transcript's dominant language.

Transcript:
{}""".format(transcript_markdown)


def command_minutes(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    args.diarize = True
    stt_fields = audio_stt_fields(args)
    reasoning_effort = getattr(args, "reasoning_effort", None)
    request_preview = {
        "file": str(args.file),
        "stt_fields": stt_fields,
        "model": args.model,
        "reasoning_effort": reasoning_effort,
    }
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "audio",
            "operation": "minutes",
            "request": request_preview,
        }
    ctx = create_run(args.cache_dir, "audio-minutes")
    write_json(ctx.directory / "request.json", request_preview)
    if args.output:
        ensure_output_path(args.output, ctx.directory / "output-preflight", args.overwrite)
    credential = load_credential(args.auth, args.auth_file)
    response, artifacts = transcribe(args, credential, ctx)
    transcript_markdown = (ctx.directory / "transcript.md").read_text(encoding="utf-8")
    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "user",
                "content": minutes_prompt(transcript_markdown),
            }
        ],
        "temperature": 0.1,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    write_json(ctx.directory / "minutes-request.json", sanitize(payload))
    log("→ turning the diarized transcript into meeting minutes")
    completion = http_json(
        "POST", "chat/completions", credential, args.timeout, payload
    )
    write_json(ctx.directory / "minutes-raw.json", sanitize(completion))
    try:
        content = completion["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GrokError(
            "Chat completion returned no meeting-minutes text; transcript was preserved at {}.".format(
                ctx.directory / "transcript.md"
            )
        ) from exc
    minutes_path = ensure_output_path(
        args.output, ctx.directory / "minutes.md", args.overwrite
    )
    write_text(minutes_path, str(content))
    artifacts.extend([minutes_path, ctx.directory / "minutes-raw.json"])
    return success(
        ctx,
        "audio",
        "minutes",
        started,
        artifacts,
        cost_from_usage(completion.get("usage")),
        minutes=str(content),
        transcript=response.get("text"),
        auth_kind=credential.kind,
    )


def image_artifacts(
    response: Dict[str, Any],
    ctx: RunContext,
    requested: Optional[Path],
    overwrite: bool,
    timeout: int,
) -> List[Path]:
    data = response.get("data")
    if not isinstance(data, list) or not data:
        raise GrokError("Image response contains no data items.")
    outputs: List[Path] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            continue
        content_type = str(item.get("mime_type", "image/jpeg"))
        suffix = extension_for_content_type(content_type, ".jpg")
        if requested:
            base = requested.expanduser()
            candidate = (
                base
                if len(data) == 1
                else base.with_name("{}-{}{}".format(base.stem, index, base.suffix or suffix))
            )
            destination = ensure_output_path(candidate, candidate, overwrite)
        else:
            destination = ensure_output_path(
                None, ctx.directory / "image-{}{}".format(index, suffix), overwrite
            )
        if item.get("url"):
            download_url(str(item["url"]), destination, timeout)
        elif item.get("b64_json"):
            try:
                destination.write_bytes(base64.b64decode(item["b64_json"]))
            except (ValueError, TypeError) as exc:
                raise GrokError("Image response contains invalid base64.") from exc
        else:
            continue
        outputs.append(destination)
    if not outputs:
        raise GrokError("Image response contains neither URL nor base64 image data.")
    return outputs


def preflight_output_path(requested: Optional[Path], overwrite: bool) -> None:
    if requested:
        ensure_output_path(requested, requested, overwrite)


def preflight_image_outputs(args: argparse.Namespace) -> None:
    if not args.output:
        return
    base = args.output.expanduser().resolve()
    if base.is_dir():
        raise GrokError("Output path is a directory: {}".format(base))
    count = args.n if args.image_operation == "generate" else 1
    if count == 1:
        candidates = [base]
    elif base.suffix:
        candidates = [
            base.with_name("{}-{}{}".format(base.stem, index, base.suffix))
            for index in range(1, count + 1)
        ]
    else:
        candidates = [
            base.with_name("{}-{}{}".format(base.stem, index, suffix))
            for index in range(1, count + 1)
            for suffix in (".jpg", ".png", ".webp")
        ]
    existing_directory = next((path for path in candidates if path.is_dir()), None)
    if existing_directory:
        raise GrokError("Output path is a directory: {}".format(existing_directory))
    existing = next((path for path in candidates if path.exists()), None)
    if existing and not args.overwrite:
        raise GrokError(
            "Output exists: {}. Pass --overwrite to replace it.".format(existing)
        )
    for candidate in candidates:
        preflight_output_path(candidate, args.overwrite)


def command_image(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    payload: Dict[str, Any] = {
        "model": args.model,
        "prompt": args.prompt,
    }
    endpoint = "images/generations"
    if args.image_operation == "generate":
        payload["n"] = args.n
        if args.aspect_ratio:
            payload["aspect_ratio"] = args.aspect_ratio
        if args.resolution:
            payload["resolution"] = args.resolution
        if args.quality:
            payload["quality"] = args.quality
    else:
        endpoint = "images/edits"
        image_inputs = [args.image] + (args.reference_image or [])
        if len(image_inputs) > 5:
            raise GrokError("Image editing accepts at most five source images.")
        image_payloads = [
            {
                "url": local_media_uri(item, MAX_IMAGE_BYTES),
                "type": "image_url",
            }
            for item in image_inputs
        ]
        if len(image_payloads) == 1:
            payload["image"] = image_payloads[0]
        else:
            payload["images"] = image_payloads
        if args.aspect_ratio:
            payload["aspect_ratio"] = args.aspect_ratio
        if args.resolution:
            payload["resolution"] = args.resolution
        if args.quality:
            payload["quality"] = args.quality
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "image",
            "operation": args.image_operation,
            "request": sanitize(payload),
        }
    preflight_image_outputs(args)
    ctx = create_run(args.cache_dir, "image-{}".format(args.image_operation))
    write_json(ctx.directory / "request.json", sanitize(payload))
    credential = load_credential(args.auth, args.auth_file)
    log("→ submitting image {}".format(args.image_operation))
    response = http_json("POST", endpoint, credential, args.timeout, payload)
    write_json(ctx.directory / "raw-response.json", sanitize(response))
    artifacts = image_artifacts(
        response, ctx, args.output, args.overwrite, args.timeout
    )
    artifacts.append(ctx.directory / "raw-response.json")
    return success(
        ctx,
        "image",
        args.image_operation,
        started,
        artifacts,
        cost_from_usage(response.get("usage")),
        model=args.model,
        auth_kind=credential.kind,
    )


def parse_keyframe_spec(value: str) -> Tuple[float, str]:
    timestamp_text, separator, image = value.partition("=")
    if not separator or not image:
        raise argparse.ArgumentTypeError(
            "keyframes must use TIMESTAMP=IMAGE, for example 2.0=frame.png"
        )
    try:
        timestamp = float(timestamp_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("keyframe timestamp must be numeric") from exc
    if not (timestamp > 0):
        raise argparse.ArgumentTypeError("keyframe timestamp must be greater than 0")
    return timestamp, image


def video_payload(args: argparse.Namespace) -> Tuple[str, Dict[str, Any]]:
    payload: Dict[str, Any] = {"model": args.model}
    if args.prompt:
        payload["prompt"] = args.prompt
    if args.video_operation == "generate":
        endpoint = "videos/generations"
        reference_images = args.reference_image or []
        reference_voices = args.reference_voice or []
        keyframes = args.keyframe or []
        is_classic = args.model == "grok-imagine-video"
        max_reference_images = 3 if is_classic else 7
        if len(reference_images) > max_reference_images:
            raise GrokError(
                "At most {} --reference-image values are supported for model {}.".format(
                    max_reference_images, args.model
                )
            )
        if len(reference_voices) > 3:
            raise GrokError("At most three --reference-voice values are supported.")
        if len(keyframes) > 4:
            raise GrokError("At most four --keyframe values are supported.")
        for timestamp, _ in keyframes:
            if timestamp >= args.duration:
                raise GrokError(
                    "Keyframe timestamps must be strictly inside the video duration."
                )
        if is_classic and (args.last_frame or keyframes or reference_voices):
            raise GrokError(
                "--last-frame, --keyframe, and --reference-voice are not supported "
                "with grok-imagine-video."
            )
        if is_classic and args.image and reference_images:
            raise GrokError(
                "grok-imagine-video does not allow --image with --reference-image."
            )
        if args.resolution == "1080p" and (
            is_classic
            or reference_images
            or reference_voices
            or args.last_frame
            or keyframes
        ):
            raise GrokError(
                "1080p is documented only for Video 1.5 text-to-video and simple "
                "image-to-video; classic, reference, and frame-pinned requests "
                "must use 720p."
            )
        if not args.prompt and not (
            args.image or reference_images or reference_voices or args.last_frame or keyframes
        ):
            raise GrokError("A prompt is required for text-to-video generation.")
        payload.update(
            {
                "duration": args.duration,
                "resolution": args.resolution,
                "aspect_ratio": args.aspect_ratio,
            }
        )
        if args.image:
            payload["image"] = {"url": local_media_uri(args.image, MAX_IMAGE_BYTES)}
        if reference_images:
            payload["reference_images"] = [
                {"url": local_media_uri(item, MAX_IMAGE_BYTES)}
                for item in reference_images
            ]
        if args.last_frame:
            payload["last_frame"] = {
                "url": local_media_uri(args.last_frame, MAX_IMAGE_BYTES)
            }
        if keyframes:
            payload["keyframes"] = [
                {
                    "image": {"url": local_media_uri(image, MAX_IMAGE_BYTES)},
                    "timestamp_s": timestamp,
                }
                for timestamp, image in keyframes
            ]
        if reference_voices:
            payload["reference_audios"] = [
                {"voice_id": voice_id} for voice_id in reference_voices
            ]
        if args.generate_audio is not None:
            payload["generate_audio"] = args.generate_audio
        return endpoint, payload
    payload["video"] = {"url": local_media_uri(args.video, MAX_VIDEO_BYTES)}
    if args.video_operation == "extend":
        payload["duration"] = args.duration
        return "videos/extensions", payload
    return "videos/edits", payload


def poll_video(
    credential: Credential,
    request_id: str,
    timeout: int,
    max_wait: int,
    poll_interval: float,
) -> Dict[str, Any]:
    started = time.monotonic()
    last_progress: Any = None
    while time.monotonic() - started < max_wait:
        status = http_json(
            "GET",
            "videos/{}".format(request_id),
            credential,
            timeout,
        )
        state = status.get("status")
        progress = status.get("progress")
        if progress != last_progress:
            log("→ video status={} progress={}".format(state, progress))
            last_progress = progress
        if state == "done":
            return status
        if state in {"failed", "expired", "cancelled"}:
            safe_status = redact_error(str(sanitize(status)), credential.token)
            raise GrokError(
                "Video request ended with status {}: {}".format(state, safe_status)
            )
        time.sleep(max(0.25, poll_interval))
    raise GrokError(
        "Video request {} did not finish within {} seconds. It may still be running; "
        "poll GET /v1/videos/{} before resubmitting.".format(
            request_id, max_wait, request_id
        )
    )


def command_video(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.monotonic()
    if args.video_operation in {"get", "resume"}:
        if args.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "module": "video",
                "operation": args.video_operation,
                "request_id": args.request_id,
                "method": "GET",
                "path": "/v1/videos/{}".format(args.request_id),
            }
        preflight_output_path(
            getattr(args, "output", None), getattr(args, "overwrite", False)
        )
        ctx = create_run(args.cache_dir, "video-{}".format(args.video_operation))
        write_json(ctx.directory / "request.json", {"request_id": args.request_id})
        credential = load_credential(args.auth, args.auth_file)
        if args.video_operation == "get":
            status = http_json(
                "GET", "videos/{}".format(args.request_id), credential, args.timeout
            )
        else:
            status = poll_video(
                credential,
                args.request_id,
                args.timeout,
                args.max_wait,
                args.poll_interval,
            )
        write_json(ctx.directory / "raw-response.json", sanitize(status))
        video = status.get("video") if isinstance(status.get("video"), dict) else {}
        if args.video_operation == "get":
            return success(
                ctx,
                "video",
                "get",
                started,
                [ctx.directory / "raw-response.json"],
                request_id=args.request_id,
                status=status.get("status"),
                progress=status.get("progress"),
                model=status.get("model"),
                video_url=video.get("url"),
                duration=video.get("duration"),
            )
        if not video.get("url"):
            raise GrokError("Completed video response contains no download URL.")
        output = ensure_output_path(
            args.output, ctx.directory / "video.mp4", args.overwrite
        )
        log("→ downloading completed video")
        download_url(str(video["url"]), output, args.timeout)
        return success(
            ctx,
            "video",
            "resume",
            started,
            [output, ctx.directory / "raw-response.json"],
            cost_from_usage(status.get("usage")),
            request_id=args.request_id,
            model=status.get("model"),
            duration=video.get("duration"),
        )
    endpoint, payload = video_payload(args)
    if args.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "module": "video",
            "operation": args.video_operation,
            "request": sanitize(payload),
        }
    preflight_output_path(args.output, args.overwrite)
    ctx = create_run(args.cache_dir, "video-{}".format(args.video_operation))
    write_json(ctx.directory / "request.json", sanitize(payload))
    credential = load_credential(args.auth, args.auth_file)
    log("→ submitting video {}".format(args.video_operation))
    submission = http_json("POST", endpoint, credential, args.timeout, payload)
    write_json(ctx.directory / "submission.json", sanitize(submission))
    request_id = submission.get("request_id") or submission.get("id")
    if not request_id:
        raise GrokError("Video submission returned no request_id.")
    status = poll_video(
        credential,
        str(request_id),
        args.timeout,
        args.max_wait,
        args.poll_interval,
    )
    write_json(ctx.directory / "raw-response.json", sanitize(status))
    video = status.get("video")
    if not isinstance(video, dict) or not video.get("url"):
        raise GrokError("Completed video response contains no download URL.")
    output = ensure_output_path(
        args.output, ctx.directory / "video.mp4", args.overwrite
    )
    log("→ downloading completed video")
    download_url(str(video["url"]), output, args.timeout)
    return success(
        ctx,
        "video",
        args.video_operation,
        started,
        [output, ctx.directory / "submission.json", ctx.directory / "raw-response.json"],
        cost_from_usage(status.get("usage")),
        request_id=str(request_id),
        model=status.get("model", args.model),
        duration=video.get("duration"),
        auth_kind=credential.kind,
    )


def add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, help="Output file path")
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace an existing output file"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument(
        "--auth",
        choices=("auto", "api-key", "session"),
        default=os.environ.get("XAI_AUTH_MODE", "auto"),
        help="Credential route (default: auto)",
    )
    parser.add_argument(
        "--auth-file",
        type=Path,
        default=Path(os.environ.get("GROK_HOME") or str(Path.home() / ".grok")).expanduser() / "auth.json",
        help="Optional Grok CLI auth store",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_root(),
        help="Run artifact root",
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print a redacted request without network"
    )
    subcommands = parser.add_subparsers(dest="module", required=True)

    system = subcommands.add_parser("system", help="Credentials and capability lists")
    system_commands = system.add_subparsers(dest="system_operation", required=True)
    system_commands.add_parser("auth-status", help="Inspect local credential availability")
    system_commands.add_parser("models", help="List models")
    system_commands.add_parser("voices", help="List TTS voices")

    text = subcommands.add_parser("text", help="Ask Grok with optional Web Search")
    text.add_argument("prompt")
    text.add_argument("--model", default=os.environ.get("XAI_TEXT_MODEL") or "grok-4.6", help="Explicit model ID; default stays grok-4.6, not grok-4.7")
    text.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"))
    text.add_argument("--image", action="append", help="Image to understand: local path or URL; repeat for multiple images")
    text.add_argument(
        "--no-search",
        action="store_true",
        help="Do not offer Web Search to the model",
    )

    search = subcommands.add_parser("search", help="Search X or the public web")
    search_commands = search.add_subparsers(dest="search_kind", required=True)
    x_search = search_commands.add_parser("x", help="Native X Search")
    x_search.add_argument("query")
    x_search.add_argument("--allow", action="append", help="Allowed X handles")
    x_search.add_argument("--exclude", action="append", help="Excluded X handles")
    x_search.add_argument("--from-date", type=parse_iso_date)
    x_search.add_argument("--to-date", type=parse_iso_date)
    x_search.add_argument(
        "--media",
        choices=("none", "image", "video", "both"),
        default="none",
    )
    x_search.add_argument("--depth", choices=tuple(DEPTHS), default="quick")
    x_search.add_argument("--model", default=os.environ.get("XAI_TEXT_MODEL") or "grok-4.6")
    x_search.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"))

    web_search = search_commands.add_parser("web", help="Native Web Search")
    web_search.add_argument("query")
    web_search.add_argument("--allow-domain", action="append")
    web_search.add_argument("--exclude-domain", action="append")
    web_search.add_argument("--depth", choices=tuple(DEPTHS), default="quick")
    web_search.add_argument("--model", default=os.environ.get("XAI_TEXT_MODEL") or "grok-4.6")
    web_search.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"))
    web_search.add_argument("--enable-image-search", action="store_true")
    web_search.add_argument("--enable-image-understanding", action="store_true")

    audio = subcommands.add_parser("audio", help="Speech synthesis and transcription")
    audio_commands = audio.add_subparsers(dest="audio_operation", required=True)
    tts = audio_commands.add_parser("tts", help="Text to speech")
    tts.add_argument("text")
    tts.add_argument(
        "--voice",
        default=os.environ.get("XAI_VOICE", "eve"),
        help="Voice ID (or set XAI_VOICE)",
    )
    tts.add_argument("--language", default=os.environ.get("XAI_TTS_LANGUAGE", "auto"))
    tts.add_argument(
        "--codec", choices=("mp3", "wav", "pcm", "mulaw", "ulaw", "alaw")
    )
    tts.add_argument(
        "--sample-rate",
        type=int,
        choices=(8000, 16000, 22050, 24000, 44100, 48000),
    )
    tts.add_argument(
        "--bit-rate", type=int, choices=(32000, 64000, 96000, 128000, 192000)
    )
    tts.add_argument("--speed", type=float)
    tts.add_argument(
        "--optimize-streaming-latency", type=int, choices=(0, 1, 2)
    )
    tts.add_argument(
        "--text-normalization",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    tts.add_argument("--with-timestamps", action="store_true")
    tts.add_argument(
        "--replace",
        action="append",
        metavar="PHRASE=PRONUNCIATION",
        help="Replace a phrase with a respelling or IPA value; repeatable",
    )
    add_output_options(tts)

    def add_stt_options(
        parser: argparse.ArgumentParser, *, allow_diarize: bool
    ) -> None:
        parser.add_argument(
            "--stt-model",
            choices=("grok-voice-transcribe-1.0", "grok-voice-transcribe-2.0"),
            default="grok-voice-transcribe-2.0",
        )
        parser.add_argument(
            "--language",
            default="auto",
            help="Language formatting code; auto omits the field",
        )
        parser.add_argument(
            "--format",
            dest="format_text",
            action="store_true",
            help="Enable inverse text normalization; requires --language",
        )
        parser.add_argument("--audio-format", choices=("pcm", "mulaw", "alaw"))
        parser.add_argument(
            "--sample-rate",
            type=int,
            choices=(8000, 16000, 22050, 24000, 44100, 48000),
        )
        parser.add_argument("--multichannel", action="store_true")
        parser.add_argument("--channels", type=int, choices=range(2, 9))
        parser.add_argument("--filler-words", action="store_true")
        parser.add_argument("--keyterm", action="append")
        parser.add_argument("--vad-threshold", type=float)
        if allow_diarize:
            parser.add_argument("--diarize", action="store_true")

    transcribe_parser = audio_commands.add_parser(
        "transcribe", help="Speech to text"
    )
    transcribe_parser.add_argument("file", type=Path)
    add_stt_options(transcribe_parser, allow_diarize=True)
    add_output_options(transcribe_parser)

    minutes = audio_commands.add_parser(
        "minutes", help="Diarized transcript and meeting minutes"
    )
    minutes.add_argument("file", type=Path)
    add_stt_options(minutes, allow_diarize=False)
    minutes.add_argument(
        "--model",
        default=os.environ.get("XAI_TEXT_MODEL") or "grok-4.6",
        help="Text model for minutes; defaults to XAI_TEXT_MODEL or grok-4.6",
    )
    minutes.add_argument(
        "--reasoning-effort", choices=("low", "medium", "high", "xhigh")
    )
    minutes.set_defaults(diarize=True)
    add_output_options(minutes)

    image = subcommands.add_parser("image", help="Image generation and editing")
    image_commands = image.add_subparsers(dest="image_operation", required=True)
    image_generate = image_commands.add_parser("generate", help="Generate images")
    image_generate.add_argument("prompt")
    image_generate.add_argument("--model", default="grok-imagine-image-2.0")
    image_generate.add_argument("--n", type=int, choices=range(1, 11), default=1)
    image_generate.add_argument("--aspect-ratio")
    image_generate.add_argument("--resolution", choices=("1k", "2k"))
    image_generate.add_argument("--quality", choices=("low", "medium", "auto"))
    add_output_options(image_generate)

    image_edit = image_commands.add_parser("edit", help="Edit one or more images")
    image_edit.add_argument("image")
    image_edit.add_argument("prompt")
    image_edit.add_argument("--model", default="grok-imagine-image-2.0")
    image_edit.add_argument(
        "--reference-image",
        action="append",
        help="Additional source image; at most four beyond the positional image",
    )
    image_edit.add_argument("--aspect-ratio")
    image_edit.add_argument("--resolution", choices=("1k", "2k"))
    image_edit.add_argument("--quality", choices=("low", "medium", "auto"))
    add_output_options(image_edit)

    video = subcommands.add_parser("video", help="Video generation and transformation")
    video_commands = video.add_subparsers(dest="video_operation", required=True)
    video_generate = video_commands.add_parser("generate", help="Generate a video")
    video_generate.add_argument(
        "prompt", nargs="?", help="Required for text-only generation"
    )
    video_generate.add_argument("--image", help="Source image path or URL")
    video_generate.add_argument(
        "--reference-image", action="append", help="Reference image, up to seven"
    )
    video_generate.add_argument("--model", default="grok-imagine-video-1.5")
    video_generate.add_argument("--duration", type=int, choices=range(1, 16), default=6)
    video_generate.add_argument(
        "--resolution", choices=("480p", "720p", "1080p"), default="720p"
    )
    video_generate.add_argument(
        "--aspect-ratio",
        choices=("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"),
        default="16:9",
    )
    video_generate.add_argument(
        "--last-frame", help="Pin the final frame (Video 1.5 only)"
    )
    video_generate.add_argument(
        "--keyframe",
        action="append",
        type=parse_keyframe_spec,
        help="Pin an interior frame as TIMESTAMP=IMAGE; repeat up to four times",
    )
    video_generate.add_argument(
        "--reference-voice",
        action="append",
        help="Preset voice_id reference; repeat up to three times",
    )
    video_generate.add_argument(
        "--generate-audio",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Include generated audio or pass --no-generate-audio for silent video",
    )
    video_generate.add_argument("--max-wait", type=int, default=600)
    video_generate.add_argument("--poll-interval", type=float, default=3.0)
    add_output_options(video_generate)

    video_get = video_commands.add_parser(
        "get", help="Fetch current status for an existing request_id (GET only)"
    )
    video_get.add_argument("request_id")

    video_resume = video_commands.add_parser(
        "resume", help="Resume polling and download an existing request_id (GET only)"
    )
    video_resume.add_argument("request_id")
    video_resume.add_argument("--max-wait", type=int, default=600)
    video_resume.add_argument("--poll-interval", type=float, default=3.0)
    add_output_options(video_resume)

    video_edit = video_commands.add_parser("edit", help="Edit a video")
    video_edit.add_argument("video")
    video_edit.add_argument("prompt")
    video_edit.add_argument(
        "--model",
        default="grok-imagine-video",
        help="Model slug (Video 1.5 edit support is not confirmed in official docs)",
    )
    video_edit.add_argument("--max-wait", type=int, default=600)
    video_edit.add_argument("--poll-interval", type=float, default=3.0)
    add_output_options(video_edit)

    video_extend = video_commands.add_parser("extend", help="Extend a video")
    video_extend.add_argument("video")
    video_extend.add_argument("prompt")
    video_extend.add_argument(
        "--model",
        default="grok-imagine-video",
        help="Model slug (Video 1.5 extension support is not confirmed in official docs)",
    )
    video_extend.add_argument("--duration", type=int, choices=range(2, 11), default=4)
    video_extend.add_argument("--max-wait", type=int, default=600)
    video_extend.add_argument("--poll-interval", type=float, default=3.0)
    add_output_options(video_extend)
    return parser


def dispatch(args: argparse.Namespace) -> Dict[str, Any]:
    if args.module == "system":
        if args.system_operation == "auth-status":
            started = time.monotonic()
            return success(
                None,
                "system",
                "auth-status",
                started,
                status=auth_status(args.auth, args.auth_file),
            )
        if args.system_operation == "models":
            return command_models(args)
        return command_voices(args)
    if args.module == "search":
        return command_search(args)
    if args.module == "text":
        return command_text(args)
    if args.module == "audio":
        if args.audio_operation == "tts":
            return command_tts(args)
        if args.audio_operation == "transcribe":
            return command_transcribe(args)
        return command_minutes(args)
    if args.module == "image":
        return command_image(args)
    if args.module == "video":
        return command_video(args)
    raise GrokError("Unknown command.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    emit(dispatch(args))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GrokError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(2)
