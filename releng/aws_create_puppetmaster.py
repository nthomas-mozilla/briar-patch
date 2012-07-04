#!/usr/bin/env python
import json
import uuid
import time

from fabric.api import run, put, env, local
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
    bdm["/dev/sda1"] = BlockDeviceType(delete_on_termination=True)

    reservation = conn.run_instances(
            image_id=config['ami'],
            key_name=options.key_name,
            instance_type=config['instance_type'],
            client_token=token,
            subnet_id=config.get('subnet_id'),
            security_group_ids=config.get('security_group_ids', []),
            block_device_map=bdm,
            placement=zones[0].name,
            disable_api_termination=True,
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
    puppetize(instance, name, options)

def puppetize(instance, name, options):
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
            run("echo '/dev/xvdl /data ext3 rw 0 0' >> /etc/fstab")
            break
        except:
            log.exception("waiting...")
            time.sleep(10)

    flavour = "puppetmaster"
    if options.puppetca:
        flavour = "puppetca"
    # Install puppet
    put("%s/setup/masterize.sh" % options.puppet_dir, "/root/masterize.sh")
    run("mkdir -p /etc/puppet/production")
    local("rsync -e 'ssh -oStrictHostKeyChecking=no' -aP "
          "--exclude repos --delete {puppet_dir}/ "
          "root@{ip}:/etc/puppet/production/".format(
              ip=instance.private_ip_address,
              puppet_dir=options.puppet_dir)
         )
    run("chown -R root:root /etc/puppet/production")
    run("hostname {name}.srv.releng.aws-{region}.mozilla.com".format(
        name=name, region=options.region))

    run("bash /root/masterize.sh")
    run("/usr/bin/puppet apply --modulepath /etc/puppet/production/modules "
        "--manifestdir /etc/puppet/production/manifests "
        "/etc/puppet/production/manifests/%s.pp" % flavour)
    run("echo 127.0.0.1 {name}.srv.releng.aws-{region}.mozilla.com >> /etc/hosts".format(
        name=name, region=options.region))
    if options.puppetca_hostname and options.puppetca_ip:
        puppetca_fqdn = "{name}.srv.releng.aws-{region}.mozilla.com".format(
            name=options.puppetca_hostname, region=options.region)
        run("echo {ip} {puppetca_fqdn} >> /etc/hosts".format(
        ip=options.puppetca_ip, puppetca_fqdn=puppetca_fqdn))
        if not options.puppetca:
            # cert request
            run("find /var/lib/puppet/ssl -type f -delete")
            # XXX: requires manual signing on puppetca
            # puppet cert --allow-dns-alt-names sign
            # puppetmaster-01.srv.releng.aws-us-west-1.mozilla.com
            run("puppetd --onetime --no-daemonize --verbose "
                "--waitforcert 10 --dns_alt_names puppet "
                "--server {puppetca_fqdn} || :".format(
                    puppetca_fqdn=puppetca_fqdn))
    instance.add_tag('moz-state', 'ready')

    #log.info("Creating EIP and associating")
    #addr = conn.allocate_address("vpc")
    #log.info("Got %s", addr)
    #conn.associate_address(instance.id, allocation_id=addr.allocation_id)
    log.info("Got %s", instance.private_ip_address)

# TODO: Move this into separate file(s)
configs =  {
    "centos-6-x86_64-base": {
        "us-west-1": {
            "ami": "ami-696f4a2c", # Centos6
            "subnet_id": "subnet-59e94330",
            "security_group_ids": ["sg-38150854"],
            "instance_type": "c1.medium",
            "repo_snapshot_id": "snap-7c61a71a", # This will be mounted at /data
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
            key_name=None,
            action="create",
            instance=None,
            puppetca=False,
            )
    parser.add_option("-c", "--config", dest="config", help="instance configuration to use")
    parser.add_option("-r", "--region", dest="region", help="region to use")
    parser.add_option("-k", "--secrets", dest="secrets", help="file where secrets can be found")
    parser.add_option("-s", "--key-name", dest="key_name", help="SSH key name")
    parser.add_option("-l", "--list", dest="action", action="store_const", const="list", help="list available configs")
    parser.add_option("-i", "--instance", dest="instance", help="puppetize existing instance")
    parser.add_option("-p", "--puppet-dir", dest="puppet_dir",
                      help="puppet repo directory")
    parser.add_option("--ca", dest="puppetca", action="store_true",
                      help="setup puppet CA")
    parser.add_option("--puppetca-hostname", dest="puppetca_hostname",
                      help="puppet CA hostname")
    parser.add_option("--puppetca-ip", dest="puppetca_ip",
                      help="puppet CA ip")

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

    if not options.puppet_dir:
        parser.error("puppet directory is required")

    if not options.key_name:
        parser.error("ssh key name is required")

    if not options.puppetca and not options.puppetca_hostname:
        parser.error("puppetca hostname is required when setting up puppet master")

    if not options.puppetca and not options.puppetca_ip:
        parser.error("puppetca ip address is required when setting up puppet master")

    secrets = json.load(open(options.secrets))
    conn = connect_to_region(options.region,
            aws_access_key_id=secrets['aws_access_key_id'],
            aws_secret_access_key=secrets['aws_secret_access_key'],
            )

    if options.instance:
        instance = conn.get_all_instances([options.instance])[0].instances[0]
        puppetize(instance, args[0], options)
        raise SystemExit(0)

    if not options.config:
        parser.error("config name is required")

    try:
        config = configs[options.config][options.region]
    except KeyError:
        parser.error("unknown configuration; run with --list for list of supported configs")

    create_master(conn, args[0], options, config)
