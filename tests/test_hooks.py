import pathlib

from cebackup import hooks


def test_resolve_hooks(tmp_path: pathlib.Path):
    hookdir = tmp_path / "hooks"
    hookdir.mkdir()
    (hookdir / "foo.sh").touch(0o755)
    (hookdir / "bar.py").touch(0o755)
    (hookdir / "nohook.txt").touch(0o640)
    (tmp_path / "testhook.sh").touch(0o500)
    resolved = set(hooks.resolve_hooks([str(hookdir), str(tmp_path / "testhook.sh")]))
    assert resolved == {
        (hookdir / "foo.sh"),
        (hookdir / "bar.py"),
        (tmp_path / "testhook.sh"),
    }
