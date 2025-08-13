#!/bin/bash

function get_last_eventId() {
	local date_now=$(date -u +"%Y-%m-%d %H:%M:%S")
	local date_old=$(date -u -d "-14400 minutes" +"%Y-%m-%d %H:%M:%S") #10hari

	#YY MM DD untuk history
	local YY=$(date -u +"%Y")
	local MM=$(date -u +"%m")
	local DD=$(date -u +"%d")

	EVENT_OUT="event_parameter.txt"
	EVENT_300="event_300.txt"
	EVENT_DETAIL="event_detail.txt"
	TEMP_FILE="tmp_event300.txt"
	TMP_LIST="tmp300.txt"

	last_id=$(seiscomp exec scevtls -d mysql://sysop:sysop@localhost/seiscomp --begin "$date_old" --end "$date_now" | tail -n 1)
	seiscomp exec scevtls -d mysql://sysop:sysop@localhost/seiscomp --begin "$date_old" --end "$date_now" > "$TMP_LIST"

	if [[ -z "$last_id" ]]; then
		echo "No New Event"
		exit 1
	fi

	#eksekusi
	seiscomp exec scbulletin -d mysql://sysop:sysop@localhost/seiscomp -E "$last_id" -4 -x -e > "$EVENT_OUT" #csv
	
	#get all event 300
	#echo "EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType" > "$TEMP_FILE"

	while read -r id300; do
 	   if [[ -n "$id300" ]]; then
  	      seiscomp exec scbulletin -d mysql://sysop:sysop@localhost/seiscomp -E "$id300" -4 -x -e | \
   	      awk 'NR > 1 && $0 !~ /^#/ {print}' >> "$TEMP_FILE"
    	fi
	done < "$TMP_LIST"
	
	{
        echo "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType"
	grep -v '^$' "$TEMP_FILE" | tail -n 300
    	} > "$EVENT_300"
	
	seiscomp exec scbulletin -d mysql://sysop:sysop@localhost/seiscomp -E "$last_id" -3 -x -e > "$EVENT_DETAIL" #detail
		
	#scp histo
	#folder_summary="summary"
	#if [ ! -d "$folder_summary" ]; then
	#	mkdir -p "$folder_summary"
	#fi
	#cp ~/.seiscomp/log/events/"$YY"/"$MM"/"$DD"/"$last_id"/"$last_id".summary ./"$folder_summary"
	
	#manual scp 
	sshpass -p "xxx" scp /home/ubuntu/bin/event/"$EVENT_OUT" litbang@103.xxx:/home/litbang/AppSMART/Services/  #tentukan host dan pass
	sshpass -p "xxx" scp /home/ubuntu/bin/event/"$EVENT_300" litbang@103.xxx:/home/litbang/AppSMART/Services/
	sshpass -p "xxx" scp /home/ubuntu/bin/event/"$EVENT_DETAIL" litbang@103.xxx:/home/litbang/AppSMART/Services/

	rm -f "$TEMP_FILE" "$TMP_LIST"

}



# Fungsi untuk ubah parameter event ke JSON
function read_event2json() {
	input_file="event_parameter.txt"

	header=$(grep '^#' "$input_file" | head -n 1 | sed 's/^#//' )
	data=$(grep -v '^#' "$input_file" | head -n 1)

	IFS='|' read -r -a keys <<< "$header"
	IFS='|' read -r -a values <<< "$data"

	echo "{"
		for i in "${!keys[@]}"; do
			key=$(echo "${keys[i]}" | xargs)
			value=""
			if [[ -n "${values[i]}" ]]; then
				value=$(echo "${values[i]}" | xargs | sed 's/\\/\\\\/g; s/"/\\"/g')
			fi
			echo "  \"${key}\": \"${value}\","
			done | sed '$s/,$//'
	echo "}"
}


if [ "$2" = "1" ]; then
	get_last_eventId
	read_event2json
	echo " $1 " | sed 's/,/, ,/g'   | festival --tts
	# Fungsi untuk ambil event terbaru dari SeisComP
else
	get_last_eventId
	read_event2json
	echo " Event update, $1" | sed 's/,/, ,/g'  | festival --tts
fi
