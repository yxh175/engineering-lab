package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httptrace"
	"os"
	"runtime"
	"strconv"
	"sync"
	"time"
)

const requestCount = 16
const bodyBytes = 256 * 1024

type traceResult struct {
	GotConnCalls int    `json:"got_conn_calls"`
	Reused       bool   `json:"reused"`
	WasIdle      bool   `json:"was_idle"`
	Local        string `json:"local,omitempty"`
	Remote       string `json:"remote,omitempty"`
}

type safeTrace struct {
	mu     sync.Mutex
	result traceResult
}

func (t *safeTrace) gotConn(info httptrace.GotConnInfo) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.result = traceResult{t.result.GotConnCalls + 1, info.Reused, info.WasIdle, info.Conn.LocalAddr().String(), info.Conn.RemoteAddr().String()}
}

func (t *safeTrace) snapshot() traceResult {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.result
}

func emit(v any) error { return json.NewEncoder(os.Stdout).Encode(v) }

func run() (int, error) {
	mode := flag.String("case", "bad-unclosed", "bad-unclosed, close-only, good-drain-close, bad-limited")
	flag.Parse()
	if *mode != "bad-unclosed" && *mode != "close-only" && *mode != "good-drain-close" && *mode != "bad-limited" {
		return 2, fmt.Errorf("invalid case")
	}
	runtime.GOMAXPROCS(2)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	t := newTracker()
	srv := httptest.NewUnstartedServer(t.handler(bytes.Repeat([]byte("x"), bodyBytes)))
	srv.Config.ConnState = t.connState
	srv.Config.ConnContext = connectionContext
	srv.Start() // plain HTTP/1.1; loopback and ephemeral port
	defer srv.Close()
	tr := &http.Transport{
		Proxy: nil, DialContext: (&net.Dialer{Timeout: 2 * time.Second}).DialContext,
		MaxIdleConns: 2, MaxIdleConnsPerHost: 2,
		DisableCompression: true, ResponseHeaderTimeout: 2 * time.Second,
	}
	if *mode == "bad-limited" {
		tr.MaxConnsPerHost = 4
	}
	defer tr.CloseIdleConnections()
	client := &http.Client{Transport: tr}
	var held []*http.Response
	defer func() {
		for _, resp := range held {
			resp.Body.Close()
		}
	}()
	if err := emit(map[string]any{"event": "config", "case": *mode, "go_version": runtime.Version(), "os": runtime.GOOS,
		"arch": runtime.GOARCH, "requests_planned": requestCount, "body_bytes": bodyBytes, "max_idle_per_host": tr.MaxIdleConnsPerHost,
		"max_conns_per_host": tr.MaxConnsPerHost, "limit_request_timeout_ms": 250}); err != nil {
		return 1, err
	}
	attempts, successes, reused, closedBodies := 0, 0, 0, 0
	var drained int64
	expectedFailure := false
	for i := 1; i <= requestCount; i++ {
		attempts++
		requestCtx := ctx
		stop := func() {}
		if *mode == "bad-limited" && i == 5 {
			requestCtx, stop = context.WithTimeout(ctx, 250*time.Millisecond)
		}
		trace := &safeTrace{}
		requestCtx = httptrace.WithClientTrace(requestCtx, &httptrace.ClientTrace{GotConn: trace.gotConn})
		req, err := http.NewRequestWithContext(requestCtx, "GET", srv.URL, nil)
		if err != nil {
			stop()
			return 1, err
		}
		resp, err := client.Do(req)
		if err != nil {
			stop()
			fmt.Fprintln(os.Stderr, err)
			deadline := errors.Is(err, context.DeadlineExceeded)
			if e := emit(map[string]any{"event": "request-error", "case": *mode, "request": i,
				"deadline_exceeded": deadline, "error": err.Error(), "trace": trace.snapshot(), "server": t.snapshot()}); e != nil {
				return 1, e
			}
			if *mode != "bad-limited" || i != 5 || !deadline {
				return 1, err
			}
			expectedFailure = true
			break
		}
		stop() // no-op for all successful requests; never cancel held response contexts
		successes++
		if resp.StatusCode != 200 || resp.Proto != "HTTP/1.1" || resp.ContentLength != bodyBytes || resp.Close {
			resp.Body.Close()
			return 1, fmt.Errorf("unexpected response framing")
		}
		id, err := strconv.Atoi(resp.Header.Get("X-Lab-Connection"))
		if err != nil {
			resp.Body.Close()
			return 1, err
		}
		var n int64
		switch *mode {
		case "bad-unclosed", "bad-limited":
			n, err = badUnclosed(resp, &held)
		case "close-only":
			n, err = closeOnly(resp)
			closedBodies++
		case "good-drain-close":
			n, err = goodDrainClose(resp)
			closedBodies++
		}
		if err != nil {
			return 1, err
		}
		drained += n
		if *mode == "close-only" {
			if err := t.waitLive(0); err != nil { // observe FIN/close before taking a snapshot
				return 1, err
			}
		}
		got := trace.snapshot()
		if got.Reused {
			reused++
		}
		if err := emit(map[string]any{"event": "request", "case": *mode, "request": i, "status": resp.StatusCode,
			"protocol": resp.Proto, "content_length": resp.ContentLength, "server_connection_id": id,
			"read_bytes": n, "body_closed": *mode == "close-only" || *mode == "good-drain-close", "trace": got, "server": t.snapshot()}); err != nil {
			return 1, err
		}
	}
	if err := emit(map[string]any{"event": "summary", "case": *mode, "attempts": attempts, "successes": successes,
		"reused_requests": reused, "body_close_calls": closedBodies, "drained_bytes": drained,
		"held_bodies": len(held), "deadline_exceeded": expectedFailure, "server": t.snapshot()}); err != nil {
		return 1, err
	}
	tr.CloseIdleConnections()
	if err := t.waitLive(len(held)); err != nil {
		return 1, err
	}
	if err := emit(map[string]any{"event": "after-close-idle", "case": *mode, "server": t.snapshot()}); err != nil {
		return 1, err
	}
	for _, resp := range held {
		if err := resp.Body.Close(); err != nil {
			return 1, err
		}
	}
	held = nil
	tr.CloseIdleConnections()
	if err := t.waitLive(0); err != nil {
		return 1, err
	}
	srv.Close()
	if err := emit(map[string]any{"event": "after-cleanup", "case": *mode, "server": t.snapshot(), "transitions": t.history, "writes": t.writes}); err != nil {
		return 1, err
	}
	if expectedFailure {
		return 3, nil
	}
	return 0, nil
}

func main() {
	code, err := run()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
	os.Exit(code)
}
