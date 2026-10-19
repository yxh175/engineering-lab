FROM golang:1.25.4-bookworm@sha256:e17419604b6d1f9bc245694425f0ec9b1b53685c80850900a376fb10cb0f70cb AS builder
WORKDIR /src
COPY go.mod ./
COPY src ./src
RUN go vet ./src && CGO_ENABLED=0 go build -trimpath -o /app ./src
FROM scratch
COPY --from=builder /app /app
USER 65532:65532
ENTRYPOINT ["/app"]
