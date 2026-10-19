package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"runtime/pprof"
	"strings"
	"sync"
	"time"
)

type sample struct {
	Mode            string `json:"mode"`
	Event           string `json:"event"`
	Wave            int    `json:"wave"`
	WorkersPerWave  int    `json:"workers_per_wave"`
	Baseline        int    `json:"baseline"`
	Goroutines      int    `json:"goroutines"`
	Delta           int    `json:"delta"`
	BadBlocked      int    `json:"bad_blocked"`
	GoodWorkerStack int    `json:"good_worker_stacks"`
}

func snapshot() ([]byte, int, int, error) {
	var b bytes.Buffer
	if err := pprof.Lookup("goroutine").WriteTo(&b, 2); err != nil {
		return nil, 0, 0, err
	}
	bad, good := 0, 0
	for _, stack := range strings.Split(b.String(), "\n\n") {
		if strings.Contains(stack, "main.badWorker(") && strings.Contains(strings.SplitN(stack, "\n", 2)[0], "[chan send]") {
			bad++
		}
		if strings.Contains(stack, "main.goodWorker(") {
			good++
		}
	}
	return b.Bytes(), bad, good, nil
}

func emit(mode, event string, wave, workers, baseline int) error {
	_, bad, good, err := snapshot()
	if err != nil {
		return err
	}
	n := runtime.NumGoroutine()
	return json.NewEncoder(os.Stdout).Encode(sample{mode, event, wave, workers, baseline, n, n - baseline, bad, good})
}

func waitFor(f func() bool) error {
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if f() {
			return nil
		}
		time.Sleep(time.Millisecond)
	}
	return fmt.Errorf("condition did not converge within 5s")
}

func run(mode string, waves, workers int, profileDir string) error {
	baseline := runtime.NumGoroutine()
	if err := emit(mode, "baseline", 0, workers, baseline); err != nil {
		return err
	}
	for wave := 1; wave <= waves; wave++ {
		ctx, cancel := context.WithCancel(context.Background())
		gate := make(chan struct{})
		out := make(chan int) // deliberately no receiver: the caller has left
		ready, attempted := make(chan struct{}, workers), make(chan struct{}, workers)
		var wg sync.WaitGroup
		wg.Add(workers)
		for i := 0; i < workers; i++ {
			go func() {
				defer wg.Done()
				if mode == "bad" {
					badWorker(out, gate, ready, attempted)
				} else {
					goodWorker(ctx, out, gate, ready, attempted)
				}
			}()
		}
		for i := 0; i < workers; i++ {
			<-ready
		}
		// Wait until each worker passes the gate and reaches the send path,
		// but leave all result channels without receivers.
		close(gate)
		for i := 0; i < workers; i++ {
			<-attempted
		}
		// This models a caller cancellation after work has reached the send.
		cancel()
		if mode == "good" {
			wg.Wait()
		}
		expected := wave * workers
		if mode == "good" {
			expected = 0
		}
		if err := waitFor(func() bool {
			_, bad, good, e := snapshot()
			return e == nil && bad == expected && good == 0 && runtime.NumGoroutine() == baseline+expected
		}); err != nil {
			return fmt.Errorf("wave %d: %w", wave, err)
		}
		if err := emit(mode, "wave", wave, workers, baseline); err != nil {
			return err
		}
	}
	runtime.GC()
	if err := emit(mode, "after_gc", waves, workers, baseline); err != nil {
		return err
	}
	if err := os.MkdirAll(profileDir, 0755); err != nil {
		return err
	}
	stack, _, _, err := snapshot()
	if err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(profileDir, "goroutine.txt"), stack, 0644); err != nil {
		return err
	}
	f, err := os.Create(filepath.Join(profileDir, "goroutine.pprof"))
	if err != nil {
		return err
	}
	err = pprof.Lookup("goroutine").WriteTo(f, 0)
	closeErr := f.Close()
	if err != nil {
		return err
	}
	return closeErr
}

func main() {
	mode := flag.String("mode", "bad", "bad or good")
	waves := flag.Int("waves", 5, "number of sequential waves")
	workers := flag.Int("workers", 50, "workers per wave")
	profileDir := flag.String("profile-dir", ".work/manual", "profile destination")
	flag.Parse()
	if (*mode != "bad" && *mode != "good") || *waves < 1 || *waves > 20 || *workers < 1 || *workers > 1000 {
		fmt.Fprintln(os.Stderr, "invalid mode or workload (waves 1..20, workers 1..1000)")
		os.Exit(2)
	}
	if err := run(*mode, *waves, *workers, *profileDir); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
