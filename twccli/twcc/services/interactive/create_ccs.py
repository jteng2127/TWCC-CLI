from datetime import datetime
import hashlib
import json
import shlex
import random
import string
import time
import questionary
import paramiko
from questionary import Choice
from yaspin import yaspin
from twccli.twcc.services.compute import GpuSite
from twccli.twcc.services.compute_util import (
    format_ccs_env_dict,
    get_pass_api_key_params,
)
from twccli.twcc.util import name_validator, env_validator


def _ask_solution_name_and_id(ccs_site: GpuSite, solution_name: str = None):
    with yaspin(
        text="Fetching solution id list...", color="cyan", timer=True
    ) as spinner:
        available_solutions = ccs_site.getSolList(reverse=True)
        spinner.text = "Available solutions fetched."
        spinner.ok("V")

    if solution_name is None:
        solution_name_choices = [
            Choice(title=f"{name} ({id})", value=name)
            for name, id in available_solutions.items()
        ]
        solution_name = questionary.select(
            "Please select a solution name:",
            choices=solution_name_choices,
            use_shortcuts=len(available_solutions) <= 36,
        ).ask()
    if solution_name is None:
        raise ValueError("Solution name must be provided.")

    solution_id = None
    for name, id in available_solutions.items():
        if name.lower() == solution_name.lower():
            solution_id = id
            break
    if solution_id is None:
        raise ValueError(
            f"Solution name '{solution_name}' not found in available solutions."
        )
    return solution_name, solution_id


def _ask_solution_image(ccs_site: GpuSite, solution_id: int, solution_name: str):
    with yaspin(
        text="Fetching solution images...", color="cyan", timer=True
    ) as spinner:
        images = ccs_site.getAvblImg(solution_id, solution_name)
        spinner.text = "Available solution images fetched."
        spinner.ok("V")
    solution_image = questionary.select(
        "Please select a solution image:",
        choices=images,
        use_shortcuts=len(images) <= 36,
    ).ask()
    if solution_image is None:
        raise ValueError("Solution image must be provided.")
    return solution_image


def _ask_gpu_flavor(ccs_site: GpuSite, solution_id: int):
    with yaspin(
        text="Fetching available GPU flavors...", color="cyan", timer=True
    ) as spinner:
        available_flavors = sorted(ccs_site.getAvblFlv(solution_id))
        spinner.text = "Available GPU flavors fetched."
        spinner.ok("V")
    gpu_flavor = questionary.select(
        "Please select a GPU flavor:",
        choices=available_flavors,
        use_shortcuts=len(available_flavors) <= 36,
    ).ask()
    if gpu_flavor is None:
        raise ValueError("GPU flavor must be provided.")
    return gpu_flavor


def _create_default_container_name():
    rand_str = "".join(random.choices(string.ascii_lowercase, k=4))
    timestamp = datetime.now().strftime("%m%d%H%M")
    return f"c{timestamp}_{rand_str}"


def _ask_container_name(default_name: str = ""):
    container_name = questionary.text(
        "Please enter a container name /^[a-z][a-z-_0-9]{{5,15}}$/:",
        default=default_name,
        validate=lambda x: name_validator(x),
    ).ask()
    if container_name is None:
        raise ValueError("Container name must be provided.")
    return container_name


def _ask_command():
    cmd = questionary.text(
        "Please enter a shell command to run after container creation (optional):",
        default="",
    ).ask()
    if cmd is None:
        raise ValueError("Cancelled by user.")
    if cmd.strip() == "":
        cmd = None
    return cmd


def _ask_rm_after_command():
    rm_after_command = questionary.confirm(
        "Do you want to remove the container after running the command?",
        default=True,
    ).ask()
    if rm_after_command is None:
        raise ValueError("Cancelled by user.")
    return rm_after_command


def _ask_log_path(container_name: str):
    log_path = questionary.text(
        f"Please enter the log file path inside the container (leave blank for default: `~/.twcc_data/log/ccs/{container_name}-<site_id>.log`):",
    ).ask()
    if log_path is None:
        raise ValueError("Cancelled by user.")
    return log_path


def _ask_show_connection_info():
    show_connection_info = questionary.confirm(
        "Do you want to show connection info (ssh and jupyter)?",
        default=True,
    ).ask()
    if show_connection_info is None:
        raise ValueError("Cancelled by user.")
    return show_connection_info


def _ask_env_list():
    env_str = questionary.text(
        "Please enter environment variables in `K1=V1 K2=V2` format (optional):",
        default="",
        validate=lambda x: env_validator(x),
    ).ask()
    if env_str is None:
        raise ValueError("Cancelled by user.")
    env_list = shlex.split(env_str)
    return env_list


def _print_full_twcc_imk_ccs_command(
    solution_name: str,
    solution_id: int,
    solution_image: str,
    gpu_flavor: str,
    env_list: list = None,
    cmd: str = None,
    rm_after_command: bool = False,
    wait: bool = False,
    dry_run: bool = False,
):
    full_command = (
        f"twccli imk ccs"
        f" \\\n  --image-type '{solution_name}' --image-type-id {solution_id}"
        f" \\\n  --image-name '{solution_image}'"
        f" \\\n  --gpu-flavor '{gpu_flavor}'"
    )
    if env_list:
        for env in env_list:
            full_command += f" \\\n  --env '{env}'"
    if cmd:
        full_command += f" \\\n  --cmd '{cmd}'"
    if rm_after_command:
        full_command += " \\\n  --rm"
    if wait:
        full_command += " \\\n  --wait"
    if dry_run:
        full_command += " \\\n  --dry-run"
    questionary.print(
        f"You can re-create the container later by running:\n```\n{full_command}\n```"
    )


def _print_connection_info(connection_info: dict):
    if not connection_info:
        questionary.print("No connection info available.")
        return

    if "ssh" in connection_info:
        username = connection_info["ssh"]["username"]
        hostname = connection_info["ssh"]["hostname"]
        port = connection_info["ssh"]["port"]
        questionary.print(
            "Connect to the container via SSH using the following command:\n"
            f'ssh -o "StrictHostKeyChecking=no" {username}@{hostname} -p {port}'
        )

    if "jupyter" in connection_info:
        # https://203-145-216-170.ccs.twcc.ai:55485/tree
        hostname = connection_info["jupyter"]["hostname"].replace(".", "-")
        hostname = hostname + ".ccs.twcc.ai"
        port = connection_info["jupyter"]["port"]
        token = connection_info["jupyter"]["token"]
        questionary.print(
            "Connect to the Jupyter Notebook via the following URL:\n"
            f"https://{hostname}:{port}/?token={token}\n"
        )


def _create_ccs_container(
    ccs_site: GpuSite,
    container_name: str,
    solution_id: int,
    solution_image: str,
    gpu_flavor: str,
    env_dict: dict = None,
):
    get_pass_api_key_params(True, env_dict)
    def_header = {
        "x-extra-property-replica": "1",
        "x-extra-property-flavor": gpu_flavor,
        "x-extra-property-image": solution_image,
        "x-extra-property-env": format_ccs_env_dict(env_dict),
    }
    with yaspin(
        text=f"Sending creation request for container {container_name}...",
        color="cyan",
        timer=True,
    ) as spinner:
        response = ccs_site.create(container_name, solution_id, def_header)
        spinner.text = f"Container {container_name} creation request sent."
        spinner.ok("V")

    if "id" not in response.keys():
        if "message" in response:
            raise ValueError(
                f"Can't find id, please check error message : {response['message']}"
            )
        elif "detail" in response:
            raise ValueError(
                f"Can't find id, please check error message : {response['detail']}"
            )
        else:
            raise ValueError(f"Can't find id in response:\n{response}")

    return response


def _wait_for_container_ready(ccs_site: GpuSite, site_id: str):
    with yaspin(
        text="Waiting for container to be ready...", color="cyan", timer=True
    ) as spinner:
        while True:
            site_info = ccs_site.queryById(site_id)
            status = site_info.get("status", "Unknown")
            if status == "Unknown":
                raise ValueError(f"Unknown status for container {site_id}: {site_info}")
            is_ready = status == "Ready" or status == "Error"
            if is_ready:
                break
            spinner.text = f"Waiting for container {site_id} to be ready, current status: {status}..."
            time.sleep(5)
        spinner.text = f"Container {site_id} is ready with status: {status}"
        spinner.ok("V")
    return site_info


def _get_connection_info(
    ccs_site: GpuSite,
    site_id: str,
    site_info: dict = None,
    site_detail: dict = None,
):
    service_connection_info = {}
    with yaspin(
        text="Fetching connection info...", color="cyan", timer=True
    ) as spinner:
        if site_detail is None:
            site_detail = ccs_site.getDetail(site_id)
        if "Service" in site_detail:
            if site_info is None:
                site_info = ccs_site.queryById(site_id)
            username = site_info.get("user", {}).get("username")
            if username is None:
                raise ValueError(
                    f"Username not found in response for site {site_id}: {site_info}"
                )

            container_ports = site_detail["Pod"][0]["container"][0]["ports"]
            container_port_to_name = {
                port["port"]: port["name"] for port in container_ports
            }

            service_public_ip = site_detail["Service"][0]["annotations"][
                "allocated-public-ip"
            ]
            service_ports = site_detail["Service"][0]["ports"]
            service_connection_info = {
                container_port_to_name[port["target_port"]]: {
                    "protocol": port["protocol"],
                    "target_port": port["target_port"],
                    "port": port["port"],
                    "hostname": service_public_ip,
                    "username": username,
                }
                for port in service_ports
            }

            if "jupyter" in service_connection_info:
                pod_name = site_detail["Pod"][0]["name"]
                jupyter_token = hashlib.md5(pod_name.encode()).hexdigest()
                service_connection_info["jupyter"]["token"] = jupyter_token
        spinner.text = "Connection info fetched."
        spinner.ok("V")
    return service_connection_info


def _do_ssh(
    ccs_site: GpuSite,
    site_id: str,
    ssh_connection_info: dict,
    command: str,
    log_path: str,
    rm_after_command: bool = True,
):
    log_path = log_path.replace("~", "${HOME}")
    mkdir_command = f"mkdir -p $(dirname {log_path})"

    command = command.strip()
    while command.endswith(";"):
        command = command[:-1]
    command = f"exec >> {log_path} 2>&1 ;\n  {command}"
    if rm_after_command:
        rm_command = "echo removing container ${site_id:-_TWCC_SITE_ID_}; twccli rm ccs -fs ${site_id:-_TWCC_SITE_ID_}"
        command = f"{command} ;\n  {rm_command}"
    safe_command = shlex.quote(command)
    full_command = (
        f"nohup bash --login -c \\\n{safe_command} < /dev/null >> {log_path} 2>&1 &"
    )

    questionary.print(f"Command to run in the background:\n```\n{full_command}\n```")
    hostname = ssh_connection_info["hostname"]
    port = ssh_connection_info["port"]
    username = ssh_connection_info["username"]
    yaspin_text = f"Sending command to {username}@{hostname}:{port} ..."
    with yaspin(text=yaspin_text, color="cyan", timer=True) as spinner:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        is_connected = False
        try:
            client.connect(
                hostname=hostname,
                port=port,
                username=username,
                look_for_keys=True,
                allow_agent=True,
            )
            is_connected = True
        except paramiko.AuthenticationException as e:
            spinner.write(
                "SSH key authentication failed, trying password authentication (Tip: you can do `ssh-copy-id` to your login node)."
            )
            while True:
                spinner.stop()
                password = questionary.password(
                    "Please enter your SSH password:",
                ).ask()
                spinner.start()
                if password is None:
                    break
                try:
                    client.connect(
                        hostname=hostname,
                        port=port,
                        username=username,
                        password=password,
                        look_for_keys=False,
                        allow_agent=False,
                    )
                    is_connected = True
                    break
                except paramiko.AuthenticationException:
                    spinner.write("SSH password authentication failed, try again.")
        if is_connected:
            stdin, stdout, stderr = client.exec_command(mkdir_command)
            stdin, stdout, stderr = client.exec_command(full_command)
            out = stdout.read().decode()
            err = stderr.read().decode()

            if out:
                spinner.write(f"Output: {out}")
            if err:
                spinner.write(f"Error: {err}")
            client.close()
            spinner.text = yaspin_text + " done"
            spinner.ok("V")
        else:
            spinner.text = "Failed to connect via SSH, removeing container..."
            ccs_site.delete(site_id)
            spinner.text = f"Container {site_id} removed due to SSH connection failure."
            spinner.fail("X")


def create_ccs_interactively(
    container_name: str = None,
    solution_name: str = None,  # "PyTorch"
    solution_id: int = None,  # 9
    solution_image: str = None,  # "pytorch-25.02-py3:latest"
    gpu_flavor: str = None,  # "1 GPU + 04 cores + 090GB memory"
    env_list: str = None,  # ["K1=V1", "K2=V2"]
    cmd: str = None,
    rm_after_command: bool = False,
    log_path: str = None,
    wait: bool = False,
    dry_run: bool = False,
):
    """Create container
    Create container by default value
    Create container by set vaule of name, solution name, gpu number, solution number
    """
    ccs_site = GpuSite()

    is_asked = False
    if solution_id is None:
        solution_name, solution_id = _ask_solution_name_and_id(ccs_site)
        is_asked = True
    if solution_image is None:
        solution_image = _ask_solution_image(ccs_site, solution_id, solution_name)
        is_asked = True
    if gpu_flavor is None:
        gpu_flavor = _ask_gpu_flavor(ccs_site, solution_id)
        is_asked = True
    if container_name is None:
        container_name = _create_default_container_name()
        if is_asked:
            container_name = _ask_container_name(container_name)
            is_asked = True
    if is_asked and cmd is None:
        cmd = _ask_command()
        if cmd and not rm_after_command:
            rm_after_command = _ask_rm_after_command()
        if cmd and log_path is None:
            log_path = _ask_log_path(container_name)
    if is_asked and not cmd and not wait:
        wait = _ask_show_connection_info()
    if is_asked and not env_list:
        env_list = _ask_env_list()
        is_asked = True
    if is_asked:
        _print_full_twcc_imk_ccs_command(
            solution_name,
            solution_id,
            solution_image,
            gpu_flavor,
            env_list,
            cmd,
            rm_after_command,
            wait,
            dry_run,
        )
    try:
        env_dict = dict(item.split("=", 1) for item in env_list)
    except ValueError:
        raise ValueError("Environment variables must be in KEY=VALUE format.")

    if dry_run:
        questionary.print("Dry run mode: not creating the container, exiting now.")
        exit()

    site_info = _create_ccs_container(
        ccs_site,
        container_name,
        solution_id,
        solution_image,
        gpu_flavor,
        env_dict,
    )

    site_id = site_info["id"]

    if cmd:
        wait = True
    if wait:
        site_info = _wait_for_container_ready(ccs_site, site_id)
        connection_info = _get_connection_info(
            ccs_site,
            site_id,
            site_info=site_info,
        )

        _print_connection_info(connection_info)

        if cmd:
            if not log_path:
                log_path = f"~/.twcc_data/log/ccs/{container_name}-{site_id}.log"
            _do_ssh(
                ccs_site,
                site_id,
                connection_info["ssh"],
                command=cmd,
                log_path=log_path,
                rm_after_command=rm_after_command,
            )

    return site_info
