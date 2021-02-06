import glob
import hashlib
import json
import logging as log
import os
import os.path
import pathlib
import shlex
import subprocess
import time
from collections import namedtuple

from typing import List, Dict, Iterable, Optional, Any

from . import BackupException
from . import hooks

Result = namedtuple("Result", "ok, created, meta, paths", defaults=(False, {}, []))


class BackupArchive:
    def __init__(
        self, backup_dir: pathlib.Path, prefix: str, compression: str, timeout: int = 60
    ):
        self.backup_dir = backup_dir
        self.prefix = prefix
        self.timeout = timeout
        self.time = int(time.time())
        self.compress_args = shlex.split(compression)
        self.archivename = "{}_{}_{}.tar".format(
            prefix,
            self.time,
            time.strftime("%Y%m%dT%H%M%S", time.localtime(self.time)),
        )
        self.compressed_file = None
        self.tar_flags = [
            "--exclude-vcs",
            "--exclude-vcs-ignores",
            "--verbose",
            "--file",
            str(self),
        ]
        self._added_paths = set()
        self.failed = set()

    def __str__(self):
        return str(self.backup_dir / self.archivename)

    @property
    def path_encrypted(self):
        return self.backup_dir / (self.compressed_file.name + ".gpg")

    def unlink(self):
        self.compressed_file.unlink()

    def make_checksum(self):
        assert self.compressed_file.exists()
        checksum = hashlib.sha256()
        bufsize = 32 * 1024 ** 2
        with self.compressed_file.open("rb") as tarfile:
            data = tarfile.read(bufsize)
            while data:
                checksum.update(data)
                data = tarfile.read(bufsize)
        log.info("Archive sha256 checksum: %s", checksum.hexdigest())
        return checksum.hexdigest()

    def add(self, path: str):
        cmdargs = ["tar", "--append" if self._added_paths else "--create"]
        cmdargs += self.tar_flags
        cmdargs.append(path)
        log.debug("Run %s", " ".join(cmdargs))
        try:
            p = subprocess.run(
                cmdargs, capture_output=True, text=True, timeout=self.timeout
            )
        except subprocess.TimeoutExpired as exc:
            log.critical(
                "Timed out while creating backup archive, cmd: %s, stderr: %s",
                exc.cmd,
                exc.stderr,
            )
            self.failed.add(path)
            return
        if p.returncode != 0:
            log.debug("stdout: %s", p.stdout)
            self.failed.add(path)
            log.error("cmd %s, stderr: %s", p.args, p.stderr)
        else:
            self._added_paths.add(path)

    def compress(self, timeout):
        cmd = self.compress_args + [str(self)]
        log.info("Compressing archive: %s", shlex.join(cmd))
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.exception(
                "Failed to compress archive, cmd: %s, stdout: %s, stderr: %s",
                exc.cmd,
                exc.stdout,
                exc.stderr,
            )
            raise BackupException("failed to compress archive")
        self.compressed_file = next(self.backup_dir.glob(f"{self.archivename}*"))


class Metadata:
    CHECKSUM_FILE = "metadata.json"

    def __init__(self, backup_dir: pathlib.Path):
        self._backup_dir = backup_dir
        self._file = backup_dir / self.CHECKSUM_FILE
        self._archives = []
        self._checksums = {}
        if self._file.exists():
            with self._file.open("r") as fp:
                self._archives = json.load(fp)
            log.debug("Loaded %d checksums", len(self._archives))
            self._set_checksums()

    def _set_checksums(self):
        self._checksums = {x["open-checksum"]: x for x in self._archives}

    def write(self):
        self._archives.sort(key=lambda arch: arch["touched"])
        self._set_checksums()
        with self._file.open("w") as file_:
            json.dump(self._archives, file_, indent=4)
        log.info("Wrote %d checksums to %s", len(self._archives), self._file)

    def get_archive(self, chk) -> Optional[Dict[str, Any]]:
        """Return archive dict or None if chk doesn't exist."""
        return self._checksums.get(chk)

    def recent_backup_exists(self, timestamp: int) -> bool:
        """Return True if there is a backup created more recently than timestamp."""
        for arch in self._archives:
            if (
                arch["created"] > timestamp
                and (self._backup_dir / arch["encrypted"]).exists()
            ):
                log.debug(
                    "Backup newer than %s exists: %s", time.ctime(timestamp), arch
                )
                return True
        return False

    def get_from_encrypted_name(self, path: pathlib.Path):
        for arch in self._archives:
            if arch["encrypted"] == path.name:
                return arch
        raise BackupException("No metadata found for %s", path)

    def remove(self, chk):
        arch = self._checksums.pop(chk)
        self._archives.remove(arch)

    def add(self, chk, archive):
        if (arch := self._checksums.get(chk)) :
            arch["touched"] = time.time()
            log.debug("Update touched timestamp for %s", arch)
            return
        log.debug("Store new archive: %s", archive.compressed_file)
        self._archives.append(
            {
                "archive": archive.compressed_file.name,
                "encrypted": archive.path_encrypted.name,
                "open-checksum": chk,
                "created": archive.time,
                "touched": archive.time,
            }
        )
        self._set_checksums()


def make_backup(
    destdir: str,
    gpg_key_id: str,
    keep_backups: int,
    keep_days: int,
    prefix: str,
    compression: str,
    sources: List[dict],
    pre_hooks: List[str],
    timeout: int,
    tar_ignore_file: str,
):
    log.debug(
        "destdir: %s, gpg_key_id: %s, keep_backups: %d",
        destdir,
        gpg_key_id,
        keep_backups,
    )
    backup_dir = pathlib.Path(destdir).expanduser().resolve(strict=False)
    backup_dir.mkdir(exist_ok=True)
    checksums = Metadata(backup_dir)

    paths = make_source_list(sources)
    failure = False
    if pre_hooks:
        success, extra_paths = hooks.call_hooks(pre_hooks)
        log.debug("Got %d paths from hooks", len(extra_paths))
        paths += extra_paths
        if not success:
            failure = True
    paths.sort()
    log.debug("Paths to include in archive:\n%s", "\n  ".join(paths))

    archive = BackupArchive(backup_dir, prefix, compression)
    log.info("Create archive %s", archive.archivename)
    archive.tar_flags.append("--exclude-ignore-recursive=" + tar_ignore_file)
    timeout_ = time.monotonic() + timeout
    # Append paths to tar archive one by one so that timeout can be checked
    # between paths.
    for path in paths:
        log.debug("Add %s to %s", path, archive.archivename)
        if time.monotonic() >= timeout_:
            log.error("Timeout (%d sec) reached", timeout)
            archive.failed.add(path)
            break
        archive.add(path)
    archive.compress(timeout)

    checksum = archive.make_checksum()
    if (existing := checksums.get_archive(checksum)) :
        log.info(
            "An archive with the same checksum already exist: %s, skipping.",
            backup_dir / existing["archive"],
        )
        if (backup_dir / existing["encrypted"]).exists():
            (backup_dir / existing["encrypted"]).touch()
            archive.unlink()
            checksums.add(checksum, archive)
            checksums.write()
            return Result(not failure)
        else:
            log.warning(
                "Expected %s to exist, but it doesn't. Remove from checksum file.",
                existing["encrypted"],
            )
            checksums.remove(checksum)

    checksums.add(checksum, archive)
    checksums.write()

    log.info("Encrypt archive %s", archive.compressed_file)
    cmdargs = [
        "gpg",
        "--encrypt",
        "--recipient",
        gpg_key_id,
        "--verbose",
        "--output",
        archive.path_encrypted.as_posix(),
        archive.compressed_file.as_posix(),
    ]
    log.debug("Run %s", cmdargs)
    p = subprocess.run(cmdargs, capture_output=True, text=True)
    log.log(log.ERROR if p.returncode else log.DEBUG, "stdout: %s", p.stdout)
    log.log(log.ERROR if p.returncode else log.DEBUG, "stderr: %s", p.stdout)
    p.check_returncode()

    archive.unlink()

    if archive.failed:
        log.error("Failed to archive some paths: %s", archive.failed)
        return Result(False, True, checksums.get_archive(checksum), paths)

    prune_backups(destdir, keep_backups, keep_days, prefix)
    return Result(not failure, True, checksums.get_archive(checksum), paths)


def prune_backups(destdir, keep_backups, keep_days, prefix):
    """Delete backup files from disk and metadata, except the `keep_backups` newest.

    A backup file must also be older than `keep_days` to be deleted.
    """
    backup_dir = pathlib.Path(destdir).expanduser().resolve(strict=False)
    if not backup_dir.is_dir():
        log.warning("No such directory: %s", backup_dir)
        return None
    checksums = Metadata(backup_dir)
    backups = [
        f
        for f in backup_dir.iterdir()
        if f.is_file() and f.name.startswith(prefix) and f.name.endswith(".gpg")
    ]
    backups.sort(key=lambda f: f.name, reverse=True)
    age_limit = time.time() - keep_days * 86400
    log.info("Delete backup archives older than %s", time.ctime(age_limit))
    for bk in backups[keep_backups:]:
        log.debug("consider for deletion: %s", bk.name)
        meta = checksums.get_from_encrypted_name(bk)
        if meta["touched"] < age_limit:
            log.info("Removing %s, timestamp: %s", bk.name, time.ctime(meta["touched"]))
            bk.unlink()
            checksums.remove(meta["open-checksum"])
        else:
            log.debug(
                "not deleting %s, last touched %s", bk.name, time.ctime(meta["touched"])
            )
    checksums.write()


def make_source_list(sources: Iterable[dict]) -> List[str]:
    ret = []
    for src in sources:
        try:
            path = os.path.expanduser(src["path"])
        except KeyError as exc:
            raise BackupException("Invalid source specification: %s, %s", exc, src)
        skip_dirs = src.get("skip_dirs", False)
        for p in glob.iglob(path, recursive=not skip_dirs):
            if skip_dirs and os.path.isdir(p):
                log.debug("Skip directory %s", p)
                continue
            log.debug("Add: %s", p)
            ret.append(os.path.normpath(p))
    return ret
