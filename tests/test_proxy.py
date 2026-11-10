import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

HEADERS = {'X-API-Key': 'test-proxy-key'}


def test_websocket_registration_ping_and_cleanup(proxy):
    with TestClient(proxy.app) as client:
        with client.websocket_connect('/ws/remote', headers=HEADERS) as ws:
            ws.send_json({'type': 'register', 'client_id': 'workstation'})
            assert ws.receive_json() == {'type': 'registered', 'client_id': 'workstation'}
            response = client.get('/v1/remote/clients', headers=HEADERS)
            assert response.status_code == 200
            assert response.json()['clients'][0]['client_id'] == 'workstation'
            ws.send_json({'type': 'ping'})
            assert ws.receive_json() == {'type': 'pong'}
        assert client.get('/v1/remote/clients', headers=HEADERS).json()['count'] == 0


@pytest.mark.parametrize('headers', [{}, {'X-API-Key': 'incorrect'}])
def test_websocket_rejects_unauthorized_clients(proxy, headers):
    with TestClient(proxy.app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws/remote', headers=headers):
                pass
        assert not proxy.connection_manager.active_connections


@pytest.mark.parametrize('registration', [[], {'type': 'ping'}, {'type': 'register'},
                                          {'type': 'register', 'client_id': []},
                                          {'type': 'register', 'client_id': ' '},
                                          {'type': 'register', 'client_id': 'x' * 129}])
def test_websocket_rejects_malformed_registration(proxy, registration):
    with TestClient(proxy.app) as client:
        with client.websocket_connect('/ws/remote', headers=HEADERS) as ws:
            ws.send_json(registration)
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1002
        assert not proxy.connection_manager.active_connections


def test_duplicate_client_cannot_disconnect_original(proxy):
    with TestClient(proxy.app) as client:
        with client.websocket_connect('/ws/remote', headers=HEADERS) as original:
            original.send_json({'type': 'register', 'client_id': 'same'})
            original.receive_json()
            with client.websocket_connect('/ws/remote', headers=HEADERS) as duplicate:
                duplicate.send_json({'type': 'register', 'client_id': 'same'})
                with pytest.raises(WebSocketDisconnect) as closed:
                    duplicate.receive_json()
                assert closed.value.code == 1008
            original.send_json({'type': 'ping'})
            assert original.receive_json() == {'type': 'pong'}
            assert client.get('/v1/remote/clients', headers=HEADERS).json()['count'] == 1


class FakeSocket:
    client = ('127.0.0.1', 1234)

    def __init__(self):
        self.sent = asyncio.Queue()

    async def send_json(self, message):
        await self.sent.put(message)


async def test_pending_response_is_bound_to_target_client(proxy):
    manager = proxy.ConnectionManager()
    socket = FakeSocket()
    await manager.connect('target', socket)
    task = asyncio.create_task(manager.send_prompt('target', 'hello'))
    message = await socket.sent.get()
    manager.resolve_response('other', message['request_id'], 'forged')
    assert not task.done()
    manager.resolve_response('target', message['request_id'], 'real answer')
    assert await task == 'real answer'
    assert not manager._pending
    assert manager.client_info['target']['status'] == 'idle'


async def test_disconnect_completes_pending_requests_immediately(proxy):
    manager = proxy.ConnectionManager()
    socket = FakeSocket()
    await manager.connect('target', socket)
    task = asyncio.create_task(manager.send_prompt('target', 'hello', timeout=60))
    await socket.sent.get()
    manager.disconnect('target')
    assert await asyncio.wait_for(task, timeout=1) == '[error] Клиент отключился'
    assert not manager._pending


async def test_timeout_and_cancellation_cleanup_pending_state(proxy):
    manager = proxy.ConnectionManager()
    socket = FakeSocket()
    await manager.connect('target', socket)
    assert (await manager.send_prompt('target', 'hello', timeout=0)).startswith('[timeout]')
    assert not manager._pending
    await socket.sent.get()
    task = asyncio.create_task(manager.send_prompt('target', 'hello'))
    await socket.sent.get()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not manager._pending
    assert manager.client_info['target']['status'] == 'idle'


async def test_busy_status_lasts_until_all_requests_complete(proxy):
    manager = proxy.ConnectionManager()
    socket = FakeSocket()
    await manager.connect('target', socket)
    first = asyncio.create_task(manager.send_prompt('target', 'one'))
    one = await socket.sent.get()
    second = asyncio.create_task(manager.send_prompt('target', 'two'))
    two = await socket.sent.get()
    manager.resolve_response('target', one['request_id'], 'one')
    await first
    assert manager.client_info['target']['status'] == 'busy'
    manager.resolve_response('target', two['request_id'], 'two')
    await second
    assert manager.client_info['target']['status'] == 'idle'


def test_dashboard_requires_auth_and_does_not_embed_server_key(proxy):
    with TestClient(proxy.app) as client:
        assert client.get('/dashboard').status_code == 401
        assert client.get('/dashboard?key=incorrect').status_code == 401
        for kwargs in ({'headers': HEADERS}, {'params': {'key': 'test-proxy-key'}}):
            response = client.get('/dashboard', **kwargs)
            assert response.status_code == 200
            assert 'test-proxy-key' not in response.text
            assert response.headers['cache-control'] == 'no-store'
            assert response.headers['referrer-policy'] == 'no-referrer'


def test_dashboard_escapes_client_and_request_text(proxy):
    proxy.connection_manager.client_info['<script>client</script>'] = {
        'connected_at': 'now', 'ip': '127.0.0.1', 'status': 'idle',
        'last_prompt': '<img src=x onerror=alert(1)>',
    }
    proxy.stats.add_request('<script>model</script>', 1)
    with TestClient(proxy.app) as client:
        response = client.get('/dashboard', headers=HEADERS)
    assert '<script>client</script>' not in response.text
    assert '<img src=x onerror=alert(1)>' not in response.text
    assert '<script>model</script>' not in response.text
    assert '&lt;script&gt;client&lt;/script&gt;' in response.text
