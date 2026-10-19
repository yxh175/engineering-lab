package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime"
)

func main() {
	caseName := flag.String("case", "bad-barrier", "bad-barrier, bad-correct, good-atomic")
	workers := flag.Int("workers", 64, "one increment per worker, 2..1024")
	flag.Parse()
	if *workers < 2 || *workers > 1024 {
		fmt.Fprintln(os.Stderr, "workers must be 2..1024")
		os.Exit(2)
	}
	p := 2
	if *caseName == "bad-correct" {
		p = 1
	}
	runtime.GOMAXPROCS(p)
	var actual int64
	switch *caseName {
	case "bad-barrier":
		actual = badBarrier(*workers)
	case "bad-correct":
		actual = badCorrect(*workers)
	case "good-atomic":
		actual = goodAtomic(*workers)
	default:
		fmt.Fprintln(os.Stderr, "unknown case")
		os.Exit(2)
	}
	report := struct {
		Case        string `json:"case"`
		GoVersion   string `json:"go_version"`
		OS          string `json:"os"`
		Arch        string `json:"arch"`
		RaceEnabled bool   `json:"race_enabled"`
		GOMAXPROCS  int    `json:"gomaxprocs"`
		Workers     int    `json:"workers"`
		Expected    int64  `json:"expected"`
		Actual      int64  `json:"actual"`
	}{*caseName, runtime.Version(), runtime.GOOS, runtime.GOARCH, raceEnabled, runtime.GOMAXPROCS(0), *workers, int64(*workers), actual}
	if err := json.NewEncoder(os.Stdout).Encode(report); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
