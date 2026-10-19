package main

import (
	"encoding/json"
	"flag"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"sync/atomic"
	"time"
)

func snapshot(path string) {
	b := make([]byte, 1<<20)
	n := runtime.Stack(b, true)
	if err := os.WriteFile(path, b[:n], 0644); err != nil {
		panic(err)
	}
}

//go:noinline
func worker(t *time.Ticker, exit <-chan struct{}, seen chan<- struct{}, done chan<- struct{}, ticks *atomic.Int64) {
	defer close(done)
	var once sync.Once
	for {
		select {
		case <-t.C:
			ticks.Add(1)
			once.Do(func() { close(seen) })
		case <-exit:
			return
		}
	}
}
func main() {
	mode := flag.String("case", "stop-only", "stop-only/stop-and-done/running-control")
	out := flag.String("outdir", "", "new directory")
	flag.Parse()
	if *out == "" || (*mode != "stop-only" && *mode != "stop-and-done" && *mode != "running-control") {
		os.Exit(64)
	}
	if err := os.Mkdir(*out, 0755); err != nil {
		panic(err)
	}
	runtime.GOMAXPROCS(1)
	ticker := time.NewTicker(20 * time.Millisecond)
	exit := make(chan struct{})
	seen := make(chan struct{})
	done := make(chan struct{})
	var ticks atomic.Int64
	go worker(ticker, exit, seen, done, &ticks)
	select {
	case <-seen:
	case <-time.After(2 * time.Second):
		panic("worker never received initial tick")
	}
	before := ticks.Load()
	stopped := *mode != "running-control"
	action := time.Now()
	if stopped {
		ticker.Stop()
	}
	requested := *mode == "stop-and-done"
	if requested {
		close(exit)
	}
	timer := time.NewTimer(100 * time.Millisecond)
	observedDone := false
	select {
	case <-done:
		observedDone = true
	case <-timer.C:
	}
	timer.Stop()
	elapsed := time.Since(action).Seconds() * 1000
	probeTicks := ticks.Load()
	snapshot(filepath.Join(*out, "probe.stack.txt"))
	if !requested {
		close(exit)
	}
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		panic("cleanup failed to join worker")
	}
	ticker.Stop()
	snapshot(filepath.Join(*out, "joined.stack.txt"))
	r := map[string]any{"case": *mode, "pid": os.Getpid(), "go": runtime.Version(), "os": runtime.GOOS, "arch": runtime.GOARCH,
		"gomaxprocs": 1, "godebug": os.Getenv("GODEBUG"), "ticker_interval_ms": 20, "observe_window_ms": 100,
		"ticker_channel_cap": cap(ticker.C), "ticks_before_action": before, "ticks_at_probe": probeTicks, "ticks_after_join": ticks.Load(),
		"ticker_stopped_before_probe": stopped, "exit_requested_before_probe": requested, "observed_done": observedDone,
		"observation_elapsed_ms": elapsed, "joined_after_cleanup": true}
	b, err := json.Marshal(r)
	if err != nil {
		panic(err)
	}
	if err := os.WriteFile(filepath.Join(*out, "result.json"), append(b, '\n'), 0644); err != nil {
		panic(err)
	}
	if _, err := os.Stdout.Write(append(b, '\n')); err != nil {
		panic(err)
	}
}
