package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"os"
	"path/filepath"
	"runtime"
	"runtime/pprof"
)

const arrayBytes = 32 << 20

var held []byte

type Sample struct {
	Stage        string `json:"stage"`
	Len          int    `json:"len"`
	Cap          int    `json:"cap"`
	PayloadHex   string `json:"payload_hex"`
	SHA256       string `json:"sha256"`
	HeapAlloc    uint64 `json:"heap_alloc"`
	HeapInuse    uint64 `json:"heap_inuse"`
	HeapSys      uint64 `json:"heap_sys"`
	HeapReleased uint64 `json:"heap_released"`
	TotalAlloc   uint64 `json:"total_alloc"`
	NumGC        uint32 `json:"num_gc"`
}

//go:noinline
func retain(mode string) []byte {
	b := make([]byte, arrayBytes)
	for i := range b {
		b[i] = byte(i % 251)
	}
	a, z := len(b)/2, len(b)/2+32
	view := b[a:z]
	if mode == "cap-limited" {
		view = b[a:z:z]
	}
	if mode == "copied" {
		view = bytes.Clone(view)
	}
	return view
}

func capture(stage, out string) Sample {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	h := sha256.Sum256(held)
	s := Sample{stage, len(held), cap(held), hex.EncodeToString(held), hex.EncodeToString(h[:]),
		m.HeapAlloc, m.HeapInuse, m.HeapSys, m.HeapReleased, m.TotalAlloc, m.NumGC}
	f, err := os.Create(filepath.Join(out, stage+".pprof"))
	if err != nil {
		panic(err)
	}
	if err = pprof.WriteHeapProfile(f); err != nil {
		panic(err)
	}
	if err = f.Close(); err != nil {
		panic(err)
	}
	runtime.KeepAlive(held)
	return s
}

func gcTwice() { runtime.GC(); runtime.GC() }

func main() {
	mode := flag.String("case", "", "subslice/cap-limited/copied")
	out := flag.String("outdir", "", "new owned evidence directory")
	flag.Parse()
	if *mode != "subslice" && *mode != "cap-limited" && *mode != "copied" {
		panic("unknown case")
	}
	if err := os.Mkdir(*out, 0700); err != nil {
		panic(err)
	}
	runtime.GOMAXPROCS(1)
	runtime.MemProfileRate = 1
	gcTwice()
	before := capture("baseline", *out)
	held = retain(*mode)
	gcTwice()
	live := capture("held", *out)
	held = nil
	gcTwice()
	released := capture("released", *out)
	result := map[string]any{"case": *mode, "pid": os.Getpid(), "go": runtime.Version(),
		"os": runtime.GOOS, "arch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0),
		"mem_profile_rate": runtime.MemProfileRate, "array_bytes": arrayBytes,
		"samples": []Sample{before, live, released}}
	raw, err := json.Marshal(result)
	if err != nil {
		panic(err)
	}
	if err = os.WriteFile(filepath.Join(*out, "result.json"), append(raw, '\n'), 0600); err != nil {
		panic(err)
	}
	os.Stdout.Write(append(raw, '\n'))
}
