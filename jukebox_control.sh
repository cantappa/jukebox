#!/bin/bash

#
# Start/stop/restart Jukebox service.
# Expects operation to execute as parameter.
#

if [ "$1" = "start" ]; then
        echo "Starting Jukebox..."
elif [ "$1" = "stop" ]; then
        echo "Stopping Jukebox..."
elif [ "$1" = "restart" ]; then
        echo "Restarting Jukebox..."
else
        echo "Invalid operation. Valid operations: start, restart, stop"
        exit 1
fi

sudo systemctl $1 jukebox

exit 0
