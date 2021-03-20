#!/bin/bash

export "PATH=$PATH:/snap/bin"
docker stop mediapolicebot || true
docker build -t mediapolicebot_image .
docker run -d --rm --network="host" --name mediapolicebot -v "$(pwd)/bot_data":/bot_data mediapolicebot_image