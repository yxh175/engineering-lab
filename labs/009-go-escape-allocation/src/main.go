package main

import (
	"encoding/json"
	"flag"
	"os"
	"runtime"
	"unsafe"
)

func main() {
	mode := flag.String("case", "PointerRetained", "case name")
	n := flag.Int("n", 100, "record count")
	flag.Parse()
	fn, ok := runners[*mode]
	if !ok || *n < 1 {
		os.Exit(2)
	}
	sum := fn(*n)
	out := map[string]any{
		"case": *mode, "n": *n, "checksum": sum,
		"record_bytes": unsafe.Sizeof(Record{}), "go_version": runtime.Version(),
		"gomaxprocs": runtime.GOMAXPROCS(0), "goos": runtime.GOOS, "goarch": runtime.GOARCH,
	}
	switch *mode {
	case "PointerRetained":
		out["retained_record"] = *pointerSink
	case "ValueRetained":
		out["retained_record"] = valueSink
	case "InterfaceRetained":
		out["retained_record"] = interfaceSink.(Record)
	}
	_ = json.NewEncoder(os.Stdout).Encode(out)
}
