import typer
from typer.testing import CliRunner

from src.config import config_cli

app = typer.Typer()
app.command()(config_cli)


def test_project_name_and_all_output_match_what_install_sh_parses():
    runner = CliRunner()

    name = runner.invoke(app, ["--project-name"])
    all_values = runner.invoke(app, ["--all"])

    assert name.stdout.strip() == "flight-calendar-updater"
    pairs = dict(line.split("=", 1) for line in all_values.stdout.splitlines())
    assert pairs["project_name"] == "flight-calendar-updater"
