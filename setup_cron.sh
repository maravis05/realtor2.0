#!/usr/bin/env bash
# Install the cron job for the Realtor 2.0 pipeline.
# Runs every 4 hours at 7am, 11am, 3pm, 7pm, 11pm.
#
# Python's own RotatingFileHandler writes to logs/pipeline.log (with rotation).
# Cron only captures stderr to logs/crash.log for unexpected failures
# (import errors, segfaults, OOM kills, etc.).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$HOME/miniconda3/envs/realtor/bin/python"
CRASH_LOG="$SCRIPT_DIR/logs/crash.log"

mkdir -p "$SCRIPT_DIR/logs"

# stdout → /dev/null (Python logs to its own rotating file)
# stderr → crash.log (only written to if something goes badly wrong)
# The tail -c keeps crash.log from growing beyond 100KB
# -m src.main ensures the project root is on sys.path so "from src.X" imports work
CRON_LINE="0 7,11,15,19,23 * * * cd $SCRIPT_DIR && $PYTHON -m src.main > /dev/null 2>> $CRASH_LOG; tail -c 100000 $CRASH_LOG > $CRASH_LOG.tmp && mv $CRASH_LOG.tmp $CRASH_LOG"

# Check if the cron job already exists
if crontab -l 2>/dev/null | grep -qF "src.main"; then
    echo "Cron job already installed. Updating..."
    # Remove old entry and add new one
    (crontab -l 2>/dev/null | grep -vF "src.main"; echo "$CRON_LINE") | crontab -
    echo "Cron job updated."
else
    # Append to existing crontab
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "Cron job installed."
fi

echo ""
echo "Schedule: 5x daily at 7am, 11am, 3pm, 7pm, 11pm"
echo "App log:  logs/pipeline.log  (rotating, 5MB x 5 files)"
echo "Crash log: logs/crash.log    (stderr only, capped at 100KB)"
echo ""
echo "To verify: crontab -l"
echo "To remove: crontab -e  (and delete the realtor line)"
