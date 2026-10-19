package main

func badUnbuffered() {
	defer func() {
		if v := recover(); v != nil {
			emit("recovered", 0, 0)
		}
	}()
	ch := make(chan int)
	emit("before-send", cap(ch), 42)
	ch <- 42
	emit("after-send", cap(ch), 42)
	emit("received", cap(ch), <-ch)
}

func badFullBuffer() {
	ch := make(chan int, 1)
	ch <- 42
	emit("buffer-filled", cap(ch), 42)
	emit("before-second-send", cap(ch), 99)
	ch <- 99
	emit("after-second-send", cap(ch), 99)
	emit("received", cap(ch), <-ch)
}
