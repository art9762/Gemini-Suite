import asyncio
import io
import json
import os
from unittest.mock import AsyncMock

import httpx
import pytest
from rich.console import Console


def sse(text):
    return 'data: ' + json.dumps({
        'candidates': [{'content': {'parts': [{'text': text}]}}]
    }) + '\n\n'


async def test_repl_renders_entire_stream_once(cli, monkeypatch):
    app = cli.GeminiCLI(cli.Config())
    app.console = Console(file=io.StringIO())
    monkeypatch.setattr(app, 'ask', AsyncMock(side_effect=['hello', '/exit']))
    requested = []

    async def stream(prompt):
        requested.append(prompt)
        for chunk in ['Hello', ', ', 'world!']:
            yield chunk

    monkeypatch.setattr(app.client, 'stream_chat', stream)
    rendered = []
    monkeypatch.setattr(app, 'render_response', rendered.append)
    await asyncio.wait_for(app.main_loop(), timeout=2)
    assert requested == ['hello']
    assert rendered == ['Hello, world!']


async def test_stream_commits_complete_turn_and_reuses_it(cli, mock_gemini):
    payloads = []

    def respond(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, text=sse('Hello') + sse(' world'))

    mock_gemini(respond)
    client = cli.GeminiClient('dummy-key', 'dummy-model')
    assert ''.join([chunk async for chunk in client.stream_chat('first')]) == 'Hello world'
    assert [message['role'] for message in client.conversation_history] == ['user', 'model']
    assert ''.join([chunk async for chunk in client.stream_chat('second')]) == 'Hello world'
    assert [message['role'] for message in payloads[1]['contents']] == ['user', 'model', 'user']
    assert payloads[1]['contents'][1]['parts'] == [{'text': 'Hello world'}]


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('failure', ['http', 'empty', 'network'])
async def test_failed_turns_do_not_poison_history(cli, mock_gemini, stream, failure):
    def respond(request):
        if failure == 'network':
            raise httpx.ConnectError('synthetic connection failure', request=request)
        if failure == 'http':
            return httpx.Response(429, text='rate limited')
        return httpx.Response(200, json={'candidates': []})

    mock_gemini(respond)
    client = cli.GeminiClient('dummy-key', 'dummy-model')
    previous = [
        {'role': 'user', 'parts': [{'text': 'before'}]},
        {'role': 'model', 'parts': [{'text': 'answer'}]},
    ]
    client.conversation_history = previous.copy()
    if stream:
        assert [chunk async for chunk in client.stream_chat('retry me')]
    else:
        _, success = await client.chat('retry me')
        assert not success
    assert client.conversation_history == previous


async def test_concurrent_local_and_remote_turns_are_serialized(cli, mock_gemini):
    payloads = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def respond(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            first_started.set()
            await release_first.wait()
        return httpx.Response(200, json={
            'candidates': [{'content': {'parts': [{'text': 'answer'}]}}]
        })

    mock_gemini(respond)
    client = cli.GeminiClient('dummy-key', 'dummy-model')
    first = asyncio.create_task(client.chat('local'))
    await first_started.wait()
    second = asyncio.create_task(client.chat('remote'))
    await asyncio.sleep(0)
    assert len(payloads) == 1
    release_first.set()
    assert await first == ('answer', True)
    assert await second == ('answer', True)
    assert [message['role'] for message in payloads[1]['contents']] == ['user', 'model', 'user']


def test_config_keys_are_private_and_masked(cli):
    config = cli.Config()
    config.set('api_key', 'test-google-key')
    config.set('proxy_api_key', 'test-proxy-key')
    assert os.stat(config.config_file).st_mode & 0o777 == 0o600
    assert os.stat(config.config_dir).st_mode & 0o777 == 0o700
    app = cli.GeminiCLI(config)
    output = io.StringIO()
    app.console = Console(file=output)
    app.show_config()
    assert 'test-google-key' not in output.getvalue()
    assert 'test-proxy-key' not in output.getvalue()


async def test_remote_requires_key_before_connecting(cli, monkeypatch):
    connect = AsyncMock()
    monkeypatch.setattr(cli, 'websocket_connect', connect)
    remote = cli.RemoteManager('ws://localhost/ws/remote', 'client', Console(file=io.StringIO()))
    assert not await remote.connect()
    connect.assert_not_called()


async def test_remote_reconnect_after_listener_disconnect(cli, monkeypatch):
    app = cli.GeminiCLI(cli.Config())
    app.console = Console(file=io.StringIO())
    app.remote_mode = True
    old = cli.RemoteManager('ws://localhost/ws/remote', 'old', app.console)
    old.connected = False
    app.remote_manager = old
    monkeypatch.setattr(cli.RemoteManager, 'connect', AsyncMock(return_value=True))
    monkeypatch.setattr(cli.RemoteManager, 'start_listener', lambda *args: None)
    await app.handle_remote('on')
    assert app.remote_manager is not old
    assert app.remote_mode


async def test_cancelled_stream_keeps_history_unchanged(cli, mock_gemini):
    mock_gemini(lambda request: httpx.Response(200, text=sse('partial') + sse('answer')))
    client = cli.GeminiClient('dummy-key', 'dummy-model')
    stream = client.stream_chat('cancel this')
    assert await anext(stream) == 'partial'
    await stream.aclose()
    assert client.conversation_history == []
    assert not client._conversation_lock.locked()


async def test_cancelled_stream_closes_upstream_immediately(cli, mock_gemini):
    closed = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse('partial').encode()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    mock_gemini(lambda request: httpx.Response(200, stream=Stream()))
    client = cli.GeminiClient('dummy-key', 'dummy-model')
    stream = client.stream_chat('cancel this')
    assert await anext(stream) == 'partial'
    await stream.aclose()
    assert closed.is_set()
    assert client.conversation_history == []
