//go:build linux

package main

import "os"

func goodClose(s *state) error {
	for i := 1; i <= s.iterations; i++ {
		f, err := os.Open("/dev/null")
		if err != nil {
			return s.failure(i, err)
		}
		if err := s.opened(i); err != nil {
			f.Close()
			return err
		}
		if err := f.Close(); err != nil {
			return err
		}
		if i%64 == 0 {
			if err := s.emit("after-close", i, 0, "", false); err != nil {
				return err
			}
		}
	}
	return nil
}
