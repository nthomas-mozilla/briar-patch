#!/usr/bin/env python
import json
import uuid
import time

from fabric.api import run, put, env, sudo
from boto.ec2 import connect_to_region
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType

import logging
log = logging.getLogger()

def assimilate(hostname, config):
    """Assimilate hostname into our collective

    What this means is that hostname will be set up with some basic things like
    a script to grab AWS user data, and get it talking to puppet (which is
    specified in said config).
    """
    env.host_string = hostname
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True

    # Sanity check
    run("date")

    # Resize the file systems
    # We do this because the AMI image usually has a smaller filesystem than
    # the instance has.
    if 'device_map' in config:
        for mapping in config['device_map'].values():
            run('resize2fs {dev}'.format(dev=mapping['instance_dev']))

    # Get puppet installed
    run('rpm -q --info puppetlabs-release || rpm -U http://yum.puppetlabs.com/el/6/products/x86_64/puppetlabs-release-6-1.noarch.rpm')
    run('rpm -q --info puppet || yum install -q -y puppet')
    run('/etc/init.d/puppet stop')

    # Set up user-data thing
    put('user-data.initrd', '/etc/init.d/aws-user-data', mode=0755)
    run('ln -sf /etc/init.d/aws-user-data /etc/rc3.d/S90aws-user-data')
    run('/etc/init.d/aws-user-data')

    # Run puppet
    run("source /etc/aws-user-data && puppetd --server $PUPPET_SERVER --onetime --no-daemonize --verbose --waitforcert 10")

    # Set up a stub buildbot.tac
    sudo("source /etc/aws-user-data && /tools/buildbot/bin/buildslave create-slave /builds/slave $BUILDBOT_MASTER $SLAVE_NAME $SLAVE_PASS", user="cltbld")

    # Start buildbot
    run("/etc/init.d/buildbot start")

def create_instance(name, options, config):
    """Creates an AMI instance with the given name and config. The config must specify things like ami id."""
    secrets = json.load(open(options.secrets))
    conn = connect_to_region(options.region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key'],
            )

    # Make sure we don't request the same things twice
    token = str(uuid.uuid4())[:16]

    user_data = """\
PUPPET_SERVER=ec2-184-169-157-185.us-west-1.compute.amazonaws.com
SLAVE_NAME={name}
SLAVE_PASS=pass
BUILDBOT_MASTER=ip-10-160-145-93.us-west-1.compute.internal
""".format(name=name)

    bdm = None
    if 'device_map' in config:
        bdm = BlockDeviceMapping()
        for device, device_info in config['device_map'].items():
            bdm[device] = BlockDeviceType(size=device_info['size'])

    reservation = conn.run_instances(
            image_id=config['ami'],
            key_name=config['key_name'],
            user_data=user_data,
            instance_type=config['instance_type'],
            block_device_map=bdm,
            client_token=token,
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

    log.info("assimilating %s", instance)
    instance.add_tag('moz-state', 'assimilating')
    while True:
        try:
            assimilate(instance.public_dns_name, config)
            break
        except:
            log.exception("problem assimilating %s", instance)
            time.sleep(10)
    instance.add_tag('moz-state', 'running')

def make_instances(names, options, config):
    """Create instances for each name of names for the given configuration"""
    for name in names:
        create_instance(name, options, config)

# TODO: Move this into separate file(s)
configs =  {
    "rhel6-mock": {
        "us-west-1": {
            "ami": "ami-250e5060", # RHEL-6.2-Starter-EBS-x86_64-4-Hourly2
            "instance_type": "c1.xlarge",
            "key_name": "linux-test-west",
            "device_map": {
                "/dev/sda1": {
                    "size": 100,
                    "instance_dev": "/dev/xvde1",
                },
            },
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

    make_instances(args, options, config)
