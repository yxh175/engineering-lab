//go:build linux

package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

type Actor struct {
	PID            int            `json:"pid"`
	ChildPID       int            `json:"child_pid"`
	Exit           int            `json:"exit"`
	Ready          map[string]any `json:"ready"`
	Done           map[string]any `json:"done"`
	cmd            *exec.Cmd
	stdin          io.WriteCloser
	scanner        *bufio.Scanner
	stdout, stderr *os.File
}
type State struct {
	PID   int    `json:"pid"`
	Role  string `json:"role"`
	State string `json:"state"`
	Wchan string `json:"wchan"`
}
type Sample struct {
	Index        int     `json:"index"`
	AtMS         float64 `json:"at_ms"`
	TargetStates []State `json:"target_states"`
}
type Write struct {
	PID   int     `json:"pid"`
	Byte  string  `json:"byte"`
	N     int     `json:"n"`
	Error string  `json:"error"`
	AtMS  float64 `json:"at_ms"`
}
type Report struct {
	Case        string   `json:"case"`
	ObserverPID int      `json:"observer_pid"`
	Actors      []*Actor `json:"actors"`
	Samples     []Sample `json:"samples"`
	Writes      []Write  `json:"writes"`
	WallMS      float64  `json:"measurement_wall_ms"`
	UsageUS     int64    `json:"usage_delta_us"`
	CPUPercent  float64  `json:"one_core_cpu_percent"`
	Throttled   int64    `json:"nr_throttled_delta"`
	VMStatExit  int      `json:"vmstat_exit"`
	AllReaped   bool     `json:"all_reaped"`
	Passed      bool     `json:"passed"`
	Failure     string   `json:"failure"`
}

var out string
var report Report
var epoch = time.Now()

func must(err error) {
	if err != nil {
		panic(err)
	}
}
func ensure(b bool, s string) {
	if !b {
		panic(s)
	}
}
func ms() float64                { return float64(time.Since(epoch).Nanoseconds()) / 1e6 }
func save(name string, b []byte) { must(os.WriteFile(filepath.Join(out, name), b, 0644)) }
func jsonSave(name string, v any) {
	b, err := json.MarshalIndent(v, "", "  ")
	must(err)
	save(name, append(b, '\n'))
}
func raw(name, path string) []byte { b, err := os.ReadFile(path); must(err); save(name, b); return b }
func counters(b []byte) map[string]int64 {
	m := map[string]int64{}
	for _, l := range strings.Split(string(b), "\n") {
		f := strings.Fields(l)
		if len(f) == 0 {
			continue
		}
		ensure(len(f) == 2, "bad counter row")
		v, err := strconv.ParseInt(f[1], 10, 64)
		must(err)
		m[f[0]] = v
	}
	return m
}
func actorLine(a *Actor) map[string]any {
	ensure(a.scanner.Scan(), "actor stdout ended before expected record")
	b := a.scanner.Bytes()
	_, err := a.stdout.Write(append(append([]byte{}, b...), '\n'))
	must(err)
	v := map[string]any{}
	must(json.Unmarshal(b, &v))
	return v
}
func write(a *Actor, b string) {
	n, err := a.stdin.Write([]byte(b))
	e := ""
	if err != nil {
		e = err.Error()
	}
	report.Writes = append(report.Writes, Write{a.PID, b, n, e, ms()})
	must(err)
	ensure(n == 1, "short control write")
}
func ps(label string) {
	cmd := exec.Command("ps", "-eo", "pid,ppid,stat,wchan:32,comm")
	errfile, err := os.Create(filepath.Join(out, label+".ps.stderr.txt"))
	must(err)
	cmd.Stderr = errfile
	b, runErr := cmd.Output()
	must(errfile.Close())
	save(label+".ps.stdout.txt", b)
	must(runErr)
}
func target(label string, pid int, role string) State {
	b := raw(fmt.Sprintf("%s.%s-%d.stat.txt", label, role, pid), fmt.Sprintf("/proc/%d/stat", pid))
	at := strings.LastIndex(string(b), ")")
	ensure(at >= 0, "bad proc stat")
	f := strings.Fields(string(b)[at+1:])
	ensure(len(f) > 12, "short proc stat")
	w := raw(fmt.Sprintf("%s.%s-%d.wchan.txt", label, role, pid), fmt.Sprintf("/proc/%d/wchan", pid))
	return State{pid, role, f[0], strings.TrimSpace(string(w))}
}
func run(kind string) {
	ensure(kind == "cpu-busy" || kind == "pipe-read" || kind == "clone-wait", "unknown case")
	report = Report{Case: kind, ObserverPID: os.Getpid()}
	raw("cpu.max.txt", "/sys/fs/cgroup/cpu.max")
	raw("memory.max.txt", "/sys/fs/cgroup/memory.max")
	raw("cpuset.txt", "/sys/fs/cgroup/cpuset.cpus.effective")
	raw("kernel.txt", "/proc/version")
	raw("proc-self-cgroup.txt", "/proc/self/cgroup")
	for i := 0; i < 4; i++ {
		a := &Actor{}
		a.cmd = exec.Command("/lab/.work/actor021-linux", kind)
		var err error
		a.stdin, err = a.cmd.StdinPipe()
		must(err)
		pipe, err := a.cmd.StdoutPipe()
		must(err)
		a.stdout, err = os.Create(filepath.Join(out, fmt.Sprintf("actor%d.stdout.jsonl", i)))
		must(err)
		a.stderr, err = os.Create(filepath.Join(out, fmt.Sprintf("actor%d.stderr.txt", i)))
		must(err)
		a.cmd.Stderr = a.stderr
		must(a.cmd.Start())
		a.PID = a.cmd.Process.Pid
		a.scanner = bufio.NewScanner(pipe)
		a.Ready = actorLine(a)
		ensure(a.Ready["stage"] == "ready" && int(a.Ready["pid"].(float64)) == a.PID && int(a.Ready["ppid"].(float64)) == os.Getpid() && a.Ready["mode"] == kind, "wrong actor ready identity")
		report.Actors = append(report.Actors, a)
	}
	beginTick := time.Now()
	before := counters(raw("measurement-begin.cpu.stat.txt", "/sys/fs/cgroup/cpu.stat"))
	for _, a := range report.Actors {
		write(a, "G")
	}
	if kind == "clone-wait" {
		for _, a := range report.Actors {
			v := actorLine(a)
			ensure(v["stage"] == "child" && int(v["pid"].(float64)) == a.PID, "wrong clone parent")
			a.ChildPID = int(v["child_pid"].(float64))
			ensure(a.ChildPID > 1 && a.ChildPID != a.PID, "wrong clone child")
		}
	}
	vm := exec.Command("vmstat", "-w", "1", "2")
	vf, err := os.Create(filepath.Join(out, "vmstat.stdout.txt"))
	must(err)
	ve, err := os.Create(filepath.Join(out, "vmstat.stderr.txt"))
	must(err)
	vm.Stdout = vf
	vm.Stderr = ve
	must(vm.Start())
	time.Sleep(50 * time.Millisecond)
	for i := 0; i < 10; i++ {
		label := fmt.Sprintf("sample%02d", i)
		s := Sample{Index: i, AtMS: ms()}
		raw(label+".loadavg.txt", "/proc/loadavg")
		raw(label+".proc-stat.txt", "/proc/stat")
		raw(label+".cpu.stat.txt", "/sys/fs/cgroup/cpu.stat")
		for _, a := range report.Actors {
			s.TargetStates = append(s.TargetStates, target(label, a.PID, "parent"))
			if a.ChildPID != 0 {
				s.TargetStates = append(s.TargetStates, target(label, a.ChildPID, "child"))
			}
		}
		ps(label)
		report.Samples = append(report.Samples, s)
		time.Sleep(150 * time.Millisecond)
	}
	must(vm.Wait())
	report.VMStatExit = vm.ProcessState.ExitCode()
	must(vf.Close())
	must(ve.Close())
	after := counters(raw("measurement-end.cpu.stat.txt", "/sys/fs/cgroup/cpu.stat"))
	report.WallMS = float64(time.Since(beginTick).Nanoseconds()) / 1e6
	report.UsageUS = after["usage_usec"] - before["usage_usec"]
	report.Throttled = after["nr_throttled"] - before["nr_throttled"]
	report.CPUPercent = float64(report.UsageUS) / (report.WallMS * 1000) * 100
	jsonSave("measurement-window.json", map[string]any{"wall_ms": report.WallMS, "usage_delta_us": report.UsageUS, "one_core_cpu_percent": report.CPUPercent, "scope": "all cgroup processes, including observer, ps and vmstat; not VM-global CPU percent", "ended_before_release": true})
	for _, a := range report.Actors {
		write(a, "R")
	}
	for _, a := range report.Actors {
		a.Done = actorLine(a)
		ensure(a.Done["stage"] == "done" && int(a.Done["pid"].(float64)) == a.PID && int(a.Done["child_pid"].(float64)) == a.ChildPID, "wrong done identity")
		ensure(!a.scanner.Scan(), "unexpected actor stdout record")
		must(a.cmd.Wait())
		a.Exit = a.cmd.ProcessState.ExitCode()
		must(a.stdin.Close())
		must(a.stdout.Close())
		must(a.stderr.Close())
	}
	ps("after-release")
	allGone := true
	for _, a := range report.Actors {
		_, err := os.Stat(fmt.Sprintf("/proc/%d", a.PID))
		allGone = allGone && os.IsNotExist(err)
		if a.ChildPID != 0 {
			_, err = os.Stat(fmt.Sprintf("/proc/%d", a.ChildPID))
			allGone = allGone && os.IsNotExist(err)
		}
	}
	report.AllReaped = allGone
	ensure(allGone, "target process remains after dependency release")
	want := map[string]string{"cpu-busy": "R", "pipe-read": "S", "clone-wait": "D"}[kind]
	stable := 0
	for _, s := range report.Samples {
		count := 0
		for _, v := range s.TargetStates {
			if v.Role == "parent" && v.State == want {
				count++
			}
			if v.Role == "child" {
				ensure(v.State == "S", "clone child not sleeping in pipe read")
			}
		}
		if count == 4 {
			stable++
		}
	}
	ensure(stable >= 8, "fewer than eight full expected-state snapshots")
	if kind == "cpu-busy" {
		ensure(report.CPUPercent > 60 && report.Throttled > 0, "CPU busy case not quota bound")
	} else {
		ensure(report.CPUPercent < 10, "waiting case consumed excessive cgroup CPU")
	}
	report.Passed = true
}
func main() {
	kind := flag.String("case", "cpu-busy", "cpu-busy | pipe-read | clone-wait")
	flag.StringVar(&out, "out", "/tmp/lab021", "new raw evidence directory")
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
		run(*kind)
	}()
	jsonSave("report.json", report)
	b, err := json.Marshal(report)
	must(err)
	fmt.Println(string(b))
	os.Exit(code)
}
