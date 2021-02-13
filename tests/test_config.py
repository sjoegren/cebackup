import pathlib

import pytest
import yaml

from cebackup import config

REPO_DIR = (pathlib.Path(__file__).parent / "..").resolve()
CONFIG_FILE = REPO_DIR / "examples/cebackup.yaml"
TEST_CONFIG = """---
backup_sources:
  - path: /etc/*
    skip_dirs: yes
  - path: foo
  - path: ~/Documents
local_backup:
  directory: backup_dir
  gpg_public_key: user@example.com
"""


@pytest.fixture(autouse=True)
def homedir(mocker):
    mocker.patch.dict("os.environ", HOME="/home/test")


@pytest.fixture
def config_file(tmp_path: pathlib.Path):
    conf: dict = yaml.safe_load(CONFIG_FILE.read_bytes())
    conf["backup_sources"] = []

    file_ = tmp_path / "config.yaml"
    with file_.open("w") as fp:
        yaml.dump(conf, fp)
    return file_


def test_get_config(mocker, config_file):
    mocker.patch("cebackup.config._process_config")
    conf = config.get_config(config_file)
    assert conf["backup_sources"] == [{"path": str(config_file), "skip_dirs": False}]
    assert (
        config._process_config.call_args.args[0] is conf
    ), "_process_config should have been called with the same dict that was returned."


def test_process_config_minimal_creates_default_config(tmp_path):
    """Test that a minimal configuration is processed, paths are resolved and
    default values inserted."""
    conf = yaml.safe_load(TEST_CONFIG)
    config._process_config(conf, tmp_path)
    assert conf == {
        "backup_sources": [
            {"path": "/etc/*", "skip_dirs": True},
            {"path": str(tmp_path / "foo"), "skip_dirs": False},
            {"path": "/home/test/Documents", "skip_dirs": False},
        ],
        "local_backup": {
            "directory": str(tmp_path / "backup_dir"),
            "gpg_public_key": ("user@example.com", False),
            "ignore_file": ".cebackup",
            "compression": "gzip",
            "prune": None,
        },
        "pre_hooks": [],
        "post_hooks": [],
        "hook_tmpdir": "/home/test/cebackup-auxdata",
    }
