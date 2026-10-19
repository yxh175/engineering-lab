package main

import (
	"fmt"
	"os"
	"os/signal"
	"syscall"
)

func main() {
	fmt.Println("{\"event\":\"ready\",\"work\":\"wait-signal\"}")
	done := make(chan os.Signal, 1)
	signal.Notify(done, syscall.SIGTERM, syscall.SIGINT)
	<-done
	signal.Stop(done)
	fmt.Println("{\"event\":\"exit\"}")
}
