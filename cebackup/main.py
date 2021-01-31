import argparse
import datetime
import importlib.metadata
import logging
import os.path
import pathlib
import sys

import yaml

from . import BackupException, DEFAULT_CONFIG_FILE
from . import backup


def _main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--debug", action="store_const", dest="log_level", const="DEBUG"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_const", dest="log_level", const="INFO"
    )
    parser.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_FILE,
        help="Specify the YAML config file (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        metavar="SECONDS",
        type=int,
        help="Timeout in seconds for the tar command.",
    )
    parser.add_argument(
        "--log-file",
        help="Log to file (append) instead of stdout.",
    )
    parser.add_argument("--prune-backup-dir", action="store_true")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version="%(prog)s {}".format(importlib.metadata.version(__package__)),
    )
    args = parser.parse_args()

    config_file = pathlib.Path(args.config).expanduser().resolve(strict=True)
    config: dict = yaml.safe_load(config_file.read_bytes())
    config["backup_sources"].append({"path": str(config_file)})
    local = config["local_backup"]

    log_file = args.log_file or config.get("log_file")
    log_level = args.log_level or config.get("log_level", "warning").upper()
    timeout = args.timeout or local.get("timeout", 120)
    tar_ignore_file = local.get("ignore_file", ".cebackup")

    logging_kwargs = {}
    if log_file:
        logging_kwargs["filename"] = os.path.expanduser(log_file)
    else:
        logging_kwargs["stream"] = sys.stdout
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(pathname)s:%(lineno)s [%(funcName)s]: "
        "%(message)s"
        if log_level == "DEBUG"
        else "%(asctime)s %(levelname)-8s %(message)s",
        **logging_kwargs,
    )

    if args.prune_backup_dir:
        backup.prune_backups(
            local["directory"],
            local["prune"]["keep_archives"],
            local["prune"]["keep_days"],
            local["archive_prefix"],
        )
        return True

    start = datetime.datetime.now()
    success = backup.make_backup(
        local["directory"],
        local["gpg_key_id"],
        local["prune"]["keep_archives"],
        local["prune"]["keep_days"],
        local["archive_prefix"],
        local.get("compression", "gzip"),
        config["backup_sources"],
        config.get("pre_hooks", []),
        timeout,
        tar_ignore_file,
    )
    logging.log(
        logging.INFO if success else logging.ERROR,
        "Backup finished %sin %s",
        "" if success else "with errors ",
        str(datetime.datetime.now() - start),
    )

    return success


def main():
    try:
        if _main() is True:
            sys.exit(0)
        sys.exit(1)
    except BackupException as exc:
        logging.error(exc._message, exc._args)
        sys.exit(exc.retcode)
