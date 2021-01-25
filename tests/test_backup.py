import json
import pathlib

import pytest

from cebackup import backup as bk
from cebackup import BackupException

CONFIG_SOURCES = [
    {"path": "~/Documents/"},
    {"path": "~/work/*", "skip_dirs": True},
]


@pytest.fixture()
def homedir(mocker, tmp_path):
    mocker.patch.dict("os.environ", HOME=tmp_path.as_posix())
    documents = tmp_path / "Documents"
    documents.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    for i in range(3):
        (documents / f"doc.{i}").write_text(f"test {i}")
        (work / f"file.{i}").write_text("foo")
        (work / f"subdir.{i}").mkdir()
    return tmp_path


def test_make_source_list(homedir):
    paths = bk.make_source_list(CONFIG_SOURCES)
    assert set(paths) == {
        (homedir / "Documents").as_posix(),
        (homedir / "work/file.0").as_posix(),
        (homedir / "work/file.1").as_posix(),
        (homedir / "work/file.2").as_posix(),
    }


@pytest.mark.parametrize(
    "prefix, compression, ext",
    [
        ("ham", "gzip", "gz"),
        ("spam", "bzip2", "bz2"),
        ("eggs", "xz", "xz"),
    ],
)
def test_backuparchive(tmp_path, faketime, prefix, compression, ext):
    a = bk.BackupArchive(tmp_path, prefix, compression)
    assert a.exists() is False
    assert str(a) == "%s/%s_%s_20210101T000000.tar.%s" % (
        tmp_path,
        prefix,
        faketime,
        ext,
    )


def test_backuparchive_invalid_compression(tmp_path):
    with pytest.raises(BackupException, match=r"^Invalid compression type: zippo"):
        bk.BackupArchive(tmp_path, "test", "zippo")


def test_checksums_empty_file(tmp_path, faketime):
    chk = bk.Checksums(tmp_path)
    assert len(chk._archives) == 0
    archive = bk.BackupArchive(tmp_path, "test", "bzip2")
    chk.add("deadbeef", archive)
    assert len(chk._archives) == 1
    chk.add("deadbeef", bk.BackupArchive(tmp_path, "test", "bzip2"))
    assert len(chk._archives) == 1
    chk.write()
    with open(tmp_path / bk.Checksums.CHECKSUM_FILE) as fp:
        data = json.load(fp)
    assert data == [
        {
            "archive": f"test_{faketime}_20210101T000000.tar.bz2",
            "encrypted": f"test_{faketime}_20210101T000000.tar.bz2.gpg",
            "sha256": "deadbeef",
            "created": faketime,
            "touched": faketime,
        }
    ]


def test_checksums_load_file(tmp_path):
    data = [
        {
            "archive": "test_12345_20210101T000000.tar.xz",
            "encrypted": "test_12345_20210101T000000.tar.xz.gpg",
            "sha256": "c0ffee",
            "created": 12345,
            "touched": 45678,
        }
    ]
    with open(tmp_path / bk.Checksums.CHECKSUM_FILE, "w") as fp:
        json.dump(data, fp)
    chk = bk.Checksums(tmp_path)
    assert len(chk._archives) == 1
    assert chk.get_archive("deadbeef") is None
    assert chk.get_archive("c0ffee") == data[0]
    assert (
        chk.get_from_encrypted_name(tmp_path / "test_12345_20210101T000000.tar.xz.gpg")
        == data[0]
    )
    chk.remove("c0ffee")
    assert chk.get_archive("c0ffee") is None


def test_resolve_hooks(tmp_path: pathlib.Path):
    hookdir = tmp_path / "hooks"
    hookdir.mkdir()
    (hookdir / "foo.sh").touch(0o755)
    (hookdir / "bar.py").touch(0o755)
    (hookdir / "nohook.txt").touch(0o640)
    (tmp_path / "testhook.sh").touch(0o500)
    hooks = set(bk.resolve_hooks([str(hookdir), str(tmp_path / "testhook.sh")]))
    assert hooks == {
        (hookdir / "foo.sh"),
        (hookdir / "bar.py"),
        (tmp_path / "testhook.sh"),
    }
