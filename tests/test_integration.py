import json
import pathlib
import re
import shutil
import subprocess
import textwrap
import time

import pytest
import toml
import yaml

pytestmark = pytest.mark.integration

# Use the example config as template, so that it gets somewhat sanity checked
# as well.
REPO_DIR = (pathlib.Path(__file__).parent / "..").resolve()
TESTDATA_DIR = REPO_DIR / "tests/data"
CONFIG_FILE = REPO_DIR / "examples/cebackup.yaml"


@pytest.fixture(scope="module", autouse=True)
def _check_dependencies():
    p = subprocess.run(["gpg", "--version"], text=True, check=True, capture_output=True)
    assert re.search(r"gpg(?: \(GnuPG\))? [2-9]", p.stdout)
    subprocess.run(["tar", "--version"], check=True)
    subprocess.run(["gzip", "--version"], check=True)


@pytest.fixture
def testdata(tmp_path: pathlib.Path):
    srcdir = shutil.copytree(REPO_DIR / "examples", tmp_path / "sources")
    (tmp_path / "data1.txt").write_text("data")
    (tmp_path / "data2.txt").write_text("data")
    return srcdir, "*.txt"


@pytest.fixture
def config_file(tmp_path: pathlib.Path, testdata):
    conf: dict = yaml.safe_load(CONFIG_FILE.read_bytes())
    conf["backup_sources"] = [{"path": str(f)} for f in testdata]
    conf["local_backup"]["directory"] = "backup_dir"  # relative to config
    conf["local_backup"]["gpg_public_key"] = str(TESTDATA_DIR / "gpg.pub")
    conf["log_level"] = "debug"

    # Make a hook script that creates a file with the exact same data and mtime each run
    pre_hook = tmp_path / "testhook.sh"
    pre_hook.write_text(
        textwrap.dedent(
            """\
        #!/bin/sh
        set -eu
        LC_ALL=C TZ=UTC date -d '06:00' > "$CEBACKUP_TMPDIR/aux.data"
        TZ=UTC touch -d '06:00' "$CEBACKUP_TMPDIR/aux.data"
        echo "$CEBACKUP_TMPDIR/aux.data"
        """
        )
    )
    pre_hook.chmod(0o755)
    conf["pre_hooks"] = ["testhook.sh"]

    file_ = tmp_path / "config.yaml"
    with file_.open("w") as fp:
        yaml.dump(conf, fp)
    return file_


def test_example_config():
    conf: dict = yaml.safe_load(CONFIG_FILE.read_bytes())
    assert isinstance(conf, dict)
    assert "backup_sources" in conf
    assert "directory" in conf["local_backup"]
    assert isinstance(conf["local_backup"]["prune"]["keep_archives"], int)
    assert isinstance(conf["local_backup"]["prune"]["keep_days"], int)
    assert "gpg_public_key" in conf["local_backup"]
    assert isinstance(conf["local_backup"]["archive_prefix"], str)


def test_cli_version_matches_project_config():
    p = subprocess.run(["cebackup", "--version"], capture_output=True, text=True)
    assert p.returncode == 0
    proj = toml.load(REPO_DIR / "pyproject.toml")
    assert p.stdout.strip() == "cebackup %s" % proj["tool"]["poetry"]["version"]


def test_make_backup_simple(config_file: pathlib.Path):
    """Make one backup and verify that archive and meadata exists."""
    p = subprocess.run(["cebackup", "-c", str(config_file)])
    assert p.returncode == 0
    bkd = config_file.parent / "backup_dir"
    backups = list(bkd.glob("*.gpg"))
    assert len(backups) == 1
    meta = json.loads((bkd / "metadata.json").read_text())
    assert len(meta) == 1
    assert backups == [bkd / meta[0]["encrypted"]]


def test_make_backups_duplicate_archive_checksum(tmp_path, config_file: pathlib.Path):
    """Verify that no new archive was stored since metadata matched existing archive."""
    logfile: pathlib.Path = tmp_path / "backup.log"
    p = subprocess.run(["cebackup", "-c", str(config_file), "--log-file", logfile])
    assert p.returncode == 0

    log = logfile.read_text()
    m = re.search(r"Created backup (\S+)", log)
    assert m
    backup_file = pathlib.Path(m[1])
    assert backup_file.exists()
    assert not re.search(r"\b(?:WARNING|ERROR|CRITICAL)\b", log)
    logfile.rename(f"{logfile}.run1")

    time.sleep(1)  # Give timestamp for filename time to change
    p = subprocess.run(["cebackup", "-c", str(config_file), "--log-file", logfile])
    assert p.returncode == 0
    bkd = config_file.parent / "backup_dir"
    meta = json.loads((bkd / "metadata.json").read_text())
    assert len(meta) == 1
    assert meta[0]["encrypted"] == backup_file.name
    list(bkd.glob("*.gpg")) == [backup_file.as_posix()]

    log = logfile.read_text()
    assert (
        "A backup with the same checksum already exist: {}".format(backup_file) in log
    )
    assert not re.search(r"\b(?:WARNING|ERROR|CRITICAL)\b", log)


def test_make_backups_skip_if_recent_exist(tmp_path, config_file: pathlib.Path):
    """Verify that no new archive was stored with --skip-if-recent."""
    logfile = tmp_path / "backup.log"
    p = subprocess.run(
        ["cebackup", "-c", str(config_file), "--skip-if-recent", "--log-file", logfile]
    )
    assert p.returncode == 0

    log = logfile.read_text()
    assert re.search(r"\bINFO\b.* Created backup (\S+)", log)
    assert not re.search(r"\b(?:WARNING|ERROR|CRITICAL)\b", log)
    logfile.unlink()

    time.sleep(1)  # Give timestamp for filename time to change
    (tmp_path / "newfile.txt").write_text("fresh data to backup")
    p = subprocess.run(
        ["cebackup", "-c", str(config_file), "--skip-if-recent", "--log-file", logfile]
    )
    assert p.returncode == 0

    # A new backup should NOT have been created
    bkd = config_file.parent / "backup_dir"
    meta = json.loads((bkd / "metadata.json").read_text())
    assert len(meta) == 1
    assert len(list(bkd.glob("*.gpg"))) == 1

    log = logfile.read_text()
    assert not re.search(r"\bINFO\b.* Created backup (\S+)", log)
    assert not re.search(r"\b(?:WARNING|ERROR|CRITICAL)\b", log)
