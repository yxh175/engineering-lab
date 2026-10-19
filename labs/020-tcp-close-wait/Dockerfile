FROM golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb
RUN apt-get update && apt-get install -y --no-install-recommends iproute2=6.1.0-3 && rm -rf /var/lib/apt/lists/*
WORKDIR /lab
