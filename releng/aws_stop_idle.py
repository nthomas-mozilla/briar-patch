#!/usr/bin/env python
"""
Watches running EC2 instances and shuts them down when idle
"""
import re
import time
try:
    import simplejson as json
except ImportError:
    import json

import boto.ec2
from paramiko import SSHClient
import requests

import logging
log = logging.getLogger()

def get_buildbot_instances(conn):
    # Look for instances with moz-state=ready and hostname *-ec2-000
    reservations = conn.get_all_instances(filters={
        'tag:moz-state': 'ready',
        'instance-state-name': 'running',
        })

    retval = []
    for r in reservations:
        for i in r.instances:
            name = i.tags['Name']
            if not re.match(".*-ec2-\d+", name):
                continue
            retval.append(i)

    return retval

class IgnorePolicy:
    def missing_host_key(self, client, hostname, key):
        pass

def get_ssh_client(name, ip, passwords):
    client = SSHClient()
    client.set_missing_host_key_policy(IgnorePolicy())
    for p in passwords:
        try:
            client.connect(hostname=ip, username='cltbld', password=p)
            return client
        except:
            pass

    raise ValueError("Couldn't log into {name} at {ip} with any known passwords".format(name=name, ip=ip))

def get_last_activity(name, client):
    stdin, stdout, stderr = client.exec_command("date +%Y%m%d%H%M%S")
    slave_time = stdout.read().strip()
    slave_time = time.mktime(time.strptime(slave_time, "%Y%m%d%H%M%S"))

    stdin, stdout, stderr = client.exec_command("tail -100 /builds/slave/twistd.log")
    stdin.close()

    last_activity = 0
    running_command = False
    for line in stdout:
        t = re.search("^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if t:
            t = time.strptime(t.group(1), "%Y-%m-%d %H:%M:%S")
            t = time.mktime(t)

        # uncomment to dump out ALL the lines
        #log.debug("%s - %s", name, line.strip())

        if "RunProcess._startCommand" in line:
            log.debug("%s - started command - %s", name, line.strip())
            running_command = True
        elif "commandComplete" in line or "stopCommand" in line:
            log.debug("%s - done command - %s", name, line.strip())
            running_command = False

        if "Shut Down" in line:
            last_activity = "stopped"
        elif running_command:
            # We're in the middle of running something, so say that our last
            # activity is now (0 seconds ago)
            last_activity = 0
        else:
            last_activity = slave_time - t

    log.debug("%s - %s - %s", name, last_activity, line.strip())
    return last_activity

def get_tacfile(client):
    stdin, stdout, stderr = client.exec_command("cat /builds/slave/buildbot.tac")
    stdin.close()
    data = stdout.read()
    return data

def get_buildbot_master(client):
    tacfile = get_tacfile(client)
    host = re.search("^buildmaster_host = '(.*?)'$", tacfile, re.M)
    port = re.search("^port = (\d+)", tacfile, re.M)
    assert host and port
    host = host.group(1)
    port = int(port.group(1))
    return host, port

def graceful_shutdown(name, ip, client):
    # Find out which master we're attached to by looking at buildbot.tac
    log.debug("%s - looking up which master we're attached to", name)
    host, port = get_buildbot_master(client)
    # http port is pb port -1000
    port -= 1000

    url = "http://{host}:{port}/buildslaves/{name}/shutdown".format(host=host, port=port, name=name)
    log.debug("%s - POSTing to %s", name, url)
    r = requests.post(url, allow_redirects=False)

def aws_stop_idle(secrets, passwords, regions):
    if not regions:
        # Look at all regions
        log.debug("loading all regions")
        regions = [r.name for r in boto.ec2.regions(**secrets)]

    min_running_by_type = 1

    for r in regions:
        log.debug("looking at region %s", r)
        conn = boto.ec2.connect_to_region(r, **secrets)

        instances = get_buildbot_instances(conn)
        instances_by_type = {}
        for i in instances:
            # TODO: Check if launch_time is too old, and terminate the instance
            # if it is
            # NB can't turn this on until aws_create_instance is working properly (with ssh keys)
            instances_by_type.setdefault(i.tags['moz-type'], []).append(i)

        # Make sure min_running_by_type are kept running
        for t in instances_by_type:
            to_remove = instances_by_type[t][:min_running_by_type]
            for i in to_remove:
                log.debug("%s - keep running (min %i instances of type %s)", i.tags['Name'], min_running_by_type, i.tags['moz-type'])
                instances.remove(i)

        for i in instances:
            name = i.tags['Name']
            # TODO: Check with slavealloc

            ip = i.private_ip_address
            ssh_client = get_ssh_client(name, ip, passwords)
            last_activity = get_last_activity(name, ssh_client)
            if last_activity == "stopped":
                log.info("%s - stopping instance", name)
                i.stop()
                continue

            log.debug("%s - last activity %is ago", name, last_activity)
            # Determine if the machine is idle for more than 10 minutes
            if last_activity > 300:
                # Hit graceful shutdown on the master
                log.info("%s - starting graceful shutdown", name)
                graceful_shutdown(name, ip, ssh_client)

                # Check if we've exited right away
                if get_last_activity(name, ssh_client) == "stopped":
                    log.info("%s - stopping instance", name)
                    i.stop()
            else:
                log.debug("%s - not stopping", name)

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.set_defaults(
            regions=[],
            secrets=None,
            passwords=None,
            loglevel=logging.INFO,
            )

    parser.add_option("-r", "--region", action="append", dest="regions")
    parser.add_option("-k", "--secrets", dest="secrets")
    parser.add_option("-s", "--key-name", dest="key_name")
    parser.add_option("-v", "--verbose", action="store_const", dest="loglevel", const=logging.DEBUG)
    parser.add_option("-p", "--paswords", dest="passwords")

    options, args = parser.parse_args()

    logging.basicConfig(level=options.loglevel, format="%(asctime)s - %(message)s")
    logging.getLogger("boto").setLevel(logging.INFO)
    logging.getLogger("paramiko").setLevel(logging.WARN)

    if not options.secrets:
        parser.error("secrets are required")

    if not options.passwords:
        parser.error("passwords are required")

    secrets = json.load(open(options.secrets))
    passwords = json.load(open(options.passwords))

    aws_stop_idle(secrets, passwords, options.regions)
