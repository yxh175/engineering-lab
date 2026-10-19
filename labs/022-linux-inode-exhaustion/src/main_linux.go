//go:build linux

package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

const scratch = "/scratch"

type Entry struct {
	Name  string `json:"name"`
	Size  int64  `json:"size"`
	Inode uint64 `json:"inode"`
}
type Operation struct {
	Action string  `json:"action"`
	Name   string  `json:"name"`
	N      int     `json:"n"`
	Errno  int     `json:"errno"`
	Error  string  `json:"error"`
	AtMS   float64 `json:"at_ms"`
}
type Snapshot struct {
	Phase          string  `json:"phase"`
	AtMS           float64 `json:"at_ms"`
	Files          uint64  `json:"inodes_total"`
	Free           uint64  `json:"inodes_free"`
	Available      uint64  `json:"bytes_available"`
	Used           uint64  `json:"bytes_used"`
	DirectoryFiles int     `json:"directory_files"`
	DFExit         []int   `json:"df_exit"`
}
type Report struct {
	Case           string      `json:"case"`
	PID            int         `json:"pid"`
	ExpectedInodes int         `json:"expected_inodes"`
	InitialCreated int         `json:"initial_created"`
	DataWritten    int         `json:"data_written"`
	DataFD         int         `json:"data_fd"`
	DataInode      uint64      `json:"data_inode"`
	Snapshots      []Snapshot  `json:"snapshots"`
	Operations     []Operation `json:"operations"`
	Passed         bool        `json:"passed"`
	Failure        string      `json:"failure"`
}

var out string
var report Report
var epoch = time.Now()

func must(err error) {
	if err != nil {
		panic(err)
	}
}
func ensure(ok bool, msg string) {
	if !ok {
		panic(msg)
	}
}
func ms() float64                { return float64(time.Since(epoch).Nanoseconds()) / 1e6 }
func save(name string, b []byte) { must(os.WriteFile(filepath.Join(out, name), b, 0644)) }
func jsonSave(name string, v any) {
	b, err := json.MarshalIndent(v, "", "  ")
	must(err)
	save(name, append(b, '\n'))
}
func record(action, name string, n int, err error) {
	text := ""
	code := 0
	if err != nil {
		text = err.Error()
		var e syscall.Errno
		if errors.As(err, &e) {
			code = int(e)
		}
	}
	report.Operations = append(report.Operations, Operation{action, name, n, code, text, ms()})
}
func snapshot(phase string) Snapshot {
	var f syscall.Statfs_t
	must(syscall.Statfs(scratch, &f))
	ensure(uint64(f.Type) == 0x01021994, "scratch is not tmpfs")
	jsonSave(phase+".statfs.json", f)
	entries, err := os.ReadDir(scratch)
	must(err)
	list := []Entry{}
	for _, e := range entries {
		info, err := e.Info()
		must(err)
		ensure(info.Mode().IsRegular(), "unexpected scratch entry")
		st := info.Sys().(*syscall.Stat_t)
		list = append(list, Entry{e.Name(), info.Size(), st.Ino})
	}
	jsonSave(phase+".files.json", list)
	s := Snapshot{Phase: phase, AtMS: ms(), Files: f.Files, Free: f.Ffree, Available: f.Bavail * uint64(f.Bsize), Used: (f.Blocks - f.Bfree) * uint64(f.Bsize), DirectoryFiles: len(list)}
	for i, argv := range [][]string{{"-B1", scratch}, {"-i", scratch}, {"-h", scratch}} {
		cmd := exec.Command("df", argv...)
		var stderr strings.Builder
		cmd.Stderr = &stderr
		b, err := cmd.Output()
		save(fmt.Sprintf("%s.df%d.stdout.txt", phase, i), b)
		save(fmt.Sprintf("%s.df%d.stderr.txt", phase, i), []byte(stderr.String()))
		must(err)
		s.DFExit = append(s.DFExit, cmd.ProcessState.ExitCode())
	}
	report.Snapshots = append(report.Snapshots, s)
	return s
}
func empty(name string) error {
	f, err := os.OpenFile(filepath.Join(scratch, name), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	record("create-empty", name, 0, err)
	if err == nil {
		err = f.Close()
		record("close-empty", name, 0, err)
		must(err)
	}
	return err
}
func remove(name string) {
	err := os.Remove(filepath.Join(scratch, name))
	record("unlink", name, 0, err)
	must(err)
}
func cleanup() {
	entries, err := os.ReadDir(scratch)
	must(err)
	for _, e := range entries {
		remove(e.Name())
	}
}
func run(kind string, limit int) {
	ensure(kind == "inode-full" || kind == "bytes-full", "unknown case")
	report = Report{Case: kind, PID: os.Getpid(), ExpectedInodes: limit}
	for label, path := range map[string]string{"mountinfo.txt": "/proc/self/mountinfo", "kernel.txt": "/proc/version", "memory.max.txt": "/sys/fs/cgroup/memory.max", "cpu.max.txt": "/sys/fs/cgroup/cpu.max"} {
		b, err := os.ReadFile(path)
		must(err)
		save(label, b)
	}
	baseline := snapshot("baseline")
	ensure(baseline.Files == uint64(limit) && baseline.DirectoryFiles == 0 && baseline.Available == 1048576 && baseline.Free > 4, "unexpected empty fixture")
	if kind == "inode-full" {
		for i := 0; i < 1024; i++ {
			err := empty(fmt.Sprintf("f%04d", i))
			if err != nil {
				ensure(errors.Is(err, syscall.ENOSPC), "expected real create ENOSPC")
				break
			}
			report.InitialCreated++
		}
		ensure(uint64(report.InitialCreated) == baseline.Free, "created count does not consume exact free inode budget")
		full := snapshot("full")
		ensure(full.Free == 0 && full.Available == baseline.Available && full.DirectoryFiles == report.InitialCreated, "inode-full counters disagree")
		for i := 0; i < 4; i++ {
			remove(fmt.Sprintf("f%04d", i))
		}
		freed := snapshot("after-delete-four")
		ensure(freed.Free == 4 && freed.Available == baseline.Available, "four closed empty files did not release four inodes")
		for i := 0; i < 4; i++ {
			must(empty(fmt.Sprintf("replacement%02d", i)))
		}
		err := empty("one-too-many")
		ensure(errors.Is(err, syscall.ENOSPC), "expected recurrent inode ENOSPC")
		restored := snapshot("after-recreate-four")
		ensure(restored.Free == 0 && restored.DirectoryFiles == report.InitialCreated && restored.Available == baseline.Available, "restored inode counters disagree")
	} else {
		f, err := os.OpenFile(filepath.Join(scratch, "data"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		record("open-data", "data", 0, err)
		must(err)
		report.DataFD = int(f.Fd())
		info, err := f.Stat()
		must(err)
		report.DataInode = info.Sys().(*syscall.Stat_t).Ino
		link, err := os.Readlink(fmt.Sprintf("/proc/self/fd/%d", report.DataFD))
		must(err)
		save("data-open.fd-link.txt", []byte(link))
		block := make([]byte, 65536)
		for i := range block {
			block[i] = byte(i % 251)
		}
		for i := 0; i < 64; i++ {
			n, err := f.Write(block)
			record("write-data", "data", n, err)
			report.DataWritten += n
			if err != nil {
				ensure(errors.Is(err, syscall.ENOSPC), "expected real write ENOSPC")
				break
			}
			ensure(n == len(block), "short successful write")
		}
		ensure(report.DataWritten == 1048576, "unexpected byte-full size")
		full := snapshot("full")
		ensure(full.Available == 0 && full.Free > 4 && full.DirectoryFiles == 1, "bytes-full counters disagree")
		must(empty("empty-while-byte-full"))
		withEmpty := snapshot("empty-created-byte-full")
		ensure(withEmpty.Available == 0 && withEmpty.Free == full.Free-1 && withEmpty.DirectoryFiles == 2, "empty file failed to demonstrate independent inode budget")
		remove("data") // deliberately retain open fd: unlink alone need not release pages
		link, err = os.Readlink(fmt.Sprintf("/proc/self/fd/%d", report.DataFD))
		must(err)
		save("data-unlinked.fd-link.txt", []byte(link))
		held := snapshot("unlinked-still-open")
		ensure(held.Available == 0 && held.DirectoryFiles == 1 && held.Free == withEmpty.Free, "open deleted file unexpectedly reclaimed")
		err = f.Close()
		record("close-data", "data", 0, err)
		must(err)
		freed := snapshot("after-close-data")
		ensure(freed.Available == baseline.Available && freed.Free == baseline.Free-1, "close did not release deleted file budget")
		repair, err := os.OpenFile(filepath.Join(scratch, "repaired"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		record("open-repaired", "repaired", 0, err)
		must(err)
		n, err := repair.Write(block[:4096])
		record("write-repaired", "repaired", n, err)
		must(err)
		ensure(n == 4096, "repair write failed")
		err = repair.Close()
		record("close-repaired", "repaired", 0, err)
		must(err)
		fixed := snapshot("after-repair-write")
		ensure(fixed.Available == 1044480 && fixed.DirectoryFiles == 2, "repair counters disagree")
	}
	cleanup()
	final := snapshot("final-cleanup")
	ensure(final.DirectoryFiles == 0 && final.Free == baseline.Free && final.Available == baseline.Available && final.Used == 0, "scratch cleanup did not restore baseline")
	report.Passed = true
}
func main() {
	kind := flag.String("case", "inode-full", "inode-full | bytes-full")
	limit := flag.Int("inodes", 32, "expected mounted inode limit")
	flag.StringVar(&out, "out", "/tmp/lab022", "new evidence directory")
	flag.Parse()
	must(os.MkdirAll(out, 0755))
	code := 0
	func() {
		defer func() {
			if r := recover(); r != nil {
				report.Failure = fmt.Sprint(r)
				code = 2
			}
		}()
		run(*kind, *limit)
	}()
	jsonSave("report.json", report)
	b, err := json.Marshal(report)
	must(err)
	fmt.Println(string(b))
	os.Exit(code)
}
