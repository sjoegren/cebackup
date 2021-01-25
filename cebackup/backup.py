import logging as log
import glob
import hashlib
import json
import pathlib
import os
import os.path
import subprocess
import time
from collections import abc

from typing import List, Dict, Iterable, Optional, Any

from . import BackupException

_COMPRESSION_MAP = {
    "xz": ("xz", "--xz"),
    "bzip2": ("bz2", "--bzip2"),
    "gzip": ("gz", "--gzip"),
}


class BackupArchive:
    def __init__(self, backup_dir: pathlib.Path, prefix: str, compression: str):
        self.backup_dir = backup_dir
        self.prefix = prefix
        self.time = int(time.time())
        try:
            self.file_ext = _COMPRESSION_MAP[compression][0]
            self.tar_flags = [_COMPRESSION_MAP[compression][1]]
        except KeyError:
            raise BackupException("Invalid compression type: %s", compression)
        self.archivename = "{}_{}_{}.tar.{}".format(
            prefix,
            self.time,
            time.strftime("%Y%m%dT%H%M%S", time.localtime(self.time)),
            self.file_ext,
        )
        self.path_encrypted = self.backup_dir / f"{self.archivename}.gpg"

    def __str__(self):
        return str(self.backup_dir / self.archivename)

    def unlink(self):
        os.unlink(str(self))

    def exists(self):
        return (self.backup_dir / self.archivename).exists()

    def make_checksum(self):
        assert self.exists()
        checksum = hashlib.sha256()
        bufsize = 32 * 1024 ** 2
        with (self.backup_dir / self.archivename).open("rb") as tarfile:
            data = tarfile.read(bufsize)
            while data:
                checksum.update(data)
                data = tarfile.read(bufsize)
            assert data == b""
        log.info("Archive sha256 checksum: %s", checksum.hexdigest())
        return checksum.hexdigest()


class Checksums:
    CHECKSUM_FILE = "metadata.json"

    def __init__(self, backup_dir: pathlib.Path):
        self._file = backup_dir / self.CHECKSUM_FILE
        self._archives = []
        self._checksums = {}
        if self._file.exists():
            with self._file.open("r") as fp:
                self._archives = json.load(fp)
            log.debug("Loaded %d checksums", len(self._archives))
            self._set_checksums()

    def _set_checksums(self):
        self._checksums = {x["sha256"]: x for x in self._archives}

    def write(self):
        with self._file.open("w") as file_:
            json.dump(self._archives, file_, indent=4)
        log.info("Wrote %d checksums to %s", len(self._archives), self._file)

    def get_archive(self, chk) -> Optional[Dict[str, Any]]:
        """Return archive dict or None if chk doesn't exist."""
        return self._checksums.get(chk)

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
        log.debug("Store new archive: %s", archive)
        self._archives.append(
            {
                "archive": archive.archivename,
                "encrypted": archive.path_encrypted.name,
                "sha256": chk,
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
    hooks: List[str],
):
    log.debug(
        "destdir: %s, gpg_key_id: %s, keep_backups: %d",
        destdir,
        gpg_key_id,
        keep_backups,
    )
    backup_dir = pathlib.Path(destdir).expanduser().resolve(strict=False)
    backup_dir.mkdir(exist_ok=True)
    checksums = Checksums(backup_dir)

    archive = BackupArchive(backup_dir, prefix, compression)
    log.info("Create archive %s", archive.archivename)
    cmdargs = ["tar", *archive.tar_flags, "-cvf", str(archive)]
    cmdargs += make_source_list(sources)
    cmdargs += call_hooks(hooks)
    log.debug("Run %s", cmdargs)
    p = subprocess.run(cmdargs, capture_output=True, text=True)
    if p.returncode != 0:
        log.debug("stdout: %s", p.stdout)
    log.log(log.ERROR if p.returncode else log.DEBUG, "stderr: %s", p.stderr)
    p.check_returncode()

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
            return
        else:
            log.warning(
                "Expected %s to exist, but it doesn't. Remove from checksum file.",
                existing["encrypted"],
            )
            checksums.remove(checksum)

    checksums.add(checksum, archive)
    checksums.write()

    log.info("Encrypt archive %s", archive.archivename)
    cmdargs = [
        "gpg",
        "--encrypt",
        "--recipient",
        gpg_key_id,
        "--verbose",
        "--output",
        archive.path_encrypted.as_posix(),
        str(archive),
    ]
    log.debug("Run %s", cmdargs)
    p = subprocess.run(cmdargs, capture_output=True, text=True)
    log.log(log.ERROR if p.returncode else log.DEBUG, "stdout: %s", p.stdout)
    log.log(log.ERROR if p.returncode else log.DEBUG, "stderr: %s", p.stdout)
    p.check_returncode()

    archive.unlink()

    prune_backups(destdir, keep_backups, keep_days, prefix)


def prune_backups(destdir, keep_backups, keep_days, prefix):
    """Delete backup files from disk and metadata, except the `keep_backups` newest.

    A backup file must also be older than `keep_days` to be deleted.
    """
    backup_dir = pathlib.Path(destdir).expanduser().resolve(strict=False)
    if not backup_dir.is_dir():
        log.warning("No such directory: %s", backup_dir)
        return None
    checksums = Checksums(backup_dir)
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
            checksums.remove(meta["sha256"])
        else:
            log.debug(
                "not deleting %s, last touched %s", bk.name, time.ctime(meta["touched"])
            )
    checksums.write()


def make_source_list(sources: Iterable[dict]) -> List[str]:
    """Relative paths in sources are relative to basedir."""
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


def call_hooks(hooks: Iterable[str]) -> List[str]:
    """Call all executables in hooks and return a list of unique paths to
    include in the backup."""
    paths = set()
    for hook in resolve_hooks(hooks):
        log.info("Run hook %s", hook)
        if (ret := run_hook(hook)) is not None:
            log.debug("%s", ret)
            paths |= set(ret)
        else:
            log.error("Failed to run hook %s", hook)
    return list(paths)


def resolve_hooks(hooks_list: Iterable[str]) -> abc.Generator[pathlib.Path, None, None]:
    for hook in hooks_list:
        path = pathlib.Path(hook).expanduser().resolve(strict=False)
        if path.is_file() and os.access(path, os.R_OK | os.X_OK):
            yield path
        elif path.is_dir():
            for f in path.iterdir():
                if f.is_file() and os.access(f, os.R_OK | os.X_OK):
                    yield f
        else:
            log.warning("No usable hooks: %s", hook)


def run_hook(hook: pathlib.Path, timeout=60) -> Optional[list[str]]:
    try:
        p = subprocess.run(
            [hook.as_posix()],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        log.error(
            "Failed to run hook %s, exit code: %d, stderr: %s",
            hook,
            exc.returncode,
            exc.stderr,
        )
        log.debug("%s stdout: %s", hook, exc.stdout, exc_info=True)
        return None
    except subprocess.TimeoutExpired as exc:
        log.error("%s timed out, stderr: %s", exc.cmd, exc.stderr)
        return None
    return p.stdout.strip().splitlines()
