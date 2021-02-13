import os
import os.path
import pathlib

import yaml

from . import BackupException

DEFAULT_CONFIG_FILE = "~/.config/cebackup.yaml"


def get_config(config_file: pathlib.Path) -> dict:
    """Read config. Resolve relative-to-config-file paths to absolute paths."""
    config: dict = yaml.safe_load(config_file.read_bytes())
    try:
        _process_config(config, config_file.parent)
    except (KeyError, TypeError) as exc:
        raise BackupException("Config error: %s (%s)", exc, config_file, retcode=2)
    config["backup_sources"].append({"path": str(config_file), "skip_dirs": False})
    return config


def _process_config(conf: dict, config_file_dir):
    # Make all source 'path' be absolute and add defaults for 'skip_dirs'.
    for source in conf.setdefault("backup_sources", []):
        path = os.path.expanduser(source["path"])
        if not os.path.isabs(path):
            path = (config_file_dir / source["path"]).resolve().as_posix()
        source["path"] = path
        source.setdefault("skip_dirs", False)

    # Resolve paths to hooks. Set them to empty empty list if not defined.
    for hook_type in {"pre_hooks", "post_hooks"}:
        if conf.get(hook_type) is None:
            conf[hook_type] = []
        for i, path in enumerate(conf[hook_type]):
            path = os.path.expanduser(path)
            if not os.path.isabs(path):
                conf[hook_type][i] = (config_file_dir / path).resolve().as_posix()

    path = os.path.expanduser(conf.setdefault("hook_tmpdir", "~/cebackup-auxdata"))
    if not os.path.isabs(path):
        path = (config_file_dir / path).resolve().as_posix()
    conf["hook_tmpdir"] = path

    local = conf["local_backup"]

    path = os.path.expanduser(local["directory"])
    if not os.path.isabs(path):
        path = (config_file_dir / path).resolve().as_posix()
    local["directory"] = path

    # Set gpg_public_key to (key: str, is_file: bool)
    gpg_public_key = local["gpg_public_key"]
    keyfile = os.path.expanduser(gpg_public_key)
    if os.path.exists(keyfile):
        if not os.path.isabs(keyfile):
            keyfile = (config_file_dir / keyfile).resolve().as_posix()
        local["gpg_public_key"] = (keyfile, True)
    else:
        local["gpg_public_key"] = (gpg_public_key, False)

    local.setdefault("ignore_file", ".cebackup")
    local.setdefault("compression", "gzip"),

    if "prune" in local:
        assert local["prune"]["keep_archives"]
        assert local["prune"]["keep_days"]
    else:
        local["prune"] = None
