package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"runtime"
	"sort"
	"strconv"
	"sync"
	"time"
)

const key = "lab017:hot"

type Configuration struct {
	Run     string `json:"run"`
	Total   int    `json:"total"`
	Gate    int    `json:"gate"`
	DelayMS int    `json:"delay_ms"`
}
type Ready struct {
	App    string `json:"app"`
	Worker int    `json:"worker"`
}
type Fetch struct {
	Ticket    int    `json:"ticket"`
	App       string `json:"app"`
	Worker    int    `json:"worker"`
	StartedNS int64  `json:"started_ns"`
	EndedNS   int64  `json:"ended_ns"`
	Completed bool   `json:"completed"`
}
type State struct {
	Config    Configuration `json:"config"`
	Ready     []Ready       `json:"ready"`
	Fetches   []*Fetch      `json:"fetches"`
	Active    int           `json:"active"`
	Peak      int           `json:"peak"`
	Completed int           `json:"completed"`
	Failed    int           `json:"failed"`
	GoVersion string        `json:"go_version"`
	GOOS      string        `json:"goos"`
	PID       int           `json:"pid"`
	start     time.Time
	readyGate chan struct{}
	fetchGate chan struct{}
	seen      map[string]bool
}

func encode(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
}

func origin(listen string) error {
	var mu sync.Mutex
	var s *State
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		encode(w, map[string]any{"ok": true, "go_version": runtime.Version(), "pid": os.Getpid()})
	})
	mux.HandleFunc("/configure", func(w http.ResponseWriter, r *http.Request) {
		var c Configuration
		if r.Method != "POST" || json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&c) != nil || c.Run == "" || c.Total != 32 || c.Gate < 1 || c.Gate > 32 || c.DelayMS != 20 {
			http.Error(w, "invalid config", 400)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		if s != nil && s.Active != 0 {
			http.Error(w, "prior fetch active", 409)
			return
		}
		s = &State{Config: c, GoVersion: runtime.Version(), GOOS: runtime.GOOS, PID: os.Getpid(), start: time.Now(), readyGate: make(chan struct{}), fetchGate: make(chan struct{}), seen: make(map[string]bool)}
		encode(w, c)
	})
	mux.HandleFunc("/ready", func(w http.ResponseWriter, r *http.Request) {
		app := r.URL.Query().Get("app")
		worker, err := strconv.Atoi(r.URL.Query().Get("worker"))
		mu.Lock()
		current := s
		identity := fmt.Sprintf("%s/%d", app, worker)
		if current == nil || r.URL.Query().Get("run") != current.Config.Run || err != nil || app == "" || worker < 0 || current.seen[identity] || len(current.Ready) >= current.Config.Total {
			mu.Unlock()
			http.Error(w, "invalid ready", 400)
			return
		}
		current.seen[identity] = true
		current.Ready = append(current.Ready, Ready{App: app, Worker: worker})
		if len(current.Ready) == current.Config.Total {
			close(current.readyGate)
		}
		gate := current.readyGate
		mu.Unlock()
		select {
		case <-gate:
			encode(w, map[string]any{"ready": true, "run": current.Config.Run})
		case <-r.Context().Done():
			return
		case <-time.After(10 * time.Second):
			http.Error(w, "ready gate timeout", 504)
		}
	})
	mux.HandleFunc("/value", func(w http.ResponseWriter, r *http.Request) {
		app := r.URL.Query().Get("app")
		worker, err := strconv.Atoi(r.URL.Query().Get("worker"))
		mu.Lock()
		current := s
		if current == nil || r.URL.Query().Get("run") != current.Config.Run || err != nil || !current.seen[fmt.Sprintf("%s/%d", app, worker)] {
			mu.Unlock()
			http.Error(w, "invalid fetch", 400)
			return
		}
		f := &Fetch{Ticket: len(current.Fetches) + 1, App: app, Worker: worker, StartedNS: time.Since(current.start).Nanoseconds()}
		current.Fetches = append(current.Fetches, f)
		current.Active++
		if current.Active > current.Peak {
			current.Peak = current.Active
		}
		if len(current.Fetches) == current.Config.Gate {
			close(current.fetchGate)
		}
		gate := current.fetchGate
		mu.Unlock()
		ok := false
		defer func() {
			mu.Lock()
			defer mu.Unlock()
			current.Active--
			f.EndedNS = time.Since(current.start).Nanoseconds()
			f.Completed = ok
			if ok {
				current.Completed++
			} else {
				current.Failed++
			}
		}()
		select {
		case <-gate:
		case <-r.Context().Done():
			return
		case <-time.After(10 * time.Second):
			http.Error(w, "fetch gate timeout", 504)
			return
		}
		select {
		case <-time.After(time.Duration(current.Config.DelayMS) * time.Millisecond):
		case <-r.Context().Done():
			return
		}
		encode(w, map[string]any{"run": current.Config.Run, "value": "42", "ticket": f.Ticket})
		ok = true
	})
	mux.HandleFunc("/snapshot", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if s == nil {
			http.Error(w, "not configured", 409)
			return
		}
		encode(w, s)
	})
	server := &http.Server{Addr: listen, Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	return server.ListenAndServe()
}

type RESP struct {
	Phase    string   `json:"phase"`
	Args     []string `json:"args"`
	Request  []byte   `json:"request"`
	Response []byte   `json:"response"`
	Kind     string   `json:"kind"`
	Value    string   `json:"value"`
}

func redisCall(address, phase string, args ...string) (*string, RESP, error) {
	record := RESP{Phase: phase, Args: args}
	var request bytes.Buffer
	fmt.Fprintf(&request, "*%d\r\n", len(args))
	for _, arg := range args {
		fmt.Fprintf(&request, "$%d\r\n%s\r\n", len(arg), arg)
	}
	record.Request = request.Bytes()
	conn, err := net.DialTimeout("tcp", address, 5*time.Second)
	if err != nil {
		return nil, record, err
	}
	defer conn.Close()
	if err = conn.SetDeadline(time.Now().Add(5 * time.Second)); err != nil {
		return nil, record, err
	}
	for left := record.Request; len(left) > 0; {
		n, e := conn.Write(left)
		if e != nil {
			return nil, record, e
		}
		if n == 0 {
			return nil, record, io.ErrShortWrite
		}
		left = left[n:]
	}
	var response bytes.Buffer
	read := func(n int) ([]byte, error) {
		b := make([]byte, n)
		got, e := io.ReadFull(conn, b)
		response.Write(b[:got])
		return b[:got], e
	}
	line := func() ([]byte, error) {
		var b []byte
		for {
			c, e := read(1)
			if e != nil {
				return nil, e
			}
			b = append(b, c[0])
			if len(b) >= 2 && bytes.Equal(b[len(b)-2:], []byte("\r\n")) {
				return b[:len(b)-2], nil
			}
			if len(b) > 1024 {
				return nil, errors.New("RESP line too long")
			}
		}
	}
	prefix, e := read(1)
	if e != nil {
		record.Response = response.Bytes()
		return nil, record, e
	}
	head, e := line()
	if e != nil {
		record.Response = response.Bytes()
		return nil, record, e
	}
	var value *string
	switch prefix[0] {
	case '$':
		n, e := strconv.Atoi(string(head))
		if e != nil || n < -1 || n > 4096 {
			err = errors.New("invalid bulk length")
			break
		}
		if n == -1 {
			record.Kind = "null"
			break
		}
		body, e := read(n)
		if e != nil {
			err = e
			break
		}
		tail, e := read(2)
		if e != nil || !bytes.Equal(tail, []byte("\r\n")) {
			err = errors.New("bad bulk tail")
			break
		}
		text := string(body)
		value = &text
		record.Kind = "bulk"
		record.Value = text
	case '+':
		text := string(head)
		value = &text
		record.Kind = "simple"
		record.Value = text
	case '-':
		err = errors.New("Redis error: " + string(head))
		record.Kind = "error"
		record.Value = string(head)
	default:
		err = errors.New("unexpected RESP type")
	}
	record.Response = response.Bytes()
	return value, record, err
}

type Operation struct {
	Worker     int    `json:"worker"`
	InitialNil bool   `json:"initial_nil"`
	Ready      bool   `json:"ready"`
	RecheckHit bool   `json:"recheck_hit"`
	SourceCall bool   `json:"source_call"`
	Ticket     int    `json:"ticket"`
	Value      string `json:"value"`
	RESP       []RESP `json:"resp"`
	Error      string `json:"error"`
}
type ActorResult struct {
	Run        string       `json:"run"`
	App        string       `json:"app"`
	Mode       string       `json:"mode"`
	PID        int          `json:"pid"`
	GoVersion  string       `json:"go_version"`
	GOOS       string       `json:"goos"`
	Workers    int          `json:"workers"`
	Operations []*Operation `json:"operations"`
}

func get(client *http.Client, url string, target any) error {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return err
	}
	response, err := client.Do(req)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, 65537))
	if err != nil {
		return err
	}
	if len(data) > 65536 {
		return errors.New("body too large")
	}
	if response.StatusCode != 200 {
		return fmt.Errorf("HTTP%d: %s", response.StatusCode, data)
	}
	return json.Unmarshal(data, target)
}

func actor(address, endpoint, run, app, mode string, workers int) error {
	if mode != "none" && mode != "mutex" && mode != "recheck" {
		return errors.New("bad mode")
	}
	transport := &http.Transport{MaxConnsPerHost: 64, MaxIdleConnsPerHost: 64}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport}
	result := ActorResult{Run: run, App: app, Mode: mode, PID: os.Getpid(), GoVersion: runtime.Version(), GOOS: runtime.GOOS, Workers: workers}
	var keyMu, resultsMu sync.Mutex
	var wg sync.WaitGroup
	for worker := 0; worker < workers; worker++ {
		wg.Add(1)
		go func(worker int) {
			defer wg.Done()
			op := &Operation{Worker: worker}
			defer func() { resultsMu.Lock(); result.Operations = append(result.Operations, op); resultsMu.Unlock() }()
			query := fmt.Sprintf("?run=%s&app=%s&worker=%d", run, app, worker)
			initial, rec, err := redisCall(address, "initial", "GET", key)
			op.RESP = append(op.RESP, rec)
			if err != nil {
				op.Error = err.Error()
				return
			}
			if initial != nil {
				op.Error = "initial GET unexpectedly hit"
				return
			}
			op.InitialNil = true
			var ready struct {
				Ready bool   `json:"ready"`
				Run   string `json:"run"`
			}
			if err = get(client, endpoint+"/ready"+query, &ready); err != nil {
				op.Error = err.Error()
				return
			}
			if !ready.Ready || ready.Run != run {
				op.Error = "bad ready response"
				return
			}
			op.Ready = true
			if mode != "none" {
				keyMu.Lock()
				defer keyMu.Unlock()
			}
			if mode == "recheck" {
				cached, rec, err := redisCall(address, "recheck", "GET", key)
				op.RESP = append(op.RESP, rec)
				if err != nil {
					op.Error = err.Error()
					return
				}
				if cached != nil {
					op.RecheckHit = true
					op.Value = *cached
					return
				}
			}
			var source struct {
				Run    string `json:"run"`
				Value  string `json:"value"`
				Ticket int    `json:"ticket"`
			}
			op.SourceCall = true
			if err = get(client, endpoint+"/value"+query, &source); err != nil {
				op.Error = err.Error()
				return
			}
			if source.Run != run || source.Value != "42" || source.Ticket < 1 {
				op.Error = "bad source response"
				return
			}
			op.Ticket = source.Ticket
			set, rec, err := redisCall(address, "fill", "SET", key, source.Value, "PX", "60000")
			op.RESP = append(op.RESP, rec)
			if err != nil {
				op.Error = err.Error()
				return
			}
			if set == nil || *set != "OK" {
				op.Error = "SET did not return OK"
				return
			}
			op.Value = source.Value
		}(worker)
	}
	wg.Wait()
	sort.Slice(result.Operations, func(i, j int) bool { return result.Operations[i].Worker < result.Operations[j].Worker })
	if err := json.NewEncoder(os.Stdout).Encode(result); err != nil {
		return err
	}
	for _, op := range result.Operations {
		if op.Error != "" || op.Value != "42" {
			return fmt.Errorf("worker%d: %s value=%q", op.Worker, op.Error, op.Value)
		}
	}
	return nil
}

func main() {
	role := flag.String("role", "actor", "actor/origin/probe")
	listen := flag.String("listen", ":8080", "origin listener")
	endpoint := flag.String("origin", "", "origin URL")
	address := flag.String("redis", "", "Redis host:port")
	run := flag.String("run", "", "unique run id")
	app := flag.String("app", "", "process label")
	mode := flag.String("mode", "none", "none/mutex/recheck")
	workers := flag.Int("workers", 32, "workers in this process")
	flag.Parse()
	var err error
	switch *role {
	case "origin":
		err = origin(*listen)
	case "actor":
		err = actor(*address, *endpoint, *run, *app, *mode, *workers)
	case "probe":
		var health any
		err = get(http.DefaultClient, *endpoint+"/health", &health)
	default:
		err = errors.New("unknown role")
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
