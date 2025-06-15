import hashlib
import paramiko
import questionary
from yaspin import yaspin

from twccli.twcc.services.compute import GpuSite


def get_connected_ssh_client(
    hostname: str, port: int, username: str
) -> paramiko.SSHClient:
    """Get an SSH client connected to the specified host."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # Try key-based authentication first
    with yaspin(
        text=f"Connecting to SSH host {username}@{hostname}:{port}...",
        color="cyan",
        timer=True,
    ) as spinner:
        try:
            client.connect(
                hostname=hostname,
                port=port,
                username=username,
                look_for_keys=True,
                allow_agent=True,
            )
        except paramiko.AuthenticationException:
            spinner.write(
                "SSH key authentication failed, trying password authentication (Tip: you can do `ssh-copy-id` to your login node)."
            )
            while True:
                spinner.stop()
                password = questionary.password("Please enter your SSH password:").ask()
                spinner.start()
                if password is None:
                    spinner.text = "Authentication cancelled by user."
                    spinner.fail("X")
                    raise ValueError("Authentication cancelled by user.")
                try:
                    client.connect(
                        hostname=hostname,
                        port=port,
                        username=username,
                        password=password,
                        look_for_keys=False,
                        allow_agent=False,
                    )
                    break
                except paramiko.AuthenticationException:
                    spinner.write("SSH password authentication failed, try again.")
        spinner.text = f"Connected to SSH host {username}@{hostname}:{port}"
        spinner.ok("V")
    return client


def get_connection_info(
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
