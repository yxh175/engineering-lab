package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/signal"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

var epoch = time.Now()
var logMu sync.Mutex

func event(kind string, fields map[string]any) {
	logMu.Lock()
	defer logMu.Unlock()
	fields["event"], fields["uptime_ms"], fields["pod_uid"] = kind, float64(time.Since(epoch).Nanoseconds())/1e6, os.Getenv("POD_UID")
	if err := json.NewEncoder(os.Stdout).Encode(fields); err != nil {
		panic(err)
	}
}
func must(err error) {
	if err != nil {
		panic(err)
	}
}
func emit(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	must(json.NewEncoder(w).Encode(v))
}
func app(mode string) {
	var active atomic.Int32
	var ready atomic.Bool
	ready.Store(true)
	gate := make(chan struct{})
	mux := http.NewServeMux()
	mux.HandleFunc("/ready", func(w http.ResponseWriter, r *http.Request) {
		if !ready.Load() {
			w.WriteHeader(503)
		} else {
			w.WriteHeader(200)
		}
	})
	mux.HandleFunc("/state", func(w http.ResponseWriter, r *http.Request) {
		emit(w, map[string]any{"active": active.Load(), "pod_uid": os.Getenv("POD_UID"), "ready": ready.Load()})
	})
	mux.HandleFunc("/work", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			w.WriteHeader(405)
			return
		}
		ticket := r.URL.Query().Get("ticket")
		body, err := io.ReadAll(r.Body)
		must(err)
		must(r.Body.Close())
		active.Add(1)
		event("enter", map[string]any{"ticket": ticket, "body": string(body), "active": active.Load()})
		<-gate
		payload := map[string]any{"ticket": ticket, "value": 42, "pod_uid": os.Getenv("POD_UID")}
		b, err := json.Marshal(payload)
		must(err)
		w.Header().Set("Content-Type", "application/json")
		n, err := w.Write(b)
		text := ""
		if err != nil {
			text = err.Error()
		}
		event("complete", map[string]any{"ticket": ticket, "written_bytes": n, "write_error": text, "active": active.Add(-1)})
	})
	server := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 2 * time.Second}
	signalCh := make(chan os.Signal, 1)
	signal.Notify(signalCh, syscall.SIGTERM, syscall.SIGINT)
	event("boot", map[string]any{"pid": os.Getpid(), "mode": mode})
	go func() {
		err := server.ListenAndServe()
		if err != nil && err != http.ErrServerClosed {
			event("server-error", map[string]any{"error": err.Error()})
			os.Exit(2)
		}
	}()
	sig := <-signalCh
	ready.Store(false)
	event("signal", map[string]any{"signal": sig.String(), "active": active.Load()})
	if mode == "exit-now" {
		event("exit", map[string]any{"code": 0, "active": active.Load()})
		return
	}
	if mode != "drain" {
		panic("unknown mode")
	}
	// Deliberately make the six already admitted jobs finish two seconds after TERM.
	go func() {
		time.Sleep(2 * time.Second)
		event("release", map[string]any{"active": active.Load()})
		close(gate)
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	err := server.Shutdown(ctx)
	text := ""
	if err != nil {
		text = err.Error()
	}
	event("shutdown", map[string]any{"error": text, "active": active.Load()})
	if err != nil {
		os.Exit(2)
	}
	event("exit", map[string]any{"code": 0, "active": active.Load()})
}

type Result struct {
	Ticket string `json:"ticket"`
	Status int    `json:"status"`
	Body   string `json:"body"`
	Error  string `json:"error"`
	Bytes  int    `json:"bytes"`
}

func harness(backend string) {
	target, err := url.Parse(backend)
	must(err)
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.Transport = &http.Transport{DisableKeepAlives: true}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		event("proxy-error", map[string]any{"ticket": r.URL.Query().Get("ticket"), "upstream_error": err.Error()})
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(502)
		must(json.NewEncoder(w).Encode(map[string]any{"ticket": r.URL.Query().Get("ticket"), "upstream_error": err.Error()}))
	}
	var mu sync.Mutex
	results := []Result{}
	started := false
	client := &http.Client{Transport: &http.Transport{DisableKeepAlives: true}, Timeout: 25 * time.Second}
	mux := http.NewServeMux()
	mux.Handle("/work", proxy)
	mux.HandleFunc("/run", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if started {
			w.WriteHeader(409)
			return
		}
		started = true
		for i := 1; i <= 6; i++ {
			ticket := fmt.Sprintf("req%d", i)
			go func() {
				result := Result{Ticket: ticket}
				body := `{"ticket":"` + ticket + `"}`
				event("request-start", map[string]any{"ticket": ticket, "method": "POST", "body": body, "url": "http://127.0.0.1:8081/work?ticket=" + ticket})
				resp, err := client.Post("http://127.0.0.1:8081/work?ticket="+ticket, "application/json", strings.NewReader(body))
				if err != nil {
					result.Error = err.Error()
				} else {
					result.Status = resp.StatusCode
					b, readErr := io.ReadAll(resp.Body)
					closeErr := resp.Body.Close()
					result.Body, result.Bytes = string(b), len(b)
					if readErr != nil {
						result.Error = readErr.Error()
					} else if closeErr != nil {
						result.Error = closeErr.Error()
					}
				}
				event("request-finish", map[string]any{"ticket": ticket, "status": result.Status, "body": result.Body, "bytes": result.Bytes, "error": result.Error})
				mu.Lock()
				results = append(results, result)
				mu.Unlock()
			}()
		}
		emit(w, map[string]any{"started": 6, "backend": backend})
	})
	mux.HandleFunc("/snapshot", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		emit(w, map[string]any{"results": results, "completed": len(results), "started": started, "backend": backend})
	})
	event("harness-boot", map[string]any{"backend": backend, "pid": os.Getpid()})
	must(http.ListenAndServe(":8081", mux))
}
func control(target string) {
	c := &http.Client{Timeout: 5 * time.Second}
	r, err := c.Get(target)
	must(err)
	b, err := io.ReadAll(r.Body)
	must(err)
	must(r.Body.Close())
	must(json.NewEncoder(os.Stdout).Encode(map[string]any{"url": target, "status": r.StatusCode, "body": string(b), "bytes": len(b)}))
}
func main() {
	role := flag.String("role", "app", "app|harness|control")
	mode := flag.String("mode", "exit-now", "exit-now|drain")
	target := flag.String("target", "", "backend or control URL")
	flag.Parse()
	switch *role {
	case "app":
		app(*mode)
	case "harness":
		harness(*target)
	case "control":
		control(*target)
	default:
		panic("role")
	}
}
