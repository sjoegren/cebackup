#!/bin/bash

# cebackup post_hook
# Notify with notify-send if backup was created.

set -eu

CEBACKUP_OK=${CEBACKUP_OK:-0}
CEBACKUP_BACKUP_CREATED=$CEBACKUP_BACKUP_CREATED
CEBACKUP_BACKUP_PATH=$CEBACKUP_BACKUP_PATH
CEBACKUP_SOURCES=$CEBACKUP_SOURCES

if [ $CEBACKUP_OK -eq 1 ]; then
	if [ $CEBACKUP_BACKUP_CREATED -eq 1 ]; then
		msg="Created: $CEBACKUP_BACKUP_PATH\nFrom $(wc -l < "$CEBACKUP_SOURCES") source paths."
	else
		msg="Up to date archive already exists ($CEBACKUP_BACKUP_PATH).\nFrom $(wc -l < "$CEBACKUP_SOURCES") source paths."
	fi
	notify-send -u normal -a cebackup --icon=emblem-package "Backup completed" "$msg"
else
	if [ -e "$CEBACKUP_LOGFILE" ]; then
		msg="Logfile: $CEBACKUP_LOGFILE\n\nLast logs: $(tail -5 "$CEBACKUP_LOGFILE")"
	else
		msg="backup failed"
	fi
	notify-send -u critical -a cebackup --icon=dialog-error "Backup failed" "$msg"
fi
