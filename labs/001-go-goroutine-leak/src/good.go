package main

import "context"

// Both possible blocking points observe cancellation.
func goodWorker(ctx context.Context, out chan<- int, gate <-chan struct{}, ready, attempted chan<- struct{}) {
	ready <- struct{}{}
	select {
	case <-gate:
	case <-ctx.Done():
		return
	}
	attempted <- struct{}{}
	select {
	case out <- 1:
	case <-ctx.Done():
		return
	}
}
