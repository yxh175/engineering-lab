package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"sync"
	"time"
)

type connectionKey struct{}

type transition struct {
	ID    int    `json:"connection_id"`
	State string `json:"state"`
}

type writeResult struct {
	ID    int    `json:"connection_id"`
	Bytes int    `json:"bytes_written"`
	Error string `json:"error,omitempty"`
}

type serverSnapshot struct {
	Accepted int `json:"accepted"`
	Live     int `json:"live"`
	Closed   int `json:"closed"`
	PeakLive int `json:"peak_live"`
	Requests int `json:"requests"`
}

type tracker struct {
	mu      sync.Mutex
	ids     map[net.Conn]int
	stats   serverSnapshot
	changed chan struct{}
	history []transition
	writes  []writeResult
}

func newTracker() *tracker {
	return &tracker{ids: make(map[net.Conn]int), changed: make(chan struct{})}
}

func (t *tracker) connState(c net.Conn, state http.ConnState) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if state == http.StateNew {
		t.stats.Accepted++
		t.stats.Live++
		t.ids[c] = t.stats.Accepted
		if t.stats.Live > t.stats.PeakLive {
			t.stats.PeakLive = t.stats.Live
		}
	}
	id := t.ids[c]
	t.history = append(t.history, transition{id, state.String()})
	if state == http.StateClosed {
		t.stats.Live--
		t.stats.Closed++
		delete(t.ids, c)
	}
	close(t.changed)
	t.changed = make(chan struct{})
}

func (t *tracker) snapshot() serverSnapshot {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.stats
}

func (t *tracker) waitLive(expected int) error {
	timer := time.NewTimer(2 * time.Second)
	defer timer.Stop()
	for {
		t.mu.Lock()
		if t.stats.Live == expected {
			t.mu.Unlock()
			return nil
		}
		changed := t.changed
		t.mu.Unlock()
		select {
		case <-changed:
		case <-timer.C:
			return fmt.Errorf("server live-connection wait: wanted %d, got %d", expected, t.snapshot().Live)
		}
	}
}

func (t *tracker) handler(payload []byte) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c := r.Context().Value(connectionKey{}).(net.Conn)
		t.mu.Lock()
		id := t.ids[c]
		t.stats.Requests++
		t.mu.Unlock()
		w.Header().Set("Content-Length", fmt.Sprint(len(payload)))
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Header().Set("X-Lab-Connection", fmt.Sprint(id))
		n, err := w.Write(payload)
		result := writeResult{ID: id, Bytes: n}
		if err != nil {
			result.Error = err.Error()
		}
		t.mu.Lock()
		t.writes = append(t.writes, result)
		t.mu.Unlock()
	})
}

func connectionContext(ctx context.Context, c net.Conn) context.Context {
	return context.WithValue(ctx, connectionKey{}, c)
}
