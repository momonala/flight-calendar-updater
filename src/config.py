import os
import tomllib
from pathlib import Path

import typer
from dotenv import load_dotenv

load_dotenv()

_config_file = Path(__file__).parent.parent / "pyproject.toml"
with _config_file.open("rb") as f:
    _config = tomllib.load(f)

_project_config = _config["project"]
_tool_config = _config["tool"]["config"]

# From pyproject.toml
OPENAI_MODEL = _tool_config["openai_model"]
SCHEDULER_TRIGGER_TIME = _tool_config["scheduler_trigger_time"]
RANGE_NAME = _tool_config["range_name"]
SERVICE_ACCOUNT_FILE = _tool_config["service_account_file"]

# From environment variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "")

# Google credentials — built only when the service account file is present (skipped in CI)
_creds_path = Path(SERVICE_ACCOUNT_FILE)
if _creds_path.exists():
    from google.oauth2 import service_account as _sa

    _SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/spreadsheets"]
    google_credentials = _sa.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=_SCOPES)
else:
    google_credentials = None


# fmt: off
def config_cli(
    # Show all
    all: bool = typer.Option(False, "--all", help="Show all configuration values"),
    # Project keys
    project_name: bool = typer.Option(False, "--project-name", help=_project_config['name']),
    project_version: bool = typer.Option(False, "--project-version", help=_project_config['version']),
) -> None:
# fmt: on
    """Get configuration values from pyproject.toml."""
    # Show all configuration
    if all:
        typer.echo(f"project_name={_project_config['name']}")
        typer.echo(f"project_version={_project_config['version']}")
        return

    # Map parameters to their actual values
    param_map = {
        project_name: _project_config["name"],
        project_version: _project_config["version"],
    }

    for is_set, value in param_map.items():
        if is_set:
            typer.echo(value)
            return

    typer.secho(
        "Error: No config key specified. Use --help to see available options.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(1)


def main():
    typer.run(config_cli)


if __name__ == "__main__":
    main()
