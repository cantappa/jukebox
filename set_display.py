#!/usr/bin/python
#
# Update contents of display.
# If two input parameters are given print first parameter
# into first line of display and second parameter to second line of display.
# If less than two input parameters are given print the string specified
# below on the display.
#

import time
import sys
from RPLCD import i2c, gpio

framebuffer = ['','']
if len(sys.argv) >= 2:
	framebuffer[0] = sys.argv[1]
	framebuffer[1] = sys.argv[2]
else:
	framebuffer[0] = "  Jukebox ist   "
	framebuffer[1] = " ausgeschaltet  "

print "Update display content to:"
print framebuffer[0]
print framebuffer[1]

# write the framebuffer out to the given LCD
def write_to_lcd(lcd, framebuffer):
	num_cols = 16
	lcd.home()
	for row in framebuffer:
		lcd.write_string(row.ljust(num_cols)[:num_cols])
		lcd.write_string('\r\n')

# create lcd object
options = {}
lcd = i2c.CharLCD('PCF8574', 0x27, port=1, charmap='A00', cols=16, rows=2, expander_params=options)

write_to_lcd(lcd, framebuffer)

# uncomment for scrolling second line
# line2 = framebuffer[1]
# for i in range(len(line2)-16+1):
# 	framebuffer[1] = line2[i:i+16]
# 	write_to_lcd(lcd, framebuffer)
# 	time.sleep(0.2)
