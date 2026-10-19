package main

import "sync"

// All reads precede release, but the writes are not ordered with each other.
func badBarrier(workers int) int64 {
	var counter int64
	ready := make(chan struct{}, workers)
	gate := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(workers)
	for i := 0; i < workers; i++ {
		go func() {
			defer wg.Done()
			old := counter
			ready <- struct{}{}
			<-gate
			counter = old + 1
		}()
	}
	for i := 0; i < workers; i++ {
		<-ready
	}
	close(gate)
	wg.Wait()
	return counter
}

// GOMAXPROCS=1 restricts execution capacity, not the memory synchronization contract.
func badCorrect(workers int) int64 {
	var counter int64
	var wg sync.WaitGroup
	wg.Add(workers)
	for i := 0; i < workers; i++ {
		go func() {
			counter++
			wg.Done()
		}()
	}
	wg.Wait()
	return counter
}
