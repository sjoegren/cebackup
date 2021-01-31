#!/bin/sh
# Place a file '.cebackup' in a sub directory of $HOME to include the sub
# directory in backup.
set -eu

fd --type file --hidden --no-ignore-vcs --exec echo '{//}' \; '^.cebackup$' "$HOME"
