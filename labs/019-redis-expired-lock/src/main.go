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
	"sync"
	"time"
)

type Config struct {
	Run    string `json:"run"`
	Fenced bool   `json:"fenced"`
}
type Input struct {
	Run   string `json:"run"`
	Actor string `json:"actor"`
	Owner string `json:"owner"`
	Fence int64  `json:"fence"`
	Value string `json:"value"`
}
type Actor struct {
	Name      string `json:"name"`
	Owner     string `json:"owner"`
	Fence     int64  `json:"fence"`
	EnteredNS int64  `json:"entered_ns"`
	LeftNS    int64  `json:"left_ns"`
	Running   bool   `json:"running"`
}
type Write struct {
	Index         int    `json:"index"`
	Actor         string `json:"actor"`
	Owner         string `json:"owner"`
	Fence         int64  `json:"fence"`
	Requested     string `json:"requested"`
	Before        string `json:"before"`
	After         string `json:"after"`
	Accepted      bool   `json:"accepted"`
	Status        int    `json:"status"`
	Reason        string `json:"reason"`
	HighestBefore int64  `json:"highest_before"`
	HighestAfter  int64  `json:"highest_after"`
	AtNS          int64  `json:"at_ns"`
}
type State struct {
	Config       Config            `json:"config"`
	Value        string            `json:"value"`
	HighestFence int64             `json:"highest_fence"`
	Actors       map[string]*Actor `json:"actors"`
	Writes       []Write           `json:"writes"`
	Active       int               `json:"active"`
	Peak         int               `json:"peak"`
	GoVersion    string            `json:"go_version"`
	GOOS         string            `json:"goos"`
	PID          int               `json:"pid"`
	start        time.Time
}

func encode(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
}
func serve(listen string) error {
	var mu sync.Mutex
	var state *State
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		encode(w, 200, map[string]any{"ok": true, "go_version": runtime.Version(), "pid": os.Getpid()})
	})
	mux.HandleFunc("/configure", func(w http.ResponseWriter, r *http.Request) {
		var c Config
		if r.Method != "POST" || json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&c) != nil || c.Run == "" {
			http.Error(w, "bad config", 400)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		if state != nil && state.Active != 0 {
			http.Error(w, "prior active", 409)
			return
		}
		state = &State{Config: c, Value: "initial", Actors: make(map[string]*Actor), Writes: make([]Write, 0), GoVersion: runtime.Version(), GOOS: runtime.GOOS, PID: os.Getpid(), start: time.Now()}
		encode(w, 200, c)
	})
	for _, operation := range []string{"enter", "leave", "write"} {
		operation := operation
		mux.HandleFunc("/"+operation, func(w http.ResponseWriter, r *http.Request) {
			var input Input
			if r.Method != "POST" || json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&input) != nil || input.Owner == "" || input.Fence <= 0 || (input.Actor != "A" && input.Actor != "B") {
				http.Error(w, "bad input", 400)
				return
			}
			mu.Lock()
			defer mu.Unlock()
			s := state
			if s == nil || input.Run != s.Config.Run {
				http.Error(w, "bad run", 400)
				return
			}
			if operation == "enter" {
				if s.Actors[input.Actor] != nil {
					http.Error(w, "duplicate enter", 409)
					return
				}
				a := &Actor{Name: input.Actor, Owner: input.Owner, Fence: input.Fence, EnteredNS: time.Since(s.start).Nanoseconds(), Running: true}
				s.Actors[input.Actor] = a
				s.Active++
				if s.Active > s.Peak {
					s.Peak = s.Active
				}
				encode(w, 200, a)
				return
			}
			a := s.Actors[input.Actor]
			if a == nil || !a.Running || a.Owner != input.Owner || a.Fence != input.Fence {
				http.Error(w, "bad actor identity", 409)
				return
			}
			if operation == "leave" {
				a.Running = false
				a.LeftNS = time.Since(s.start).Nanoseconds()
				s.Active--
				encode(w, 200, a)
				return
			}
			if (input.Actor == "A" && input.Value != "A-stale") || (input.Actor == "B" && input.Value != "B-new") {
				http.Error(w, "bad fixture value", 400)
				return
			}
			event := Write{Index: len(s.Writes), Actor: input.Actor, Owner: input.Owner, Fence: input.Fence, Requested: input.Value, Before: s.Value, HighestBefore: s.HighestFence, AtNS: time.Since(s.start).Nanoseconds()}
			if s.Config.Fenced && input.Fence < s.HighestFence {
				event.Status = 409
				event.Reason = "stale_fence"
			} else {
				event.Status = 200
				event.Accepted = true
				event.Reason = "accepted"
				s.Value = input.Value
				if input.Fence > s.HighestFence {
					s.HighestFence = input.Fence
				}
			}
			event.After = s.Value
			event.HighestAfter = s.HighestFence
			s.Writes = append(s.Writes, event)
			encode(w, event.Status, event)
		})
	}
	mux.HandleFunc("/snapshot", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if state == nil {
			http.Error(w, "unconfigured", 409)
			return
		}
		encode(w, 200, state)
	})
	return (&http.Server{Addr: listen, Handler: mux, ReadHeaderTimeout: 5 * time.Second}).ListenAndServe()
}
func main() {
	listen := flag.String("listen", ":8080", "listen address")
	probe := flag.String("probe", "", "health URL")
	flag.Parse()
	if *probe != "" {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		request, err := http.NewRequestWithContext(ctx, "GET", *probe, nil)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		response, err := http.DefaultClient.Do(request)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		defer response.Body.Close()
		body, err := io.ReadAll(io.LimitReader(response.Body, 4096))
		var result struct {
			OK bool `json:"ok"`
		}
		if err != nil || response.StatusCode != 200 || json.Unmarshal(body, &result) != nil || !result.OK {
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
