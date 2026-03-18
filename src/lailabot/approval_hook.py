"""Standalone script called by Claude Code's PreToolUse hook.

Reads the hook request JSON from stdin, forwards it to the LailaBot
approval server via Unix socket, and writes the decision to stdout.
"""

import json
import os
import socket
import sys


DEFAULT_SOCKET_PATH = "/tmp/lailabot-approval.sock"
LOG_PATH = os.path.expanduser("~/.lailabot/logs/approval_hook.log")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main():
    # Only intercept Claude Code sessions started by LailaBot
    if not os.environ.get("LAILABOT_SESSION"):
        sys.exit(0)

    socket_path = os.environ.get("LAILABOT_SOCKET", DEFAULT_SOCKET_PATH)

    raw = sys.stdin.read()
    log(f"--- Hook invoked ---")
    log(f"Socket: {socket_path}")
    log(f"Stdin length: {len(raw)}")
    log(f"Stdin: {raw[:500]}")

    try:
        parsed = json.loads(raw)
        request_line = json.dumps(parsed)
    except json.JSONDecodeError as e:
        log(f"JSON parse error: {e}")
        sys.exit(2)

    log(f"Tool: {parsed.get('tool_name', '?')}")
    log(f"Connecting to {socket_path}...")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(660)

    try:
        sock.connect(socket_path)
    except Exception as e:
        log(f"Connect failed: {e}, falling through to default behavior")
        # Can't reach LailaBot — exit 0 with no output so Claude Code
        # falls through to its normal permission prompt
        sys.exit(0)

    log("Connected, sending request...")
    sock.sendall(request_line.encode() + b"\n")
    sock.shutdown(socket.SHUT_WR)
    log("Request sent, waiting for response...")

    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk

    sock.close()

    log(f"Response length: {len(response)}")
    log(f"Response: {response[:500]}")

    sys.stdout.write(response.decode())
    log("Done, wrote to stdout")


if __name__ == "__main__":
    main()
