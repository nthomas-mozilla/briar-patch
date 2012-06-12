#!/usr/bin/env python
import json
import uuid
import time

from fabric.api import run, put, env, sudo, local
from boto.ec2 import connect_to_region
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType

import logging
log = logging.getLogger()

def create_master(conn, name, options, config):
    """Creates an AMI instance with the given name and config. The config must specify things like ami id."""
    zones = conn.get_all_zones()

    # Make sure we don't request the same things twice
    token = str(uuid.uuid4())[:16]

    # Wait for the snapshot to be ready
    snap = conn.get_all_snapshots([config['repo_snapshot_id']])[0]
    while not snap.status == "completed":
        log.info("waiting for snapshot... (%s)", snap.status)
        snap.update()
        time.sleep(10)

    bdm = BlockDeviceMapping()
    bdm["/dev/sdh"] = BlockDeviceType(delete_on_termination=True, snapshot_id=config['repo_snapshot_id'])

    reservation = conn.run_instances(
            image_id=config['ami'],
            key_name=config['key_name'],
            instance_type=config['instance_type'],
            client_token=token,
            subnet_id=config.get('subnet_id'),
            security_group_ids=config.get('security_group_ids', []),
            block_device_map=bdm,
            placement=zones[0].name,
            )

    instance = reservation.instances[0]
    log.info("instance %s created, waiting to come up", instance)
    # Wait for the instance to come up
    while True:
        try:
            instance.update()
            if instance.state == 'running':
                break
            if instance.state == 'terminated':
                log.error("%s got terminated", instance)
                return
        except:
            log.exception("hit error waiting for instance to come up")
        time.sleep(10)
        log.info("waiting...")

    instance.add_tag('Name', name)
    instance.add_tag('moz-type', 'puppetmaster')

    instance.add_tag('moz-state', 'pending')
    puppetize(instance, name)

def puppetize(instance, name):
    env.host_string = instance.private_ip_address
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True
    while True:
        try:
            run("date")
            run("test -d /data || mkdir /data")
            # TODO: Use label!
            run("test -d /data/lost+found || mount /dev/xvdl /data")
            break
        except:
            log.exception("waiting...")
            time.sleep(10)

    # Install puppet
    put("/home/catlee/mozilla/puppet/setup/masterize.sh", "/root/masterize.sh")
    run("mkdir -p /etc/puppet/production")
    local("rsync -e 'ssh -oStrictHostKeyChecking=no' -aP --exclude repos --delete /home/catlee/mozilla/puppet/ root@{ip}:/etc/puppet/production/".format(ip=instance.private_ip_address))
    run("echo 0 > /selinux/enforce")
    run("chown -R root:root /etc/puppet/production")
    run("hostname {name}.releng.aws-us-west-1.mozilla.com".format(name=name))
    run("bash /root/masterize.sh")
    instance.add_tag('moz-state', 'ready')

    #log.info("Creating EIP and associating")
    #addr = conn.allocate_address("vpc")
    #log.info("Got %s", addr)
    #conn.associate_address(instance.id, allocation_id=addr.allocation_id)

# TODO: Move this into separate file(s)
configs =  {
    "rhel6": {
        "us-west-1": {
            #"ami": "ami-250e5060", # RHEL-6.2-Starter-EBS-x86_64-4-Hourly2
            "ami": "ami-cda8f288", # Centos6
            "subnet_id": "subnet-59e94330",
            "security_group_ids": ["sg-38150854"],
            "instance_type": "c1.medium",
            "key_name": "linux-test-west",
            "repo_snapshot_id": "snap-923f90f5", # This will be mounted at /data
        },
    },
}

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.set_defaults(
            config=None,
            region="us-west-1",
            secrets=None,
            action="create",
            instance=None,
            )
    parser.add_option("-c", "--config", dest="config", help="instance configuration to use")
    parser.add_option("-r", "--region", dest="region", help="region to use")
    parser.add_option("-k", "--secrets", dest="secrets", help="file where secrets can be found")
    parser.add_option("-l", "--list", dest="action", action="store_const", const="list", help="list available configs")
    parser.add_option("-i", "--instance", dest="instance", help="puppetize existing instance")

    options, args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if options.action == "list":
        for config, regions in configs.items():
            print config, regions.keys()
        # All done!
        raise SystemExit(0)

    if not args:
        parser.error("at least one instance name is required")

    if not options.secrets:
        parser.error("secrets are required")

    secrets = json.load(open(options.secrets))
    conn = connect_to_region(options.region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key'],
            )

    if options.instance:
        instance = conn.get_all_instances([options.instance])[0].instances[0]
        puppetize(instance, args[0])
        raise SystemExit(0)

    if not options.config:
        parser.error("config name is required")

    try:
        config = configs[options.config][options.region]
    except KeyError:
        parser.error("unknown configuration; run with --list for list of supported configs")

    create_master(conn, args[0], options, config)
