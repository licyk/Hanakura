"""Entry point: ``get_app()`` registers every command; ``main()`` runs it with uniform error handling."""

import sys
import traceback

import typer
from typer import Abort, Exit

from hanakura.cli.commands.config import config_get, config_path, config_set, config_show
from hanakura.cli.commands.download import download_hf, download_model, download_modelscope, download_url
from hanakura.cli.commands.library import (
    library_delete,
    library_identify,
    library_import,
    library_info,
    library_list,
    library_move,
    library_rename,
    library_scan,
    root_add,
    root_list,
    root_remove,
)
from hanakura.cli.commands.search import auth_connect, auth_disconnect, auth_status, auth_use, info, search, source_list
from hanakura.cli.commands.system import env, version
from hanakura.cli.commands.webui import webui
from hanakura.cli.factory import ClickException, typer_factory
from hanakura.logger import setup_logging

logger = setup_logging()


def get_app() -> typer.Typer:
    """Build the Hanakura command line. Every command is registered here, and nowhere else."""
    app = typer_factory("Download and manage Stable Diffusion models")

    app.command(help="Start the server and open the web UI", name="webui")(webui)
    app.command(help="Show the version of Hanakura and its main components", name="version")(version)
    app.command(help="List the environment variables Hanakura reads", name="env")(env)
    app.command(help="Search a source or hub for models", name="search")(search)
    app.command(help="Show a model's versions and files", name="info")(info)

    config_cli = typer_factory(help="Show and change settings")
    config_cli.command(help="Show the effective settings", name="show")(config_show)
    config_cli.command(help="Print one setting", name="get")(config_get)
    config_cli.command(help="Change one setting and save it", name="set")(config_set)
    config_cli.command(help="Print the path of the settings file", name="path")(config_path)
    app.add_typer(config_cli, name="config")

    source_cli = typer_factory(help="Model sources and hubs")
    source_cli.command(help="List sources and hubs, with token status", name="list")(source_list)
    app.add_typer(source_cli, name="source")

    auth_cli = typer_factory(help="Civitai authentication: a manual API token or a connected account")
    auth_cli.command(help="Show which Civitai credential is in use", name="status")(auth_status)
    auth_cli.command(help="Choose the credential to use: manual or oauth", name="use")(auth_use)
    auth_cli.command(help="How to connect a Civitai account", name="connect")(auth_connect)
    auth_cli.command(help="Revoke and forget the connected Civitai account", name="disconnect")(auth_disconnect)
    app.add_typer(auth_cli, name="auth")

    download_cli = typer_factory(help="Download models")
    download_cli.command(help="Download a model file from a searchable source", name="model")(download_model)
    download_cli.command(help="Download a file from a plain URL", name="url")(download_url)
    download_cli.command(help="Download files from a Hugging Face repository", name="hf")(download_hf)
    download_cli.command(help="Download files from a ModelScope repository", name="modelscope")(download_modelscope)
    app.add_typer(download_cli, name="download")

    library_cli = typer_factory(help="Manage local models")
    root_cli = typer_factory(help="Model root folders")
    root_cli.command(help="List model roots", name="list")(root_list)
    root_cli.command(help="Add a model root", name="add")(root_add)
    root_cli.command(help="Forget a model root; files are not touched", name="remove")(root_remove)
    library_cli.add_typer(root_cli, name="root")
    library_cli.command(help="List models in a folder", name="list")(library_list)
    library_cli.command(help="Show detection result, hash and sidecar data for one model", name="info")(library_info)
    library_cli.command(help="Look the file's hash up on the sources", name="identify")(library_identify)
    library_cli.command(help="Detect every model in a root and fill the cache", name="scan")(library_scan)
    library_cli.command(help="Copy or move models into a root", name="import")(library_import)
    library_cli.command(help="Move models or folders to another folder", name="move")(library_move)
    library_cli.command(help="Rename a model and its companion files", name="rename")(library_rename)
    library_cli.command(help="Delete models with their companions", name="delete")(library_delete)
    app.add_typer(library_cli, name="library")

    return app


def main() -> None:
    """Run the command line."""
    from hanakura.core.errors import HanakuraError

    try:
        get_app()()
    except Exit as e:
        sys.exit(e.exit_code)
    except Abort:
        logger.error("Cancelled")
        sys.exit(1)
    except ClickException as e:
        e.show()
        sys.exit(e.exit_code)
    except HanakuraError as e:
        logger.error("%s", e.message)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        logger.error("Interrupted")
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        logger.error("Command failed: %s", e)
        sys.exit(1)
