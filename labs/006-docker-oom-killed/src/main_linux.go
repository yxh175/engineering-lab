//go:build linux

package main

import (
	"flag"
	"fmt"
	"os"
	"runtime"
	"time"
)

const chunkBytes = 8 * 1024 * 1024
const iterations = 32

func touchPages(b []byte, iteration int) {
	for offset := 0; offset < len(b); offset += os.Getpagesize() {
		b[offset] = byte(iteration + offset/os.Getpagesize())
	}
}

func badRetain(mode string) error {
	buffers := make([][]byte, 0, iterations)
	for i := 1; i <= iterations; i++ {
		b := make([]byte, chunkBytes)
		touchPages(b, i)
		buffers = append(buffers, b)
		if err := emit(mode, "sample", i, len(buffers)); err != nil {
			return err
		}
	}
	runtime.KeepAlive(buffers)
	return emit(mode, "completed", iterations, len(buffers))
}

func goodReuse(mode string) error {
	b := make([]byte, chunkBytes)
	for i := 1; i <= iterations; i++ {
		touchPages(b, i)
		if err := emit(mode, "sample", i, 1); err != nil {
			return err
		}
	}
	runtime.KeepAlive(b)
	return emit(mode, "completed", iterations, 1)
}

func run() error {
	mode := flag.String("case", "bad-retain", "bad-retain, good-reuse, manual-kill")
	flag.Parse()
	if *mode != "bad-retain" && *mode != "good-reuse" && *mode != "manual-kill" {
		return fmt.Errorf("invalid case")
	}
	runtime.GOMAXPROCS(2)
	if err := emit(*mode, "baseline", 0, 0); err != nil {
		return err
	}
	switch *mode {
	case "bad-retain":
		return badRetain(*mode)
	case "good-reuse":
		return goodReuse(*mode)
	default:
		b := make([]byte, chunkBytes)
		touchPages(b, 1)
		if err := emit(*mode, "ready", 1, 1); err != nil {
			return err
		}
		time.Sleep(30 * time.Second) // runner waits for ready, then sends SIGKILL
		runtime.KeepAlive(b)
		return fmt.Errorf("manual SIGKILL was not injected within the bounded wait")
	}
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
