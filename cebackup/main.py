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

from . import BackupException
from . import backup
from . import config
from . import hooks


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
        default=config.DEFAULT_CONFIG_FILE,
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
        help="Skip if there is a backup in archive directory from the last 'days'."
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

    conf = config.get_config(
        pathlib.Path(args.config).expanduser().resolve(strict=True)
    )
    local = conf["local_backup"]

    log_file = args.log_file or conf.get("log_file")
    log_level = args.log_level or conf.get("log_level", "warning").upper()
    timeout = args.timeout or local.get("timeout", 120)

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
        if not local["prune"]:
            logging.warning("backup pruning not configured")
            return False
        backup.cleanup_backups(
            local["directory"],
            local["prune"],
            local["archive_prefix"],
        )
        return True

    if args.skip_if_recent:
        md = backup.Metadata(local["directory"])
        # Add a few hours to the "recent" limit, so that periodic runs exactly
        # 24h after previous run arent't skipped, which would cause the period
        # runs to drift.
        if md.recent_backup_exists(
            time.time() - abs(args.skip_if_recent) * 86400 + 3600 * 8
        ):
            return True

    start = datetime.datetime.now()
    os.environ["CEBACKUP"] = "1"
    tmpdir = pathlib.Path(conf["hook_tmpdir"])
    tmpdir.mkdir(0o700)
    os.environ["CEBACKUP_TMPDIR"] = str(tmpdir)

    post_hooks_env = {
        "CEBACKUP_OK": "0",
        "CEBACKUP_BACKUP_CREATED": "0",
        "CEBACKUP_BACKUP_PATH": "",
        "CEBACKUP_SOURCES": "",
        "CEBACKUP_LOGFILE": logging_kwargs.get("filename", ""),
    }
    logging.info("Start backup")
    try:
        result = backup.make_backup(
            local["directory"],
            local["gpg_public_key"],
            local["prune"],
            local["archive_prefix"],
            local["compression"],
            conf["backup_sources"],
            conf["pre_hooks"],
            timeout,
            local["ignore_file"],
        )
    except Exception:
        logging.debug("", exc_info=True)
        raise
    else:
        logging.log(
            logging.INFO if result.ok else logging.ERROR,
            "Backup finished %sin %s",
            "" if result.ok else "with errors ",
            str(datetime.datetime.now() - start),
        )
        post_hooks_env["CEBACKUP_OK"] = str(int(result.ok))
        post_hooks_env["CEBACKUP_BACKUP_CREATED"] = str(int(result.created))
        if result.meta:
            post_hooks_env["CEBACKUP_BACKUP_PATH"] = os.path.join(
                local["directory"], result.meta["encrypted"]
            )
        if result.paths:
            # Write all used backup sources to file if post_hooks wants to know.
            src_file = tmpdir / "backup_sources"
            with src_file.open("w") as fp:
                for path in result.paths:
                    print(path, file=fp)
            post_hooks_env["CEBACKUP_SOURCES"] = str(src_file)
        return result.ok
    finally:
        os.environ.update(post_hooks_env)
        hooks.call_hooks(conf.get("post_hooks", []))
        logging.debug("removing %s", tmpdir)
        shutil.rmtree(tmpdir.as_posix())


def main():
    try:
        if _main() is True:
            sys.exit(0)
        sys.exit(1)
    except BackupException as exc:
        logging.error(exc._message, *exc._args)
        sys.exit(exc.retcode)
