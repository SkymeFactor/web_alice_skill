#!/bin/bash
# Executes the curl command for multipart/form-data Content-type
# that explicitly allows to use it within azure docker container
# Arguments:
#   - OAuth_ID
#   - file_path to the file
#   - url to send the file to
DATA=$(curl -s\
    -H "Content-Type: multipart/form-data" \
    -H "Authorization: OAuth $1" \
    -X POST \
    -F file=@$2 \
    $3)
echo $DATA