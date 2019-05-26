#!/bin/bash

#
# Start/stop/restart/show info of jukebox service.
# Expects operation to execute as parameter.
#

if [ "$1" = "start" ]; then
        echo "Starting Jukebox..."
elif [ "$1" = "stop" ]; then
        echo "Stopping Jukebox..."
elif [ "$1" = "restart" ]; then
        echo "Restarting Jukebox..."
elif [ "$1" = "status" ]; then
        echo "Jukebox status:"
elif [ "$1" = "ip" ]; then
        echo "IP Adresse: "$(ip addr show wlan0 | grep -Po 'inet \K[\d.]+')
        exit 0
else
        echo "Invalid operation. Valid operations: start, restart, stop, status, ip"
        exit 1
fi

sudo systemctl $1 jukebox

exit 0
