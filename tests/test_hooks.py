import logging
import pathlib
import pytest

from cebackup import hooks


def test_resolve_hooks_dirs_pre_post(tmp_path: pathlib.Path, caplog):
    (tmp_path / "testhook.sh").touch(0o500)
    (tmp_path / "nohook.txt").touch(0o644)
    hookdir = tmp_path / "hookdir"
    hookdir.mkdir()
    (hookdir / "pre_1.sh").touch(0o755)
    (hookdir / "pre_2").touch(0o755)
    (hookdir / "post_1.sh").touch(0o755)
    (hookdir / "post_2").touch(0o755)
    (hookdir / "pre_nohook.txt").touch(0o640)
    (hookdir / "post_nohook.txt").touch(0o640)
    (hookdir / "pre-underscore-missing.sh").touch(0o755)

    # pre hooks
    resolved = set(
        hooks.resolve_hooks(
            [
                str(hookdir),
                str(tmp_path / "testhook.sh"),
                str(tmp_path / "nohook.txt"),
            ],
            hooks.HookType.pre,
        )
    )
    assert resolved == {
        (tmp_path / "testhook.sh"),
        (hookdir / "pre_1.sh"),
        (hookdir / "pre_2"),
    }
    _, level, message = caplog.record_tuples[0]
    assert level == logging.WARNING
    assert message == "Not usable hook: %s" % (tmp_path / "nohook.txt")
    assert len(caplog.record_tuples) == 1

    # post hooks
    resolved = set(
        hooks.resolve_hooks(
            [
                str(hookdir),
                str(tmp_path / "testhook.sh"),
            ],
            hooks.HookType.post,
        )
    )
    assert resolved == {
        (tmp_path / "testhook.sh"),
        (hookdir / "post_1.sh"),
        (hookdir / "post_2"),
    }


@pytest.mark.parametrize("hook_type", [hooks.HookType.pre, hooks.HookType.post])
def test_resolve_hooks_name_doesnt_matter_for_specific_hooks(
    tmp_path: pathlib.Path, hook_type
):
    hookdir = tmp_path / "hookdir"
    hookdir.mkdir()
    (hookdir / "pre_hook.sh").touch(0o755)
    (hookdir / "post_hook.pl").touch(0o755)

    resolved = set(
        hooks.resolve_hooks([str(p) for p in hookdir.glob("*.*")], hook_type)
    )
    assert resolved == {
        (hookdir / "pre_hook.sh"),
        (hookdir / "post_hook.pl"),
    }
