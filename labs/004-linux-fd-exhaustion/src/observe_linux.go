//go:build linux

package main

import (
	"fmt"
	"os"
	"sort"
	"strconv"
)

type descriptor struct {
	FD     int    `json:"fd"`
	Target string `json:"target"`
}

// Reuse this directory FD after exhaustion; do not open a new diagnostics FD.
func inventory(dir *os.File, details bool) (int, []descriptor, error) {
	if _, err := dir.Seek(0, 0); err != nil {
		return 0, nil, err
	}
	names, err := dir.Readdirnames(-1)
	if err != nil {
		return 0, nil, err
	}
	var records []descriptor
	if details {
		for _, name := range names {
			fd, err := strconv.Atoi(name)
			if err != nil {
				return 0, nil, err
			}
			target, err := os.Readlink("/proc/self/fd/" + name)
			if err != nil {
				return 0, nil, fmt.Errorf("readlink fd %s: %w", name, err)
			}
			records = append(records, descriptor{fd, target})
		}
		sort.Slice(records, func(i, j int) bool { return records[i].FD < records[j].FD })
	}
	return len(names), records, nil
}
