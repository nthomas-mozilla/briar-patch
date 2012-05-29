#!/usr/bin/env python
import json
import uuid
import time

from fabric.api import run, put, env, sudo
from boto.ec2 import connect_to_region
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType

import logging
log = logging.getLogger()

def create_master(name, options, config):
    """Creates an AMI instance with the given name and config. The config must specify things like ami id."""
    secrets = json.load(open(options.secrets))
    conn = connect_to_region(options.region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key'],
            )

    # Make sure we don't request the same things twice
    token = str(uuid.uuid4())[:16]

    reservation = conn.run_instances(
            image_id=config['ami'],
            key_name=config['key_name'],
            instance_type=config['instance_type'],
            client_token=token,
            subnet_id=config.get('subnet_id'),
            security_group_ids=config.get('security_group_ids', []),
            )

    instance = reservation.instances[0]
    log.info("instance %s created, waiting to come up", instance)
    # Wait for the instance to come up
    while True:
        try:
            instance.update()
            if instance.state == 'running':
                break
        except:
            log.exception("hit error waiting for instance to come up")
        time.sleep(10)

    instance.add_tag('Name', name)

    log.info("Creating EIP and associating")
    addr = conn.allocate_address("vpc")
    log.info("Got %s", addr)
    conn.associate_address(instance.id, allocation_id=addr.allocation_id)

# TODO: Move this into separate file(s)
configs =  {
    "rhel6": {
        "us-west-1": {
            "ami": "ami-250e5060", # RHEL-6.2-Starter-EBS-x86_64-4-Hourly2
            "subnet_id": "subnet-59e94330",
            "security_group_ids": ["sg-38150854"],
            "instance_type": "c1.medium",
            "key_name": "linux-test-west",
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
            )
    parser.add_option("-c", "--config", dest="config", help="instance configuration to use")
    parser.add_option("-r", "--region", dest="region", help="region to use")
    parser.add_option("-k", "--secrets", dest="secrets", help="file where secrets can be found")
    parser.add_option("-l", "--list", dest="action", action="store_const", const="list", help="list available configs")

    options, args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if options.action == "list":
        for config, regions in configs.items():
            print config, regions.keys()
        # All done!
        raise SystemExit(0)

    if not args:
        parser.error("at least one instance name is required")

    if not options.config:
        parser.error("config name is required")

    if not options.secrets:
        parser.error("secrets are required")

    try:
        config = configs[options.config][options.region]
    except KeyError:
        parser.error("unknown configuration; run with --list for list of supported configs")

    create_master(args[0], options, config)
