package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
)

var scenario string

func emit(event string, capacity, value int) {
	if err := json.NewEncoder(os.Stdout).Encode(struct {
		Scenario string `json:"scenario"`
		Event    string `json:"event"`
		Capacity int    `json:"capacity"`
		Value    int    `json:"value"`
	}{scenario, event, capacity, value}); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func main() {
	flag.StringVar(&scenario, "case", "bad-unbuffered", "bad-unbuffered, bad-full-buffer, good-concurrent, good-buffered")
	flag.Parse()
	switch scenario {
	case "bad-unbuffered":
		badUnbuffered()
	case "bad-full-buffer":
		badFullBuffer()
	case "good-concurrent":
		goodConcurrent()
	case "good-buffered":
		goodBuffered()
	default:
		fmt.Fprintln(os.Stderr, "unknown case")
		os.Exit(2)
	}
}
