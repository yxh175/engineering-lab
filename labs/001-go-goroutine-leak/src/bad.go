package main

// The caller has stopped receiving. Cancellation is not observed here.
func badWorker(out chan<- int, gate <-chan struct{}, ready, attempted chan<- struct{}) {
	ready <- struct{}{}
	<-gate
	attempted <- struct{}{}
	out <- 1
}
