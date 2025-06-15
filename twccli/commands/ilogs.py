"""
twccli ilogs <log_pattern> [-f|--follow] [--dir <remote_dir>]
twccli logs <log_file> [-f|--follow] [--dir <remote_dir>]

get log list using sftp and ask user which log to view (with log_pattern to filter)
check if container is running
    if running, `ssh -c tail -f`
    if not running, `sftp + less -r` without saving log file
when ctrl-c, show `twccli logs <log_file>` command help
"""

import click
from twccli.twcc.services.interactive.show_ccs_log import show_ccs_log_interactively
from twccli.twcc.util import (
    table_layout,
    jpp,
)


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Interactively select and show TWCC logs.",
)
def cli():
    pass


@click.command(
    help="Select and show logs interactively. Provide `log_keyword` to filter logs."
)
@click.option(
    "-f",
    "--follow",
    is_flag=True,
    default=False,
    help="Follow the log output in real-time.",
)
@click.option(
    "-d",
    "--dir",
    type=str,
    default="~/.twcc_data/log/ccs",
    show_default=True,
    help="Remote directory to search for logs (relative path to `~`).",
)
@click.argument("log_keyword", type=str, default=".log")
def ccs(
    log_keyword,
    follow,
    dir,
):
    show_ccs_log_interactively(
        log_keyword=log_keyword,
        log_dir=dir,
        follow=follow,
    )


cli.add_command(ccs)


def main():
    cli()


if __name__ == "__main__":
    main()
