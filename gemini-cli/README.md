# Gemini CLI

A production-quality CLI tool powered by Google Gemini API, similar to Claude Code. Features an interactive REPL chat interface with multi-turn conversations, syntax-highlighted output, file editing capabilities, and remote management through proxy server integration.

## Features

- **Interactive REPL Chat Interface**: Multi-turn conversations with full context maintained across messages
- **Streaming Responses**: Real-time token streaming from Gemini API with spinners
- **Syntax-Highlighted Code**: Beautiful code output using the Rich library with language detection
- **File Editing**: Ask the AI to suggest file edits and apply them directly
- **Shell Command Execution**: Execute shell commands with user confirmation prompts
- **Remote Management**: Connect to gemini-proxy server via WebSocket for remote control
- **Configuration Management**: Store API keys and preferences in `~/.gemini-cli/config.json`
- **Model Switching**: Easily switch between different Gemini models
- **Markdown Support**: Responses rendered with full markdown formatting

## Requirements

- Python 3.10 or higher
- Linux/macOS (Windows support via WSL)
- Google Gemini API key (free tier available at https://aistudio.google.com/app/apikeys)

## Installation

### Automatic Installation

```bash
git clone https://github.com/art9762/Gemini-Suite.git
cd gemini-suite/gemini-cli
chmod +x install.sh
./install.sh
```

The installer will:
- Verify Python 3.10+ is installed
- Create a virtual environment at `~/.gemini-cli/venv`
- Install all required dependencies
- Create a wrapper script at `/usr/local/bin/gemini-cli`
- Create a default configuration file

### Manual Installation

```bash
python3 -m venv ~/.gemini-cli/venv
source ~/.gemini-cli/venv/bin/activate
pip install -r requirements.txt
cp gemini_cli.py ~/.gemini-cli/
deactivate
```

Then create `/usr/local/bin/gemini-cli`:

```bash
#!/bin/bash
source "$HOME/.gemini-cli/venv/bin/activate"
python3 "$HOME/.gemini-cli/gemini_cli.py" "$@"
```

## Configuration

Configuration is stored in `~/.gemini-cli/config.json`:

```json
{
  "api_key": "YOUR_GEMINI_API_KEY",
  "model": "gemini-1.5-pro",
  "server_url": "ws://localhost:8000/ws/remote",
  "remote_enabled": false,
  "timeout": 30
}
```

### Getting Your API Key

1. Go to https://aistudio.google.com/app/apikeys
2. Click "Get API Key" → "Create API Key in new project"
3. Copy the API key
4. In Gemini CLI, run `/setup` and paste your key

## Usage

### Starting the CLI

```bash
gemini-cli
```

You'll see the interactive prompt:

```
╔════════════════════════════════════════╗
║         Gemini CLI v1.0                 ║
║   Powered by Google Gemini API         ║
╚════════════════════════════════════════╝

Type /help for commands • Ctrl+C to exit
You >
```

### Commands

#### General Commands

| Command | Description |
|---------|-------------|
| `/help` | Display help and list of all commands |
| `/clear` | Clear conversation history |
| `/exit` | Exit the application |
| `/config` | Show current configuration |
| `/setup` | Configure your API key interactively |

#### Model Management

| Command | Description |
|---------|-------------|
| `/model <name>` | Switch to a different Gemini model |
| `/model` | Show currently active model |

Available models:
- `gemini-1.5-pro` - Most capable model (default)
- `gemini-1.5-flash` - Fast and efficient
- `gemini-2.0-flash` - Latest flash model
- `gemini-pro` - Legacy model

Example:
```
You > /model gemini-1.5-flash
✓ Model switched to gemini-1.5-flash
```

#### Remote Management

| Command | Description |
|---------|-------------|
| `/remote on` | Connect to proxy server for remote control |
| `/remote off` | Disconnect from remote server |

### Regular Chat

Simply type your message and press Enter:

```
You > Explain quantum computing in simple terms
```

The response will be streamed in real-time with syntax highlighting for code blocks.

### File Editing

Ask the AI to edit files:

```
You > Edit my_script.py to add a function that prints "Hello World"
```

The AI will suggest changes, which you can then apply.

### Shell Commands

Execute shell commands with confirmation:

```
You > execute: ls -la /tmp
Execute command: ls -la /tmp? [y/n]: y
```

## Remote Mode

Remote mode allows you to control the CLI from a gemini-proxy server via WebSocket.

### Setup

1. Start the gemini-proxy server (see gemini-proxy README)
2. In your Gemini CLI session:

```
You > /remote on
Connecting to ws://localhost:8000/ws/remote...
✓ Remote mode enabled
```

3. You can now send prompts to this CLI from the proxy dashboard or other clients

### How It Works

- CLI connects to proxy server via WebSocket
- Registers itself with a unique client ID
- Waits for prompt messages from the proxy
- Sends responses back to the proxy
- All communication is JSON-based

## Architecture

### Config Class

Manages configuration stored in `~/.gemini-cli/config.json`:
- Loads/saves configuration
- Provides defaults
- Supports get/set operations

### GeminiClient Class

Async client for Gemini API:
- Maintains conversation history for multi-turn chats
- Handles streaming responses
- Manages API requests with proper error handling
- Supports multiple models

### RemoteManager Class

Manages WebSocket connection to proxy server:
- Handles connection lifecycle
- Sends registration message
- Receives prompts from proxy
- Sends responses back

### GeminiCLI Class

Main application:
- REPL loop with rich prompt
- Command handling
- Response processing with syntax highlighting
- Spinner animations during API calls

## Dependencies

- **httpx** - Async HTTP client for Gemini API
- **websockets** - WebSocket client for remote management
- **rich** - Beautiful terminal UI with syntax highlighting
- **aiofiles** - Async file I/O operations

## Performance

- Streaming responses: Tokens appear in real-time
- Async operations: Non-blocking I/O throughout
- Configurable timeout: Default 30 seconds (adjustable in config)
- Efficient memory usage: Conversation history managed per session

## Troubleshooting

### "API key not configured"

```
You > /setup
```

Enter your Gemini API key from https://aistudio.google.com/app/apikeys

### "Request timeout"

Increase timeout in `~/.gemini-cli/config.json`:

```json
{
  "timeout": 60
}
```

### "Failed to connect to remote"

Ensure gemini-proxy is running:

```bash
# Start proxy server
python3 /opt/gemini-proxy/gemini_proxy.py

# Or via systemd
sudo systemctl start gemini-proxy
```

### "ModuleNotFoundError"

Reinstall dependencies:

```bash
source ~/.gemini-cli/venv/bin/activate
pip install --upgrade -r requirements.txt
```

## Security

- API keys are stored locally in `~/.gemini-cli/config.json`
- Configure file permissions: `chmod 600 ~/.gemini-cli/config.json`
- Never commit config file with API key to version control
- API calls go directly to Google's servers
- WebSocket connection can use WSS for secure remote mode

## Examples

### Example 1: Simple Question

```
You > What are the benefits of async/await in Python?
```

### Example 2: Code Generation

```
You > Write a Python function to calculate fibonacci numbers up to n

Gemini will generate code with syntax highlighting
```

### Example 3: Multi-turn Conversation

```
You > How do decorators work in Python?
Gemini > Decorators are functions that modify other functions...

You > Can you show me a practical example?
Gemini > Here's a practical example of a timing decorator...

You > How can I use this with async functions?
Gemini > With async functions, you need to be careful about...
```

### Example 4: Remote Control

```
Terminal 1: gemini-cli
You > /remote on
✓ Remote mode enabled

Terminal 2: curl -X POST http://localhost:8000/v1/messages \
  -H "X-API-Key: secret-key" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Say hello"}]}'

Terminal 1: Remote prompt: Say hello
✓ Response sent to server
```

## License

MIT License - See LICENSE file for details

## Support

For issues, feature requests, or contributions, visit the project repository.

## Version History

### v1.0.0 (Current)
- Initial release
- Core REPL functionality
- Streaming responses
- Remote management
- Configuration management
- Multi-turn conversations

## Author

Developed as a production-quality CLI alternative to Claude Code, powered by Google Gemini API.
