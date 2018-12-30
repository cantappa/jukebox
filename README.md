# Paula's Jukebox

This repository contains the Python script and an example library specification for the Raspberry Pi Jukebox I created for my god child Paula.

For more information on this project have a look at this page: https://martinaeikel.de/wp/paulas-jukebox

## Adding Media to the Jukebox

Before we can describe how to actually media to the Jukebox we need to present the required underlying file structure.
In order to run the Jukebox on a Raspberry PI the file and directory structure are supposed to look as follows:

```
/home/pi/Jukebox
|---- jukebox.py
|---- library.json
|---- Media
      |---- tag-01
            |----- <media file 1>.mp3
            |----- <media file 2>.mp3
            |----- ...
      |---- tag-02
            |----- <further media file 1>.mp3
            |----- <further media file 2>.mp3
            |----- ...
      |---- ...
```

The file `library.json` defines the title of the directories `tag-*` and associates RFID cards with `tag-*` directories.
Whenever the jukebox detects an RFID tag the contents of the `tag-*` directory associated with that RFID tag (defined in `library.json`) the current playlist is reset to the contents of the associated `tag-*` directory and the jukebox starts playing that playlist (beginning with the first media file.

Adding new media to the Jukebox involves the following two steps:
 * Adapt the file library.json.
 * Upload media to directory /home/pi/Jukebox/Media/tag-*.
 
 ### Adapt library.json
 
 The library.json file contains a JSON array where each of its entries defines one directory and the associated path.
 An entry of the JSON array is supposed to have the following format:
 ```
 {
 "directory" : "tag-01",
 "name" : "<description/title of/for the contents of the considered directory>",
 "uid" : "<UID of RFID tag that initiates playing the contents of the considered directory>"
 }
```

A concrete example of an entry in the library looks as follows:
```
{
"directory" : "tag-01",
"name" : "Bobo Siebenschläfer",
"uid" : "176,223,243,121"
}
```

Such an entry defines the following behavior for the Jukebox: Whenever an RFID tag with UID "176,223,243,121" is detected, reset the current playlist to the contents of directory "tag-01" and start playing that playlist. The display is updated as follows: The first line shows "Bobo Siebenschläfer" and the second line shows the title of the currently played media file which is extracted from the ID3 information of the media file.
Hence, in order to correctly display the currently played media the title field of the ID3 tags of the media files needs to be set correctly.

