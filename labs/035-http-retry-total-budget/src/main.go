package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"sync"
	"time"
)

type recorder struct {
	mu     sync.Mutex
	start  time.Time
	events []map[string]any
}

func (r *recorder) now() float64 { return time.Since(r.start).Seconds() * 1000 }
func (r *recorder) emit(name string, fields map[string]any) {
	r.mu.Lock()
	defer r.mu.Unlock()
	fields["event"] = name
	fields["seq"] = len(r.events) + 1
	fields["at_ms"] = r.now()
	r.events = append(r.events, fields)
}
func main() {
	mode := flag.String("case", "attempt-only", "attempt-only/shared-budget/normal")
	out := flag.String("outdir", "", "new directory")
	flag.Parse()
	if *out == "" || (*mode != "attempt-only" && *mode != "shared-budget" && *mode != "normal") {
		os.Exit(64)
	}
	if err := os.Mkdir(*out, 0755); err != nil {
		panic(err)
	}
	rec := &recorder{start: time.Now()}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		panic(err)
	}
	delay := 120 * time.Millisecond
	if *mode == "normal" {
		delay = 30 * time.Millisecond
	}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, q *http.Request) {
		id, _ := strconv.Atoi(q.URL.Query().Get("attempt"))
		rec.emit("server_enter", map[string]any{"attempt": id, "method": q.Method, "proto": q.Proto, "remote": q.RemoteAddr})
		timer := time.NewTimer(delay)
		defer timer.Stop()
		select {
		case <-q.Context().Done():
			rec.emit("server_cancel", map[string]any{"attempt": id, "error": q.Context().Err().Error()})
			return
		case <-timer.C:
		}
		status, body := http.StatusServiceUnavailable, "unavailable\n"
		if *mode == "normal" {
			status, body = http.StatusOK, "{\"value\":42}\n"
		}
		w.WriteHeader(status)
		n, err := io.WriteString(w, body)
		text := ""
		if err != nil {
			text = err.Error()
		}
		rec.emit("server_response", map[string]any{"attempt": id, "status": status, "bytes": n, "write_error": text})
	})}
	serveDone := make(chan error, 1)
	go func() { serveDone <- server.Serve(listener) }()
	transport := &http.Transport{Proxy: nil, ForceAttemptHTTP2: false}
	client := &http.Client{Transport: transport}
	opStart := rec.now()
	parent := context.Background()
	cancelParent := func() {}
	if *mode != "attempt-only" {
		parent, cancelParent = context.WithTimeout(parent, 250*time.Millisecond)
	}
	attempts := []map[string]any{}
	success := false
	for i := 1; i <= 3; i++ {
		if parent.Err() != nil {
			break
		}
		begun := rec.now()
		attemptCtx, cancel := context.WithTimeout(parent, 200*time.Millisecond)
		deadline, _ := attemptCtx.Deadline()
		rec.emit("client_attempt_start", map[string]any{"attempt": i, "deadline_ms": deadline.Sub(rec.start).Seconds() * 1000})
		url := "http://" + listener.Addr().String() + "/work?attempt=" + strconv.Itoa(i)
		request, err := http.NewRequestWithContext(attemptCtx, http.MethodGet, url, nil)
		if err != nil {
			panic(err)
		}
		response, callErr := client.Do(request)
		status := 0
		body := ""
		readErrText := ""
		closeErrText := ""
		if response != nil {
			status = response.StatusCode
			b, readErr := io.ReadAll(io.LimitReader(response.Body, 512))
			body = string(b)
			if readErr != nil {
				readErrText = readErr.Error()
			}
			if closeErr := response.Body.Close(); closeErr != nil {
				closeErrText = closeErr.Error()
			}
		}
		text := ""
		if callErr != nil {
			text = callErr.Error()
		}
		ctxErr := ""
		if attemptCtx.Err() != nil {
			ctxErr = attemptCtx.Err().Error()
		}
		ended := rec.now()
		a := map[string]any{"attempt": i, "url": url, "start_ms": begun, "end_ms": ended, "elapsed_ms": ended - begun,
			"deadline_ms": deadline.Sub(rec.start).Seconds() * 1000, "status": status, "body": body, "error": text,
			"deadline_exceeded": errors.Is(callErr, context.DeadlineExceeded), "context_error": ctxErr, "read_error": readErrText, "close_error": closeErrText}
		attempts = append(attempts, a)
		rec.emit("client_attempt_end", map[string]any{"attempt": i, "status": status, "deadline_exceeded": errors.Is(callErr, context.DeadlineExceeded)})
		cancel()
		if callErr == nil && readErrText == "" && status == 200 && body == "{\"value\":42}\n" {
			success = true
			break
		}
		if i < 3 && parent.Err() == nil {
			rec.emit("backoff_start", map[string]any{"after_attempt": i})
			timer := time.NewTimer(30 * time.Millisecond)
			select {
			case <-timer.C:
			case <-parent.Done():
			}
			timer.Stop()
			rec.emit("backoff_end", map[string]any{"after_attempt": i})
		}
	}
	elapsed := rec.now() - opStart
	parentError := ""
	if parent.Err() != nil {
		parentError = parent.Err().Error()
	}
	cancelParent()
	transport.CloseIdleConnections()
	shutdownCtx, cancelShutdown := context.WithTimeout(context.Background(), 2*time.Second)
	err = server.Shutdown(shutdownCtx)
	cancelShutdown()
	if err != nil {
		panic(err)
	}
	if err := <-serveDone; !errors.Is(err, http.ErrServerClosed) {
		panic(fmt.Sprintf("serve exit: %v", err))
	}
	r := map[string]any{"case": *mode, "pid": os.Getpid(), "go": runtime.Version(), "os": runtime.GOOS, "arch": runtime.GOARCH,
		"listener": listener.Addr().String(), "server_delay_ms": delay.Milliseconds(), "attempt_timeout_ms": 200, "total_budget_ms": 250,
		"max_attempts": 3, "backoff_ms": 30, "operation_start_ms": opStart, "operation_elapsed_ms": elapsed,
		"parent_error": parentError, "business_success": success, "attempts": attempts, "events": rec.events, "server_joined": true}
	b, err := json.Marshal(r)
	if err != nil {
		panic(err)
	}
	if err := os.WriteFile(filepath.Join(*out, "result.json"), append(b, '\n'), 0644); err != nil {
		panic(err)
	}
	if _, err := os.Stdout.Write(append(b, '\n')); err != nil {
		panic(err)
	}
}
