//go:build linux

package main

import "os"

func badUnclosed(s *state) error {
	files := make([]*os.File, 0, s.iterations)
	// Cleanup is after the failure snapshot, not inside the work loop.
	defer func() {
		for _, f := range files {
			if err := f.Close(); err != nil {
				panic(err)
			}
		}
	}()
	for i := 1; i <= s.iterations; i++ {
		f, err := os.Open("/dev/null")
		if err != nil {
			return s.failure(i, err)
		}
		files = append(files, f) // keep references; no finalizer-based recovery
		if err := s.opened(i); err != nil {
			return err
		}
	}
	return nil
}

func badDeferred(s *state) error {
	for i := 1; i <= s.iterations; i++ {
		f, err := os.Open("/dev/null")
		if err != nil {
			return s.failure(i, err)
		}
		defer f.Close() // runs on function return, not at the end of this iteration
		if err := s.opened(i); err != nil {
			return err
		}
	}
	return nil
}
