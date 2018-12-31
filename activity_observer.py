#!/usr/bin/python
# -*- coding: utf-8 -*-

#
# Shutdown raspberry after mpc has not been playing after
# the specified amount of time.
# NOTE: This script is not used currently since
# the LED lights behind the buttons are always on power
# even if the raspberry has already been shut down.
#

import time
import subprocess
import os

# shutdown if mpc has not been playing for 20 minutes
shutdown_time = 5 # 1200

# check mpc status every 60 seconds
check_interval = 2 # 60

now = time.time()
last_time_running_observed = time.time()

while last_time_running_observed + shutdown_time > now:
	now = time.time()
	status = subprocess.check_output(["mpc", "status"])
	playing = status.find("[playing]")
	if (playing != -1):
		last_time_running_observed = time.time()
	time.sleep(check_interval)

print "Shutting down system..."
os.system("sudo shutdown -h now")

