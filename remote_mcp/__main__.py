"""CLI entry point: python -m remote_mcp --host <name>"""
import argparse
import asyncio
import sys

from .server import main as server_main


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="remote-mcp",
        description="MCP server proxying tools to a remote Linux host over SSH",
    )
    parser.add_argument(
        "--host", required=True,
        help="Host name from config.yaml to connect to",
    )
    parser.add_argument(
        "--config", default="~/.config/remote-mcp/config.yaml",
        help="Path to config.yaml (default: ~/.config/remote-mcp/config.yaml)",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Connect, smoke-test, then exit (no stdio loop)",
    )
    args = parser.parse_args()

    if args.test:
        from .config import load_config
        from .connection import SSHConnection
        root = load_config(args.config)
        host_cfg = root.hosts[args.host]
        jump_cfg = root.hosts.get(host_cfg.jump_host) if host_cfg.jump_host else None
        conn = SSHConnection(host_cfg, jump_config=jump_cfg)
        conn.connect()
        try:
            r = conn.exec("echo OK")
            if r.stdout.strip() == "OK":
                print(f"Connected to {args.host} ({host_cfg.user}@{host_cfg.hostname}). All tools: OK")
                sys.exit(0)
            else:
                print(f"Connected but echo failed: {r.stdout!r}")
                sys.exit(1)
        finally:
            conn.close()

    asyncio.run(server_main(args.host, args.config))


if __name__ == "__main__":
    cli()
