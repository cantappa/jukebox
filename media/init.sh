#!/bin/bash

for i in $(echo $(seq 23)); do
	if (( $i < 10 )); then
		dir="0"$i
	else
		dir=$i
	fi
	echo $dir
	mkdir -p "tag-$dir"
done

exit 0

