import click
from twccli.twcc.services.interactive.delete_ccs import (
    delete_ccs_interactively,
)


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Interactively delete your TWCC resources.",
)
def cli():
    pass


@click.command(help="Delete CCS (Container Compute Service) resources.")
@click.option(
    "-s",
    "--site-id",
    multiple=True,
    type=int,
    help="ID of the container.",
)
@click.option(
    "-a",
    "--all",
    "delete_all",
    is_flag=True,
    show_default=True,
    default=False,
    help="Delete all CCS containers.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container without confirm.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="If set, the container will not be deleted, but the command will be printed.",
)
def ccs(
    site_id: tuple[int] = None,
    delete_all: bool = False,
    force: bool = False,
    dry_run: bool = False,
):
    delete_ccs_interactively(
        selected_site_ids=site_id,
        delete_all=delete_all,
        force=force,
        dry_run=dry_run,
        fetch_all_user=False,  # Causion
    )


cli.add_command(ccs)


def main():
    cli()


if __name__ == "__main__":
    main()
