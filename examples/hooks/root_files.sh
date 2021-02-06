#!/bin/bash
# cebackup hook
# Copy files with sudo.
# cebackup tool exports CEBACKUP_TMPDIR.
set -eu

dir="$CEBACKUP_TMPDIR/root"
mkdir "$dir"

paths=(
    /etc/NetworkManager/system-connections/
)
for path in ${paths[*]}; do
	if [ -e "$path" ]; then
		sudo --non-interactive cp -a "$path" "$dir/"
	fi
done
/usr/bin/sudo --non-interactive chown -R $(id -u):$(id -g) "$dir"
echo "$dir"
