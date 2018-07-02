#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# This script runs in the following threads:
# * display thread: 
#   - prints contents of display_current to the display,
#   - this thread is also responsible for scrolling the text
# * control thread:
#   - this thread controls button presses and reading of RFID tags
#   - when a button is pressed it also initiates the according actions
#
# The following actions are taken when a button is pressed:
# * play/pause button:
#   - execute "mpc -q play/pause" as subprocess
#   - updates contents of display_current to the currently running track
# * next button:
#   - execute "mpc -q next" as subprocess
#   - updates contents of display_current to the currently running track
# * previous button:
#   - execute "mpc -q prev" as subprocess
#   - updates contents of display_current to the currently running track
# * volume up button:
#   - executes "mpc -q volume +2" as subprocess
#   - update the contents of display_current to hold the text "Lauter"
#     and the current volume
#   - store previous display contents and timestamp of when to display them again
# * volume down button:
#   - executes "mpc -q volume -2" as subprocess
#   - the rest is analgous to the volume up action
#
# Furthermore, immediately after each button press it is checked
# if the sequences of recently pressed buttons matches one of the
# predefined "hidden options".
#
# Currently, the following hidden options are supported:
# * prev - play/pause - next: switch to next directory
# * volume down - volume up - volume down - volume up: disable/enable the display
#

import RPi.GPIO as GPIO
from RPLCD import i2c, gpio
import MFRC522
import time
import subprocess
from threading import Thread, Lock
import sys

########################################################################
# CONFIGURATION
########################################################################

# available media directories
media_list = ['tag-01', 'tag-02', 'tag-03']
media = {}
media['tag-01'] = 'Bibi Blocksberg'
media['tag-02'] = u'Benjamin Blümchen'
media['tag-03'] = 'Kinderlieder'

uid_to_tag = {}
uid_to_tag['176,223,243,121'] = 'tag-01'
uid_to_tag['227,237,212,28'] = 'tag-02'

ping_sound = 'ping.mp3'

# via button sequences specific "hidden" functions can be triggered
PLAY_PAUSE = 0
PREV = 1
NEXT = 2
VOLUME_DOWN = 3
VOLUME_UP = 4

# sequence of recently pressed buttons
button_press_sequence = []

# sequence for switching to next directory
sequence_next_dir = [PREV, PLAY_PAUSE, NEXT]

# sequence for disabling/enabling display
sequence_display = [VOLUME_DOWN, VOLUME_UP, VOLUME_DOWN, VOLUME_UP]


# current (and initial) start media directory 
media_current_dir_index = 0

# define GPIO pins of the buttons
gpio_play_pause=4	# red button
gpio_prev=27		# green button
gpio_next=17		# yellow button
gpio_volume_up=23	# blue button
gpio_volume_down=24	# white button

# configure buttons
GPIO.setmode(GPIO.BCM)
GPIO.setup(gpio_play_pause, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(gpio_prev, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(gpio_next, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(gpio_volume_up, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(gpio_volume_down, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)

# sleep time after a button press
button_press_sleep_time=0.3

# initial text at display:
display_initial = ['', '']
display_initial[0] = '* * Paulas * * *'
display_initial[1] = '* * Jukebox  * *'

# create lcd object
options = {}
lcd = i2c.CharLCD('PCF8574', 0x3f, port=1, charmap='A00', cols=16, rows=2, expander_params=options)

# RFID reader object
MIFAREReader = MFRC522.MFRC522()
rfid_reader_running = True

# display related variables
display_current = list(display_initial)
display_current_lock = Lock()
display_running = True
display_scrolling_enabled = True
display_enabled = True
display_previous = list(display_current) # in case the display temporarily shows
										 # status information (e.g. volume info)
										 # this variable holds the contents of
										 # the display before showing the status
										 # informations
display_previous_scrolling_status = display_scrolling_enabled
display_sleep=0.2

# lock for accessing the variable lcd
lcd_lock = Lock()

# lock for performing a sequence of operations with the mpc command
# lock the variables media_current_dir_index, playing and sequences of calls to mpc
# that should better not be "interrupted"
mpc_lock = Lock()

# list of threads created during execution
threads = []

short_msg_time = 1500 # how long to short info messages (in ms)
show_previous_timestamp = -1 # if set to a positive number display the contents
                             # of the previous display again

playing = False

########################################################################
# FUNCTIONS
########################################################################

# write the framebuffer out to the given LCD
def write_to_lcd(framebuffer):
	global display_enabled
	global lcd
	global lcd_lock
	if not display_enabled:
		return

	num_cols = 16
	lcd_lock.acquire()
	try:
		lcd.home()
		for row in framebuffer:
			lcd.write_string(row.ljust(num_cols)[:num_cols])
			lcd.write_string('\r\n')
	finally:
		lcd_lock.release()


# enable/disable display scrolling
def set_display_scrolling(value):
	global lcd_lock
	global display_scrolling_enabled
	display_scrolling_enabled = value

	# for some reason we need to clear the lcd
	lcd_lock.acquire()
	try:
		lcd.clear()
	finally:
		lcd_lock.release()

# get current volume
def get_current_volume():
	cmd = "mpc | grep 'volume:' | awk -F'%' '{print $1}' | awk -F':' '{print $2}' | tr -d '[:space:]'"
	return subprocess.check_output(cmd, shell=True)


# handle a button press, i.e.:
# * run the function button_press_callback in a background thread
# * add the created thread to the global list of threads
# * sleep for the configured amount of seconds
def handle_volume_button_press(text, up):
	global display_short_msg_thread
	global display_current
	global display_current_lock
	global display_previous
	global show_previous_timestamp
	global display_previous_scrolling_status
	global display_scrolling_enabled

	if up:
		subprocess.Popen(["mpc", "-q", "volume", "+2"])
	else:
		subprocess.Popen(["mpc", "-q", "volume", "-2"])

	new_volume=get_current_volume()
	print('New volume: '+new_volume)

	if not new_volume:
		return

	# update display contents to show volume info
	display_current_lock.acquire()
	try:
		# only update display_previous if a short message is currently not shown
		if show_previous_timestamp == -1:
			display_previous = list(display_current) # need to copy the list in display_current
			display_previous_scrolling_status = display_scrolling_enabled
		display_current[0] = text
		display_current[1] = u'Lautstärke: '+str(new_volume)+'%'
		show_previous_timestamp = short_msg_time + int(round(time.time() * 1000))
	finally:
		display_current_lock.release()

	# disable scrolling
	set_display_scrolling(False)


# check whether to show the previous display contents again
def check_and_show_previous():
	global show_previous_timestamp
	global display_current
	global display_current_lock
	global display_previous
	global display_previous_scrolling_status

	current = int(round(time.time() * 1000))
	if show_previous_timestamp >= 0 and current >= show_previous_timestamp:
		display_current_lock.acquire()
		try:
			display_current = list(display_previous)
		finally:
			display_current_lock.release()
		show_previous_timestamp = -1
		set_display_scrolling(display_previous_scrolling_status)


# convert the given string to unicode string (if it not already is a unicode string)
def to_unicode(str):
	text = str
	try:
		text = unicode(str, "utf-8")
	except TypeError:
		return text
	return text


# update the contents of display_current (the array, not the display itself) 
# to the currently running track
def update_display_current(display_title):
	global display_current_lock
	global mpc_lock

	title = ''
	if display_title:
		cmd="mpc current | head -1"
		try:
			mpc_lock.acquire()
			title=subprocess.check_output(cmd, shell=True)
		finally:
			mpc_lock.release()

	# if no track is selected do not change the display contents
	if not title:
		return

	# get information about current track
	try:
		mpc_lock.acquire()
		directory = media[media_list[media_current_dir_index]]
	finally:
		mpc_lock.release()

	directory = to_unicode(directory)
	title = to_unicode(title)

	# update display_current
	display_current_lock.acquire()
	try:
		display_current[0] = directory
		display_current[1] = title
	finally:
		display_current_lock.release()

# print the given sequence of button presses
def print_button_press_sequence(sequence):
	sequence_str = ''
	for elem in sequence:
		if len(sequence_str) > 0:
			sequence_str += ','
		if elem == PLAY_PAUSE:
			sequence_str += 'PLAY_PAUSE'
		if elem == NEXT:
			sequence_str += 'NEXT'
		if elem == PREV:
			sequence_str += 'PREV'
		if elem == VOLUME_UP:
			sequence_str += 'VOLUME_UP'
		if elem == VOLUME_DOWN:
			sequence_str += 'VOLUME_DOWN'
	print(sequence_str)


# compares the last elements of the first list with all elements of the second list,
# returns true if all compared elements equal
def sequences_match(long_list, short_list):
	if len(long_list) < len(short_list):
		return False

	for i in range(len(short_list)):
		if short_list[len(short_list)-1-i] != long_list[len(long_list)-1-i]:
			return False
	return True


# check if currently pressed button sequence matches any of the predefined sequences
def matching_sequence_found():
	global display_enabled
	global media_current_dir_index
	global button_press_sequence
	if sequences_match(button_press_sequence, sequence_next_dir):
		print('Sequence found: change to next directory')
		play_ping_sound()
		button_press_sequence[:] = []
		try:
			mpc_lock.acquire();
			media_current_dir_index = (media_current_dir_index + 1) % len(media_list)
			subprocess.Popen(["mpc", "stop"])
			playing = False
			subprocess.Popen(["mpc", "clear"])
			subprocess.Popen(["mpc", "update"])
			subprocess.Popen(["mpc", "add", media_list[media_current_dir_index]])
		finally:
			mpc_lock.release();
		update_display_current(False)
		return True

	if sequences_match(button_press_sequence, sequence_display):
		print('Sequence found: enable/disable display')
		play_ping_sound()
		button_press_sequence[:] = []
		if display_enabled:
			# disable display
			display_enabled = False
			lcd_lock.acquire()
			try:
				lcd.display_enabled = False
				lcd.backlight_enabled = False
			finally:
				lcd_lock.release()
		else:
			display_enabled = True
			# enable display
			lcd_lock.acquire()
			try:
				lcd.display_enabled = True
				lcd.backlight_enabled = True
			finally:
				lcd_lock.release()
		return True
	return False

def play_ping_sound():
	subprocess.Popen(["mpg123", "-q", ping_sound])

def shutdown():
	display_enabled = False
	lcd_lock.acquire()
	try:
		lcd.display_enabled = False
		lcd.backlight_enabled = False
	finally:
		lcd_lock.release()

def get_current_media_dir(dir_name):
	i = 0
	for item in media_list:
		if item == dir_name:
			return i
		i = i+1
	return -1
	

########################################################################
# THREAD FUNCTIONS
########################################################################

# function run by the separate display thread
# update the current contents of the LCD with the currently playing track
def display_thread_callback():
	global display_running
	global display_current
	global display_current_lock
	global show_previous_timestamp

	display_framebuffer = ['','']
	
	while display_running:

		check_and_show_previous()
		if not display_scrolling_enabled:
			write_to_lcd(display_current)
			continue
		
		# scroll the second row of the LCD
		for i in range(len(display_current[1])-16+1):

			# check whether to show the previous display contents again
			check_and_show_previous()

			# note that the scrolling may be disabled while it is running
			if not display_scrolling_enabled:
				write_to_lcd(display_current)
				continue

			display_current_lock.acquire()
			display_framebuffer[0] = display_current[0]
			display_framebuffer[1] = display_current[1][i:i+16]
			display_current_lock.release()
			write_to_lcd(display_framebuffer)
			time.sleep(display_sleep)

# function run by the thread that handles reading RFID tags,
# whenever a known tag is recognized the player switches
# to the directory associated with the tag and selects the
# first song to be played next
def rfid_thread_callback():
	global rfid_reader_running
	global uid_to_tag
	global media
	global media_list
	global playing
	global media_current_dir_index
	global button_press_sleep_time
	global MIFAREReader

	while rfid_reader_running:
		(status,TagType) = MIFAREReader.MFRC522_Request(MIFAREReader.PICC_REQIDL)
		if status == MIFAREReader.MI_OK:
			print "Karte gelesen"

		(status,uid) = MIFAREReader.MFRC522_Anticoll()
		if status == MIFAREReader.MI_OK:
			uid_str = str(uid[0])+","+str(uid[1])+","+str(uid[2])+","+str(uid[3])
			if uid_str == "0,0,0,0":
				continue
			elif uid_str not in uid_to_tag.keys():
				print "Karte mit dieser UID nicht von der Jukebox erfasst"
			else:
				print "UID: "+uid_str
				print "Wechsle in Ordner "+uid_to_tag[uid_str]+" ("+media[uid_to_tag[uid_str]]+")"
				play_ping_sound()
				try:
					mpc_lock.acquire();
					subprocess.Popen(["mpc", "-q", "stop"])
					playing_old = playing
					playing = False
					subprocess.Popen(["mpc", "-q", "clear"])
					subprocess.Popen(["mpc", "-q", "update"])
					media_current_dir_index = get_current_media_dir(uid_to_tag[uid_str])
					subprocess.Popen(["mpc", "-q", "add", media_list[media_current_dir_index]])
					if playing_old:
						subprocess.Popen(["mpc", "-q", "play"])
					else:
						# hack for selecting first song (required for updating display)
						subprocess.Popen(["mpc", "-q", "play"])
						subprocess.Popen(["mpc", "-q", "pause"])
					playing = playing_old
				finally:
					mpc_lock.release();
				update_display_current(True)
				time.sleep(button_press_sleep_time)


########################################################################
# MAIN
########################################################################

# initialize audio player
mpc_lock.acquire();
subprocess.Popen(["mpc", "clear"])
subprocess.Popen(["mpc", "update"])
subprocess.Popen(["mpc", "add", media_list[media_current_dir_index]])
subprocess.Popen(["mpc", "repeat", "on"])
mpc_lock.release();

# start display thread 
display_thread = Thread(target=display_thread_callback)
display_thread.start()

# start RFID thread
rfid_thread = Thread(target=rfid_thread_callback)
rfid_thread.start()

while True:

	if GPIO.input(gpio_play_pause) == True:
		button_press_sequence += [PLAY_PAUSE]
		if matching_sequence_found():
			continue
		if playing:
			print('Pause')
			try:
				mpc_lock.acquire();
				subprocess.Popen(["mpc", "-q", "pause"])
				playing = False
			finally:
				mpc_lock.release();
			set_display_scrolling(False)
		else:
			print('Play')
			try:
				mpc_lock.acquire();
				subprocess.Popen(["mpc", "-q", "play"])
				playing = True
			finally:
				mpc_lock.release();
			set_display_scrolling(True)

		update_display_current(True)
		time.sleep(button_press_sleep_time)

	elif GPIO.input(gpio_next) == True:
		print(u'Vorwärts')
		button_press_sequence += [NEXT]
		if matching_sequence_found():
			continue
		try:
			mpc_lock.acquire();
			subprocess.Popen(["mpc", "-q", "next"])
		finally:
			mpc_lock.release();
		update_display_current(True)
		time.sleep(button_press_sleep_time)

	elif GPIO.input(gpio_prev) == True:
		print(u'Rückwärts')
		button_press_sequence += [PREV]
		if matching_sequence_found():
			continue
		try:
			mpc_lock.acquire();
			subprocess.Popen(["mpc", "-q", "prev"])
		finally:
			mpc_lock.release();
		update_display_current(True)
		time.sleep(button_press_sleep_time)

	elif GPIO.input(gpio_volume_up) == True:
		print('Lauter')
		button_press_sequence += [VOLUME_UP]
		if matching_sequence_found():
			continue
		handle_volume_button_press('Lauter', True)
		time.sleep(button_press_sleep_time)

	elif GPIO.input(gpio_volume_down) == True:
		print('Leiser')
		button_press_sequence += [VOLUME_DOWN]
		if matching_sequence_found():
			continue
		handle_volume_button_press('Leiser', False)
		time.sleep(button_press_sleep_time)

# join all previously started threads
display_running = False
display_thread.join()
rfid_reader_running = False
rfid_thread.join()

GPIO.cleanup()
