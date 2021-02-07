import json
import pathlib

import pytest

from cebackup import backup as bk

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


@pytest.mark.subprocess
def test_backuparchive_make_archive(tmp_path: pathlib.Path, faketime):
    archive = bk.BackupArchive(tmp_path, "foo", "gzip")
    assert str(archive) == "%s/%s_%s_20210101T000000.tar" % (tmp_path, "foo", faketime)
    for f in {"alpha.txt", "bravo.txt"}:
        (tmp_path / f).write_text("back this up")
        archive.add((tmp_path / f).as_posix())
    archive.compress(timeout=5)
    assert archive.compressed_file.exists()
    assert len(archive.make_checksum()) == 64
    archive.unlink()
    assert not archive.compressed_file.exists()


def test_checksums_empty_file(tmp_path, faketime):
    chk = bk.Metadata(tmp_path)
    assert len(chk._archives) == 0
    archive = bk.BackupArchive(tmp_path, "test", "bzip2", 60)
    archive.compressed_file = tmp_path / (archive.archivename + ".bz2")
    chk.add("deadbeef", archive)
    assert len(chk._archives) == 1
    chk.add("deadbeef", bk.BackupArchive(tmp_path, "test", "bzip2", 60))
    assert len(chk._archives) == 1
    chk.write()
    with open(tmp_path / bk.Metadata.CHECKSUM_FILE) as fp:
        data = json.load(fp)
    assert data == [
        {
            "archive": f"test_{faketime}_20210101T000000.tar.bz2",
            "encrypted": f"test_{faketime}_20210101T000000.tar.bz2.gpg",
            "open-checksum": "deadbeef",
            "created": faketime,
            "touched": faketime,
        }
    ]


def test_checksums_load_file(tmp_path):
    data = [
        {
            "archive": "test_12345_20210101T000000.tar.xz",
            "encrypted": "test_12345_20210101T000000.tar.xz.gpg",
            "open-checksum": "c0ffee",
            "created": 12345,
            "touched": 45678,
        }
    ]
    with open(tmp_path / bk.Metadata.CHECKSUM_FILE, "w") as fp:
        json.dump(data, fp)
    chk = bk.Metadata(tmp_path)
    assert len(chk._archives) == 1
    assert chk.get_archive("deadbeef") is None
    assert chk.get_archive("c0ffee") == data[0]
    assert (
        chk.get_from_encrypted_name(tmp_path / "test_12345_20210101T000000.tar.xz.gpg")
        == data[0]
    )
    chk.remove("c0ffee")
    assert chk.get_archive("c0ffee") is None


@pytest.mark.parametrize(
    "filename, month",
    [
        ("foo-bar-baz_1545606000_20181224T000000.tar", "2018-12"),
        ("foo-bar-baz_1545606000_19000000T000000.tar.gz", "2018-12"),
        ("_1610665200_20210115T000000.tar.bz2.gpg", "2021-1"),
        ("_1612688337_20210207T000000.tar.gz.gpg", "2021-2"),
    ],
)
def test_get_month_from_backup(filename, month):
    path = pathlib.Path("/backup-dir") / filename
    assert bk.get_month_from_backup_file(path) == month
    assert bk.get_month_from_backup_file(str(path)) == month
