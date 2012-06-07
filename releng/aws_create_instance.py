#!/usr/bin/env python
import json
import uuid
import time

from fabric.api import run, put, env, sudo, settings
from boto.ec2 import connect_to_region
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType

import logging
log = logging.getLogger()

def assimilate(ip_addr, config, instance_data, cleanup):
    """Assimilate hostname into our collective

    What this means is that hostname will be set up with some basic things like
    a script to grab AWS user data, and get it talking to puppet (which is
    specified in said config).
    """
    env.host_string = ip_addr
    env.user = 'root'
    env.abort_on_prompts = True
    env.disable_known_hosts = True

    # Sanity check
    run("date")

    # Set our hostname
    run("hostname {hostname}".format(**instance_data))

    # Resize the file systems
    # We do this because the AMI image usually has a smaller filesystem than
    # the instance has.
    if 'device_map' in config:
        for mapping in config['device_map'].values():
            run('resize2fs {dev}'.format(dev=mapping['instance_dev']))

    # Set up /etc/hosts to talk to 'puppet'
    run('echo "127.0.0.1 localhost.localdomain localhost\n::1 localhost6.localdomain6 localhost6\n{puppet_ip} puppet\n" > /etc/hosts'.format(**instance_data))

    # Set up yum repos
    run('rm -f /etc/yum.repos.d/*')
    put('releng-public.repo', '/etc/yum.repos.d/releng-public.repo')
    run('yum clean all')

    # Get puppet installed
    run('yum install -q -y puppet')

    # Run puppet
    # We need --detailed-exitcodes here otherwise puppet will return 0
    # sometimes when it fails to install dependencies
    with settings(warn_only=True):
        result = run("puppetd --server puppet --onetime --no-daemonize --verbose --detailed-exitcodes --waitforcert 10")
        assert result.return_code in (0,2)

    if cleanup:
        run('find /var/lib/puppet/ssl -type f -delete')
        return

    # Set up a stub buildbot.tac
    sudo("/tools/buildbot/bin/buildslave create-slave /builds/slave {buildbot_master} {name} {buildslave_password}".format(**instance_data), user="cltbld")

    # Start buildbot
    run("/etc/init.d/buildbot start")

def create_instance(name, config, region, secrets, cleanup):
    """Creates an AMI instance with the given name and config. The config must specify things like ami id."""
    conn = connect_to_region(region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key'],
            )

    # Make sure we don't request the same things twice
    token = str(uuid.uuid4())[:16]

    instance_data = {
            'puppet_ip': '10.130.236.242',
            'name': name,
            'buildbot_master': '10.12.48.14:9049',
            'buildslave_password': 'pass',
            'hostname': '{name}.releng.aws-{region}.mozilla.com'.format(name=name, region=region),
            }

    bdm = None
    if 'device_map' in config:
        bdm = BlockDeviceMapping()
        for device, device_info in config['device_map'].items():
            bdm[device] = BlockDeviceType(size=device_info['size'], delete_on_termination=True)

    reservation = conn.run_instances(
            image_id=config['ami'],
            key_name=config['key_name'],
            instance_type=config['instance_type'],
            block_device_map=bdm,
            client_token=token,
            subnet_id=config.get('subnet_id'),
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
    instance.add_tag('moz-type', config['type'])

    log.info("assimilating %s", instance)
    instance.add_tag('moz-state', 'pending')
    while True:
        try:
            if instance.subnet_id:
                assimilate(instance.private_ip_address, config, instance_data, cleanup)
            else:
                assimilate(instance.public_dns_name, config, instance_data, cleanup)
            break
        except:
            log.exception("problem assimilating %s", instance)
            time.sleep(10)
    if not cleanup:
        instance.add_tag('moz-state', 'ready')
    else:
        ami_from_instance(instance)

def ami_from_instance(instance):
    base_ami = instance.connection.get_image(instance.image_id)
    target_name = '%s-ready' % base_ami.name
    v = instance.connection.get_all_volumes(
        filters={'attachment.instance-id': instance.id})[0]
    instance.stop()
    while True:
        try:
            instance.update()
            if instance.state == 'stopped':
                break
        except:
            log.info('Waiting for instance stop')
            time.sleep(10)
    snapshot = v.create_snapshot('EBS-backed %s' % target_name)
    while True:
        try:
            snapshot.update()
            if snapshot.status == 'completed':
                break
        except:
            log.exception('hit error waiting for snapshot to be taken')
            time.sleep(10)
    snapshot.add_tag('Name', target_name)

    log.info('Creating AMI')
    block_map = BlockDeviceMapping()
    block_map[base_ami.root_device_name] = BlockDeviceType(
        snapshot_id=snapshot.id)
    instance.connection.register_image(
        target_name,
        '%s EBS AMI' % target_name,
        architecture=base_ami.architecture,
        kernel_id=base_ami.kernel_id,
        ramdisk_id=base_ami.ramdisk_id,
        root_device_name=base_ami.root_device_name,
        block_device_map=block_map,
    )
    instance.terminate()

import multiprocessing
import sys

class LoggingProcess(multiprocessing.Process):
    def __init__(self, log, *args, **kwargs):
        self.log = log
        super(LoggingProcess, self).__init__(*args, **kwargs)

    def run(self):
        output = open(self.log, 'wb', 0)
        logging.basicConfig(stream=output)
        sys.stdout = output
        sys.stderr = output
        return super(LoggingProcess, self).run()

def make_instances(names, config_name, region, secrets, cleanup):
    """Create instances for each name of names for the given configuration"""
    procs = []
    config = configs[config_name][region]
    for name in names:
        p = LoggingProcess(log="{name}.log".format(name=name),
                           target=create_instance,
                           args=(name, config, region, secrets, cleanup),
                           )
        p.start()
        procs.append(p)

    log.info("waiting for workers")
    for p in procs:
        p.join()

# TODO: Move this into separate file(s)
configs =  {
    "rhel6-mock": {
        "us-west-1": {
            "type": "rhel6-mock",
            "ami": "ami-250e5060", # RHEL-6.2-Starter-EBS-x86_64-4-Hourly2
            "subnet_id": "subnet-59e94330",
            "security_group_ids": [],
            "instance_type": "c1.xlarge",
            "key_name": "linux-test-west",
            "device_map": {
                "/dev/sda1": {
                    "size": 50,
                    "instance_dev": "/dev/xvde1",
                },
            },
        },
    },
    "centos-6-x86_64-build": {
        "us-west-1": {
            "type": "centos-6-x86_64-build",
            "ami": "ami-19b6ec5c",
            "subnet_id": "subnet-59e94330",
            "security_group_ids": [],
            "instance_type": "c1.xlarge",
            "key_name": "rail-test",
            "device_map": {
                "/dev/sda1": {
                    "size": 50,
                    "instance_dev": "/dev/xvde1",
                },
            },
        },
    },
    "centos-6-x86_64-base": {
        "us-west-1": {
            "type": "centos-6-x86_64-base",
            "ami": "ami-ffbce6ba",
            "subnet_id": "subnet-59e94330",
            "security_group_ids": [],
            "instance_type": "c1.xlarge",
            "key_name": "rail-test",
            "device_map": {
                "/dev/sda1": {
                    "size": 5,
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
            cleanup=False,
            )
    parser.add_option("-c", "--config", dest="config", help="instance configuration to use")
    parser.add_option("-r", "--region", dest="region", help="region to use")
    parser.add_option("-k", "--secrets", dest="secrets", help="file where secrets can be found")
    parser.add_option("-l", "--list", dest="action", action="store_const", const="list", help="list available configs")
    parser.add_option("--cleanup", dest="cleanup", action="store_true", help="cleanup instance")

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

    secrets = json.load(open(options.secrets))
    make_instances(args, options.config, options.region, secrets, options.cleanup)
