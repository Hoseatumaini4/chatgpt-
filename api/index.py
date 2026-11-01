"""Vercel entry point."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from gateway.app import create_app  # noqa: E402

app = create_app()
