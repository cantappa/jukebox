#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# This script runs the following threads:
# * display thread: 
#   - prints contents of display_current to the display,
#   - this thread is also responsible for scrolling the text
# * RFID thread:
#	- listens for an interrupt caused by reading an RFID tag
#   - on detection of an RFID tag play contents of associated directory
# * main thread
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
import threading
import logging
import sys
import string
import json

########################################################################
# CONFIGURATION
########################################################################

print("###########################################")
print("Jukebox startet...")

GPIO.setwarnings(False)

reload(sys)
sys.setdefaultencoding('utf8')

this_script_dir = sys.path[0]+"/"

# library information are stored in this JSON file
library_file = this_script_dir+"library.json"

# directory containing the "tag-*" directories which in turn contain the audio files
# NOTE: /etc/mpd.conf should contain 'music_directory "/home/pi/Jukebox/media"'
media_dir = "/home/pi/Jukebox/media/"
suonds_dir = media_dir+"sounds"

# will be filled with contents from JSON library
media_directories = [] # example: ["/home/pi/Jukebox/media/tag-01", "/home/pi/Jukebox/media/tag-02"]
media_titles = {}      # example: {"tag-01" : "Kitafrösche", "tag-02" : "Bobo"}
uid_to_tag = {}        # example: { "176,223,243,121" : "tag-01", "64,128,53,131" : "tag-02"}

# sounds
ping_sound = suonds_dir+"ping.mp3"				# sound to play when a registered RFID card is recognized 
													# or a hidden button sequence is pressed	
# startup_sound = suonds_dir+"hallo_paula.mp3"	# sound to play when Jukebox is successfully started and ready for interaction
startup_sound = ping_sound
play_startup_sound = True 							# whether to play the startup sound right after boot

initial_volume = "90"	# mpc percentage of initial volume
mpc_begin_volume = 50		# if the mpc volume is 50% display a volume of 0% at the LCD
scale_volume = 100/(100-mpc_begin_volume)

# display status
PAUSE=1
UNPAUSE=0

# via button sequences specific "hidden" functions can be triggered
PLAY_PAUSE = 0
PREV = 1
NEXT = 2
VOLUME_DOWN = 3
VOLUME_UP = 4

# sequence of recently pressed buttons
button_press_sequence = []

# button press sequences for hidden options,
# note that the sequences may not overlap
sequence_next_dir = [PREV, PLAY_PAUSE, PLAY_PAUSE, NEXT] 			# sequence for switching to next directory
sequence_display = [VOLUME_DOWN, PREV, PLAY_PAUSE, VOLUME_UP]		# sequence for disabling/enabling display
sequence_ip = [PREV, PREV, PREV, PREV, PREV]      					# show the IP address on the display
back_to_initial_volume = [VOLUME_DOWN, VOLUME_UP, VOLUME_DOWN, VOLUME_UP] # set volume to initial volume

# current (and initial) start media directory 
media_current_dir_index = 0

# define GPIO pins of the buttons
gpio_play_pause=4	# red button
gpio_prev=27		# green button
gpio_next=17		# yellow button
gpio_volume_up=23	# blue button
gpio_volume_down=18	# white button

# configure buttons
GPIO.setmode(GPIO.BCM)
GPIO.setup(gpio_play_pause, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(gpio_prev, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(gpio_next, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(gpio_volume_up, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(gpio_volume_down, GPIO.IN,pull_up_down=GPIO.PUD_DOWN)

button_callback_lock = Lock()

# store timestamp of last handled button press
now = time.time()
prev_callback_play_pause = now
prev_callback_prev = now
prev_callback_next = now
prev_callback_volume_up = now
prev_callback_volume_down = now

# sleep time after a button press (do not recognize a button press before x seconds)
button_press_sleep_time=0.5
volume_button_press_sleep_time=0.3

# initial text at display:
display_initial = ['', '']
display_initial[0] = '* * Paulas * * *'
display_initial[1] = '* * Jukebox  * *'

# the second row of the display is scrolled if it is larger than
# the display width; in this case this separator is used between
# the end of the end and the begin of the text to show
title_separator =  " * "

# show this when the jukebox has been stopped
jukebox_off_text = ["  Jukebox ist   ", " ausgeschaltet  "]

# create lcd object
options = {}
lcd = i2c.CharLCD('PCF8574', 0x27, port=1, charmap='A00', cols=16, rows=2, expander_params=options)
lcd_lock = Lock()

# RFID reader configuration
rfid_enabled = True			# the RFID reader can be disabled in this case the RFID reader thread is not created
rfid_reader_running = False	# whether the RFID reader thread is running
rfid_sleep_time = 1			# how long to wait (in seconds) until to accept a next card
if rfid_enabled:
	MIFAREReader = MFRC522.MFRC522()
	rfid_reader_running = True

#-----------------------------------------------------------------------
# display related variables

display_width = 16							# number of characters the display can show
display_enabled = True						# whether the display is used 
display_running = True						# whether the display thread is running
display_scrolling_always_disabled = False	# whether to deactivate scrolling of scrolling, 
											# by default the second display line containing the title is scrolled
display_scrolling_enabled = True			# whether to stop scrolling of second display line,
											# this is only used for *temporarily* disabling the scrolling, 
											# this is used when showing the volume after increasing or decreasing it
											# or in case the playback has been paused
display_current = list(display_initial)		# array holding the text to show in display
display_current_lock = Lock()				# lock access to any display related variables
display_previous = list(display_current)	# in case the display temporarily shows status information (e.g. volume info)
											# this variable holds the contents of the display before showing the status
											# informations
display_sleep=0.5							# sleep time (in s) for text scrolling,
											# this value defines the speed of text scrolling
											# the larger the value the slower the scrolling
display_thread_paused = False				# whether the diyplay is interrupted,
											# this variable is only set by the function set_display_thread_paused
											# and read by the display thread callback function
display_thread_paused_lock = Lock()
display_event_skip_wait = False				# whether the display thread shall skip waiting for the display event to be triggered
display_event_skip_wait_lock = Lock()
title_changed_observer_running = True		# If enabled an observer thread is run that periodically checks whether
											# the currently playing track coincides with the track shown on the display.
											# Those may diverge if the track has automatically changed (without RFID tag or button press).
											# This may happen if the selected track has ended and the next track in the same
											# directory is automatically started.
current_track = ""							# holds the currently played track,
											# updated on according button press, RFID card or by observer thread
title_changed_observer_sleep=2				# number of seconds to wait until new comparison of currently played track and diplay contents.

show_ip_address_on_startup = False			# whether to show the IP address right after booting on display
no_ip_text = "nicht verbunden"
enable_volume_info_output = True			# whether to output the new volume on the display on volum button press
show_volume_change_time_ms = 1500 			# how long to short info messages (in ms)
show_ip_time_ms = 4500						# how long to show the IP address at the display (in ms)
show_previous_timestamp = -1				# if set to a positive number, display the contents
                            				# of the previous display again at this time


#-----------------------------------------------------------------------
# debug output configuration

print_library = False		# print library contents at the beginning to console
print_button_info = True	# print pressed button to console
debug_output = True			# whether to enable/disable debug output

display_previous_scrolling_status = display_scrolling_enabled

# lock for performing a sequence of operations with the mpc command
# lock the variables media_current_dir_index, playing and sequences of calls to mpc
# that should better not be "interrupted"
mpc_lock = Lock()

# list of threads created during execution
threads = []

# whether the jukebox is playing a track or it is currently paused
playing = False
library_loaded = False

# event that can be triggered and causes the display thread to update its contents
display_event = threading.Event()
display_event_lock = Lock()

########################################################################
# FUNCTIONS
########################################################################

# get IP of wlan0 interface
def get_ip_address():
	cmd = "ip addr show wlan0 | grep -Po 'inet \K[\d.]+'"
	try:
		ip = subprocess.check_output(cmd, shell=True)
	except subprocess.CalledProcessError as e:
		return no_ip_text

	if ip == "":
		return no_ip_text

	return ip

# unbuffered printing is required for correctly printing when running this script as systemd service
def my_print(print_str):
	logging.debug(print_str)
	print "thread"+str(threading.current_thread().ident)+": "+print_str
	sys.stdout.flush()

def print_button_info(button):
	if print_button_info:
		my_print(button + " Knopf gedrückt")

def debug_output(print_str):
	if debug_output:
		my_print(print_str)

# convert the given string to unicode string (if it not already a unicode string)
def to_unicode(str):
	text = str
	try:
		text = unicode(str, "utf-8")
	except TypeError:
		return text
	return text

# prepare the given text for being displayed on the LCD
def prepare_for_display(str):
		# replace ß
		str=str.replace("ß", "ss")

		# remove non-printable characters
		# source: https://stackoverflow.com/questions/92438/stripping-non-printable-characters-from-a-string-in-python
		special_chars = "äÄöÖüÜ"
		str=''.join([x for x in str if(x in string.printable and x != '\n' and x != '\r') or (x in special_chars) ])
		
		return to_unicode(str)

def play_ping_sound():
	subprocess.Popen(["mpg123", "-q", ping_sound])
	

# print library contents (library needs to be loaded before)
def print_library():

	if not print_library:
		return

	if not library_loaded:
		return

	my_print("Inhalt der Bibliothek:")
	my_print("-------------------------------------------")
	for uid in uid_to_tag:
			dir_name = uid_to_tag[uid]
			my_print("Ordner: "+ dir_name)
			my_print("Titel: "+media_titles[dir_name])
			my_print("UID: "+uid)
			my_print("-------------------------------------------")
	

# load library from JSON file
def load_library():
	global media_directories
	global media_titles
	global uid_to_tag
	global library_loaded

	with open(library_file) as data_file:
	    library_as_json = json.load(data_file)
	    data_file.close()

	for entry in library_as_json:
		name = prepare_for_display(entry['name'])
		media_directories.append(entry['directory'])
		media_titles[entry['directory']] = name
		uid_to_tag[entry['uid']] = entry['directory']

	my_print("Bibliothek mit "+str(len(media_titles))+" Einträgen erfolgreich geladen.")
	library_loaded = True

# write the framebuffer out to the given LCD
def write_to_lcd(framebuffer):
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
	if display_scrolling_always_disabled:
		return

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
	mpc_volume = int(subprocess.check_output(cmd, shell=True))
	return mpc_volume

# clear the contents of display_current
# NOTE: this method may only be called if the display lock is already acquired
def clear_display_current():
	global display_current
	display_current[0] = '                '
	display_current[1] = '                '
	
def trigger_display_event():
	global display_event
	try:
		display_event_lock.acquire()
		display_event.set()
	finally:
		display_event_lock.release()

# thread safe setting of display thread status (paused or unpaused)
def set_display_thread_paused(status):
	global display_thread_paused
	global display_thread_paused_lock
	global display_event_skip_wait

	try:
		display_thread_paused_lock.acquire()
		if status == PAUSE:
			display_thread_paused = True
		elif status == UNPAUSE:
			display_thread_paused = False
	finally:
		display_thread_paused_lock.release()

	try:
		display_event_skip_wait_lock.acquire()
		display_event_skip_wait = True
	finally:
		display_event_skip_wait_lock.release()

# threadsafe getting of display thread status
def get_display_thread_paused():
	try:
		display_thread_paused_lock.acquire()
		paused = display_thread_paused
	finally:
		display_thread_paused_lock.release()
	return paused


# threadsafe getting of display array contents
def get_display_current():
	display_framebuffer = ['','']
	try:
		display_current_lock.acquire()
		display_framebuffer[0] = display_current[0]
		display_framebuffer[1] = display_current[1]
	finally:
		display_current_lock.release()
	return display_framebuffer


# Prints the given message for the given number of ms on the display.
# Remembers the previously shown text and shows that text after
# duration_in_ms ms has ellapsed.
def display_short_message(message_row_1, message_row_2, duration_in_ms):
	global display_current_lock
	global display_previous
	global display_previous_scrolling_status
	global display_current
	global show_previous_timestamp

	my_print("Zeige Nachricht für "+str(duration_in_ms)+"ms auf dem Display:")
	my_print(message_row_1)
	my_print(message_row_2)

	display_current_lock.acquire()
	try:
		# only update display_previous if a short message is currently not shown
		if show_previous_timestamp == -1:
			display_previous = list(display_current) # need to copy the list in display_current
			display_previous_scrolling_status = display_scrolling_enabled

		clear_display_current()
		display_current[0] = message_row_1
		display_current[1] = message_row_2

		# show previous display contents at this timestamp
		show_previous_timestamp = duration_in_ms + int(round(time.time() * 1000))
		set_display_scrolling(False)
		trigger_display_event()

		set_display_thread_paused(UNPAUSE)

	finally:
		display_current_lock.release()


# handle a button press, i.e.:
# * increase/decrease volume
# * pause display thread
# * change contents of display to current volume
# * disable display scrolling
# * unpause display thread
# * trigger display thread to proceed
def handle_volume_button_press(text, up):

	if up:
		subprocess.Popen(["mpc", "-q", "volume", "+2"])
	else:
		subprocess.Popen(["mpc", "-q", "volume", "-2"])

	new_volume=get_current_volume()

	if not enable_volume_info_output:
		return

	# display own scale of volume instead of the direct mpc volume
	display_volume = (new_volume - mpc_begin_volume)*scale_volume
	display_short_message(text, u'Lautstärke: '+str(display_volume)+'%', show_volume_change_time_ms)
	

# check whether to show the previous display contents again
# if so: update display array contents
def check_and_show_previous():
	global show_previous_timestamp
	global display_current
	global display_current_lock

	current = int(round(time.time() * 1000))
	if show_previous_timestamp >= 0 and current >= show_previous_timestamp:
		display_current_lock.acquire()
		try:
			clear_display_current()
			display_current = list(display_previous)
		finally:
			display_current_lock.release()
		show_previous_timestamp = -1
		set_display_scrolling(display_previous_scrolling_status)
		trigger_display_event()


# update the contents of display_current (the array, not the display itself) 
# to the currently running track
def update_display_current(update_display_title):
	global display_current_lock
	global mpc_lock
	global current_track
	global display_event

	title = ''
	if update_display_title:
		cmd="mpc current --format %title% | head -1"
		try:
			mpc_lock.acquire()
			title = subprocess.check_output(cmd, shell=True)
			title = prepare_for_display(title)
		finally:
			mpc_lock.release()

	# if no track is selected do not change the display contents
	if not title:
		return

	# get information about current track
	try:
		mpc_lock.acquire()
		directory = media_titles[media_directories[media_current_dir_index]]
	finally:
		mpc_lock.release()

	# update display_current
	set_display_thread_paused(PAUSE)
	display_current_lock.acquire()
	try:
		clear_display_current()
		display_current[0] = directory
		display_current[1] = title
	finally:
		display_current_lock.release()
	set_display_thread_paused(UNPAUSE)
	trigger_display_event() # fire event for waking up display thread

	# Store the currently running track in order to periodically update it with mpc current.
	# This is required since the track may change by itself without a button press happening.
	# This in turn happens if a track is finished and automatically the next one in the 
	# playlist is played.
	current_track="mpc current --format %file% | head -1"


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
	my_print(sequence_str)


# compares the last elements of the first list with all elements of the second list,
# returns true if all compared elements equal
def sequences_match(long_list, short_list):
	if len(long_list) < len(short_list):
		return False

	for i in range(len(short_list)):
		if short_list[len(short_list)-1-i] != long_list[len(long_list)-1-i]:
			return False

	my_print("Versteckte Option erkannt: "+str(short_list))
	return True


# check if currently pressed button sequence matches any of the predefined sequences
def matching_sequence_found():
	global display_enabled
	global media_current_dir_index
	global button_press_sequence

	# hidden option: show IP address at display
	if(sequences_match(button_press_sequence, sequence_ip)):
		my_print('Versteckte Option: Zeige IP-Addresse')
		play_ping_sound()
		button_press_sequence[:] = []
		display_short_message("IP Adresse:", get_ip_address(), show_ip_time_ms)
		return True

	# hidden option: switch to next directory
	if sequences_match(button_press_sequence, sequence_next_dir):
		my_print('Versteckte Option aktiviert: wechsle in nächsten Ordner')
		play_ping_sound()
		button_press_sequence[:] = []
		try:
			mpc_lock.acquire();
			media_current_dir_index = (media_current_dir_index + 1) % len(media_directories)
			subprocess.Popen(["mpc", "stop"])
			playing = False
			subprocess.Popen(["mpc", "clear"])
			subprocess.Popen(["mpc", "update"])
			subprocess.Popen(["mpc", "add", media_dir+media_directories[media_current_dir_index]])
		finally:
			mpc_lock.release();
		update_display_current(True) # TODO was False, check if it still works	
		return True

	# hidden option: enable/disable display
	if sequences_match(button_press_sequence, sequence_display):
		play_ping_sound()
		button_press_sequence[:] = []
		if display_enabled:
			my_print('Versteckte Option aktiviert: deaktiviere Display')
			# disable display
			display_enabled = False
			lcd_lock.acquire()
			try:
				lcd.display_enabled = False
				lcd.backlight_enabled = False
			finally:
				lcd_lock.release()
		else:
			my_print('Versteckte Option aktiviert: aktiviere Display')
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

def shutdown_display():
	display_enabled = False
	lcd_lock.acquire()
	try:
		lcd.display_enabled = False
		lcd.backlight_enabled = False
	finally:
		lcd_lock.release()

def get_current_media_dir(dir_name):
	i = 0
	for item in media_directories:
		if item == dir_name:
			return i
		i = i+1
	return -1


########################################################################
# THREAD FUNCTIONS
########################################################################

# function run by the separate display thread
# updates the current contents of the LCD with the currently playing track
def display_thread_callback():
	global display_running
	global display_current
	global display_current_lock
	global show_previous_timestamp
	global display_event
	global display_event_skip_wait

	if not display_enabled:
		shutdown_display()
		return

	while display_running:
		paused = get_display_thread_paused()
		if paused:
			time.sleep(0.1)
			continue
		# Triggering the display event may have been missed.
		# This is the case, if the display event is triggered while 
		# the display thread (that executes this function) is currently 
		# somewhere after the call of display_event.wait()
		# but before the next call of display_event.wait().
		# This may only happen if the display thread has been paused.
		# In those cases the variable display_event_skip_wait is
		# set to true.
		skip_wait = False
		try:
			display_event_skip_wait_lock.acquire()
			skip_wait = display_event_skip_wait
		finally:
			display_event_skip_wait_lock.release()
		if skip_wait:
			try:
				display_event_skip_wait_lock.acquire()
				display_event_skip_wait = True
			finally:
				display_event_skip_wait_lock.release()
		else:
			display_event.wait()
			display_event.clear()
		check_and_show_previous()
		if not display_scrolling_enabled:
			write_to_lcd(display_current)
			continue

		#
		# Show contents of display array on the display.
		# If the text of the second row is longer than the
		# display width, then the text is scrolled over the display.
		#

		display_framebuffer = get_display_current()

		# if text fits on the display or if the scrolling is disabled, just print the text
		if len(display_framebuffer[1]) <= display_width or not display_scrolling_enabled:
				write_to_lcd(display_framebuffer)
				continue
		
		# iterate over text of the second row
		i = 0
		paused = False
		display_contents_changed = True
		display_current_copy = get_display_current()
		while not paused:
			
			# check whether to show the previous display contents again (may update display_current)
			display_contents_before = get_display_current()
			check_and_show_previous()
			display_current_copy = get_display_current()
			if i != 0 and display_contents_before != display_current_copy: # TODO check if array comparsion works
				i = 0

			# do not scroll short texts or if the scrolling is disabled in general
			if len(display_current_copy[1]) <= display_width or not display_scrolling_enabled:
				write_to_lcd(display_current_copy)
				continue # go back to waiting for display event
			# text is too long => scroll it
			text_length = len(display_current_copy[1] + title_separator)
			second_row = display_current_copy[1] + title_separator + display_current_copy[1]

			#
			# Example with an 8 characters display: 
			#
			# s c r o l l   t e x t   *   s c r o l l
			#    |i _ _ _ _ _ _ _|_ _ _ _ _ _ _ _
			#     0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7
			#

			# update LCD
			display_current_copy[1] = second_row[i:i+display_width]
			write_to_lcd(display_current_copy)
			i = (i+1) % text_length
			time.sleep(display_sleep)
			paused = get_display_thread_paused()

# function run by the thread that handles reading RFID tags,
# whenever a known tag is recognized the player switches
# to the directory associated with the tag and selects the
# first song to be played next
def rfid_thread_callback():
	global rfid_reader_running
	global uid_to_tag
	global media_titles
	global media_directories
	global playing
	global media_current_dir_index
	global MIFAREReader
	
	while rfid_reader_running:
		MIFAREReader.MFRC522_WaitForCard()

		(status,TagType) = MIFAREReader.MFRC522_Request(MIFAREReader.PICC_REQIDL)
		if status == MIFAREReader.MI_OK:
			my_print("RFID-Karte gelesen")

		(status,uid) = MIFAREReader.MFRC522_Anticoll()
		if status == MIFAREReader.MI_OK:
			uid_str = str(uid[0])+","+str(uid[1])+","+str(uid[2])+","+str(uid[3])
			if uid_str == "0,0,0,0":
				continue
			elif uid_str not in uid_to_tag.keys():
				my_print("Karte mit dieser UID nicht von der Jukebox erfasst.")
			else:
				my_print("UID: "+uid_str)
				my_print("Wechsle in Ordner "+uid_to_tag[uid_str]+" ("+media_titles[uid_to_tag[uid_str]]+")")
				play_ping_sound()
				try:
					mpc_lock.acquire();
					subprocess.Popen(["mpc", "-q", "stop"])
					playing = False
					subprocess.Popen(["mpc", "-q", "clear"])
					subprocess.Popen(["mpc", "-q", "update"])
					media_current_dir_index = get_current_media_dir(uid_to_tag[uid_str])
					subprocess.Popen(["mpc", "-q", "add", media_dir+media_directories[media_current_dir_index]])
					subprocess.Popen(["mpc", "-q", "play"])
				finally:
					mpc_lock.release();

				set_display_scrolling(True)
				playing = True
				set_display_thread_paused(UNPAUSE)
				update_display_current(True)


# check whether current title has changed and in case it has, initiate display update
def title_changed_observer_callback():
	while title_changed_observer_running:

		# if the jukebox is not playing, the title cannot change automatically
		if not playing:
			continue

		mpc_current_track="mpc current --format %file% | head -1"
		if mpc_current_track != current_track:
			update_display_current(True)

		time.sleep(title_changed_observer_sleep)

#-----------------------------------------------------------------------
# CALLBACK FUNCTIONS FOR BUTTON PRESSES

# manual handling of prelling (bounce of add_event_detect does not always seem to work)
def proceed_handling(prev_timestamp, bounce_time):
	now = time.time()
	sum = prev_timestamp + bounce_time
	if now < sum:
		return False
	return True

def play_pause_callback(channel):

	try:
		button_callback_lock.acquire()

		global prev_callback_play_pause
		if not proceed_handling(prev_callback_play_pause, button_press_sleep_time):
			return 	
		prev_callback_play_pause = time.time()

		global button_press_sequence
		global playing
		button_press_sequence += [PLAY_PAUSE]
		if matching_sequence_found():
			return

		if playing:
			my_print(u'>> \"Pause Knopf\" gedrückt')
			try:
				mpc_lock.acquire();
				subprocess.Popen(["mpc", "-q", "pause"])
				playing = False
			finally:
				mpc_lock.release();
			set_display_scrolling(False)
		else:
			my_print(u'>> \"Play Knopf\" gedrückt')
			try:
				mpc_lock.acquire();
				subprocess.Popen(["mpc", "-q", "play"])
				playing = True
			finally:
				mpc_lock.release();
			set_display_scrolling(True)
		update_display_current(True)
	finally:
		button_callback_lock.release()
	
#-----------------------------------------------------------------------

def next_callback(channel):
	try:
		button_callback_lock.acquire()

		global prev_callback_next
		if not proceed_handling(prev_callback_next, button_press_sleep_time):
			return 	
		prev_callback_next = time.time()

		global button_press_sequence
		global playing
		my_print(u'>> \"Nächster Knopf\" gedrückt')
		button_press_sequence += [NEXT]
		if matching_sequence_found():
			return

		try:
			mpc_lock.acquire();
			subprocess.Popen(["mpc", "-q", "next"])
			playing = True
		finally:
			mpc_lock.release();

		set_display_scrolling(True)
		update_display_current(True)
	finally:
		button_callback_lock.release()

#-----------------------------------------------------------------------

def prev_callback(channel):

	try:
		button_callback_lock.acquire()

		global prev_callback_prev
		if not proceed_handling(prev_callback_prev, button_press_sleep_time):
			return 	

		prev_callback_prev = time.time()

		global button_press_sequence
		global playing
		button_press_sequence += [PREV]
		if matching_sequence_found():
			return
		try:
			mpc_lock.acquire();
			subprocess.Popen(["mpc", "-q", "prev"])
			playing = True
		finally:
			mpc_lock.release();
		
		set_display_scrolling(True)
		update_display_current(True)
	finally:
		button_callback_lock.release()

#-----------------------------------------------------------------------

def volume_up_callback(channel):

 	if GPIO.input(channel):
 		return

	# TODO why no locking?
	global prev_callback_volume_up
	if not proceed_handling(prev_callback_volume_up, volume_button_press_sleep_time):
		return 	
	prev_callback_volume_up = time.time()

	global button_press_sequence
	my_print(u'>> \"Lautstärke erhöhen Knopf\" gedrückt')
	button_press_sequence += [VOLUME_UP]
	if matching_sequence_found():
		return

	handle_volume_button_press('Lauter', True)

#-----------------------------------------------------------------------

def volume_down_callback(channel):

 	if GPIO.input(channel):
 		return

	global prev_callback_volume_down
	if not proceed_handling(prev_callback_volume_down, volume_button_press_sleep_time):
		return 	
	prev_callback_volume_down = time.time()

	global button_press_sequence
	my_print(u'>> \"Lautstärke verringern Knopf\" gedrückt')
	button_press_sequence += [VOLUME_DOWN]
	if matching_sequence_found():
		return

	handle_volume_button_press('Leiser', False)

########################################################################
# MAIN
########################################################################

# define button callbacks
bounce_time = 1000
bounce_time_volume_button = 400
GPIO.add_event_detect(gpio_play_pause,GPIO.RISING, callback=play_pause_callback, bouncetime=bounce_time)
GPIO.add_event_detect(gpio_next,GPIO.RISING, callback=next_callback, bouncetime=bounce_time)
GPIO.add_event_detect(gpio_prev,GPIO.RISING, callback=prev_callback, bouncetime=bounce_time)
GPIO.add_event_detect(gpio_volume_up,GPIO.RISING, callback=volume_up_callback, bouncetime=bounce_time_volume_button)
GPIO.add_event_detect(gpio_volume_down,GPIO.RISING, callback=volume_down_callback, bouncetime=bounce_time_volume_button)

# load library
load_library()
print_library()

# initialize audio player
mpc_lock.acquire()
my_print("Initialisiere mpc...")
subprocess.Popen(["mpc", "-q", "stop"]) # just in case mpc is currently running
subprocess.Popen(["mpc", "-q", "volume", initial_volume])
subprocess.Popen(["mpc", "clear"])
subprocess.Popen(["mpc", "update"])
subprocess.Popen(["mpc", "add", media_dir+media_directories[media_current_dir_index]])
subprocess.Popen(["mpc", "repeat", "on"])
mpc_lock.release()

# start display thread (only if scrolling is enabled)
display_thread = Thread(target=display_thread_callback)
display_thread.start()

# show the IP address after startup for show_ip_time_ms seconds (if already connected)
if show_ip_address_on_startup:
	ip_address = get_ip_address()
	if ip_address != no_ip_text: 
		display_short_message("IP Adresse:", get_ip_address(), show_ip_time_ms)

trigger_display_event()

# start RFID thread
if rfid_enabled:
	rfid_thread = Thread(target=rfid_thread_callback)
	rfid_thread.start()

# thread for checking whether the current title has changed
# without a button press, in case it has changed initiate a display update
title_changed_observer_thread = Thread(target=title_changed_observer_callback)
title_changed_observer_thread.start()

# play startup sound
if play_startup_sound:
	subprocess.Popen(["mpg123", "-q", startup_sound])

try:
	time.sleep(99999999999)
except KeyboardInterrupt:  
	GPIO.cleanup()

my_print("Jukebox wird beendet...")

display_current_lock.acquire()
try:
	clear_display_current()
	display_current = jukebox_off_text
finally:
	display_current_lock.release()
trigger_display_event()

# join all previously started threads
display_running = False
display_thread.join()

if rfid_enabled:
	rfid_reader_running = False
	rfid_thread.join()

title_changed_observer_running = False
title_changed_observer_thread.join()

GPIO.cleanup()
