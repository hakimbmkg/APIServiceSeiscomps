#!/bin/bash

SCRIPT_PATH="$(readlink -f "$0")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

#echo "$SCRIPT_PATH"

EVENT_TRIGER="${SCRIPT_DIR}/triger.sh"
LOG_TRIGER="${SCRIPT_DIR}/log_triger.log"

#echo "$EVENT_TRIGER"

if [ ! -f "$LOG_TRIGER" ]; then
    touch "$LOG_TRIGER"
    echo "[`date`] File:: $LOG_TRIGER"
fi

#echo "$HOME"

echo "[`date`] Starting Trigger by Scvoice .." >> "$LOG_TRIGER"
$HOME/seiscomp/bin/seiscomp exec scvoice --event-script "$EVENT_TRIGER" >> "$LOG_TRIGER" 2>&1
