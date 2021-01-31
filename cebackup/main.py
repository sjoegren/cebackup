import argparse
import datetime
import importlib.metadata
import logging
import os
import os.path
import pathlib
import shutil
import sys
import time

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
    parser.add_argument(
        "--log-stdout",
        action="store_true",
        help="Override log_file from config.",
    )
    parser.add_argument(
        "--skip-if-recent",
        metavar="days",
        nargs="?",
        const=1,
        type=int,
        help="Skip if there are a backup in archive directory from the last 'days'."
        " If no argument given, defaults to %(const)s",
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
    if log_file and not args.log_stdout:
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

    if args.skip_if_recent:
        md = backup.Metadata(
            pathlib.Path(local["directory"]).expanduser().resolve(strict=False)
        )
        if md.recent_backup_exists(time.time() - abs(args.skip_if_recent) * 86400):
            return True

    start = datetime.datetime.now()
    os.environ["CEBACKUP"] = "1"
    tmpdir = pathlib.Path(local.get("tmpdir", pathlib.Path.home() / "cebackup-tmpdir"))
    tmpdir.mkdir(0o755)
    os.environ["CEBACKUP_TMPDIR"] = str(tmpdir)

    logging.info("Start backup")
    try:
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
    except Exception:
        logging.debug("", exc_info=True)
        raise
    else:
        logging.log(
            logging.INFO if success else logging.ERROR,
            "Backup finished %sin %s",
            "" if success else "with errors ",
            str(datetime.datetime.now() - start),
        )
        return success
    finally:
        logging.debug("removing %s", tmpdir)
        shutil.rmtree(tmpdir.as_posix())


def main():
    try:
        if _main() is True:
            sys.exit(0)
        sys.exit(1)
    except BackupException as exc:
        logging.error(exc._message, exc._args)
        sys.exit(exc.retcode)
