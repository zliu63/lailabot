# LailaBot

Telegram bot that wraps Claude Code, letting you interact with your local Claude Code sessions from anywhere via Telegram.

## Prerequisites

- Python 3.11+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed and available in PATH
- A Telegram bot token (create one via [BotFather](https://t.me/BotFather))
- Your Telegram user ID (you can get it from [@userinfobot](https://t.me/userinfobot))

## Installation

```bash
git clone https://github.com/zliu63/lailabot.git
cd lailabot
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configuration

LailaBot uses two environment variables:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_USER_ID` | Your Telegram numeric user ID (only this user can control the bot) |

## Running manually

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export TELEGRAM_USER_ID="987654321"
python -m lailabot
```

## Running as a launchd daemon

### Setup

1. Create the log directory:

```bash
mkdir -p ~/.lailabot/logs
```

2. Edit `com.lailabot.plist` and replace `YOUR_BOT_TOKEN_HERE` and `YOUR_USER_ID_HERE` with your actual values. Also verify that the `ProgramArguments` and `WorkingDirectory` paths match your installation.

3. Copy the plist to LaunchAgents:

```bash
cp com.lailabot.plist ~/Library/LaunchAgents/
```

4. Load the daemon:

```bash
launchctl load ~/Library/LaunchAgents/com.lailabot.plist
```

LailaBot will now start automatically on login and restart if it crashes.

### Checking status

```bash
launchctl list | grep lailabot
```

### Viewing logs

```bash
tail -f ~/.lailabot/logs/lailabot.log
tail -f ~/.lailabot/logs/stdout.log
```

### Stopping the daemon

```bash
launchctl unload ~/Library/LaunchAgents/com.lailabot.plist
```

### Removing the daemon

```bash
launchctl unload ~/Library/LaunchAgents/com.lailabot.plist
rm ~/Library/LaunchAgents/com.lailabot.plist
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/new {path}` | Start a Claude Code session in the given directory |
| `/ls [path]` | List directory contents (defaults to home directory) |
| `/list` | List all active sessions |
| `/kill {id}` | Kill a session |
| `/set_default {id}` | Switch the default session |
| `/send {id} {message}` | Send a message to a specific session |

Plain text messages are forwarded to the default session.

## Running tests

```bash
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
```
