"""Entry point for gunicorn: `gunicorn wsgi:app`."""
from dotenv import load_dotenv

load_dotenv()

from gateway.app import create_app  # noqa: E402

app = create_app()
