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

## Remote Approval (Permission Requests)

When Claude Code needs permission to run a tool (e.g. execute a Bash command, write a file), LailaBot can forward the request to Telegram so you can approve or deny it remotely.

### How it works

1. Claude Code triggers a `PreToolUse` hook before executing a tool
2. The hook script (`lailabot-approval-hook`) forwards the request to LailaBot via a Unix socket
3. LailaBot sends you a Telegram message with **Approve** / **Deny** buttons
4. You tap a button, and the decision is sent back to Claude Code

### Setup

**Step 1: Install lailabot** (this also installs the `lailabot-approval-hook` command)

```bash
pip install -e .
```

Verify the hook script is available:

```bash
which lailabot-approval-hook
```

**Step 2: Configure Claude Code hooks**

Add the following to your **global** Claude Code settings at `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "lailabot-approval-hook",
            "timeout": 600
          }
        ]
      }
    ]
  }
}
```

> **Tip:** If you only want approval for dangerous tools, change `"matcher": ""` to `"matcher": "Bash|Write|Edit"`. An empty matcher matches all tools.

**Step 3: (Optional) Custom socket path**

By default the approval server listens on `/tmp/lailabot-approval.sock`. To change it, set `LAILABOT_SOCKET` in your environment:

```bash
export LAILABOT_SOCKET="/tmp/my-custom.sock"
```

Both LailaBot and the hook script read this variable.

If you use the launchd daemon, add it to the `EnvironmentVariables` section of `com.lailabot.plist`.

### Verifying

1. Start LailaBot (manually or via launchd)
2. Open a Claude Code session that triggers a tool (e.g. ask it to run a command)
3. You should receive a Telegram message like:

```
Permission Request

Tool: Bash
Input:
{
  "command": "ls -la"
}

[Approve] [Deny]
```

4. Tap **Approve** or **Deny** — Claude Code will proceed or abort accordingly

### Troubleshooting

- **Hook not triggered**: Make sure `~/.claude/settings.json` has the `hooks` config and restart Claude Code
- **Hook fails to connect**: Check that LailaBot is running and the socket file exists (`ls /tmp/lailabot-approval.sock`)
- **No Telegram message**: Check LailaBot logs (`~/.lailabot/logs/lailabot.log`)
- **Test the hook manually**:
  ```bash
  # Start LailaBot first, then in another terminal:
  echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | lailabot-approval-hook
  ```
  You should see an approval message in Telegram. After you tap Approve/Deny, the command will print the decision JSON.

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
