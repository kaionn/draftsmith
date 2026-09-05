#!/bin/sh
python3 "$(dirname -- "$0")/../skills/draftsmith/scripts/delivery_hook.py" session-start 2>/dev/null
exit 0
