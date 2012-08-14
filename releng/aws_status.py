#!/usr/bin/env python
"""
Looks up current status of EC2 instances and EBS volumes
"""

try:
    import simplejson as json
except ImportError:
    import json

import boto.ec2

import logging
log = logging.getLogger()

def aws_instance_status(region, secrets, output_report=True):
    "look for currently running/stopped/terminated instances"

    # ideas: figure out how long machines have been off for

    status = {}
    template = {'running': [], 'stopped': []}
    conn = boto.ec2.connect_to_region(region, **secrets)
    reservations = conn.get_all_instances()
    for r in reservations:
        for i in r.instances:
            i_type = i.tags.get('moz-type', 'none set')
            status.setdefault(i_type, template)[i.state].append(i.tags['Name'])
            log.debug("Found %s of type %s, %s" %
                     (i.tags['Name'], i_type, i.state))

    if output_report and status:
        line_format = "%-20s %10s %10s"
        bar_line = '-' * len(line_format % ('', '', ''))
        running = 0
        stopped = 0
        print "\nInstance report for %s:" % region
        print line_format % ("moz-type", "running", "stopped")
        print bar_line
        for k,d in status.items():
            print line_format % (k, len(d['running']), len(d['stopped']))
            running += int(len(d['running']))
            stopped += int(len(d['stopped']))
        print bar_line
        print line_format % ("Total", running, stopped)

    return status

def aws_volume_status(region, secrets, output_report=True):
    "look for currently running/stopped/terminated instances"
    status = {}
    template = {'count': 0, 'total_size': 0}
    conn = boto.ec2.connect_to_region(region, **secrets)
    volumes = conn.get_all_volumes()
    for v in volumes:
        state = v.attachment_state()
        status.setdefault(state, template)
        status[state]['count'] += 1
        status[state]['total_size'] += v.size
        log.debug("Found %s of size %s, %s" %
                 (v.id, v.size, state))

    if output_report and status:
        line_format = "%-20s %10s %10s"
        print "\nVolumes report for %s:" % region
        print line_format % ("attachment state", "count", "size (GB)")
        for k,d in status.items():
            print line_format % (k, d['count'], d['total_size'])

    return status

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.set_defaults(
            regions=[],
            secrets=None,
            loglevel=logging.INFO,
            )

    parser.add_option("-r", "--region", action="append", dest="regions")
    parser.add_option("-k", "--secrets", dest="secrets")
    parser.add_option("-v", "--verbose", action="store_const", dest="loglevel", const=logging.DEBUG)

    options, args = parser.parse_args()

    logging.basicConfig(level=options.loglevel, format="%(asctime)s - %(message)s")
    logging.getLogger("boto").setLevel(logging.INFO)

    if not options.secrets:
        parser.error("secrets are required")
    secrets = json.load(open(options.secrets))

    if not options.regions:
        # Look at all regions
        log.debug("loading all regions")
        options.regions = [r.name for r in boto.ec2.regions(**secrets)]

    for region in options.regions:
        log.info("Checking %s ..." % region)
        aws_instance_status(region, secrets)
        aws_volume_status(region, secrets)