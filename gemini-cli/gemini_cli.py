#!/usr/bin/env python3
"""
Gemini CLI - A production-quality CLI tool powered by Google Gemini API.

Interactive REPL chat interface with file editing, shell execution, and remote management.
Supports streaming responses, multi-turn conversations, and remote control via WebSocket.

When in remote mode, the CLI connects to gemini-proxy and can receive prompts
from external systems (including AI-managed control via Gemini 2.5 Flash).
"""

import asyncio
import json
import os
import platform
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles
import httpx
import websockets
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.syntax import Syntax
from rich.spinner import Spinner
from rich.live import Live
from rich.text import Text
from rich.table import Table

# ─── Configuration constants ─────────────────────────────────────────────────
CONFIG_DIR = Path.home() / ".gemini-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
DEFAULT_MODEL = "gemini-2.5-flash-preview-05-20"
DEFAULT_SERVER = "ws://localhost:8000/ws/remote"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class Config:
    """Manages CLI configuration stored in ~/.gemini-cli/config.json"""

    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.config_file = CONFIG_FILE
        self.data = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration from file, create defaults if not exists."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return self._get_defaults()
        return self._get_defaults()

    def _get_defaults(self) -> dict:
        return {
            "api_key": "",
            "model": DEFAULT_MODEL,
            "server_url": DEFAULT_SERVER,
            "timeout": 60,
            "max_tokens": 8192,
            "temperature": 0.7,
            "auto_remote": False,
            "client_name": platform.node() or "gemini-cli",
        }

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()


class GeminiClient:
    """Async client for Google Gemini API with streaming support."""

    def __init__(self, api_key: str, model: str, timeout: int = 60,
                 max_tokens: int = 8192, temperature: float = 0.7):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.conversation_history = []

    async def chat(self, prompt: str) -> tuple[str, bool]:
        """Send a message and get the full response (non-streaming)."""
        if not self.api_key:
            return "Ошибка: API ключ не настроен. Используйте /setup", False

        self.conversation_history.append({"role": "user", "parts": [{"text": prompt}]})

        url = f"{GEMINI_API_BASE}/{self.model}:generateContent"
        payload = {
            "contents": self.conversation_history,
            "generationConfig": {
                "temperature": self.temperature,
                "topP": 0.95,
                "maxOutputTokens": self.max_tokens,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url, json=payload,
                    headers={"Content-Type": "application/json"},
                    params={"key": self.api_key},
                )

                if resp.status_code != 200:
                    return f"API Error {resp.status_code}: {resp.text[:500]}", False

                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return "Пустой ответ от API", False

                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)

                if text:
                    self.conversation_history.append(
                        {"role": "model", "parts": [{"text": text}]}
                    )
                    return text, True
                return "Пустой ответ", False

        except httpx.TimeoutException:
            return f"Таймаут запроса ({self.timeout}с)", False
        except httpx.RequestError as e:
            return f"Ошибка сети: {e}", False
        except Exception as e:
            return f"Ошибка: {e}", False

    async def stream_chat(self, prompt: str):
        """Stream chat response, yields text chunks."""
        if not self.api_key:
            yield "Ошибка: API ключ не настроен. Используйте /setup"
            return

        self.conversation_history.append({"role": "user", "parts": [{"text": prompt}]})

        url = f"{GEMINI_API_BASE}/{self.model}:streamGenerateContent"
        payload = {
            "contents": self.conversation_history,
            "generationConfig": {
                "temperature": self.temperature,
                "topP": 0.95,
                "maxOutputTokens": self.max_tokens,
            },
        }

        response_text = ""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST", url, json=payload,
                    headers={"Content-Type": "application/json"},
                    params={"key": self.api_key, "alt": "sse"},
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield f"API Error {resp.status_code}: {body.decode()[:500]}"
                        return

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
                                        yield text
                        except json.JSONDecodeError:
                            continue

            if response_text:
                self.conversation_history.append(
                    {"role": "model", "parts": [{"text": response_text}]}
                )
        except Exception as e:
            yield f"\nОшибка: {e}"

    def clear_history(self) -> None:
        self.conversation_history = []


class RemoteManager:
    """Manages WebSocket connection to gemini-proxy for remote control."""

    def __init__(self, server_url: str, client_id: str, console: Console):
        self.server_url = server_url
        self.client_id = client_id
        self.console = console
        self.ws = None
        self.connected = False
        self._listen_task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """Connect to remote proxy server and register."""
        try:
            self.ws = await websockets.connect(
                self.server_url,
                ping_interval=20,
                ping_timeout=10,
            )
            await self.ws.send(json.dumps({
                "type": "register",
                "client_id": self.client_id,
            }))
            self.connected = True
            return True
        except Exception as e:
            self.console.print(f"[red]Не удалось подключиться: {e}[/red]")
            return False

    async def disconnect(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            self._listen_task = None
        if self.ws:
            await self.ws.close()
        self.connected = False

    async def listen_and_handle(self, gemini_client: GeminiClient) -> None:
        """
        Background listener: receives prompts from the proxy server,
        processes them through Gemini, and sends back responses.
        """
        self.console.print(
            "[dim]Удалённый режим активен — ожидание команд от сервера...[/dim]"
        )
        try:
            while self.connected and self.ws:
                raw = await self.ws.recv()
                msg = json.loads(raw)

                if msg.get("type") == "pong":
                    continue

                if msg.get("type") == "prompt":
                    request_id = msg.get("request_id", "")
                    prompt = msg.get("prompt", "")

                    self.console.print(f"\n[bold yellow]⚡ Удалённый запрос:[/bold yellow] {prompt[:120]}")

                    # Process the prompt through Gemini
                    response_text, success = await gemini_client.chat(prompt)

                    # Send response back
                    await self.ws.send(json.dumps({
                        "type": "response",
                        "request_id": request_id,
                        "response": response_text,
                    }))

                    # Show a preview locally
                    preview = response_text[:200] + ("..." if len(response_text) > 200 else "")
                    status_mark = "[green]✓[/green]" if success else "[red]✗[/red]"
                    self.console.print(f"{status_mark} Ответ отправлен ({len(response_text)} символов)")

        except websockets.ConnectionClosed:
            self.console.print("[yellow]Соединение с сервером закрыто[/yellow]")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.console.print(f"[red]Ошибка удалённого режима: {e}[/red]")
        finally:
            self.connected = False

    def start_listener(self, gemini_client: GeminiClient) -> None:
        """Start background listener task."""
        self._listen_task = asyncio.create_task(
            self.listen_and_handle(gemini_client)
        )

    async def send_ping(self) -> None:
        """Send keepalive ping."""
        if self.ws and self.connected:
            try:
                await self.ws.send(json.dumps({"type": "ping"}))
            except Exception:
                self.connected = False


class GeminiCLI:
    """Main CLI application with REPL interface."""

    def __init__(self, config: Config):
        self.config = config
        self.console = Console()
        self.client = GeminiClient(
            api_key=config.get("api_key", ""),
            model=config.get("model", DEFAULT_MODEL),
            timeout=int(config.get("timeout", 60)),
            max_tokens=int(config.get("max_tokens", 8192)),
            temperature=float(config.get("temperature", 0.7)),
        )
        self.remote_manager: Optional[RemoteManager] = None
        self.remote_mode = False

    def show_banner(self) -> None:
        banner_text = Text()
        banner_text.append("  Gemini CLI v2.0\n", style="bold cyan")
        banner_text.append(f"  Model: {self.client.model}\n", style="dim")
        banner_text.append("  Type /help for commands", style="dim")

        panel = Panel(
            banner_text,
            border_style="cyan",
            padding=(1, 2),
        )
        self.console.print(panel)

    def show_help(self) -> None:
        table = Table(title="Команды", border_style="cyan", show_header=True)
        table.add_column("Команда", style="cyan", width=22)
        table.add_column("Описание")

        commands = [
            ("/help", "Показать справку"),
            ("/clear", "Очистить историю разговора"),
            ("/exit", "Выйти из приложения"),
            ("/model <имя>", "Переключить модель (gemini-2.5-flash, gemini-2.5-pro, ...)"),
            ("/remote on|off", "Включить/выключить удалённое управление"),
            ("/config", "Показать текущие настройки"),
            ("/setup", "Настроить API ключ"),
            ("/file read <path>", "Прочитать файл"),
            ("/file write <path>", "Записать последний код в файл"),
            ("/exec <command>", "Выполнить shell-команду"),
            ("/models", "Список доступных моделей"),
        ]
        for cmd, desc in commands:
            table.add_row(cmd, desc)

        self.console.print(table)

    async def setup(self) -> None:
        self.console.print("\n[bold yellow]Настройка Gemini CLI[/bold yellow]\n")
        api_key = Prompt.ask("Введите Google Gemini API ключ", password=True)
        if api_key:
            self.config.set("api_key", api_key)
            self.client.api_key = api_key
            self.console.print("[green]✓ API ключ сохранён[/green]")
        else:
            self.console.print("[red]✗ API ключ обязателен[/red]")

    def show_config(self) -> None:
        cfg = self.config.data.copy()
        if cfg.get("api_key"):
            cfg["api_key"] = cfg["api_key"][:8] + "..." + cfg["api_key"][-4:]

        text = "\n".join(f"  [cyan]{k}:[/cyan] {v}" for k, v in cfg.items())
        self.console.print(Panel(text, title="Конфигурация", border_style="cyan"))

    def show_models(self) -> None:
        table = Table(title="Доступные модели", border_style="cyan")
        table.add_column("Модель", style="cyan")
        table.add_column("Описание")
        table.add_column("", style="green")

        models = [
            ("gemini-2.5-flash-preview-05-20", "Быстрая, лёгкая (рекомендуемая)", ""),
            ("gemini-2.5-pro-preview-05-06", "Мощная, для сложных задач", ""),
            ("gemini-2.0-flash", "Предыдущее поколение Flash", ""),
            ("gemini-1.5-pro", "Стабильная Pro", ""),
            ("gemini-1.5-flash", "Стабильная Flash", ""),
        ]
        current = self.client.model
        for name, desc, _ in models:
            marker = "← текущая" if name == current else ""
            table.add_row(name, desc, marker)
        self.console.print(table)

    # ── File operations ──────────────────────────────────────────────────────

    async def read_file(self, filepath: str) -> None:
        """Read and display a file."""
        path = Path(filepath).expanduser().resolve()
        if not path.exists():
            self.console.print(f"[red]Файл не найден: {path}[/red]")
            return
        try:
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
            # Guess language from extension
            ext_map = {
                ".py": "python", ".js": "javascript", ".ts": "typescript",
                ".sh": "bash", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
                ".html": "html", ".css": "css", ".sql": "sql", ".rs": "rust",
                ".go": "go", ".java": "java", ".cpp": "cpp", ".c": "c",
                ".rb": "ruby", ".php": "php", ".toml": "toml", ".md": "markdown",
            }
            lang = ext_map.get(path.suffix.lower(), "text")
            self.console.print(
                Syntax(content, lang, theme="monokai", line_numbers=True),
            )
        except Exception as e:
            self.console.print(f"[red]Ошибка чтения: {e}[/red]")

    async def write_file(self, filepath: str, content: str) -> None:
        """Write content to a file with confirmation."""
        path = Path(filepath).expanduser().resolve()
        if path.exists():
            overwrite = Confirm.ask(f"Файл {path} существует. Перезаписать?")
            if not overwrite:
                return

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(path, "w") as f:
                await f.write(content)
            self.console.print(f"[green]✓ Записано: {path} ({len(content)} байт)[/green]")
        except Exception as e:
            self.console.print(f"[red]Ошибка записи: {e}[/red]")

    # Store last code block from response for /file write
    _last_code_block: str = ""

    # ── Shell execution ──────────────────────────────────────────────────────

    async def execute_shell(self, command: str) -> None:
        """Execute shell command with user confirmation."""
        self.console.print(Panel(command, title="Команда", border_style="yellow"))
        if not Confirm.ask("Выполнить?"):
            return

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30,
            )
            if result.stdout:
                self.console.print(
                    Syntax(result.stdout, "text", theme="monokai", line_numbers=False)
                )
            if result.stderr:
                self.console.print(f"[red]{result.stderr}[/red]")
            self.console.print(f"[dim]Exit code: {result.returncode}[/dim]")
        except subprocess.TimeoutExpired:
            self.console.print("[red]Таймаут команды (30с)[/red]")
        except Exception as e:
            self.console.print(f"[red]Ошибка: {e}[/red]")

    # ── Response rendering ───────────────────────────────────────────────────

    def render_response(self, response: str) -> None:
        """Render API response with syntax highlighting for code blocks."""
        code_pattern = r"```(\w+)?\n(.*?)```"
        matches = list(re.finditer(code_pattern, response, re.DOTALL))

        if matches:
            last_end = 0
            for match in matches:
                # Text before code block
                before = response[last_end:match.start()].strip()
                if before:
                    self.console.print(Markdown(before))

                language = match.group(1) or "text"
                code = match.group(2).rstrip()
                self._last_code_block = code

                self.console.print(
                    Syntax(code, language, theme="monokai", line_numbers=True, padding=1)
                )
                last_end = match.end()

            # Text after last code block
            after = response[last_end:].strip()
            if after:
                self.console.print(Markdown(after))
        else:
            self.console.print(Markdown(response))

    # ── Command handler ──────────────────────────────────────────────────────

    async def handle_command(self, command: str) -> bool:
        """Handle /commands. Returns False to exit."""
        parts = command.split(maxsplit=2)
        cmd = parts[0].lower()
        arg1 = parts[1] if len(parts) > 1 else ""
        arg2 = parts[2] if len(parts) > 2 else ""

        if cmd == "/help":
            self.show_help()
        elif cmd == "/clear":
            self.client.clear_history()
            self.console.print("[green]✓ История очищена[/green]")
        elif cmd == "/exit":
            return False
        elif cmd == "/setup":
            await self.setup()
        elif cmd == "/config":
            self.show_config()
        elif cmd == "/models":
            self.show_models()
        elif cmd == "/model":
            if arg1:
                self.config.set("model", arg1)
                self.client.model = arg1
                self.console.print(f"[green]✓ Модель: {arg1}[/green]")
            else:
                self.console.print(f"[cyan]Текущая модель: {self.client.model}[/cyan]")
        elif cmd == "/remote":
            await self.handle_remote(arg1)
        elif cmd == "/file":
            if arg1 == "read" and arg2:
                await self.read_file(arg2)
            elif arg1 == "write" and arg2:
                if self._last_code_block:
                    await self.write_file(arg2, self._last_code_block)
                else:
                    self.console.print("[yellow]Нет кода для записи[/yellow]")
            else:
                self.console.print("[yellow]Использование: /file read <path> | /file write <path>[/yellow]")
        elif cmd == "/exec":
            rest = command[len("/exec"):].strip()
            if rest:
                await self.execute_shell(rest)
            else:
                self.console.print("[yellow]Использование: /exec <command>[/yellow]")
        else:
            self.console.print(f"[red]Неизвестная команда: {cmd}. Используйте /help[/red]")

        return True

    # ── Remote management ────────────────────────────────────────────────────

    async def handle_remote(self, arg: str) -> None:
        if arg.lower() == "on":
            if self.remote_mode:
                self.console.print("[yellow]Удалённый режим уже включён[/yellow]")
                return

            server_url = self.config.get("server_url", DEFAULT_SERVER)
            client_name = self.config.get("client_name", platform.node())
            client_id = f"{client_name}-{datetime.now().strftime('%H%M%S')}"

            self.remote_manager = RemoteManager(server_url, client_id, self.console)
            self.console.print(f"[cyan]Подключение к {server_url}...[/cyan]")

            if await self.remote_manager.connect():
                self.remote_mode = True
                self.remote_manager.start_listener(self.client)
                self.console.print(
                    f"[green]✓ Удалённый режим включён (id: {client_id})[/green]"
                )
                self.console.print(
                    "[dim]Вы можете продолжать работу. "
                    "Удалённые запросы обрабатываются в фоне.[/dim]"
                )
            else:
                self.remote_manager = None

        elif arg.lower() == "off":
            if not self.remote_mode:
                self.console.print("[yellow]Удалённый режим не включён[/yellow]")
                return
            if self.remote_manager:
                await self.remote_manager.disconnect()
            self.remote_mode = False
            self.console.print("[green]✓ Удалённый режим выключен[/green]")

        else:
            status_text = "включён" if self.remote_mode else "выключен"
            self.console.print(f"[cyan]Удалённый режим: {status_text}[/cyan]")
            self.console.print("[dim]Использование: /remote on | /remote off[/dim]")

    # ── Main REPL loop ───────────────────────────────────────────────────────

    async def main_loop(self) -> None:
        self.show_banner()

        if not self.config.get("api_key"):
            self.console.print(
                "[yellow]API ключ не настроен. Используйте[/yellow] [cyan]/setup[/cyan]"
            )

        # Auto-connect remote if configured
        if self.config.get("auto_remote"):
            await self.handle_remote("on")

        while True:
            try:
                user_input = Prompt.ask("\n[bold cyan]▶[/bold cyan]")

                if not user_input.strip():
                    continue

                # Handle /commands
                if user_input.startswith("/"):
                    if not await self.handle_command(user_input):
                        break
                    continue

                # Send to Gemini with streaming
                self.console.print()
                response_text = ""

                with self.console.status("[cyan]Думаю...[/cyan]", spinner="dots"):
                    # Collect first chunk to clear the spinner
                    first_chunk = True
                    chunks = []
                    async for chunk in self.client.stream_chat(user_input):
                        chunks.append(chunk)
                        if first_chunk:
                            first_chunk = False
                            break

                # Now render all: first chunk already collected, continue streaming
                full_response = "".join(chunks)
                async for chunk in self.client.stream_chat.__wrapped__(self.client, user_input) if False else []:
                    full_response += chunk

                # Simpler approach: collect full response then render
                if not full_response:
                    # Re-do with simple chat for reliability
                    response_text = ""
                    with self.console.status("[cyan]Думаю...[/cyan]", spinner="dots"):
                        async for chunk in self.client.stream_chat(user_input):
                            response_text += chunk
                    full_response = response_text

                self.render_response(full_response)
                self.console.print()

            except KeyboardInterrupt:
                self.console.print("\n[dim]Нажмите /exit для выхода[/dim]")
            except EOFError:
                break
            except Exception as e:
                self.console.print(f"[red]Ошибка: {e}[/red]")

    async def cleanup(self) -> None:
        """Clean up resources on exit."""
        if self.remote_manager:
            await self.remote_manager.disconnect()


async def main():
    config = Config()
    cli = GeminiCLI(config)

    try:
        await cli.main_loop()
    except KeyboardInterrupt:
        cli.console.print("\n[yellow]До свидания![/yellow]")
    except Exception as e:
        cli.console.print(f"[red]Критическая ошибка: {e}[/red]")
        sys.exit(1)
    finally:
        await cli.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
