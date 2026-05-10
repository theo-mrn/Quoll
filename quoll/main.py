import typer

from quoll.commands import add, cd, ci, docker, k8s, remove
from quoll.commands.add_secret import app as add_secret_app
from quoll.commands.new import new
from quoll.console import console

app = typer.Typer(
    name="quoll",
    help="Scaffold new projects and maintain their CI, Docker image and delivery with company standards.",
    no_args_is_help=True,
)

app.command("new")(new)
app.add_typer(add.app, name="add")
app.add_typer(remove.app, name="remove")
app.add_typer(ci.app, name="ci")
app.add_typer(docker.app, name="docker")
app.add_typer(cd.app, name="cd")
app.add_typer(k8s.app, name="k8s")
app.add_typer(add_secret_app, name="add-secret")
# Kept for scripts written against 0.1.x.
app.command("init-ci", hidden=True, help="Alias of `quoll ci init`.")(ci.init)


@app.command("init", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@app.command("create-project", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def _replaced() -> None:
    """The scaffolding of 0.1.x."""
    console.print("[red]Error:[/red] replaced by [bold]quoll new[/bold], e.g. quoll new shop --front angular "
                  "--back express (see quoll new --help).")
    raise typer.Exit(1)

if __name__ == "__main__":
    app()
