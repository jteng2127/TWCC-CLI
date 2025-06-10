import click
from twccli.twcc.util import (
    table_layout,
    jpp,
)
from twccli.twcc.services.interactive.create_ccs import (
    create_ccs_interactively,
)


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Interactively create (allocate) TWCC resources.",
)
def cli():
    pass


@click.command(
    help="Create CCS containers interactively. If `name`, `image_type`, `image_type_id`, `image_name`, `gpu_flavor`, or `cmd` is not provided, you will be prompted to enter them interactively."
)
@click.option("-n", "--name", type=str, default=None, help="Name of the container.")
@click.option(
    "--image-type",
    type=str,
    default=None,
    help="Type of the image (e.g. 'PyTorch').",
)
@click.option(
    "-t",
    "--image-type-id",
    type=str,
    default=None,
    help="Type ID of the image (e.g. '9' for PyTorch).",
)
@click.option(
    "-i",
    "--image-name",
    type=str,
    default=None,
    help="Name of the solution image (e.g. 'pytorch-25.02-py3:latest').",
)
@click.option(
    "-g",
    "--gpu-flavor",
    type=str,
    default=None,
    help="GPU flavor (e.g. '1 GPU + 04 cores + 090GB memory').",
)
@click.option(
    "-c",
    "--cmd",
    type=str,
    default=None,
    help="Shell command to run after container creation. If provided, automatically sets --wait and deletes the container after execution.",
)
@click.option(
    "--rm",
    is_flag=True,
    default=False,
    help="If set, the container will be deleted after execution of the command. This option is only effective if --cmd is provided.",
)
@click.option(
    "-l",
    "--log-path",
    type=str,
    default=None,
    help="Path to save the log file in the container if the command is provided. Default is `~/.twcc_data/log/ccs/<container_name>-<site_id>.log`.",
)
@click.option(
    "-w",
    "--wait",
    is_flag=True,
    show_default=True,
    default=False,
    help="Wait for the container to be stable before returning. Will also display the ssh and Jupyter connection info",
)
@click.option(
    "-b / -j",
    "--table-view / --json-view",
    "is_table",
    is_flag=True,
    default=True,
    help="Show information in Table view or JSON view (default: --table-view).",
)
@click.option(
    "-e",
    "--env",
    multiple=True,
    help="Additional environment variables (e.g., --env KEY1=VALUE1 --env KEY2=VALUE2).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="If set, the container will not be created, but the command will be printed.",
)
def ccs(
    name: str = None,
    image_type: str = None,
    image_type_id: str = None,
    image_name: str = None,
    gpu_flavor: str = None,
    cmd: str = None,
    rm: bool = False,
    log_path: str = None,
    wait: bool = False,
    is_table: bool = True,
    env: list = None,
    dry_run: bool = False,
):
    response = create_ccs_interactively(
        container_name=name,
        solution_name=image_type,
        solution_id=image_type_id,
        solution_image=image_name,
        gpu_flavor=gpu_flavor,
        env_list=env,
        cmd=cmd,
        rm_after_command=rm,
        log_path=log_path,
        wait=wait,
        dry_run=dry_run,
    )

    if is_table:
        cols = ["id", "name", "status"]
        table_layout("CCS Site:{}".format(response["id"]), response, cols, isPrint=True)
    else:
        jpp(response)


cli.add_command(ccs)


def main():
    cli()


if __name__ == "__main__":
    main()
