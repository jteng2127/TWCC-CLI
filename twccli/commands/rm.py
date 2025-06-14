# -*- coding: utf-8 -*-
from __future__ import print_function
from twccli.commands.mk import eip
import click
import re
import sys
from twccli.twcc.util import (
    pp,
    table_layout,
    SpinCursor,
    isNone,
    mk_names,
    isFile,
    is_vcs_env,
)
from twccli.twcc.services.base import acls, users, image_commit, Keypairs
from twccli.twcc.session import Session2
from twccli.twcc.services.s3_tools import S3
from twccli.twcc.services.compute import (
    Fixedip,
    GpuSite,
    Secrets,
    VcsSite,
    VcsSecurityGroup,
    getSecGroupList,
    VcsImage,
    Volumes,
    LoadBalancers,
    SecurityGroups,
)
from twccli.twcc.services.compute_util import del_vcs, getConfirm
from twccli.twcc.services.generic import GenericService
from twccli.twcc.services.network import Networks
from twccli.twcc.util import (
    isNone,
    resource_id_validater,
    _debug,
    get_environment_params,
)
from twccli.twccli import pass_environment, logger
from botocore.exceptions import ClientError


def del_bucket(name, is_recursive, isForce=False):
    """Delete bucket

    :param name: name for deleting bucket.
    :type name: string
    :param is_recursive: is recursive or not
    :type is_recursive: bool
    :param isForce: Force to delete any resources at your own cost.
    :type isForce: bool
    """
    txt = "!! Recursive is ON !!\n" * 3 if is_recursive else ""
    if getConfirm("COS Delete Buckets", name, isForce, ext_txt=txt):
        s3 = S3()
        for bucket_name in name.split(","):
            try:
                s3.del_bucket(bucket_name, is_recursive)
                print("Bucket name '{}' is deleted".format(bucket_name))
            except ClientError as e:
                print(e)
                error_msg = "Note: Use `-r` to delete files in bucket recursively."
                print(error_msg)


def del_object(okey, bucket_name, isForce=False):
    """Delete Objects by bucket name

    :param okey: name for deleting object.
    :type okey: string
    :param bucket_name: bucket name
    :type bucket_name: string
    :param isForce: Force to delete any resources at your own cost.
    :type isForce: bool
    """
    txt = "Deleting objects: {} \n in bucket name: {}".format(okey, bucket_name)
    if getConfirm("COS Delete Object ", okey, isForce, ext_txt=txt):
        S3().del_object(bucket_name=bucket_name, file_name=okey)


def del_ccs(ids_or_names, isForce=False):
    """Delete ccs by id or name

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    if getConfirm("Delete CCS", ", ".join(ids_or_names), isForce):
        ccs = GpuSite()
        for con_id in ids_or_names:
            if ccs.delete(con_id):
                print("Successfully remove {}".format(con_id))
    else:
        print("No delete operations.")


def del_keypair(ids_or_names, isForce=False):
    """Delete keypair by name

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    if getConfirm("Keypair", ", ".join(ids_or_names), isForce):
        keyring = Keypairs()
        for key_name in ids_or_names:
            if "name" in keyring.queryById(key_name):
                print("Keypair: {} deleted.".format(key_name))
                keyring.delete(key_name)
            else:
                raise ValueError("Keypair: {}, not found.".format(key_name))


def del_vnet(ids_or_names, isForce=False, isAll=False):
    net = Networks()
    ans = [net.queryById(x) for x in ids_or_names]
    for the_net in ans:
        txt = "You about to delete virtual network \n- id: {}\n- created by: {}\n- created time: {}".format(
            the_net["id"], the_net["user"]["username"], the_net["create_time"]
        )
        if getConfirm("Virtal Network", ",".join(ids_or_names), isForce, ext_txt=txt):
            del_info = net.delete(the_net["id"])
        if not del_info == b"":
            print(del_info)


def del_snap(ids_or_names, isForce=False, isAll=False):
    """Delete security group by site id

    :param ids_or_names: ids for snapshots
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    :param site_id: resources for vcs id
    :type site_id: int
    :param isAll: Operates as tenant admin
    :type isAll: bool
    """
    if len(ids_or_names) > 0:
        snap = VcsImage()
        all_snaps = snap.list(isAll=isAll)
        if isNone(all_snaps):
            return None
        for snap_id in ids_or_names:
            the_snap = [x for x in all_snaps if x["id"] == int(snap_id)]
            if len(the_snap) > 0:
                the_snap = the_snap[0]
                txt = "You about to delete snapshot \n- id: {}\n- created by: {}\n- created time: {}".format(
                    snap_id, the_snap["user"]["username"], the_snap["create_time"]
                )
                if getConfirm("Snapshots", snap_id, isForce, txt):
                    snap.deleteById(snap_id)


def del_secg_from_vcs(ids_or_names, site_id=None, isForce=False, isAll=False):
    """Delete security group by site id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    :param site_id: resources for vcs id
    :type site_id: int
    :param isAll: Operates as tenant admin
    :type isAll: bool
    """
    secg_id = ids_or_names[0]
    if len(secg_id) <= 6:
        raise ValueError(
            "Security Group id: {} need to longer than 6 characters".format(secg_id)
        )

    vcs = VcsSite()
    if isNone(site_id):
        sites = vcs.list(isAll)
    else:
        sites = [vcs.queryById(site_id)]

    secg = VcsSecurityGroup()
    found = []
    for ele in sites:
        secg_list = getSecGroupList(ele["id"])
        if not "security_group_rules" in secg_list:
            continue
        for rule in secg_list["security_group_rules"]:
            if re.search(secg_id, rule["id"]):
                if getConfirm(
                    "Security Group",
                    ",".join(ids_or_names),
                    isForce,
                    ext_txt="Resource id: {}\nSecurity Group Rule id: {}".format(
                        ele["id"], rule["id"]
                    ),
                ):
                    secg.deleteRule(rule["id"])


def del_ip(ids_or_names, isForce=False):
    """Delete ip by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    eip = Fixedip()
    for ip_id in ids_or_names:
        ans = eip.list(ip_id)
        txt = "You about to delete ip \n- id: {}\n- created by: {}\n- created time: {}".format(
            ip_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("IP", ip_id, isForce, txt):
            eip.deleteById(ip_id)
            print("Successfully remove {}".format(ip_id))
        else:
            print("No delete operations.")


def del_ssl(ids_or_names, isforce=False):
    """Delete ssl by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    ssl = Secrets()
    for ssl_id in ids_or_names:
        ans = ssl.list(ssl_id)
        txt = "You about to delete SSL \n- id: {}\n- created by: {}\n- created time: {}".format(
            ssl_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("SSL", ssl_id, isforce, txt):
            ssl.deleteById(ssl_id)
            print("Successfully remove {}".format(ssl_id))
        else:
            print("No delete operations.")


def del_ssl(ids_or_names, isforce=False):
    """Delete ssl by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    ssl = Secrets()
    for ssl_id in ids_or_names:
        ans = ssl.list(ssl_id)
        txt = "You about to delete SSL \n- id: {}\n- created by: {}\n- created time: {}".format(
            ssl_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("SSL", ssl_id, isforce, txt):
            ssl.deleteById(ssl_id)
            print("Successfully remove {}".format(ssl_id))
        else:
            print("No delete operations.")


def del_ssl(ids_or_names, isforce=False):
    """Delete ssl by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    ssl = Secrets()
    for ssl_id in ids_or_names:
        ans = ssl.list(ssl_id)
        txt = "You about to delete SSL \n- id: {}\n- created by: {}\n- created time: {}".format(
            ssl_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("SSL", ssl_id, isforce, txt):
            ssl.deleteById(ssl_id)
            print("Successfully remove {}".format(ssl_id))
        else:
            print("No delete operations.")


def del_ssl(ids_or_names, isforce=False):
    """Delete ssl by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    ssl = Secrets()
    for ssl_id in ids_or_names:
        ans = ssl.list(ssl_id)
        txt = "You about to delete SSL \n- id: {}\n- created by: {}\n- created time: {}".format(
            ssl_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("SSL", ssl_id, isforce, txt):
            ssl.deleteById(ssl_id)
            print("Successfully remove {}".format(ssl_id))
        else:
            print("No delete operations.")


def del_ssl(ids_or_names, isforce=False):
    """Delete ssl by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    ssl = Secrets()
    for ssl_id in ids_or_names:
        ans = ssl.list(ssl_id)
        txt = "You about to delete SSL \n- id: {}\n- created by: {}\n- created time: {}".format(
            ssl_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("SSL", ssl_id, isforce, txt):
            ssl.deleteById(ssl_id)
            print("Successfully remove {}".format(ssl_id))
        else:
            print("No delete operations.")


def del_ssl(ids_or_names, isforce=False):
    """Delete ssl by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    ssl = Secrets()
    for ssl_id in ids_or_names:
        ans = ssl.list(ssl_id)
        txt = "You about to delete SSL \n- id: {}\n- created by: {}\n- created time: {}".format(
            ssl_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("SSL", ssl_id, isforce, txt):
            ssl.deleteById(ssl_id)
            print("Successfully remove {}".format(ssl_id))
        else:
            print("No delete operations.")


def del_secg(ids_or_names, isforce=False):
    """Delete ssl by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """

    for secg_id in ids_or_names:
        secg = SecurityGroups()  # need in the for loop！
        ans = secg.list(ids=[secg_id], secg_type="detail")[0]
        txt = "You about to delete security group \n- id: {}\n- created by: {}\n- created time: {}".format(
            secg_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("Security Group", secg_id, isforce, txt):
            secg.deleteById(secg_id)
            print("Successfully remove {}".format(secg_id))
        else:
            print("No delete operations.")


def del_secg_rule(ids_or_names, isforce=False):
    """Delete ssl by ip id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    """
    for rule_id in ids_or_names:
        secg = SecurityGroups()
        txt = "You about to delete security group rule \n- id: {}\n".format(rule_id)
        if getConfirm("Security Group rule", rule_id, isforce, txt):
            secg.deleteRule(rule_id)
            print("Successfully remove {}".format(rule_id))
        else:
            print("No delete operations.")


def del_load_balancer(ids_or_names, isForce=False):
    """Delete vlb by vlb id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool

    """
    vlb = LoadBalancers()
    for vlb_id in ids_or_names:
        ans = vlb.list(vlb_id)
        txt = "You about to delete load balancer \n- id: {}\n- created by: {}\n- created time: {}".format(
            vlb_id, ans["user"]["display_name"], ans["create_time"]
        )
        if getConfirm("Load Balancer", vlb_id, isForce, txt):
            vlb.deleteById(vlb_id)
            print("Successfully remove {}".format(vlb_id))
        else:
            print("No delete operations.")


def del_volume(ids_or_names, isForce=False, snapshot=None):
    """Delete volume by volume id

    :param ids_or_names: name for deleting object.
    :type ids_or_names: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    :param site_id: resources for vcs id
    :type site_id: int
    :param isAll: Operates as tenant admin
    :type isAll: bool
    """
    if snapshot:
        title = "Delete Volume Snapshot"
    else:
        title = "Delete Volumes"
    if getConfirm(title, ", ".join(ids_or_names), isForce):
        vol = Volumes()
        for vol_id in ids_or_names:
            ans = vol.deleteById(vol_id, snapshot)
            print("Successfully remove {}".format(vol_id))
    else:
        print("No delete operations.")


# Create groups for command
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS, help="Delete your TWCC resources.")
def cli():
    try:
        ga = GenericService()
        func_call = "_".join(
            [i for i in sys.argv[1:] if re.findall(r"\d", i) == [] and not i == "-sv"]
        ).replace("-", "")
        ga._send_ga(func_call)
    except Exception as e:
        logger.warning(e)
    pass


@click.command(help="Remove your key in VCS ")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force to delete any resource at your own cost.",
)
@click.option(
    "-n", "--name", "name", default=None, help="Enter name for your resource name"
)
@click.argument("ids_or_names", nargs=-1)
@pass_environment
@click.pass_context
def key(ctx, env, name, ids_or_names, force):
    """Removing key operation

    :param name: Enter name for your resource name
    :type name: string
    :param ids_or_names: Enter ids or names
    :type ids_or_names: string
    :param force: Force to delete any resource at your own cost.
    :type force: bool
    """
    ids_or_names = mk_names(name, ids_or_names)

    if len(ids_or_names) > 0:
        del_keypair(ids_or_names, force)
        wfn = "{}/{}.pem".format(Session2._getTwccDataPath(), name)
        if isFile(wfn):
            print("Please `rm {}` by yourself!".format(wfn))
    else:
        print("Key name is required.")


@click.command(help="'Delete' Operations for VCS (Virtual Compute Service) resources.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force to delete any resource at your own cost.",
)
@click.option(
    "-n",
    "--name",
    "name",
    help="Name of the keypair, hash ID of the security group, or ID of the instance.",
)
@click.option("-s", "--site-id", "site_id", help="ID of the VCS.")
@click.option("-cus-img-id", "--custom-image-id", "name", help="ID of custom image.")
@click.option(
    "-all",
    "--show-all",
    "is_all",
    is_flag=True,
    type=bool,
    help="Operates as tenant admin.",
)
@click.option(
    "-key",
    "--keypair",
    "res_property",
    flag_value="Keypair",
    help="Delete existing keypair(s).",
)
@click.option(
    "-cus-img",
    "--custom-image",
    "res_property",
    flag_value="Snapshot",
    help="delete a custom image. `-cus-img-id` is required!",
)
@click.option(
    "-secg",
    "--security-group",
    "res_property",
    flag_value="SecurityGroup",
    help="Delete existing security group(s).",
)
@click.argument("ids_or_names", nargs=-1)
@pass_environment
def vcs(env, res_property, name, force, is_all, site_id, ids_or_names):
    """Command line for VCS removing
    Function :
    1. Keypair
    2. Security Group

    :param res_property: Function type (Keypair, SecurityGroup)
    :type res_property: string
    :param name: Key name, security group hash id, or VCS resource id.
    :type name: string
    :param name: Key name, security group hash id, or VCS resource id.
    :type name: string
    :param is_recursive: Recursively delete all objects in COS. NOTE: Use this with caution.
    :type is_recursive: bool
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    :param is_all: Operates as tenant admin.
    :type is_all: bool
    """
    if res_property == "SecurityGroup":
        del_secg_from_vcs(mk_names(name, ids_or_names), site_id, force, is_all)
    if res_property == "Snapshot":
        del_snap(mk_names(name, ids_or_names), force, is_all)
    if isNone(res_property):
        ids_or_names = mk_names(site_id, ids_or_names)
        if len(ids_or_names) > 0:
            del_vcs(ids_or_names, force)
        else:
            print("resource id is required.")


@click.command(help="Remove your system (bootable) image(s)")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force to delete the objects.",
)
@click.option("-id", "--vcsi-id", "vcsi_id", help="ID of the IMAGE.")
@click.option(
    "-all",
    "--show-all",
    "is_all",
    is_flag=True,
    type=bool,
    help="Operates as tenant admin.",
)
@click.argument("ids_or_names", nargs=-1)
@pass_environment
@click.pass_context
def vcsi(ctx, env, vcsi_id, ids_or_names, is_all, force):
    """Removing key operation

    :param name: Enter name for your resource name
    :type name: string
    :param ids_or_names: Enter ids or names
    :type ids_or_names: string
    :param force: Force to delete any resource at your own cost.
    :type force: bool
    """
    del_snap(mk_names(vcsi_id, ids_or_names), force, is_all)


@click.command(help="'Delete' Operations for COS (Cloud Object Storage) resources.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the objects.",
)
@click.option(
    "-r",
    "--recursively",
    "is_recursive",
    is_flag=True,
    show_default=True,
    default=False,
    help="Recursively delete all objects in the bucket. NOTE: Use with caution.",
)
@click.option("-bkt", "--bucket_name", "name", help="Name of the bucket.")
@click.option("-okey", "--cos_key", "okey", help="Name of the object for deleting.")
@pass_environment
def cos(env, name, force, okey, is_recursive):
    """Command Line for COS deleting buckets

    :param name: Bucket name for deleting object.
    :type name: string
    :param force: Force to delete any resources at your own cost.
    :type force: bool
    :param okey: the COS key which you want to operate
    :type okey: string
    :param is_recursive: Recursively delete all objects in COS. NOTE: Use this with caution.
    :type is_recursive: bool
    """
    if isNone(name):
        print("please enter name")

    if isNone(okey):
        del_bucket(name, is_recursive, force)
    else:
        del_object(okey, name, force)


@click.command(
    help="'Delete' Operations for CCS (Container Compute Service) resources."
)
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.option("-s", "--site-id", "site_id", help="ID of the container.")
@click.argument("ids_or_names", nargs=-1)
@pass_environment
def ccs(env, site_id, force, ids_or_names):
    ids_or_names = mk_names(site_id, ids_or_names)
    if len(ids_or_names) == 0:
        raise ValueError("Resource id is required.")
    else:
        # print(isinstance(ids_or_names, int))
        result = True
        for id in ids_or_names:
            if resource_id_validater(id) == False:
                result = False

        if result:
            del_ccs(ids_or_names, force)
        else:
            print("site id must be integer")


@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.option(
    "-id",
    "--virtual_network_id",
    "vnetid",
    default="twccli",
    type=str,
    help="ID of the virtual Network.",
)
@click.command(help="Create your Virtual Network.")
@click.argument("ids_or_names", nargs=-1)
@pass_environment
def vnet(env, ids_or_names, vnetid, force):
    """Command line for create virtual network

    :param name: Enter name for your resources.
    :type name: string
    """
    del_vnet(mk_names(vnetid, ids_or_names), force)


@click.option("-id", "--disk-id", "name", help="Index of the disk.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.option(
    "-sn",
    "--snapshot",
    "snapshot",
    is_flag=True,
    default=False,
    help="Delete volume snapshots.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your VDS (Virtual Disk Service).")
@click.pass_context
def vds(ctx, name, ids_or_names, snapshot, force):
    """Command line for delete vds

    :param name: Enter name for your resources.
    :type name: string
    """
    ids_or_names = mk_names(name, ids_or_names)
    del_volume(ids_or_names, force, snapshot=snapshot)


@click.option("-id", "--vlb-id", "vlb_id", help="Index of the volume.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your Load Balancers.")
@click.pass_context
def vlb(ctx, vlb_id, ids_or_names, force):
    """Command line for delete vlb

    :param vlb_id: Enter name for your load balancer.
    :type vlb_id: string
    """
    ids_or_names = mk_names(vlb_id, ids_or_names)
    del_load_balancer(ids_or_names, force)


@click.option("-id", "--ip-id", "ip_id", help="Index of the private-net.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your IPs.")
@click.pass_context
def eip(ctx, ip_id, ids_or_names, force):
    """Command line for delete eip

    :param ip_id: Enter id for your eip.
    :type ip_id: string
    """
    ids_or_names = mk_names(ip_id, ids_or_names)
    del_ip(ids_or_names, force)


@click.option("-id", "--ssl-id", "ssl_id", help="Index of the ssls.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your SSLs.")
@click.pass_context
def ssl(ctx, ssl_id, ids_or_names, force):
    """Command line for delete eip

    :param ip_id: Enter id for your eip.
    :type ip_id: string
    """
    ids_or_names = mk_names(ssl_id, ids_or_names)
    del_ssl(ids_or_names, force)


@click.option("-id", "--ssl-id", "ssl_id", help="Index of the ssls.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your SSLs.")
@click.pass_context
def ssl(ctx, ssl_id, ids_or_names, force):
    """Command line for delete eip

    :param ip_id: Enter id for your eip.
    :type ip_id: string
    """
    ids_or_names = mk_names(ssl_id, ids_or_names)
    del_ssl(ids_or_names, force)


@click.option(
    "-f",
    "--force",
    "is_force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Forcely delete the resource.",
)
@click.option(
    "-dry/-no-dry",
    "--dry-run/--no-dry-run",
    "is_dry",
    is_flag=True,
    show_default=True,
    default=True,
    help="Check out command.",
)
@click.command(help="Delete ME now! Equals to `rm [ccs|vcs] -s $_TWCC_SITE_ID_`")
@click.pass_context
def me(ctx, is_dry, is_force):
    _site_id_ = get_environment_params("_TWCC_SITE_ID_")

    if isNone(_site_id_):
        click.echo(
            click.style(
                "[TWCC-CLI] Error! No `$_TWCC_SITE_ID_` found in environment variables.",
                bg="red",
                fg="white",
            )
        )
        return True
    in_cnv = "vcs" if is_vcs_env() else "ccs"

    if is_dry:
        click.echo(
            click.style(
                "[TWCC-CLI] Dry run: `twccli rm {} -s {}{}`.".format(
                    in_cnv, _site_id_, " -f" if is_force else ""
                ),
                fg="bright_magenta",
            )
        )
        click.echo(
            click.style(
                ">>> use `--no-dry-run` flag for actully executing command.",
                fg="bright_magenta",
            )
        )
    else:
        if getConfirm(in_cnv.upper(), _site_id_, is_force):
            if is_vcs_env():
                ctx.invoke(vcs, force=True, site_id=_site_id_)
            else:
                ctx.invoke(ccs, force=True, site_id=_site_id_)


@click.option("-id", "--ssl-id", "ssl_id", help="Index of the ssls.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your SSLs.")
@click.pass_context
def ssl(ctx, ssl_id, ids_or_names, force):
    """Command line for delete eip

    :param ip_id: Enter id for your eip.
    :type ip_id: string
    """
    ids_or_names = mk_names(ssl_id, ids_or_names)
    del_ssl(ids_or_names, force)


@click.option("-id", "--ssl-id", "ssl_id", help="Index of the ssls.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your SSLs.")
@click.pass_context
def ssl(ctx, ssl_id, ids_or_names, force):
    """Command line for delete eip

    :param ip_id: Enter id for your eip.
    :type ip_id: string
    """
    ids_or_names = mk_names(ssl_id, ids_or_names)
    del_ssl(ids_or_names, force)


@click.option(
    "-f",
    "--force",
    "is_force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Forcely delete the resource.",
)
@click.option(
    "-dry/-no-dry",
    "--dry-run/--no-dry-run",
    "is_dry",
    is_flag=True,
    show_default=True,
    default=True,
    help="Check out command.",
)
@click.command(help="Delete ME now! Equals to `rm [ccs|vcs] -s $_TWCC_SITE_ID_`")
@click.pass_context
def me(ctx, is_dry, is_force):
    _site_id_ = get_environment_params("_TWCC_SITE_ID_")

    if isNone(_site_id_):
        click.echo(
            click.style(
                "[TWCC-CLI] Error! No `$_TWCC_SITE_ID_` found in environment variables.",
                bg="red",
                fg="white",
            )
        )
        return True
    in_cnv = "vcs" if is_vcs_env() else "ccs"

    if is_dry:
        click.echo(
            click.style(
                "[TWCC-CLI] Dry run: `twccli rm {} -s {}{}`.".format(
                    in_cnv, _site_id_, " -f" if is_force else ""
                ),
                fg="bright_magenta",
            )
        )
        click.echo(
            click.style(
                ">>> use `--no-dry-run` flag for actully executing command.",
                fg="bright_magenta",
            )
        )
    else:
        if getConfirm(in_cnv.upper(), _site_id_, is_force):
            if is_vcs_env():
                ctx.invoke(vcs, force=True, site_id=_site_id_)
            else:
                ctx.invoke(ccs, force=True, site_id=_site_id_)


@click.option("-id", "--ssl-id", "ssl_id", help="Index of the ssls.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your SSLs.")
@click.pass_context
def ssl(ctx, ssl_id, ids_or_names, force):
    """Command line for delete eip

    :param ip_id: Enter id for your eip.
    :type ip_id: string
    """
    ids_or_names = mk_names(ssl_id, ids_or_names)
    del_ssl(ids_or_names, force)


@click.option("-id", "--ssl-id", "ssl_id", help="Index of the ssls.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your SSLs.")
@click.pass_context
def ssl(ctx, ssl_id, ids_or_names, force):
    """Command line for delete eip

    :param ip_id: Enter id for your eip.
    :type ip_id: string
    """
    ids_or_names = mk_names(ssl_id, ids_or_names)
    del_ssl(ids_or_names, force)


@click.option(
    "-f",
    "--force",
    "is_force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Forcely delete the resource.",
)
@click.option(
    "-dry/-no-dry",
    "--dry-run/--no-dry-run",
    "is_dry",
    is_flag=True,
    show_default=True,
    default=True,
    help="Check out command.",
)
@click.command(help="Delete ME now! Equals to `rm [ccs|vcs] -s $_TWCC_SITE_ID_`")
@click.pass_context
def me(ctx, is_dry, is_force):
    _site_id_ = get_environment_params("_TWCC_SITE_ID_")

    if isNone(_site_id_):
        click.echo(
            click.style(
                "[TWCC-CLI] Error! No `$_TWCC_SITE_ID_` found in environment variables.",
                bg="red",
                fg="white",
            )
        )
        return True
    in_cnv = "vcs" if is_vcs_env() else "ccs"

    if is_dry:
        click.echo(
            click.style(
                "[TWCC-CLI] Dry run: `twccli rm {} -s {}{}`.".format(
                    in_cnv, _site_id_, " -f" if is_force else ""
                ),
                fg="bright_magenta",
            )
        )
        click.echo(
            click.style(
                ">>> use `--no-dry-run` flag for actully executing command.",
                fg="bright_magenta",
            )
        )
    else:
        if getConfirm(in_cnv.upper(), _site_id_, is_force):
            if is_vcs_env():
                ctx.invoke(vcs, force=True, site_id=_site_id_)
            else:
                ctx.invoke(ccs, force=True, site_id=_site_id_)


@click.option("-id", "--secg-id", "secg_id", help="Index of the security group.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your security groups.")
@click.pass_context
def secg(ctx, secg_id, ids_or_names, force):

    ids_or_names = mk_names(secg_id, ids_or_names)
    del_secg(ids_or_names, force)


@click.option("-id", "--rule-id", "rule_id", help="Index of the security group rule.")
@click.option(
    "-f",
    "--force",
    "force",
    is_flag=True,
    show_default=True,
    default=False,
    help="Force delete the container.",
)
@click.argument("ids_or_names", nargs=-1)
@click.command(help="Delete your security group rule(s).")
@click.pass_context
def secg_rule(ctx, rule_id, ids_or_names, force):

    ids_or_names = mk_names(rule_id, ids_or_names)
    del_secg_rule(ids_or_names, force)


cli.add_command(vcs)
cli.add_command(cos)
cli.add_command(ccs)
cli.add_command(key)
cli.add_command(vds)
cli.add_command(vnet)
cli.add_command(vlb)
cli.add_command(eip)
cli.add_command(ssl)
cli.add_command(me)
cli.add_command(vcsi)
cli.add_command(secg)
cli.add_command(secg_rule)


def main():
    cli()


if __name__ == "__main__":
    main()
