FROM golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb
WORKDIR /lab
COPY go.mod ./
COPY src/ ./src/
ENV CGO_ENABLED=0 GOTOOLCHAIN=local
RUN go build -trimpath -o /usr/local/bin/lab ./src
ENTRYPOINT ["/usr/local/bin/lab"]
CMD ["-role", "origin", "-listen", ":8080"]
