import os
import shlex
import subprocess
import traceback
from typing import List, Dict, Optional

from questionary import Choice
import questionary
from yaspin import yaspin

from twccli.twcc.services.compute import GpuSite
from twccli.twcc.services.connections import (
    get_connected_ssh_client,
    get_connection_info,
)
from twccli.twcc.session import Session2


def _is_container_running(ccs_site: GpuSite, site_id: str) -> bool:
    """Check if container is running by querying its status."""
    try:
        site_info = ccs_site.queryById(site_id)
        status = site_info.get("status", "Unknown")
        return status == "Ready"
    except Exception:
        return False


def _list_log_files_via_sftp(
    username: str, log_dir: str, log_keyword: str
) -> List[str]:
    """List log files in the remote directory via SFTP."""
    hostname = "xdata1.twcc.ai"
    port = 22

    client = get_connected_ssh_client(hostname, port, username)
    with yaspin(
        text="Fetching log file list via SFTP...", color="cyan", timer=True
    ) as spinner:
        # Get SFTP client and list files
        sftp = client.open_sftp()
        try:
            # Expand environment variables in log_dir
            home_dir = sftp.normalize(".")
            log_dir = log_dir.replace("${HOME}", home_dir)
            log_dir = log_dir.replace("~", home_dir)
            try:
                files = sftp.listdir(log_dir)
            except FileNotFoundError:
                spinner.text = f"Log directory '{log_dir}' does not exist."
                spinner.fail("✗")
                return []

            # Filter files by pattern
            log_files = []
            for file in files:
                if log_keyword in file:
                    log_files.append(file)
            log_files = [os.path.join(log_dir, f) for f in log_files]

            spinner.text = f"Found {len(log_files)} log files matching pattern '{log_keyword}' under '{log_dir}'"
            spinner.ok("✓")
            return sorted(log_files, reverse=True)

        except Exception as e:
            spinner.text = f"Failed to fetch log files under '{log_dir}': {str(e)}"
            spinner.fail("✗")
            raise
        finally:
            sftp.close()
            client.close()


def _ask_log_file_selection(log_files: List[str]):
    if len(log_files) == 1:
        return log_files[0]
    log_file_choices = [Choice(title=os.path.basename(f), value=f) for f in log_files]
    selected_log = questionary.select(
        "Please select a log file to view:",
        choices=log_file_choices,
        use_shortcuts=len(log_files) <= 36,
        use_indicator=len(log_files) > 36,
    ).ask()
    return selected_log


def _extract_site_id_from_log_filename(log_filename: str) -> Optional[str]:
    """Extract site ID from log filename (assuming format: container_name-site_id.log)."""
    # Pattern to match site ID at the end of filename before .log
    tmp = log_filename[:-4]  # remove .log
    site_id = tmp.split("-")[-1]  # get last part after the last '-'
    if not site_id.isdigit():
        questionary.print(
            f"Warning: Unable to extract site ID from log filename '{log_filename}'."
        )
        return None
    return site_id


def _view_running_container_log(ssh_connection_info: Dict[str, str], log_path: str):
    """View log of running container using SSH tail -f."""
    hostname = ssh_connection_info["hostname"]
    port = ssh_connection_info["port"]
    username = ssh_connection_info["username"]

    ssh_command = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        f"{username}@{hostname}",
        "-p",
        str(port),
        f"tail -f {shlex.quote(log_path)}",
    ]

    questionary.print(f"Running: {' '.join(ssh_command)}")

    try:
        subprocess.run(ssh_command, check=True)
    except subprocess.CalledProcessError as e:
        if e.returncode == 255:
            questionary.print("Container have been removed or is unreachable.")
        else:
            questionary.print("Error: Failed to connect or read log.")
            traceback.print_exc()


def _view_static_container_log(username: str, log_path: str):
    """View log of stopped container using SFTP + less without saving."""
    hostname = "xdata1.twcc.ai"
    port = 22

    client = get_connected_ssh_client(hostname, port, username)
    with yaspin(
        text=f"Downloading log from {log_path}", color="cyan", timer=True
    ) as spinner:
        try:
            # Download file content via SFTP
            sftp = client.open_sftp()
            with sftp.open(log_path, "r") as remote_file:
                log_content = remote_file.read().decode("utf-8", errors="replace")

            sftp.close()
            client.close()

            spinner.text = f"Log downloaded successfully from {log_path}"
            spinner.ok("V")

        except Exception as e:
            spinner.text = f"Failed to download log: {str(e)}"
            spinner.fail("X")
            raise

    # Use less to view the content
    questionary.print(f"Viewing static log: {log_path}")

    process = subprocess.Popen(["less", "-r"], stdin=subprocess.PIPE, text=True)
    process.communicate(input=log_content)


def _show_twccli_logs_help(log_file: str):
    """Show help message for twccli logs command."""
    questionary.print(
        f"\nTo view this log file in the future, you can use:\n"
        f"  twccli logs {shlex.quote(log_file)}\n"
    )


def show_ccs_log_interactively(
    log_keyword: str = ".log",
    log_dir: str = ".twcc_data/log/ccs",
    follow: bool = False,
):
    """
    Interactively select and show CCS container logs.

    Args:
        log_pattern: Pattern to filter log files
        dir: Directory path where logs are stored
    """
    ccs_site = GpuSite()
    session = Session2()
    username = session.twcc_username

    # List log files via SFTP
    log_files = _list_log_files_via_sftp(username, log_dir, log_keyword)

    if not log_files:
        questionary.print(
            f"No log files found matching keyword '{log_keyword}' in '{log_dir}'"
        )
        return

    # Ask user to select a log file
    selected_log = _ask_log_file_selection(log_files)
    if selected_log is None:
        questionary.print("No log file selected.")
        return

    # Extract site ID from log filename
    site_id = _extract_site_id_from_log_filename(selected_log)
    if site_id is None:
        questionary.print(
            f"Could not extract site ID from log filename '{selected_log}'."
        )
        return

    # Check if container is running
    is_running = _is_container_running(ccs_site, site_id)
    status_text = "running" if is_running else "not running"
    questionary.print(f"Container {site_id} is {status_text}")

    # View log based on container status
    try:
        if is_running:
            connection_info = get_connection_info(ccs_site, site_id)
            _view_running_container_log(connection_info["ssh"], selected_log)
        else:
            _view_static_container_log(username, selected_log)
    except KeyboardInterrupt:
        questionary.print("\nLog viewing interrupted.")
        _show_twccli_logs_help(selected_log)
    except Exception as e:
        questionary.print(f"Error viewing log: {e}")
        traceback.print_exc()
