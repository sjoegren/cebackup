#!/bin/sh
set -eu

# cebackup tool exports CEBACKUP_TMPDIR to the environment of hooks and removes
# the directory after the backup is created.
crontab="$CEBACKUP_TMPDIR/crontab.txt"
crontab -l > "$crontab"
echo "$crontab"
