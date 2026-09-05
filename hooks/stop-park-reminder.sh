#!/bin/sh
python3 "$(dirname -- "$0")/../skills/draftsmith/scripts/delivery_hook.py" stop 2>/dev/null
exit 0
