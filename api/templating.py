"""One shared Jinja2 environment, so every router renders with the same filters."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _format_dt(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


templates.env.filters["dt"] = _format_dt
