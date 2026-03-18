"""Standalone script called by Claude Code's PreToolUse hook.

Reads the hook request JSON from stdin, forwards it to the LailaBot
approval server via Unix socket, and writes the decision to stdout.
"""

import json
import os
import socket
import sys


DEFAULT_SOCKET_PATH = "/tmp/lailabot-approval.sock"


def main():
    socket_path = os.environ.get("LAILABOT_SOCKET", DEFAULT_SOCKET_PATH)

    request = sys.stdin.read()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(660)  # Slightly longer than server-side timeout
    sock.connect(socket_path)

    sock.sendall(request.encode() + b"\n")

    response = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        response += chunk

    sock.close()

    sys.stdout.write(response.decode())


if __name__ == "__main__":
    main()
