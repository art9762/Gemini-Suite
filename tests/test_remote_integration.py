"""Exercise the real local HTTP/WebSocket path; Gemini is always mocked."""
import asyncio
import io
import socket
from unittest.mock import AsyncMock

import httpx
import pytest
import uvicorn
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console


async def wait_until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout=5)


@pytest.fixture
async def local_proxy(proxy):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        proxy.app, log_level='error', lifespan='off', ws='wsproto',
    ))
    # Avoid installing process signal handlers in a test server.
    async def serve():
        await server._serve(sockets=[listener])
    task = asyncio.create_task(serve())
    try:
        await wait_until(lambda: server.started or task.done())
        if task.done():
            await task
        yield f'http://127.0.0.1:{port}', f'ws://127.0.0.1:{port}/ws/remote'
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        listener.close()


async def test_remote_request_is_processed_while_real_repl_waits_for_input(cli, proxy, local_proxy):
    http_url, ws_url = local_proxy
    config = cli.Config()
    config.data.update(api_key='dummy-google-key', proxy_api_key='test-proxy-key',
                       server_url=ws_url, auto_remote=True)
    app = cli.GeminiCLI(config)
    app.console = Console(file=io.StringIO())
    app.client.chat = AsyncMock(return_value=('synthetic Gemini answer', True))
    waiting = asyncio.Event()
    real_ask = app.ask

    async def ask(message, **kwargs):
        waiting.set()
        return await real_ask(message, **kwargs)

    app.ask = ask
    with create_pipe_input() as pipe:
        app._prompt_session = PromptSession(input=pipe, output=DummyOutput())
        task = asyncio.create_task(app.main_loop())
        try:
            await asyncio.wait_for(waiting.wait(), timeout=5)
            async with httpx.AsyncClient(base_url=http_url, headers={'X-API-Key': 'test-proxy-key'}) as http:
                clients = (await http.get('/v1/remote/clients')).json()['clients']
                assert len(clients) == 1
                response = await http.post('/v1/remote/send', json={
                    'client_id': clients[0]['client_id'], 'prompt': 'remote task', 'timeout': 2,
                })
            assert response.status_code == 200
            assert response.json()['response'] == 'synthetic Gemini answer'
            app.client.chat.assert_awaited_once_with('remote task')
            assert not task.done(), 'REPL should still be waiting for local input'
            pipe.send_text('/exit\n')
            await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await app.cleanup()
    await wait_until(lambda: not proxy.connection_manager.active_connections)
    assert not proxy.connection_manager._pending


async def test_real_remote_rejects_bad_key(cli, local_proxy):
    _, ws_url = local_proxy
    manager = cli.RemoteManager(ws_url, 'unauthorized', Console(file=io.StringIO()), 'wrong-key')
    assert not await manager.connect()
    assert not manager.connected
    assert manager.ws is None


async def test_async_terminal_prompt_can_be_cancelled(cli):
    app = cli.GeminiCLI(cli.Config())
    with create_pipe_input() as pipe:
        app._prompt_session = PromptSession(input=pipe, output=DummyOutput())
        task = asyncio.create_task(app.ask('waiting: '))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
