//go:build linux

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"runtime/pprof"
	"sync"
	"syscall"
	"time"
)

type cpuSample struct {
	UserUS   int64 `json:"user_us"`
	SystemUS int64 `json:"system_us"`
}

func cpu() cpuSample {
	var r syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &r); err != nil {
		panic(err)
	}
	return cpuSample{r.Utime.Sec*1000000 + r.Utime.Usec, r.Stime.Sec*1000000 + r.Stime.Usec}
}

func writeProfile(dir, name string, debug int) {
	suffix := ".pprof"
	if debug == 1 {
		suffix = ".txt"
	}
	f, err := os.Create(filepath.Join(dir, name+suffix))
	if err != nil {
		panic(err)
	}
	if err := pprof.Lookup(name).WriteTo(f, debug); err != nil {
		panic(err)
	}
	if err := f.Close(); err != nil {
		panic(err)
	}
}

func main() {
	mode := flag.String("case", "inside", "inside or outside")
	workers := flag.Int("workers", 16, "4 or 16 closed-loop workers")
	out := flag.String("out", "/out/manual", "profiles output directory")
	flag.Parse()
	if (*mode != "inside" && *mode != "outside") || (*workers != 4 && *workers != 16) {
		os.Exit(2)
	}
	if err := os.MkdirAll(*out, 0755); err != nil {
		panic(err)
	}
	runtime.GOMAXPROCS(1)
	debug.SetGCPercent(-1)
	const total = 128
	delay := 4 * time.Millisecond
	var s service
	ops := make([]operation, total)
	var ready, done sync.WaitGroup
	ready.Add(*workers)
	done.Add(*workers)
	gate := make(chan struct{})
	for w := 0; w < *workers; w++ {
		go func(worker int) {
			ready.Done()
			<-gate
			defer done.Done()
			for j := 0; j < total / *workers; j++ {
				id := worker + j*(*workers) + 1
				var op operation
				if *mode == "inside" {
					op = s.lockedDelay(id, delay)
				} else {
					op = s.outsideDelay(id, delay)
				}
				op.Worker = worker
				ops[id-1] = op // Each ID owns a distinct element; read only after Wait.
			}
		}(w)
	}
	ready.Wait()
	runtime.SetMutexProfileFraction(1)
	runtime.SetBlockProfileRate(1)
	before := cpu()
	begin := time.Now()
	close(gate)
	done.Wait()
	wallNS := time.Since(begin).Nanoseconds()
	after := cpu()
	runtime.SetMutexProfileFraction(0)
	runtime.SetBlockProfileRate(0)
	for _, name := range []string{"mutex", "block"} {
		writeProfile(*out, name, 0)
		writeProfile(*out, name, 1)
	}
	if s.count != total || s.sum != total*(total+1)/2 {
		fmt.Fprintln(os.Stderr, "required work missing or wrong sum")
		os.Exit(3)
	}
	_ = json.NewEncoder(os.Stdout).Encode(struct {
		Case       string      `json:"case"`
		GoVersion  string      `json:"go_version"`
		GOOS       string      `json:"goos"`
		GOARCH     string      `json:"goarch"`
		GOMAXPROCS int         `json:"gomaxprocs"`
		Workers    int         `json:"workers"`
		Total      int         `json:"total"`
		DelayNS    int64       `json:"delay_ns"`
		Count      int         `json:"completed"`
		Sum        int         `json:"sum"`
		WallNS     int64       `json:"wall_ns"`
		CPUBefore  cpuSample   `json:"cpu_before"`
		CPUAfter   cpuSample   `json:"cpu_after"`
		CPUTimeUS  int64       `json:"cpu_time_us"`
		CPUPercent float64     `json:"cpu_one_core_percent"`
		Operations []operation `json:"operations"`
	}{*mode, runtime.Version(), runtime.GOOS, runtime.GOARCH, runtime.GOMAXPROCS(0),
		*workers, total, delay.Nanoseconds(), s.count, s.sum, wallNS, before, after,
		after.UserUS + after.SystemUS - before.UserUS - before.SystemUS,
		float64(after.UserUS+after.SystemUS-before.UserUS-before.SystemUS) * 100000 / float64(wallNS), ops})
}
