# Gemini Proxy

A production-quality FastAPI-based proxy server for Google Gemini API with Anthropic Messages API compatibility layer, streaming support, WebSocket remote management, and a web dashboard.

## Features

- **Anthropic Messages API Compatibility**: Drop-in replacement that translates Anthropic format to Gemini format
- **Streaming Support**: Server-Sent Events (SSE) for real-time token streaming
- **WebSocket Remote Management**: Control gemini-cli instances remotely via `/ws/remote`
- **Web Dashboard**: Real-time monitoring of stats, connected clients, and request history
- **Model Mapping**: Automatic translation of Claude model names to Gemini equivalents
- **Request Statistics**: Track total requests, tokens used, and connection history
- **Authentication**: X-API-Key header authentication for all endpoints
- **CORS Support**: Enabled for cross-origin requests
- **Health Checks**: Built-in health check endpoint
- **Systemd Integration**: Easy installation as systemd service with log rotation

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Clients                                  │
│  ├─ gemini-cli (WebSocket)                                  │
│  ├─ HTTP clients (Anthropic format)                          │
│  └─ Direct Gemini API users                                 │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│                  Gemini Proxy                                │
│  ├─ /v1/messages (Anthropic API)                            │
│  ├─ /v1/messages/stream (SSE)                               │
│  ├─ /v1/gemini/generate (Native Gemini)                     │
│  ├─ /ws/remote (WebSocket)                                  │
│  ├─ /dashboard (Web UI)                                      │
│  └─ /health (Health check)                                  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│              Google Gemini API                              │
│  generativelanguage.googleapis.com                          │
└─────────────────────────────────────────────────────────────┘
```

## Requirements

- Python 3.10 or higher
- Linux/macOS (for systemd service)
- Google Gemini API key
- Root access for installation as systemd service

## Installation

### Quick Installation (with systemd)

```bash
git clone https://github.com/art9762/Gemini-Suite.git
cd gemini-suite/gemini-proxy
sudo chmod +x install.sh
sudo ./install.sh
```

The installer will:
- Create a service user `gemini-proxy`
- Install the app to `/opt/gemini-proxy`
- Create configuration at `/etc/gemini-proxy/config.env`
- Install as systemd service
- Set up log rotation

### Manual Installation

```bash
# Create directory
mkdir -p ~/.gemini-proxy
cd ~/.gemini-proxy

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy application
cp /path/to/gemini_proxy.py .

# Create config
mkdir -p config
cat > config/env << 'EOF'
GEMINI_API_KEY=your_api_key_here
PROXY_API_KEY=secret-proxy-key
HOST=0.0.0.0
PORT=8000
EOF

# Run
python3 gemini_proxy.py
```

## Configuration

### Environment Variables

Configuration is done via environment variables. Set them in `/etc/gemini-proxy/config.env` for systemd or export them:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `GEMINI_API_KEY` | Your Google Gemini API key | Yes | - |
| `PROXY_API_KEY` | Proxy authentication key | No | `secret-proxy-key` |
| `HOST` | Server bind address | No | `0.0.0.0` |
| `PORT` | Server port | No | `8000` |

### Getting Your Gemini API Key

1. Visit https://aistudio.google.com/app/apikeys
2. Click "Get API Key" → "Create API Key in new project"
3. Copy the API key
4. Set it in config: `GEMINI_API_KEY=your_key`

### Changing the Proxy API Key

Edit `/etc/gemini-proxy/config.env`:

```bash
sudo nano /etc/gemini-proxy/config.env
```

Change `PROXY_API_KEY` to a secure value:

```bash
PROXY_API_KEY=your-very-secure-key-12345
```

Then restart:

```bash
sudo systemctl restart gemini-proxy
```

## Running as Systemd Service

### Start the Service

```bash
sudo systemctl start gemini-proxy
```

### Enable on Boot

```bash
sudo systemctl enable gemini-proxy
```

### Check Status

```bash
sudo systemctl status gemini-proxy
```

### View Logs

```bash
# Real-time logs
journalctl -u gemini-proxy -f

# Last 100 lines
journalctl -u gemini-proxy -n 100

# By severity
journalctl -u gemini-proxy -p err
```

### Restart the Service

```bash
sudo systemctl restart gemini-proxy
```

## API Documentation

### Authentication

All endpoints require the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-proxy-api-key" http://localhost:8000/health
```

### Endpoints

#### POST /v1/messages

Anthropic Messages API compatible endpoint. Translates request to Gemini format.

**Request:**

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "X-API-Key: your-proxy-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-sonnet",
    "messages": [
      {"role": "user", "content": "What is 2+2?"}
    ],
    "max_tokens": 1024
  }'
```

**Response:**

```json
{
  "id": "msg_abc123",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "2 + 2 = 4"
    }
  ],
  "model": "claude-3-sonnet",
  "usage": {
    "input_tokens": 10,
    "output_tokens": 5
  }
}
```

#### POST /v1/messages/stream

Streaming endpoint using Server-Sent Events (SSE).

**Request:**

```bash
curl -X POST http://localhost:8000/v1/messages/stream \
  -H "X-API-Key: your-proxy-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-sonnet",
    "messages": [
      {"role": "user", "content": "Write a poem about code"}
    ]
  }'
```

**Response (SSE Stream):**

```
data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Code flows"}}

data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " like rivers"}}

data: {"type": "message_stop", "message": {...}}
```

#### POST /v1/gemini/generate

Native Gemini API endpoint (pass-through).

**Request:**

```bash
curl -X POST http://localhost:8000/v1/gemini/generate \
  -H "X-API-Key: your-proxy-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [
      {"role": "user", "parts": [{"text": "Hello"}]}
    ]
  }'
```

#### WebSocket /ws/remote

WebSocket endpoint for remote CLI management.

**Protocol:**

1. Client connects to `/ws/remote`
2. Client sends registration: `{"type": "register", "client_id": "cli-123"}`
3. Server can send prompts: `{"type": "prompt", "prompt": "Your task"}`
4. Client sends responses: `{"type": "response", "response": "Result"}`

**Example (Python):**

```python
import asyncio
import json
import websockets

async def main():
    async with websockets.connect('ws://localhost:8000/ws/remote') as ws:
        # Register
        await ws.send(json.dumps({"type": "register", "client_id": "cli-123"}))

        # Receive prompt
        message = await ws.recv()
        print(f"Received: {message}")

        # Send response
        await ws.send(json.dumps({"type": "response", "response": "Done"}))

asyncio.run(main())
```

#### GET /dashboard

Web dashboard with real-time statistics.

Navigate to: `http://localhost:8000/dashboard?key=your-proxy-api-key`

Or pass X-API-Key header:

```bash
curl -H "X-API-Key: your-proxy-api-key" http://localhost:8000/dashboard
```

**Features:**
- Real-time request stats
- Connected clients list
- Request history
- Auto-refreshes every 5 seconds

#### GET /health

Health check endpoint.

**Request:**

```bash
curl -H "X-API-Key: your-proxy-api-key" http://localhost:8000/health
```

**Response:**

```json
{
  "status": "ok",
  "version": "1.0.0",
  "gemini_api_configured": true,
  "connected_clients": 2
}
```

#### GET /

Root endpoint with API information.

```bash
curl -H "X-API-Key: your-proxy-api-key" http://localhost:8000/
```

## Model Mapping

The proxy automatically maps Anthropic Claude model names to Gemini models:

| Anthropic Model | Gemini Model |
|-----------------|--------------|
| claude-3-opus | gemini-1.5-pro |
| claude-3-sonnet | gemini-1.5-flash |
| claude-3-haiku | gemini-2.0-flash |
| claude-3.5-sonnet | gemini-1.5-pro |
| gemini-1.5-pro | gemini-1.5-pro |
| gemini-1.5-flash | gemini-1.5-flash |
| gemini-2.0-flash | gemini-2.0-flash |

## Performance

- **Streaming**: Tokens appear in real-time via SSE
- **Async I/O**: Non-blocking operations throughout
- **Connection Pooling**: Reuses HTTP connections via httpx
- **Timeout**: 60 seconds for API calls
- **WebSocket**: Async WebSocket implementation

## Security

### Configuration Security

- Store `config.env` securely (mode 600)
- Never commit config with API keys to version control
- Use strong `PROXY_API_KEY` values
- Consider using environment-specific keys

### Network Security

- Use WSS (WebSocket Secure) in production: `wss://your-domain.com/ws/remote`
- Implement HTTPS via reverse proxy (nginx, etc.)
- Restrict API access via firewall rules
- Use VPN or private networks for sensitive deployments

### Systemd Hardening

The provided systemd unit includes:
- `NoNewPrivileges=true` - Prevents privilege escalation
- `PrivateTmp=true` - Isolated temp directory
- `ProtectSystem=strict` - Read-only filesystem
- `ProtectHome=true` - No access to home directory
- `ReadWritePaths=/var/log/gemini-proxy` - Minimal write access

## Troubleshooting

### Service Won't Start

Check logs:

```bash
journalctl -u gemini-proxy -n 50
```

Common issues:
- `GEMINI_API_KEY` not set
- Port already in use (change `PORT` in config)
- Permission issues (check ownership with `ls -l /opt/gemini-proxy`)

### "API key not configured"

```bash
sudo nano /etc/gemini-proxy/config.env
```

Set `GEMINI_API_KEY` to your actual API key from https://aistudio.google.com/app/apikeys

### Port Already in Use

Check what's using the port:

```bash
sudo lsof -i :8000
```

Change the port in `/etc/gemini-proxy/config.env`:

```bash
PORT=8080
```

### Dashboard Not Loading

1. Check service is running: `sudo systemctl status gemini-proxy`
2. Verify X-API-Key header is correct
3. Check firewall: `sudo ufw allow 8000/tcp`

### WebSocket Connection Failed

1. Verify proxy is accessible: `curl http://localhost:8000/health`
2. Check WebSocket endpoint: `wscat -c ws://localhost:8000/ws/remote --header "X-API-Key: key"`
3. Verify `PROXY_API_KEY` matches client

## Integration with gemini-cli

Configure gemini-cli to use your proxy:

```bash
gemini-cli
You > /setup
Enter your Gemini API key: (skip if using proxy)

You > /config
# Edit ~/.gemini-cli/config.json to set server_url
"server_url": "ws://proxy-server:8000/ws/remote"

You > /remote on
# Connect to your proxy
```

## Examples

### Using with Python

```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/v1/messages",
        json={
            "model": "claude-3-sonnet",
            "messages": [{"role": "user", "content": "Hello!"}],
            "max_tokens": 100
        },
        headers={"X-API-Key": "your-proxy-api-key"}
    )
    print(response.json())
```

### Using with curl

```bash
curl -X POST http://localhost:8000/v1/messages \
  -H "X-API-Key: your-proxy-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-sonnet",
    "messages": [{"role": "user", "content": "What is Python?"}],
    "max_tokens": 1024
  }'
```

### Streaming with curl

```bash
curl -X POST http://localhost:8000/v1/messages/stream \
  -H "X-API-Key: your-proxy-api-key" \
  -H "Content-Type: application/json" \
  -N \
  -d '{
    "model": "claude-3-sonnet",
    "messages": [{"role": "user", "content": "Write code"}]
  }'
```

## Performance Tuning

### Increase Worker Count

For production, use multiple uvicorn workers:

Edit `/etc/systemd/system/gemini-proxy.service`:

```ini
ExecStart=/opt/gemini-proxy/venv/bin/python3 -m uvicorn \
  gemini_proxy:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4
```

### Use a Reverse Proxy

```nginx
upstream gemini_proxy {
    server localhost:8000;
}

server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://gemini_proxy;
        proxy_set_header X-API-Key $http_x_api_key;
        proxy_set_header Host $host;
    }

    location /ws/remote {
        proxy_pass http://gemini_proxy;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## License

MIT License - See LICENSE file for details

## Support

For issues or feature requests, visit the project repository.

## Version History

### v1.0.0 (Current)
- Initial release
- Anthropic Messages API compatibility
- Streaming support via SSE
- WebSocket remote management
- Web dashboard
- Model mapping
- Request statistics
- Systemd service integration
