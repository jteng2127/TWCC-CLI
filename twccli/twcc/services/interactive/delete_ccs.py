import questionary
from questionary import Choice
import requests
from yaspin import yaspin
from twccli.twcc.services.compute import GpuSite


def _fetch_sites_to_delete(ccs_site: GpuSite, fetch_all_user=False) -> list[dict]:
    with yaspin(text="Fetching CCS containers...", color="cyan", timer=True) as spinner:
        sites = ccs_site.list(is_all=fetch_all_user)
        sites = [site for site in sites if site["status"] != "Deleting"]
        spinner.text = "Fetched CCS containers."
        spinner.ok("V")
    return sites


def _ask_site_ids(sites) -> list[int] | None:
    site_choices = [
        Choice(
            f'{site["id"]} - {site["name"]} ({site["create_time"]}) <{site["user"]["display_name"]}> [{site["status"]}]',
            site["id"],
        )
        for site in sites
    ]
    selected_site_ids = questionary.checkbox(
        "Select the CCS container IDs you want to delete:",
        choices=site_choices,
    ).ask()

    return selected_site_ids


def _print_full_twcc_irm_ccs_command(
    sites: list,
    selected_site_ids: list[int],
    dry_run: bool = False,
):
    full_command = "twccli irm ccs"
    site_ids = [site["id"] for site in sites]
    if set(site_ids) == set(selected_site_ids):
        full_command += " \\\n  --all"
    else:
        for site_id in selected_site_ids:
            full_command += f" \\\n  --site-id {site_id}"
    if dry_run:
        full_command += " \\\n  --dry-run"
    questionary.print(f"Command to delete these containers:\n```\n{full_command}\n```")


def _confirm_delete_container(site_id: int) -> bool:
    confirm = questionary.confirm(
        f"Are you sure you want to delete the container with ID {site_id}?",
        default=False,
    ).ask()
    return confirm


def delete_ccs_interactively(
    selected_site_ids: list[int] = None,
    delete_all: bool = False,
    force: bool = False,
    dry_run: bool = False,
    fetch_all_user: bool = False,
):
    ccs_site = GpuSite()
    sites = []
    if not selected_site_ids:
        sites = _fetch_sites_to_delete(ccs_site, fetch_all_user=fetch_all_user)
        if not sites:
            questionary.print("No CCS containers found.")
            return
        if delete_all:
            selected_site_ids = [site["id"] for site in sites]
        if not selected_site_ids:
            selected_site_ids = _ask_site_ids(sites)
        if not selected_site_ids:
            questionary.print("No CCS containers selected for deletion.")
            return
        if not delete_all:
            _print_full_twcc_irm_ccs_command(
                sites,
                selected_site_ids,
                dry_run=dry_run,
            )
    if dry_run:
        questionary.print("Dry run mode: not deleting the containers, exiting now.")
        return

    for site_id in selected_site_ids:
        if not force:
            confirm = _confirm_delete_container(site_id)
        else:
            confirm = True
        if not confirm:
            questionary.print(f"Skipping deletion of container {site_id}.")
            continue
        try:
            with yaspin(
                text=f"Deleting container {site_id}...", color="cyan", timer=True
            ) as spinner:
                try:
                    ccs_site.delete(site_id)
                    spinner.text = f"Container {site_id} deleted successfully."
                    spinner.ok("V")
                except requests.HTTPError as e:
                    spinner.text = f"Failed to delete container {site_id}: {e}"
                    spinner.fail("X")
                    continue
        except Exception as e:
            questionary.print(f"Failed to delete container {site_id}: {e}")
            continue
