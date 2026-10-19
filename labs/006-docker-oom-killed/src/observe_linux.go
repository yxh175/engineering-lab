//go:build linux

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"strconv"
	"strings"
)

func readNumber(name string) (uint64, error) {
	b, err := os.ReadFile("/sys/fs/cgroup/" + name)
	if err != nil {
		return 0, err
	}
	return strconv.ParseUint(strings.TrimSpace(string(b)), 10, 64)
}

func emit(mode, event string, iteration int, retained int) error {
	metrics := make(map[string]uint64)
	for _, name := range []string{"memory.current", "memory.peak", "memory.max", "memory.swap.max"} {
		n, err := readNumber(name)
		if err != nil {
			return err
		}
		metrics[name] = n
	}
	b, err := os.ReadFile("/sys/fs/cgroup/memory.events")
	if err != nil {
		return err
	}
	events := make(map[string]uint64)
	for _, line := range strings.Split(strings.TrimSpace(string(b)), "\n") {
		f := strings.Fields(line)
		if len(f) != 2 {
			return fmt.Errorf("invalid memory.events row")
		}
		n, err := strconv.ParseUint(f[1], 10, 64)
		if err != nil {
			return err
		}
		events[f[0]] = n
	}
	status, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return err
	}
	var rssKiB uint64
	for _, line := range strings.Split(string(status), "\n") {
		if strings.HasPrefix(line, "VmRSS:") {
			fields := strings.Fields(line)
			rssKiB, err = strconv.ParseUint(fields[1], 10, 64)
			if err != nil {
				return err
			}
		}
	}
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)
	return json.NewEncoder(os.Stdout).Encode(map[string]any{
		"case": mode, "event": event, "iteration": iteration, "iterations_planned": iterations,
		"chunk_bytes": chunkBytes, "page_bytes": os.Getpagesize(), "regions_processed_bytes": iteration * chunkBytes,
		"page_writes": iteration * (chunkBytes / os.Getpagesize()), "retained_buffers": retained,
		"cgroup": metrics, "memory_events": events, "process_vm_rss_kib": rssKiB,
		"heap_alloc_bytes": mem.HeapAlloc, "heap_sys_bytes": mem.HeapSys,
		"go_version": runtime.Version(), "pid": os.Getpid(), "gogc": os.Getenv("GOGC"), "gomemlimit": os.Getenv("GOMEMLIMIT"),
	})
}
