"""Print a free TCP port on 127.0.0.1, starting at the preferred one.

Used by `make dev` so the web app still starts when another app holds port 3000.
Usage: python scripts/pick_port.py PREFERRED [--strict]
  --strict: the port was chosen explicitly (WEB_PORT=...): fail instead of moving on.
"""

from __future__ import annotations

import socket
import sys


def free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def main() -> None:
    preferred = int(sys.argv[1])
    strict = "--strict" in sys.argv
    for port in range(preferred, preferred + (1 if strict else 20)):
        if free(port):
            if port != preferred:
                print(f"Port {preferred} is in use by another app; using {port}.", file=sys.stderr)
            print(port)
            return
    print(f"Port {preferred} is in use. Pick another, e.g. make dev WEB_PORT={preferred + 1}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
