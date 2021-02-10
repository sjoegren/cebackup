"""
Configuration can contain the optional lists:

    pre_hooks:
      - /path/to/hook script or dirs containing executables
    post_hooks:
      - /path/to/hook script or dirs containing executables

pre_hooks run before the backup is created and their responsibility is to
output absolute paths to files/directories to include in the backup on stdout.

post_hooks run after the backup execution is done.

Hook scripts should exit with exit code 0 if there are no errors. Other exit
codes will cause cebackup to log an error and include stderr output from the
hook.
"""
import logging as log
import os
import os.path
import pathlib
import subprocess
from collections import abc

from typing import Iterable, Optional


def call_hooks(hooks: Optional[Iterable[str]]) -> tuple[bool, list[str]]:
    """Call all executables in hooks and return a list of lines written to
    stdout.

    pre_hooks uses the stdout API to print paths that should be included in the
    backup.
    """
    if not hooks:
        return True, []
    paths = set()
    all_ok = True
    for hook in resolve_hooks(hooks):
        log.info("Run hook %s", hook)
        if (ret := run_hook(hook)) is not None:
            log.debug("got paths: %s", ret)
            paths |= set(ret)
        else:
            log.error("Failed to run hook %s", hook)
            all_ok = False
    return all_ok, list(paths)


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
            log.warning("Not usable hook: %s", hook)


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
    log.debug("stdout %s, stderr: %s", p.stdout, p.stderr)
    return p.stdout.strip().splitlines()
