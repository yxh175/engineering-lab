package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

type Config struct {
	Run     string `json:"run"`
	Total   int    `json:"total"`
	DelayMS int    `json:"delay_ms"`
}
type Fetch struct {
	Ticket    int    `json:"ticket"`
	Key       string `json:"key"`
	Payload   string `json:"payload"`
	StartedNS int64  `json:"started_ns"`
	EndedNS   int64  `json:"ended_ns"`
	Completed bool   `json:"completed"`
}
type State struct {
	Config    Config   `json:"config"`
	Fetches   []*Fetch `json:"fetches"`
	Active    int      `json:"active"`
	Peak      int      `json:"peak"`
	Completed int      `json:"completed"`
	Failed    int      `json:"failed"`
	GoVersion string   `json:"go_version"`
	GOOS      string   `json:"goos"`
	PID       int      `json:"pid"`
	start     time.Time
}

func encode(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
}
func serve(listen string) error {
	var mu sync.Mutex
	var state *State
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		encode(w, map[string]any{"ok": true, "go_version": runtime.Version(), "pid": os.Getpid()})
	})
	mux.HandleFunc("/configure", func(w http.ResponseWriter, r *http.Request) {
		var c Config
		if r.Method != "POST" || json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&c) != nil || c.Run == "" || c.Total != 80 || c.DelayMS != 10 {
			http.Error(w, "bad config", 400)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		if state != nil && state.Active != 0 {
			http.Error(w, "active prior work", 409)
			return
		}
		state = &State{Config: c, Fetches: make([]*Fetch, 0), GoVersion: runtime.Version(), GOOS: runtime.GOOS, PID: os.Getpid(), start: time.Now()}
		encode(w, c)
	})
	mux.HandleFunc("/value", func(w http.ResponseWriter, r *http.Request) {
		key := r.URL.Query().Get("key")
		id, err := strconv.Atoi(strings.TrimPrefix(key, "lab018:item:"))
		mu.Lock()
		s := state
		if s == nil || r.URL.Query().Get("run") != s.Config.Run || err != nil || id < 0 || id >= 80 || key != fmt.Sprintf("lab018:item:%03d", id) {
			mu.Unlock()
			http.Error(w, "bad value request", 400)
			return
		}
		f := &Fetch{Ticket: len(s.Fetches) + 1, Key: key, Payload: "fresh:" + key, StartedNS: time.Since(s.start).Nanoseconds()}
		s.Fetches = append(s.Fetches, f)
		s.Active++
		if s.Active > s.Peak {
			s.Peak = s.Active
		}
		mu.Unlock()
		select {
		case <-time.After(time.Duration(s.Config.DelayMS) * time.Millisecond):
			mu.Lock()
			f.EndedNS = time.Since(s.start).Nanoseconds()
			f.Completed = true
			s.Completed++
			s.Active--
			mu.Unlock()
			encode(w, map[string]any{"run": s.Config.Run, "key": key, "payload": f.Payload, "ticket": f.Ticket})
		case <-r.Context().Done():
			mu.Lock()
			f.EndedNS = time.Since(s.start).Nanoseconds()
			s.Failed++
			s.Active--
			mu.Unlock()
		}
	})
	mux.HandleFunc("/snapshot", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if state == nil {
			http.Error(w, "unconfigured", 409)
			return
		}
		encode(w, state)
	})
	return (&http.Server{Addr: listen, Handler: mux, ReadHeaderTimeout: 5 * time.Second}).ListenAndServe()
}
func main() {
	listen := flag.String("listen", ":8080", "listen address")
	probe := flag.String("probe", "", "probe URL")
	flag.Parse()
	if *probe != "" {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		req, err := http.NewRequestWithContext(ctx, "GET", *probe, nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		response, err := http.DefaultClient.Do(req)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		defer response.Body.Close()
		body, err := io.ReadAll(io.LimitReader(response.Body, 4096))
		if err != nil || response.StatusCode != 200 {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		var result struct {
			OK bool `json:"ok"`
		}
		if json.Unmarshal(body, &result) != nil || !result.OK {
			os.Exit(1)
		}
		fmt.Print(string(body))
		return
	}
	if err := serve(*listen); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
