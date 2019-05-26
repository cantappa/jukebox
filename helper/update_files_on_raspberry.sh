#!/bin/bash

#
# Update Jukebox files on raspberry.
#

REMOTE_CONTENTS=$(ssh pi@raspberry "ls Jukebox")

rsync -avh ${REMOTE_CONTENTS} pi@raspberry:Jukebox/

exit 0
