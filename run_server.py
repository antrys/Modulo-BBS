#!/usr/bin/env python3
"""
NetRunner BBS - Entry Point
Run the server: python run_server.py
Run with options: python run_server.py --host 0.0.0.0 --port 6400 --ssh-port 6422 --nodes 16
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.app import BBSApp
from core.loader import PluginLoader
from server.server import BBSServer


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    host = "127.0.0.1"
    port = 6400
    ssh_port = 6422
    max_nodes = 8
    plain_text = False
    enable_ssh = False

    if '--port' in sys.argv:
        idx = sys.argv.index('--port')
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    if '--host' in sys.argv:
        idx = sys.argv.index('--host')
        if idx + 1 < len(sys.argv):
            host = sys.argv[idx + 1]

    if '--nodes' in sys.argv:
        idx = sys.argv.index('--nodes')
        if idx + 1 < len(sys.argv):
            max_nodes = int(sys.argv[idx + 1])

    if '--plain' in sys.argv:
        plain_text = True

    if '--ssh' in sys.argv:
        enable_ssh = True

    if '--ssh-port' in sys.argv:
        idx = sys.argv.index('--ssh-port')
        if idx + 1 < len(sys.argv):
            ssh_port = int(sys.argv[idx + 1])
            enable_ssh = True

    # Build the core application object, load plugins, then wire the server.
    bbs = BBSApp(max_nodes=max_nodes)
    bbs.plugins = await PluginLoader().load(bbs)

    server = BBSServer(bbs=bbs, host=host, port=port, plain_text=plain_text)

    # Start SSH server if requested
    tasks = [server.start()]
    if enable_ssh:
        from server.ssh_server import start_ssh_server
        tasks.append(start_ssh_server(server, host=host, port=ssh_port))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
