//go:build linux

package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"runtime"
	"syscall"
)

type state struct {
	mode                        string
	iterations                  int
	dir                         *os.File
	soft, hard, originalSoft    uint64
	baseline, peak, successes   int
	failedAttempt, failureErrno int
}

func (s *state) emit(event string, operation, errno int, message string, details bool) error {
	n, fds, err := inventory(s.dir, details)
	if err != nil {
		return fmt.Errorf("inventory failed: %w", err)
	}
	if n > s.peak {
		s.peak = n
	}
	return json.NewEncoder(os.Stdout).Encode(struct {
		Case          string       `json:"case"`
		Event         string       `json:"event"`
		Operation     int          `json:"operation"`
		FDCount       int          `json:"fd_count"`
		Baseline      int          `json:"baseline"`
		Peak          int          `json:"peak_observed"`
		Soft          uint64       `json:"soft_limit"`
		Hard          uint64       `json:"hard_limit"`
		OriginalSoft  uint64       `json:"original_soft"`
		Successes     int          `json:"successes"`
		FailedAttempt int          `json:"failed_attempt"`
		Errno         int          `json:"errno"`
		Error         string       `json:"error,omitempty"`
		FDs           []descriptor `json:"fds,omitempty"`
		GoVersion     string       `json:"go_version"`
	}{s.mode, event, operation, n, s.baseline, s.peak, s.soft, s.hard, s.originalSoft, s.successes, s.failedAttempt, errno, message, fds, runtime.Version()})
}

func (s *state) opened(i int) error {
	s.successes = i
	n, _, err := inventory(s.dir, false)
	if err != nil {
		return err
	}
	if n > s.peak {
		s.peak = n
	}
	if i%8 == 0 {
		return s.emit("opened", i, 0, "", false)
	}
	return nil
}

func (s *state) failure(i int, err error) error {
	s.failedAttempt = i
	var errno syscall.Errno
	if !errors.As(err, &errno) {
		return fmt.Errorf("not an errno: %w", err)
	}
	s.failureErrno = int(errno)
	fmt.Fprintln(os.Stderr, err) // preserve the actual os.Open PathError
	if e := s.emit("open-error", i, int(errno), err.Error(), true); e != nil {
		return e
	}
	return err
}

func run() (int, error) {
	mode := flag.String("case", "bad-unclosed", "bad-unclosed, bad-deferred, good-close")
	soft := flag.Uint64("limit", 64, "soft RLIMIT_NOFILE (32..128)")
	iterations := flag.Int("iterations", 512, "number of open operations, 256..1024")
	flag.Parse()
	if (*mode != "bad-unclosed" && *mode != "bad-deferred" && *mode != "good-close") || *soft < 32 || *soft > 128 || *iterations < 256 || *iterations > 1024 {
		return 2, fmt.Errorf("invalid case or bounded workload")
	}
	runtime.GOMAXPROCS(1)
	dir, err := os.Open("/proc/self/fd")
	if err != nil {
		return 1, err
	}
	defer dir.Close()
	// Warm Go's poller initialization before baseline sampling.
	f, err := os.Open("/dev/null")
	if err != nil {
		return 1, err
	}
	if err := f.Close(); err != nil {
		return 1, err
	}
	var original syscall.Rlimit
	if err := syscall.Getrlimit(syscall.RLIMIT_NOFILE, &original); err != nil {
		return 1, err
	}
	if *soft > original.Max {
		return 1, fmt.Errorf("requested soft limit exceeds inherited hard limit")
	}
	if err := syscall.Setrlimit(syscall.RLIMIT_NOFILE, &syscall.Rlimit{Cur: *soft, Max: original.Max}); err != nil {
		return 1, err
	}
	baseline, _, err := inventory(dir, false)
	if err != nil {
		return 1, err
	}
	s := &state{mode: *mode, iterations: *iterations, dir: dir, soft: *soft, hard: original.Max, originalSoft: original.Cur, baseline: baseline, peak: baseline}
	if err := s.emit("baseline", 0, 0, "", true); err != nil {
		return 1, err
	}
	switch *mode {
	case "bad-unclosed":
		err = badUnclosed(s)
	case "bad-deferred":
		err = badDeferred(s)
	case "good-close":
		err = goodClose(s)
	}
	if e := s.emit("after-cleanup", s.successes, s.failureErrno, "", true); e != nil {
		return 1, e
	}
	if err != nil {
		if errors.Is(err, syscall.EMFILE) {
			return 3, nil // explicit demo status; errno=24 is recorded separately
		}
		return 1, err
	}
	return 0, nil
}

func main() {
	code, err := run()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
	os.Exit(code)
}
