# Configurable encrypted backup tool

Requirements:

* Python 3.9+
* GnuPG 2.0+

Install:

```
pipx install git+https://github.com/akselsjogren/cebackup.git
cebackup --help
```

Place config file in `~/.config/cebackup.yaml`. Example config:
[examples/cebackup.yaml](examples/cebackup.yaml).

Setup rsync of local backup directory to a remote host.
