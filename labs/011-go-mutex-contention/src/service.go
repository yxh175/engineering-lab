package main

import (
	"sync"
	"time"
)

type service struct {
	mu    sync.Mutex
	count int
	sum   int
}

type operation struct {
	ID        int   `json:"id"`
	Worker    int   `json:"worker"`
	LatencyNS int64 `json:"latency_ns"`
	WaitNS    int64 `json:"wait_ns"`
	HoldNS    int64 `json:"hold_ns"`
}

// Independent preparation: no shared data is read by this simulated wait.
func prepare(id int, delay time.Duration) int {
	time.Sleep(delay)
	return id
}

func (s *service) lockedDelay(id int, delay time.Duration) operation {
	begin := time.Now()
	beforeLock := time.Now()
	s.mu.Lock()
	acquired := time.Now()
	value := prepare(id, delay)
	s.count++
	s.sum += value
	beforeUnlock := time.Now()
	s.mu.Unlock()
	return operation{ID: id, LatencyNS: time.Since(begin).Nanoseconds(),
		WaitNS: acquired.Sub(beforeLock).Nanoseconds(), HoldNS: beforeUnlock.Sub(acquired).Nanoseconds()}
}

func (s *service) outsideDelay(id int, delay time.Duration) operation {
	begin := time.Now()
	value := prepare(id, delay)
	beforeLock := time.Now()
	s.mu.Lock()
	acquired := time.Now()
	s.count++
	s.sum += value
	beforeUnlock := time.Now()
	s.mu.Unlock()
	return operation{ID: id, LatencyNS: time.Since(begin).Nanoseconds(),
		WaitNS: acquired.Sub(beforeLock).Nanoseconds(), HoldNS: beforeUnlock.Sub(acquired).Nanoseconds()}
}
