package main

func goodConcurrent() {
	ch := make(chan int)
	received := make(chan int)
	go func() {
		v := <-ch
		received <- v
	}()
	emit("before-send", cap(ch), 42)
	ch <- 42
	emit("after-send", cap(ch), 42)
	emit("received", cap(ch), <-received)
}

func goodBuffered() {
	ch := make(chan int, 1)
	emit("before-send", cap(ch), 42)
	ch <- 42
	emit("after-send", cap(ch), 42)
	emit("received", cap(ch), <-ch)
}
