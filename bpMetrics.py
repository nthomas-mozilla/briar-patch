#!/usr/bin/env python

""" bpMetrics

    :copyright: (c) 2012 by Mozilla
    :license: MPLv2

    Assumes Python v2.6+

    Usage
        -c --config         Configuration file (json format)
                            default: None
           --address        IP Address
                                127.0.0.1 or 127.0.0.1:5555
                            Required Value
        -r --redis          Redis server connection string
                            default: localhost:6379
           --redisdb        Redis database ID
                            default: 8
        -d --debug          Turn on debug logging
                            default: False
        -l --logpath        Path where the log file output is written
                            default: None
        -b --background     Fork to a daemon process
                            default: False
           --graphite       host:port where Graphite's carbon-cache service is running

    Sample Configuration file

        { 'redis': 'localhost:6379',
          'debug': True,
          'logpath': '.'
        }

    Authors:
        bear    Mike Taylor <bear@mozilla.com>
"""

import os, sys
import json
import time
import socket
import logging

from Queue import Empty
from multiprocessing import Process, Queue, current_process, get_logger, log_to_stderr

import zmq

from releng import initOptions, initLogs, dbRedis
from releng.metrics import Metric
from releng.constants import PORT_METRICS, ID_METRICS_WORKER, \
                             METRICS_COUNT, METRICS_TIME, METRICS_SET


log      = get_logger()
jobQueue = Queue()


def worker(jobQueue, graphite, db):
    log.info('starting')

    metrics = Metric(graphite)

    while True:
        try:
            job = jobQueue.get(False)
        except Empty:
            job = None

        if job is not None:
            try:
                jobs = json.loads(job)

                for item in jobs:
                    metric, data = item
                    log.debug('%s [%s]' % (metric, data))
                    if metric == METRICS_COUNT:
                        # data will be a tuple of two values
                        #   ('group', 'key')
                        # group will be sent standalone to count overall totals
                        # if key has any sub-items, denoted by ':' then it will
                        #   be sent standalone also
                        # key will transformed to "." notation to take advantage of
                        #   Graphite's built-in rules
                        #
                        # c [build:finished:slave, talos-r3-xp-039]
                        #
                        group = data[0]
                        key   = data[1]

                        metrics.count('bp:metrics.counts')
                        metrics.count('%s.%s' % (group, key))
                        metrics.count(group)

                        if ':' in group:
                            subgroups = group.split(':', 1)
                            metrics.count('%s.%s' % (subgroups[0], subgroups[1]))

                    elif metric == METRICS_SET:
                        metrics.count('bp:metrics.sets')
                        if len(data) == 3:
                            log.debug('setting %s %s to %s' % (data[0], data[1], data[2]))
                            db.hset(data[0], data[1], data[2])
            except:
                log.error('Error converting incoming job to json', exc_info=True)

            metrics.check()

    log.info('done')


_defaultOptions = { 'config':      ('-c', '--config',      None,             'Configuration file'),
                    'debug':       ('-d', '--debug',       True,             'Enable Debug', 'b'),
                    'background':  ('-b', '--background',  False,            'daemonize ourselves', 'b'),
                    'logpath':     ('-l', '--logpath',     None,             'Path where log file is to be written'),
                    'redis':       ('-r', '--redis',       'localhost:6379', 'Redis connection string'),
                    'redisdb':     ('',   '--redisdb',     '8',              'Redis database'),
                    'address':     ('',   '--address' ,    None,             'IP Address'),
                    'graphite':    ('',   '--graphite',    None,             "host:port where Graphite's carbon-cache service is running")
                  }

if __name__ == '__main__':
    options = initOptions(_defaultOptions)
    initLogs(options)

    log.info('Starting')

    if options.address is None:
        log.error('Address is a required parameter, exiting')
        sys.exit(2)

    log.info('Connecting to datastore')
    db = dbRedis(options)

    if db.ping():
        log.info('Creating processes')
        Process(name='worker', target=worker, args=(jobQueue, options.graphite, db)).start()

        if ':' not in options.address:
            options.address = '%s:%s' % (options.address, PORT_METRICS)

        log.debug('binding to tcp://%s' % options.address)

        context = zmq.Context()
        server  = context.socket(zmq.ROUTER)

        server.identity = '%s:%s' % (ID_METRICS_WORKER, options.address)
        server.bind('tcp://%s' % options.address)

        log.info('Adding %s to the list of active servers' % server.identity)
        db.rpush(ID_METRICS_WORKER, server.identity)

        while True:
            try:
                request = server.recv_multipart()
            except:
                log.error('error raised during recv_multipart()', exc_info=True)
                break

            # [ destination, sequence, control, payload ]
            address, sequence, control = request[:3]
            reply = [address, sequence]

            if control == 'ping':
                reply.append('pong')
            else:
                reply.append('ok')
                jobQueue.put(request[3])

            server.send_multipart(reply)

        log.info('Removing ourselves to the list of active servers')
        db.lrem(ID_METRICS_WORKER, 0, server.identity)
    else:
        log.error('Unable to reach the database')

    log.info('done')

