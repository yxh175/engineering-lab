//go:build linux

package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type Endpoint struct {
	FD     int    `json:"fd"`
	Inode  uint64 `json:"inode"`
	Local  string `json:"local"`
	Remote string `json:"remote"`
}
type Pair struct {
	ID           int      `json:"id"`
	Wave         int      `json:"wave"`
	Server       Endpoint `json:"server"`
	Peer         Endpoint `json:"peer"`
	server, peer *net.TCPConn
}
type FD struct {
	Number string `json:"number"`
	Target string `json:"target"`
	Error  string `json:"error"`
}
type Row struct {
	Local  string
	Remote string
	State  string
	Inode  uint64
}
type Operation struct {
	Pair    int     `json:"pair"`
	Action  string  `json:"action"`
	AtMS    float64 `json:"at_ms"`
	N       int     `json:"n"`
	Error   string  `json:"error"`
	Payload string  `json:"payload"`
}
type Snapshot struct {
	Phase             string  `json:"phase"`
	AtMS              float64 `json:"at_ms"`
	Prefix            string  `json:"prefix"`
	SSExit            int     `json:"ss_exit"`
	ServerFD          int     `json:"server_fd"`
	PeerFD            int     `json:"peer_fd"`
	ServerEstablished int     `json:"server_established"`
	ServerCloseWait   int     `json:"server_close_wait"`
	PeerFinWait2      int     `json:"peer_fin_wait2"`
	PeerTimeWait      int     `json:"peer_time_wait"`
	AllCloseWait      int     `json:"all_close_wait"`
	SocketFD          int     `json:"socket_fd"`
}
type Report struct {
	Case       string      `json:"case"`
	N          int         `json:"n"`
	Waves      int         `json:"waves"`
	HoldMS     float64     `json:"hold_ms"`
	PID        int         `json:"pid"`
	NetNS      string      `json:"netns"`
	GoVersion  string      `json:"go_version"`
	StartedUTC string      `json:"started_utc"`
	Pairs      []Pair      `json:"pairs"`
	Operations []Operation `json:"operations"`
	Snapshots  []Snapshot  `json:"snapshots"`
	Passed     bool        `json:"passed"`
	Failure    string      `json:"failure"`
}

var start = time.Now()
var out string
var report Report

func must(err error) {
	if err != nil {
		panic(err)
	}
}
func ensure(ok bool, message string) {
	if !ok {
		panic(message)
	}
}
func ms() float64 { return float64(time.Since(start).Nanoseconds()) / 1e6 }
func errText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
func save(name string, b []byte) { must(os.WriteFile(filepath.Join(out, name), b, 0644)) }
func saveJSON(name string, v any) {
	b, err := json.MarshalIndent(v, "", "  ")
	must(err)
	save(name, append(b, '\n'))
}
func endpoint(c *net.TCPConn) Endpoint {
	r, err := c.SyscallConn()
	must(err)
	var fd int
	var st syscall.Stat_t
	var statErr error
	must(r.Control(func(p uintptr) { fd = int(p); statErr = syscall.Fstat(fd, &st) }))
	must(statErr)
	target, err := os.Readlink(fmt.Sprintf("/proc/self/fd/%d", fd))
	must(err)
	ensure(target == fmt.Sprintf("socket:[%d]", st.Ino), "Fstat and fd symlink disagree")
	return Endpoint{fd, st.Ino, c.LocalAddr().String(), c.RemoteAddr().String()}
}
func address(raw string) string {
	parts := strings.Split(raw, ":")
	ensure(len(parts) == 2 && len(parts[0]) == 8, "expected IPv4 proc address")
	value, err := strconv.ParseUint(parts[0], 16, 32)
	must(err)
	port, err := strconv.ParseUint(parts[1], 16, 16)
	must(err)
	return fmt.Sprintf("%d.%d.%d.%d:%d", byte(value), byte(value>>8), byte(value>>16), byte(value>>24), port)
}
func tcpRows(b []byte) []Row {
	rows := []Row{}
	for _, line := range strings.Split(string(b), "\n")[1:] {
		f := strings.Fields(line)
		if len(f) == 0 {
			continue
		}
		ensure(len(f) >= 10, "short proc TCP row")
		inode, err := strconv.ParseUint(f[9], 10, 64)
		must(err)
		rows = append(rows, Row{address(f[1]), address(f[2]), f[3], inode})
	}
	return rows
}
func snapshot(phase string) Snapshot {
	s := Snapshot{Phase: phase, AtMS: ms(), Prefix: phase}
	raw, err := os.ReadFile("/proc/self/net/tcp")
	must(err)
	save(phase+".proc-tcp.txt", raw)
	entries, err := os.ReadDir("/proc/self/fd")
	must(err)
	fds := []FD{}
	targets := map[string]string{}
	for _, entry := range entries {
		target, err := os.Readlink("/proc/self/fd/" + entry.Name())
		fds = append(fds, FD{entry.Name(), target, errText(err)})
		targets[entry.Name()] = target
		if strings.HasPrefix(target, "socket:[") {
			s.SocketFD++
		}
	}
	saveJSON(phase+".fds.json", fds)
	cmd := exec.Command("ss", "-H", "-t", "-a", "-n", "-p", "-e", "-O")
	var stderr strings.Builder
	cmd.Stderr = &stderr
	stdout, err := cmd.Output()
	s.SSExit = cmd.ProcessState.ExitCode()
	save(phase+".ss.stdout.txt", stdout)
	save(phase+".ss.stderr.txt", []byte(stderr.String()))
	must(err)
	rows := tcpRows(raw)
	for _, row := range rows {
		if row.State == "08" {
			s.AllCloseWait++
		}
	}
	for _, p := range report.Pairs {
		if targets[strconv.Itoa(p.Server.FD)] == fmt.Sprintf("socket:[%d]", p.Server.Inode) {
			s.ServerFD++
		}
		if targets[strconv.Itoa(p.Peer.FD)] == fmt.Sprintf("socket:[%d]", p.Peer.Inode) {
			s.PeerFD++
		}
		for _, row := range rows {
			if row.Local == p.Server.Local && row.Remote == p.Server.Remote && row.Inode == p.Server.Inode {
				if row.State == "01" {
					s.ServerEstablished++
				}
				if row.State == "08" {
					s.ServerCloseWait++
				}
			}
			if row.Local == p.Peer.Local && row.Remote == p.Peer.Remote {
				if row.Inode == p.Peer.Inode && row.State == "05" {
					s.PeerFinWait2++
				}
				if row.State == "06" {
					s.PeerTimeWait++
				}
			}
		}
	}
	ensure(s.AllCloseWait == s.ServerCloseWait, "unmapped CLOSE_WAIT")
	report.Snapshots = append(report.Snapshots, s)
	return s
}
func operation(id int, action string, n int, err error, payload string) {
	report.Operations = append(report.Operations, Operation{id, action, ms(), n, errText(err), payload})
}
func closePair(p *Pair) {
	err := p.server.Close()
	operation(p.ID, "server-close", 0, err, "")
	must(err)
	var b [1]byte
	n, err := p.peer.Read(b[:])
	operation(p.ID, "peer-read-eof", n, err, string(b[:n]))
	ensure(n == 0 && err == io.EOF, "peer did not receive EOF")
	err = p.peer.Close()
	operation(p.ID, "peer-close", 0, err, "")
	must(err)
}
func run(kind string, n, waves int, hold time.Duration) {
	ensure(kind == "retain-eof" || kind == "close-eof" || kind == "reply-then-close", "unknown case")
	ns, err := os.Readlink("/proc/self/ns/net")
	must(err)
	report = Report{Case: kind, N: n, Waves: waves, HoldMS: float64(hold.Nanoseconds()) / 1e6, PID: os.Getpid(), NetNS: ns, GoVersion: runtime.Version(), StartedUTC: time.Now().UTC().Format(time.RFC3339Nano)}
	l, err := net.ListenTCP("tcp4", &net.TCPAddr{IP: net.IPv4(127, 0, 0, 1), Port: 0})
	must(err)
	baseline := snapshot("baseline")
	ensure(baseline.SocketFD == 1, "baseline should own only listener socket")
	for wave := 1; wave <= waves; wave++ {
		begin := len(report.Pairs)
		for i := 0; i < n; i++ {
			peer, err := net.DialTCP("tcp4", nil, l.Addr().(*net.TCPAddr))
			must(err)
			server, err := l.AcceptTCP()
			must(err)
			must(peer.SetDeadline(time.Now().Add(10 * time.Second)))
			must(server.SetDeadline(time.Now().Add(10 * time.Second)))
			p := Pair{ID: len(report.Pairs) + 1, Wave: wave, Server: endpoint(server), Peer: endpoint(peer), server: server, peer: peer}
			ensure(p.Server.Local == p.Peer.Remote && p.Server.Remote == p.Peer.Local, "TCP endpoints disagree")
			report.Pairs = append(report.Pairs, p)
		}
		established := snapshot(fmt.Sprintf("wave%d-established", wave))
		ensure(established.ServerEstablished == n, "new servers not ESTABLISHED")
		for i := begin; i < len(report.Pairs); i++ {
			p := &report.Pairs[i]
			err = p.peer.CloseWrite()
			operation(p.ID, "peer-close-write", 0, err, "")
			must(err)
			var b [1]byte
			k, readErr := p.server.Read(b[:])
			operation(p.ID, "server-read-eof", k, readErr, string(b[:k]))
			ensure(k == 0 && readErr == io.EOF, "server did not read EOF")
		}
		time.Sleep(50 * time.Millisecond) // let local ACK processing finish; no claim about FIN latency
		eof := snapshot(fmt.Sprintf("wave%d-eof", wave))
		want := n
		if kind == "retain-eof" {
			want = wave * n
		}
		ensure(eof.ServerCloseWait == want && eof.ServerFD == want && eof.PeerFinWait2 == want, "EOF state/fd mismatch")
		if kind == "reply-then-close" {
			for i := begin; i < len(report.Pairs); i++ {
				p := &report.Pairs[i]
				payload := fmt.Sprintf("reply:%02d\n", p.ID)
				k, writeErr := p.server.Write([]byte(payload))
				operation(p.ID, "server-write-reply", k, writeErr, payload)
				must(writeErr)
				ensure(k == len(payload), "short reply write")
				b := make([]byte, len(payload))
				k, readErr := io.ReadFull(p.peer, b)
				operation(p.ID, "peer-read-reply", k, readErr, string(b))
				must(readErr)
				ensure(string(b) == payload, "wrong reply bytes")
			}
			replied := snapshot(fmt.Sprintf("wave%d-replied-before-close", wave))
			ensure(replied.ServerCloseWait == n && replied.ServerFD == n, "reply unexpectedly closed socket")
		}
		if kind != "retain-eof" {
			for i := begin; i < len(report.Pairs); i++ {
				closePair(&report.Pairs[i])
			}
		}
		time.Sleep(hold)
		after := snapshot(fmt.Sprintf("wave%d-after-policy", wave))
		afterWant := 0
		if kind == "retain-eof" {
			afterWant = wave * n
		}
		ensure(after.ServerCloseWait == afterWant && after.ServerFD == afterWant, "policy did not produce expected socket ownership")
		ensure(after.AtMS-eof.AtMS >= float64(hold.Nanoseconds())/1e6, "hold interval too short")
	}
	if kind == "retain-eof" {
		for i := range report.Pairs {
			closePair(&report.Pairs[i])
		}
	}
	must(l.Close())
	time.Sleep(50 * time.Millisecond)
	final := snapshot("final-cleanup")
	ensure(final.ServerFD == 0 && final.PeerFD == 0 && final.SocketFD == 0 && final.AllCloseWait == 0, "socket cleanup failed")
	runtime.KeepAlive(report.Pairs)
	report.Passed = true
}
func main() {
	kind := flag.String("case", "retain-eof", "retain-eof | close-eof | reply-then-close")
	n := flag.Int("n", 16, "connections per wave")
	waves := flag.Int("waves", 3, "waves")
	hold := flag.Duration("hold", 500*time.Millisecond, "observation interval after policy")
	flag.StringVar(&out, "out", "/tmp/lab020", "raw evidence directory")
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
		run(*kind, *n, *waves, *hold)
	}()
	saveJSON("report.json", report)
	b, err := json.Marshal(report)
	must(err)
	fmt.Println(string(b))
	os.Exit(code)
}
