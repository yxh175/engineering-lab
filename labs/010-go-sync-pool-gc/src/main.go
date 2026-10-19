package main

import (
	"encoding/json"
	"flag"
	"os"
	"runtime"
	"runtime/debug"
	"sync"
	"sync/atomic"
)

type GCPoint struct {
	Step  int    `json:"step"`
	NumGC uint32 `json:"num_gc"`
}

type Summary struct {
	Case             string    `json:"case"`
	GoVersion        string    `json:"go_version"`
	GOOS             string    `json:"goos"`
	GOARCH           string    `json:"goarch"`
	GOMAXPROCS       int       `json:"gomaxprocs"`
	GCPercent        int       `json:"gc_percent"`
	MemoryLimit      int64     `json:"memory_limit"`
	SeedID           uint64    `json:"seed_id"`
	SeedValue        int64     `json:"seed_value"`
	GCBaseline       uint32    `json:"gc_baseline"`
	GCFinal          uint32    `json:"gc_final"`
	GCPoints         []GCPoint `json:"gc_points"`
	IntermediateID   uint64    `json:"intermediate_id"`
	Found            bool      `json:"found"`
	ReturnedID       uint64    `json:"returned_id"`
	ValueBeforeReset int64     `json:"value_before_reset"`
	ReturnedValue    int64     `json:"returned_value"`
	InitialNewCalls  uint64    `json:"initial_new_calls"`
	NewCalls         uint64    `json:"new_calls"`
	Completed        int       `json:"completed"`
	ReuseHits        int       `json:"reuse_hits"`
	Checksum         int64     `json:"checksum"`
	Error            string    `json:"error"`
	ExitCode         int       `json:"exit_code"`
}

func numGC() uint32 {
	var stats runtime.MemStats
	runtime.ReadMemStats(&stats)
	return stats.NumGC
}

func main() {
	mode := flag.String("case", "pool-two-gc", "pool/cache case")
	flag.Parse()
	valid := map[string]bool{"pool-no-gc": true, "pool-one-gc": true, "pool-two-gc": true,
		"pool-refresh-two-gc": true, "pool-new-two-gc": true, "cache-two-gc": true, "pool-new-hot": true}
	if !valid[*mode] {
		os.Exit(2)
	}
	runtime.GOMAXPROCS(1)
	debug.SetGCPercent(-1)
	// Complete an initial GC before seeding, so all reported deltas are post-Put.
	runtime.GC()
	s := Summary{Case: *mode, GoVersion: runtime.Version(), GOOS: runtime.GOOS, GOARCH: runtime.GOARCH,
		GOMAXPROCS: runtime.GOMAXPROCS(0), GCPercent: -1, MemoryLimit: debug.SetMemoryLimit(-1),
		SeedID: 1, SeedValue: 314159, GCBaseline: numGC()}
	s.GCPoints = append(s.GCPoints, GCPoint{0, s.GCBaseline})
	var pool sync.Pool
	var cache Cache
	var newCalls atomic.Uint64
	if *mode == "pool-new-two-gc" || *mode == "pool-new-hot" {
		pool.New = func() any { return &Object{ID: newCalls.Add(1)} }
		seed := pool.Get().(*Object)
		seed.Value = s.SeedValue
		pool.Put(seed)
	} else if *mode == "cache-two-gc" {
		cache.Put("required-config", &Object{ID: s.SeedID, Value: s.SeedValue})
	} else {
		pool.Put(&Object{ID: s.SeedID, Value: s.SeedValue})
	}
	s.InitialNewCalls = newCalls.Load()
	forced := 2
	if *mode == "pool-no-gc" || *mode == "pool-new-hot" {
		forced = 0
	} else if *mode == "pool-one-gc" {
		forced = 1
	}
	for step := 1; step <= forced; step++ {
		runtime.GC()
		s.GCPoints = append(s.GCPoints, GCPoint{step, numGC()})
		if *mode == "pool-refresh-two-gc" && step == 1 {
			v, ok := pool.Get().(*Object)
			if !ok || v == nil {
				s.Error, s.ExitCode = "intermediate_required_object_missing", 3
				break
			}
			s.IntermediateID = v.ID
			pool.Put(v)
		}
	}
	if s.ExitCode == 0 {
		if *mode == "pool-new-hot" {
			for i := 0; i < 1000; i++ {
				v := pool.Get().(*Object)
				if v.ID == s.SeedID {
					s.ReuseHits++
				}
				v.Value = int64(i) // Reinitialize for this operation before use.
				s.Checksum += v.Value
				s.Completed++
				s.ReturnedID, s.ReturnedValue = v.ID, v.Value
				pool.Put(v)
			}
			s.Found = true
		} else {
			var v *Object
			if *mode == "cache-two-gc" {
				v, s.Found = cache.Get("required-config")
			} else {
				v, s.Found = pool.Get().(*Object)
			}
			if !s.Found || v == nil {
				s.Found = false
				s.Error, s.ExitCode = "required_object_missing", 3
			} else {
				s.ValueBeforeReset = v.Value
				if *mode == "pool-new-two-gc" {
					v.Value = 42 // Temporary-object contract: data is rebuilt, not recovered.
					s.Completed, s.Checksum = 1, v.Value
				}
				s.ReturnedID, s.ReturnedValue = v.ID, v.Value
			}
		}
	}
	s.NewCalls, s.GCFinal = newCalls.Load(), numGC()
	_ = json.NewEncoder(os.Stdout).Encode(s)
	os.Exit(s.ExitCode)
}
