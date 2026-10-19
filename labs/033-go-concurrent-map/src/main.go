package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"sync"
	"sync/atomic"
)

const total = 100000

func emit(fields map[string]any) {
	if err := json.NewEncoder(os.Stdout).Encode(fields); err != nil {
		panic(err)
	}
}
func main() {
	mode := flag.String("case", "bad", "bad/mutex/single-writer")
	out := flag.String("outdir", "", "new evidence directory")
	flag.Parse()
	if *out == "" || (*mode != "bad" && *mode != "mutex" && *mode != "single-writer") {
		os.Exit(64)
	}
	if err := os.Mkdir(*out, 0755); err != nil {
		panic(err)
	}
	runtime.GOMAXPROCS(2)
	writers := 4
	if *mode == "single-writer" {
		writers = 1
	}
	emit(map[string]any{"event": "start", "case": *mode, "pid": os.Getpid(), "go": runtime.Version(), "os": runtime.GOOS, "arch": runtime.GOARCH, "gomaxprocs": runtime.GOMAXPROCS(0), "writers": writers, "total": total})
	m := make(map[int]int, total)
	var mu sync.Mutex
	var ready, done sync.WaitGroup
	var completed atomic.Int32
	start := make(chan struct{})
	ready.Add(writers)
	done.Add(writers)
	for w := 0; w < writers; w++ {
		go func(w int) {
			defer done.Done()
			defer func() {
				if v := recover(); v != nil {
					emit(map[string]any{"event": "worker_recovered", "panic": fmt.Sprint(v)})
				}
			}()
			ready.Done()
			<-start
			low, high := w*(total/writers), (w+1)*(total/writers)
			for i := low; i < high; i++ {
				if *mode == "mutex" {
					mu.Lock()
				}
				m[i] = i*3 + 7
				if *mode == "mutex" {
					mu.Unlock()
				}
			}
			completed.Add(1)
		}(w)
	}
	ready.Wait()
	emit(map[string]any{"event": "barrier", "ready_writers": writers})
	close(start)
	done.Wait()
	keys := make([]int, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Ints(keys)
	f, err := os.Create(filepath.Join(*out, "entries.tsv"))
	if err != nil {
		panic(err)
	}
	h := sha256.New()
	b := bufio.NewWriter(io.MultiWriter(f, h))
	for _, k := range keys {
		if _, err := fmt.Fprintf(b, "%d\t%d\n", k, m[k]); err != nil {
			panic(err)
		}
	}
	if err := b.Flush(); err != nil {
		panic(err)
	}
	if err := f.Close(); err != nil {
		panic(err)
	}
	emit(map[string]any{"event": "completed", "entries": len(m), "writers_completed": completed.Load(), "entries_sha256": hex.EncodeToString(h.Sum(nil))})
}
