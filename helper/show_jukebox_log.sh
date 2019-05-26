#!/bin/bash
#
# Show logfile entries of Jukebox service.
# Optional parameter: If $1="-f" behave just like tail -f
#

if [ "$1" = "-f" ]; then
    PARAM="-f"
else
    PARAM=""
fi

sudo journalctl ${PARAM} -u jukebox -b

exit 0
