#!/usr/bin/env python3
"""
Entry point for the Accessibility MCP Server.

Run with: python run_server.py
Or: ./venv/bin/python run_server.py
"""

import asyncio
from src.mcp_server import main

if __name__ == "__main__":
    asyncio.run(main())
