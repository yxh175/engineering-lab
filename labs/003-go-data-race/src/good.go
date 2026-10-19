package main

import (
	"sync"
	"sync/atomic"
)

func goodAtomic(workers int) int64 {
	var counter atomic.Int64
	ready := make(chan struct{}, workers)
	gate := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(workers)
	for i := 0; i < workers; i++ {
		go func() {
			defer wg.Done()
			ready <- struct{}{}
			<-gate
			counter.Add(1)
		}()
	}
	for i := 0; i < workers; i++ {
		<-ready
	}
	close(gate)
	wg.Wait()
	return counter.Load()
}
