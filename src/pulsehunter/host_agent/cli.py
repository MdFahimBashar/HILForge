"""Run the Windows host agent as an ordinary user process outside Docker."""

from __future__ import annotations

import argparse
import sys

import uvicorn
from pydantic import ValidationError

from pulsehunter.host_agent.config import HostAgentSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pulsehunter-host-agent")
    parser.add_argument("--server", required=True, help="PulseHunter API base URL")
    parser.add_argument("--public-url", required=True, help="LAN URL of this laptop on port 9000")
    parser.add_argument("--name", required=True, help="stable device name shown in PulseHunter")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("pulsehunter-host-agent runs only on Windows", file=sys.stderr)
        return 2
    try:
        settings = HostAgentSettings(
            name=args.name,
            server_url=args.server,
            public_url=args.public_url,
        )
    except ValidationError as exc:
        print(f"Invalid host agent configuration: {exc.errors()[0]['msg']}", file=sys.stderr)
        return 2

    from pulsehunter.host_agent.app import create_app

    uvicorn.run(create_app(settings), host="0.0.0.0", port=9000, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
