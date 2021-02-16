#!/bin/bash
# Copy files with sudo that the running user doesn't have read access to.
# Requires a sudoers rule for /usr/bin/{cp,chown} with NOPASSWD flag.

set -eu

# cebackup tool exports CEBACKUP_TMPDIR.
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
/usr/bin/sudo --non-interactive chown -R "$(id -u):$(id -g)" "$dir"

# The directory where this script copied files to will be included in the backup.
echo "$dir"
