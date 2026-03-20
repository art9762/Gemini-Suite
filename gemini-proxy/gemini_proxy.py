#!/usr/bin/env python3
"""
Gemini Proxy Server - FastAPI-based proxy for Google Gemini API.

Provides Anthropic Messages API compatibility layer, native Gemini endpoints,
WebSocket remote management for gemini-cli instances, and a web dashboard.
Includes AI-powered management via Gemini 2.5 Flash for natural language control.

Features:
- Anthropic Messages API → Gemini format translation
- Streaming responses via Server-Sent Events (SSE)
- WebSocket remote management for connected CLI clients
- REST API for managing remote CLI instances
- AI-powered management console (Gemini 2.5 Flash interprets commands)
- Web dashboard for monitoring
- Request statistics tracking
- CORS support
- X-API-Key authentication
"""

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import httpx
import uvicorn
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    Header,
    HTTPException,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

# ─── Configuration from environment ──────────────────────────────────────────
PROXY_API_KEY = os.getenv("PROXY_API_KEY", "secret-proxy-key")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Model used for AI-powered management (lightweight, fast)
MANAGEMENT_MODEL = os.getenv("MANAGEMENT_MODEL", "gemini-2.5-flash-preview-05-20")

# ─── Model mapping: Anthropic model names → Gemini model names ───────────────
MODEL_MAPPING = {
    "claude-3-opus": "gemini-1.5-pro",
    "claude-3-sonnet": "gemini-1.5-flash",
    "claude-3-haiku": "gemini-2.0-flash",
    "claude-3.5-sonnet": "gemini-2.5-pro-preview-05-06",
    "claude-3.5-haiku": "gemini-2.5-flash-preview-05-20",
    # Native Gemini models (pass through)
    "gemini-1.5-pro": "gemini-1.5-pro",
    "gemini-1.5-flash": "gemini-1.5-flash",
    "gemini-2.0-flash": "gemini-2.0-flash",
    "gemini-2.5-pro": "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-flash": "gemini-2.5-flash-preview-05-20",
}


# ─── Pydantic request/response models ────────────────────────────────────────
class Message(BaseModel):
    """Single message in conversation."""
    role: str
    content: str


class ContentBlock(BaseModel):
    """Content block in response."""
    type: str
    text: Optional[str] = None


class MessagesRequest(BaseModel):
    """Anthropic Messages API request format."""
    model: str
    messages: List[Message]
    system: Optional[str] = None
    max_tokens: int = 4096
    stream: bool = False
    temperature: float = 0.7


class MessagesResponse(BaseModel):
    """Anthropic Messages API response format."""
    id: str
    type: str = "message"
    role: str = "assistant"
    content: List[ContentBlock]
    model: str
    usage: Dict[str, int] = {}


class GeminiGenerateRequest(BaseModel):
    """Native Gemini API request."""
    contents: List[Dict[str, Any]]
    generationConfig: Dict[str, Any] = {}


class RemoteSendRequest(BaseModel):
    """Send a prompt to a remote CLI client."""
    client_id: str
    prompt: str
    timeout: int = 60


class ManageRequest(BaseModel):
    """AI-powered management request — natural language command."""
    command: str
    target_client: Optional[str] = None


# ─── Statistics tracking ─────────────────────────────────────────────────────
@dataclass
class ProxyStats:
    """Statistics tracking for proxy."""
    total_requests: int = 0
    total_tokens: int = 0
    total_management_requests: int = 0
    connected_clients: Set[str] = field(default_factory=set)
    request_history: List[Dict[str, Any]] = field(default_factory=list)

    def add_request(self, model: str, tokens: int) -> None:
        """Record a request."""
        self.total_requests += 1
        self.total_tokens += tokens
        self.request_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "model": model,
            "tokens": tokens,
        })
        if len(self.request_history) > 100:
            self.request_history = self.request_history[-100:]


# ─── WebSocket Connection Manager ────────────────────────────────────────────
class ConnectionManager:
    """Manages WebSocket connections for remote CLI instances."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.client_info: Dict[str, Dict[str, Any]] = {}
        # Pending response futures: request_id → asyncio.Future
        self._pending: Dict[str, asyncio.Future] = {}

    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        """Register a new client connection."""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.client_info[client_id] = {
            "connected_at": datetime.utcnow().isoformat(),
            "ip": websocket.client[0] if websocket.client else "unknown",
            "status": "idle",
            "last_prompt": None,
        }

    def disconnect(self, client_id: str) -> None:
        """Remove a client connection."""
        self.active_connections.pop(client_id, None)
        self.client_info.pop(client_id, None)

    async def send_prompt(self, client_id: str, prompt: str, timeout: int = 60) -> Optional[str]:
        """
        Send a prompt to a specific client and wait for the response.
        Returns the response text, or None on failure.
        """
        if client_id not in self.active_connections:
            return None

        request_id = uuid.uuid4().hex[:12]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        # Update client status
        if client_id in self.client_info:
            self.client_info[client_id]["status"] = "busy"
            self.client_info[client_id]["last_prompt"] = prompt[:80]

        try:
            await self.active_connections[client_id].send_json({
                "type": "prompt",
                "request_id": request_id,
                "prompt": prompt,
            })
            # Wait for the response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return "[timeout] Клиент не ответил вовремя"
        except Exception as e:
            return f"[error] {str(e)}"
        finally:
            self._pending.pop(request_id, None)
            if client_id in self.client_info:
                self.client_info[client_id]["status"] = "idle"

    def resolve_response(self, request_id: str, response: str) -> None:
        """Resolve a pending future when client responds."""
        future = self._pending.get(request_id)
        if future and not future.done():
            future.set_result(response)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        for websocket in self.active_connections.values():
            try:
                await websocket.send_json(message)
            except Exception:
                pass

    def get_connected_clients(self) -> List[Dict[str, Any]]:
        """Get list of connected clients with status info."""
        result = []
        for client_id, info in self.client_info.items():
            result.append({
                "client_id": client_id,
                "connected_at": info["connected_at"],
                "ip": info["ip"],
                "status": info.get("status", "unknown"),
                "last_prompt": info.get("last_prompt"),
            })
        return result


# ─── Global state ────────────────────────────────────────────────────────────
stats = ProxyStats()
connection_manager = ConnectionManager()


# ─── Format translation functions ────────────────────────────────────────────
def anthropic_to_gemini_format(request: MessagesRequest) -> Dict[str, Any]:
    """Translate Anthropic Messages API format to Gemini format."""
    contents = []

    if request.system:
        contents.append({
            "role": "user",
            "parts": [{"text": f"System: {request.system}"}],
        })

    for msg in request.messages:
        contents.append({
            "role": "user" if msg.role == "user" else "model",
            "parts": [{"text": msg.content}],
        })

    return {
        "contents": contents,
        "generationConfig": {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
            "topP": 0.95,
        },
    }


def gemini_to_anthropic_format(gemini_response: Dict[str, Any], model: str) -> MessagesResponse:
    """Translate Gemini response format to Anthropic Messages API format."""
    response_text = ""
    candidates = gemini_response.get("candidates", [])
    if candidates:
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            if "text" in part:
                response_text += part["text"]

    usage_meta = gemini_response.get("usageMetadata", {})

    return MessagesResponse(
        id=f"msg_{uuid.uuid4().hex[:12]}",
        role="assistant",
        content=[ContentBlock(type="text", text=response_text)],
        model=model,
        usage={
            "input_tokens": usage_meta.get("inputTokenCount", 0),
            "output_tokens": usage_meta.get("outputTokenCount", 0),
        },
    )


async def call_gemini_api(
    payload: Dict[str, Any],
    model: str,
    stream: bool = False,
) -> httpx.Response:
    """Call Gemini API with given payload."""
    if stream:
        url = f"{GEMINI_API_BASE}/{model}:streamGenerateContent"
    else:
        url = f"{GEMINI_API_BASE}/{model}:generateContent"

    headers = {"Content-Type": "application/json"}
    params = {"key": GEMINI_API_KEY}

    async with httpx.AsyncClient(timeout=120) as client:
        if stream:
            # Return the client context for streaming
            req = client.build_request("POST", url, json=payload, headers=headers, params=params)
            return await client.send(req, stream=True)
        else:
            return await client.post(url, json=payload, headers=headers, params=params)


async def call_gemini_simple(prompt: str, model: str = None) -> str:
    """Quick helper: send a single prompt to Gemini, get text back."""
    model = model or MANAGEMENT_MODEL
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2048},
    }
    try:
        resp = await call_gemini_api(payload, model, stream=False)
        if resp.status_code != 200:
            return f"[Gemini API error {resp.status_code}]"
        data = resp.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)
    except Exception as e:
        return f"[error] {e}"


# ─── FastAPI app setup ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown."""
    print(f"Starting Gemini Proxy Server on {HOST}:{PORT}")
    print(f"Dashboard: http://{HOST}:{PORT}/dashboard")
    print(f"API docs:  http://{HOST}:{PORT}/docs")
    print(f"Management model: {MANAGEMENT_MODEL}")
    yield
    print("Shutting down Gemini Proxy Server")


app = FastAPI(
    title="Gemini Proxy",
    description="Proxy server for Google Gemini API with Anthropic compatibility and AI management",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """Verify X-API-Key header."""
    if x_api_key != PROXY_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Anthropic-compatible endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/v1/messages")
async def messages_endpoint(
    request: MessagesRequest,
    x_api_key: Optional[str] = Header(None),
):
    """Anthropic Messages API compatible endpoint (non-streaming + streaming)."""
    verify_api_key(x_api_key)

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")

    gemini_model = MODEL_MAPPING.get(request.model, request.model)
    gemini_payload = anthropic_to_gemini_format(request)

    # ── Streaming mode ────────────────────────────────────────────────────
    if request.stream:
        async def sse_generator():
            total_tokens = 0
            response_text = ""
            try:
                url = f"{GEMINI_API_BASE}/{gemini_model}:streamGenerateContent"
                params = {"key": GEMINI_API_KEY, "alt": "sse"}
                async with httpx.AsyncClient(timeout=120) as client:
                    async with client.stream(
                        "POST", url, json=gemini_payload,
                        headers={"Content-Type": "application/json"},
                        params=params,
                    ) as resp:
                        if resp.status_code != 200:
                            err = await resp.aread()
                            yield f"data: {json.dumps({'error': err.decode()})}\n\n"
                            return

                        # Send message_start
                        msg_id = f"msg_{uuid.uuid4().hex[:12]}"
                        yield f"data: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'model': request.model}})}\n\n"
                        yield f"data: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"

                        async for line in resp.aiter_lines():
                            if not line.strip() or not line.startswith("data:"):
                                continue
                            raw = line.removeprefix("data:").strip()
                            if not raw:
                                continue
                            try:
                                chunk = json.loads(raw)
                                candidates = chunk.get("candidates", [])
                                if candidates:
                                    parts = candidates[0].get("content", {}).get("parts", [])
                                    for part in parts:
                                        if "text" in part:
                                            text = part["text"]
                                            response_text += text
                                            yield f"data: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"
                                usage = chunk.get("usageMetadata", {})
                                if usage:
                                    total_tokens = usage.get("totalTokenCount", 0)
                            except json.JSONDecodeError:
                                continue

                yield f"data: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
                yield f"data: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': total_tokens}})}\n\n"
                yield f"data: {json.dumps({'type': 'message_stop'})}\n\n"
                stats.add_request(request.model, total_tokens)

            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    # ── Non-streaming mode ────────────────────────────────────────────────
    try:
        response = await call_gemini_api(gemini_payload, gemini_model, stream=False)
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Gemini API error: {response.text}")

        anthropic_response = gemini_to_anthropic_format(response.json(), request.model)
        stats.add_request(request.model, anthropic_response.usage.get("output_tokens", 0))
        return anthropic_response

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Gemini API request timeout")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error calling Gemini API: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Native Gemini endpoint
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/v1/gemini/generate")
async def gemini_endpoint(
    request: GeminiGenerateRequest,
    x_api_key: Optional[str] = Header(None),
):
    """Native Gemini API pass-through endpoint."""
    verify_api_key(x_api_key)
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")

    model = request.generationConfig.get("model", "gemini-2.5-flash-preview-05-20")
    try:
        response = await call_gemini_api(request.model_dump(), model, stream=False)
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Gemini API error: {response.text}")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Remote management — REST API
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/v1/remote/clients")
async def list_remote_clients(x_api_key: Optional[str] = Header(None)):
    """List all connected remote CLI clients."""
    verify_api_key(x_api_key)
    clients = connection_manager.get_connected_clients()
    return {"clients": clients, "count": len(clients)}


@app.post("/v1/remote/send")
async def send_to_remote_client(
    request: RemoteSendRequest,
    x_api_key: Optional[str] = Header(None),
):
    """
    Send a prompt to a specific remote CLI client and get the response.
    The CLI will process the prompt through Gemini and return the result.
    """
    verify_api_key(x_api_key)

    clients = connection_manager.get_connected_clients()
    client_ids = [c["client_id"] for c in clients]

    if request.client_id not in client_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Client '{request.client_id}' not found. Connected: {client_ids}",
        )

    response = await connection_manager.send_prompt(
        request.client_id, request.prompt, timeout=request.timeout
    )

    if response is None:
        raise HTTPException(status_code=504, detail="Client did not respond")

    return {"client_id": request.client_id, "prompt": request.prompt, "response": response}


@app.post("/v1/remote/broadcast")
async def broadcast_to_clients(
    prompt: str = "",
    x_api_key: Optional[str] = Header(None),
):
    """Broadcast a prompt to ALL connected CLI clients."""
    verify_api_key(x_api_key)
    await connection_manager.broadcast({"type": "prompt", "request_id": "broadcast", "prompt": prompt})
    return {"status": "sent", "clients": len(connection_manager.active_connections)}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: AI-powered management via Gemini 2.5 Flash
# ═══════════════════════════════════════════════════════════════════════════════

MANAGEMENT_SYSTEM_PROMPT = """Ты — менеджер удалённых CLI-консолей gemini-cli.
У тебя есть доступ к подключённым клиентам через proxy-сервер.

Твоя задача — интерпретировать команды пользователя на естественном языке и
сформировать JSON-ответ с действием.

Доступные действия:
1. {"action": "send_prompt", "client_id": "<id>", "prompt": "<текст промпта для CLI>"}
   — отправить промпт конкретному клиенту
2. {"action": "send_all", "prompt": "<текст>"}
   — отправить промпт всем клиентам
3. {"action": "list_clients"}
   — показать список подключённых клиентов
4. {"action": "status"}
   — показать статистику сервера
5. {"action": "chat", "response": "<ответ>"}
   — просто ответить пользователю (без действий на клиентах)

Подключённые клиенты: {clients}
Статистика: запросов={total_requests}, токенов={total_tokens}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста вне JSON.
Если команда неоднозначна — используй action "chat" и попроси уточнить.
"""


@app.post("/v1/manage")
async def ai_manage_endpoint(
    request: ManageRequest,
    x_api_key: Optional[str] = Header(None),
):
    """
    AI-powered management endpoint.

    Send a natural language command in Russian or English.
    Gemini 2.5 Flash will interpret the command and execute the appropriate action
    on connected CLI clients.

    Examples:
      - "покажи подключённых клиентов"
      - "отправь первому клиенту: напиши hello world на python"
      - "попроси все консоли показать версию python"
      - "статистика сервера"
    """
    verify_api_key(x_api_key)

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key not configured")

    stats.total_management_requests += 1

    # Build context for the AI
    clients = connection_manager.get_connected_clients()
    system_prompt = MANAGEMENT_SYSTEM_PROMPT.format(
        clients=json.dumps(clients, ensure_ascii=False),
        total_requests=stats.total_requests,
        total_tokens=stats.total_tokens,
    )

    full_prompt = f"{system_prompt}\n\nКоманда пользователя: {request.command}"

    # If a target client was specified, hint it
    if request.target_client:
        full_prompt += f"\nЦелевой клиент: {request.target_client}"

    # Ask Gemini 2.5 Flash to interpret the command
    ai_response = await call_gemini_simple(full_prompt, MANAGEMENT_MODEL)

    # Parse the AI's JSON decision
    try:
        # Try to extract JSON from the response (sometimes wrapped in ```json)
        cleaned = ai_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        decision = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "status": "ai_response",
            "ai_raw": ai_response,
            "note": "AI не вернул валидный JSON, показываем сырой ответ",
        }

    action = decision.get("action", "chat")
    result: Dict[str, Any] = {"action": action, "management_model": MANAGEMENT_MODEL}

    # ── Execute the decided action ────────────────────────────────────────
    if action == "list_clients":
        result["clients"] = clients
        result["count"] = len(clients)

    elif action == "status":
        result["stats"] = {
            "total_requests": stats.total_requests,
            "total_tokens": stats.total_tokens,
            "management_requests": stats.total_management_requests,
            "connected_clients": len(clients),
        }

    elif action == "send_prompt":
        target = decision.get("client_id", "")
        prompt = decision.get("prompt", "")

        if not target and clients:
            target = clients[0]["client_id"]

        if target:
            response = await connection_manager.send_prompt(target, prompt, timeout=60)
            result["client_id"] = target
            result["prompt_sent"] = prompt
            result["client_response"] = response
        else:
            result["error"] = "Нет подключённых клиентов"

    elif action == "send_all":
        prompt = decision.get("prompt", "")
        responses = {}
        for c in clients:
            resp = await connection_manager.send_prompt(c["client_id"], prompt, timeout=60)
            responses[c["client_id"]] = resp
        result["prompt_sent"] = prompt
        result["responses"] = responses

    elif action == "chat":
        result["response"] = decision.get("response", ai_response)

    else:
        result["response"] = decision

    return result


# Convenience GET endpoint to quickly send a management command
@app.get("/v1/manage/{command}")
async def ai_manage_get(command: str, x_api_key: Optional[str] = Header(None)):
    """Quick management via GET — URL-encoded command."""
    verify_api_key(x_api_key)
    req = ManageRequest(command=command)
    return await ai_manage_endpoint(req, x_api_key)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: WebSocket remote management
# ═══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/remote")
async def websocket_remote_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for remote CLI management.

    Protocol:
      Client → Server: {"type": "register", "client_id": "..."}
      Server → Client: {"type": "prompt", "request_id": "...", "prompt": "..."}
      Client → Server: {"type": "response", "request_id": "...", "response": "..."}
    """
    client_id = None
    try:
        data = await websocket.receive_text()
        message = json.loads(data)

        if message.get("type") != "register":
            await websocket.close(code=status.WS_1002_PROTOCOL_ERROR)
            return

        client_id = message.get("client_id")
        if not client_id:
            await websocket.close(code=status.WS_1002_PROTOCOL_ERROR)
            return

        await connection_manager.connect(client_id, websocket)
        stats.connected_clients.add(client_id)

        # Keep connection alive, handle responses
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "response":
                request_id = msg.get("request_id", "")
                response = msg.get("response", "")
                connection_manager.resolve_response(request_id, response)

            elif msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except json.JSONDecodeError:
        pass
    except Exception:
        pass
    finally:
        if client_id:
            connection_manager.disconnect(client_id)
            stats.connected_clients.discard(client_id)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_endpoint():
    """Web dashboard showing proxy statistics, connected clients, and management console."""
    connected_clients = connection_manager.get_connected_clients()

    clients_rows = ""
    for c in connected_clients:
        status_badge = "🟢" if c["status"] == "idle" else "🔴"
        clients_rows += f"""<tr>
            <td><code>{c['client_id']}</code></td>
            <td>{c['ip']}</td>
            <td>{status_badge} {c['status']}</td>
            <td>{c['connected_at']}</td>
            <td>{c.get('last_prompt') or '—'}</td>
        </tr>"""

    if not clients_rows:
        clients_rows = '<tr><td colspan="5" style="text-align:center;color:#999;">Нет подключённых клиентов</td></tr>'

    history_rows = ""
    for req in stats.request_history[-20:]:
        history_rows += f"<tr><td>{req['timestamp']}</td><td>{req['model']}</td><td>{req['tokens']}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Gemini Proxy — Dashboard</title>
    <meta http-equiv="refresh" content="10">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e0e0e0; padding: 20px; }}
        .header {{ display: flex; align-items: center; gap: 16px; margin-bottom: 24px; border-bottom: 2px solid #4285f4; padding-bottom: 16px; }}
        .header h1 {{ font-size: 28px; color: #fff; }}
        .header .badge {{ background: #4285f4; color: white; padding: 4px 12px; border-radius: 12px; font-size: 13px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 28px; }}
        .card {{ background: #1a1d27; padding: 20px; border-radius: 12px; border: 1px solid #2a2d37; }}
        .card .value {{ font-size: 36px; font-weight: 700; color: #4285f4; }}
        .card .label {{ color: #888; font-size: 13px; margin-top: 6px; }}
        h2 {{ margin: 20px 0 12px; color: #ccc; font-size: 18px; }}
        table {{ width: 100%; border-collapse: collapse; background: #1a1d27; border-radius: 12px; overflow: hidden; }}
        th {{ background: #4285f4; color: white; padding: 10px 14px; text-align: left; font-size: 13px; }}
        td {{ padding: 10px 14px; border-bottom: 1px solid #2a2d37; font-size: 13px; }}
        code {{ background: #2a2d37; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
        .mgmt {{ background: #1a1d27; padding: 20px; border-radius: 12px; border: 1px solid #2a2d37; margin-top: 20px; }}
        .mgmt input {{ width: 70%; padding: 10px; background: #0f1117; border: 1px solid #4285f4; border-radius: 6px; color: #fff; font-size: 14px; }}
        .mgmt button {{ padding: 10px 20px; background: #4285f4; border: none; border-radius: 6px; color: #fff; cursor: pointer; font-size: 14px; }}
        .mgmt button:hover {{ background: #5a95f5; }}
        #mgmt-result {{ margin-top: 12px; padding: 12px; background: #0f1117; border-radius: 6px; white-space: pre-wrap; font-family: monospace; font-size: 13px; min-height: 60px; max-height: 400px; overflow-y: auto; }}
        .refresh-note {{ color: #555; font-size: 11px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Gemini Proxy</h1>
        <span class="badge">v2.0</span>
        <span class="badge">{MANAGEMENT_MODEL}</span>
    </div>

    <div class="grid">
        <div class="card"><div class="value">{stats.total_requests}</div><div class="label">Запросов всего</div></div>
        <div class="card"><div class="value">{stats.total_tokens}</div><div class="label">Токенов всего</div></div>
        <div class="card"><div class="value">{len(connected_clients)}</div><div class="label">Клиентов онлайн</div></div>
        <div class="card"><div class="value">{stats.total_management_requests}</div><div class="label">Управляющих команд</div></div>
    </div>

    <h2>Подключённые клиенты</h2>
    <table>
        <tr><th>ID</th><th>IP</th><th>Статус</th><th>Подключён</th><th>Последний промпт</th></tr>
        {clients_rows}
    </table>

    <div class="mgmt">
        <h2>Управление через AI (Gemini Flash)</h2>
        <p style="color:#888;font-size:13px;margin-bottom:12px;">Введите команду на русском или английском. AI интерпретирует и выполнит действие.</p>
        <div style="display:flex;gap:8px;">
            <input type="text" id="mgmt-input" placeholder="напр: отправь первому клиенту — напиши скрипт бэкапа" />
            <button onclick="sendMgmt()">Отправить</button>
        </div>
        <div id="mgmt-result">Результат появится здесь...</div>
    </div>

    <h2>Последние запросы</h2>
    <table>
        <tr><th>Время</th><th>Модель</th><th>Токены</th></tr>
        {history_rows}
    </table>

    <p class="refresh-note">Авто-обновление каждые 10 сек. Обновлено: {datetime.utcnow().isoformat()}</p>

    <script>
    async function sendMgmt() {{
        const input = document.getElementById('mgmt-input');
        const result = document.getElementById('mgmt-result');
        const cmd = input.value.trim();
        if (!cmd) return;

        result.textContent = 'Обработка...';
        try {{
            const resp = await fetch('/v1/manage', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'X-API-Key': '{PROXY_API_KEY}'
                }},
                body: JSON.stringify({{command: cmd}})
            }});
            const data = await resp.json();
            result.textContent = JSON.stringify(data, null, 2);
        }} catch (e) {{
            result.textContent = 'Ошибка: ' + e.message;
        }}
    }}

    document.getElementById('mgmt-input').addEventListener('keydown', function(e) {{
        if (e.key === 'Enter') sendMgmt();
    }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Health & info
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_endpoint():
    """Health check."""
    return {
        "status": "ok",
        "version": "2.0.0",
        "gemini_configured": bool(GEMINI_API_KEY),
        "management_model": MANAGEMENT_MODEL,
        "connected_clients": len(connection_manager.active_connections),
    }


@app.get("/")
async def root_endpoint():
    """Root endpoint with API info."""
    return {
        "name": "Gemini Proxy",
        "version": "2.0.0",
        "endpoints": {
            "messages": "POST /v1/messages",
            "gemini": "POST /v1/gemini/generate",
            "remote_clients": "GET /v1/remote/clients",
            "remote_send": "POST /v1/remote/send",
            "remote_broadcast": "POST /v1/remote/broadcast",
            "ai_manage": "POST /v1/manage",
            "ai_manage_quick": "GET /v1/manage/{command}",
            "websocket": "WS /ws/remote",
            "dashboard": "GET /dashboard",
            "health": "GET /health",
            "docs": "GET /docs",
        },
    }


# ─── Entry point ─────────────────────────────────────────────────────────────
def main():
    if not GEMINI_API_KEY:
        print("WARNING: GEMINI_API_KEY not set")
        print("Set it: export GEMINI_API_KEY=your_key")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
