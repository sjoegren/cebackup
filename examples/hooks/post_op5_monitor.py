#!/usr/bin/env python3
"""
Send a passive check result with backup creation status to an ITRS OP5 Monitor instance.

Put a config file named "post_op5_monitor.conf" next to this script with contents:

    [op5-monitor]
    server = op5-monitor-host.example.com
    username = api-user
    password = secret
    host_name = name
    service_description = name
"""
import argparse
import configparser
import enum
import logging
import os
import pathlib
import socket

import requests

THIS_FILE = pathlib.Path(__file__)
CONFIG_FILE = THIS_FILE.with_name(THIS_FILE.name.replace(".py", ".conf"))


class OP5Status(enum.Enum):
    OK = 0
    WARNING = 1
    CRITICAL = 2
    UNKNOWN = 3


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        dest="log_level",
        const=logging.DEBUG,
        default=logging.WARNING,
    )
    p.add_argument(
        "--config",
        default=CONFIG_FILE,
        type=pathlib.Path,
        help="Config file (default: %(default)s)",
    )
    args = p.parse_args()
    logging.basicConfig(level=args.log_level)

    cp = configparser.ConfigParser()
    cp.read(args.config)
    config = cp["op5-monitor"]
    logging.debug("config: %s", dict(config))

    if int(os.environ.get("CEBACKUP_OK", 0)):
        status = (
            OP5Status.OK
            if int(os.environ.get("CEBACKUP_BACKUP_CREATED", 0))
            else OP5Status.WARNING
        )
    else:
        status = OP5Status.CRITICAL

    path = os.environ["CEBACKUP_BACKUP_PATH"]
    output = "{}".format(status.name)
    if status == OP5Status.OK:
        output += " - Created {} on {} | archive_size={:.2f}MB".format(
            path, socket.getfqdn(), (os.stat(path).st_size / 1_000_000)
        )

    r = requests.post(
        "https://%(server)s/api/command/PROCESS_SERVICE_CHECK_RESULT" % config,
        headers={"content-type": "application/json"},
        auth=(config["username"], config["password"]),
        json={
            "host_name": config["host_name"],
            "service_description": config["service_description"],
            "status_code": status.value,
            "plugin_output": output,
        },
    )
    logging.debug("Response: %s %s", r.status_code, r.json())
    if r.status_code != requests.codes.OK:
        logging.error("HTTP %s: %s", r.status_code, r.json())


main()
