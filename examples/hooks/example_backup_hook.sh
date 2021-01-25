#!/bin/sh
# Place an empty file '.backup' in a sub directory of $HOME to include the sub
# directory in backup.
set -eu

fd --fixed-strings --type empty --hidden --no-ignore-vcs --exec echo '{//}' \; .backup "$HOME"
