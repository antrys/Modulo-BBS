#!/usr/bin/env python3
"""
NetRunner BBS - Entry Point
Run the server: python run_server.py
Run with options: python run_server.py --host 0.0.0.0 --port 6400 --nodes 16
"""

import asyncio
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server.server import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
