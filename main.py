"""
Entry point for the automated follow-up system.

Run with: python main.py
Or with uv: uv run python main.py
"""

import asyncio
from app.main import main


if __name__ == "__main__":
    asyncio.run(main())
