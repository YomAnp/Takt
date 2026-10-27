"""Export OpenAPI from the running code without a database connection."""

import json
from pathlib import Path

from takt.app import create_app

target = Path(__file__).resolve().parents[1] / "apps/frontend/.openapi.json"
target.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
