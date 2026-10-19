package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"
)

const poisonPath = "/tmp/lab023-poison"

var epoch = time.Now()
var instance string
var logMu sync.Mutex

func event(kind string, extra map[string]any) {
	logMu.Lock()
	defer logMu.Unlock()
	extra["event"], extra["instance"], extra["uptime_ms"] = kind, instance, float64(time.Since(epoch).Nanoseconds())/1e6
	if err := json.NewEncoder(os.Stdout).Encode(extra); err != nil {
		panic(err)
	}
}
func main() {
	poison := flag.Bool("poison", false, "create this container's liveness fault marker")
	warm := flag.Duration("warm", 15*time.Second, "fixed initialization duration")
	flag.Parse()
	if *poison {
		if err := os.WriteFile(poisonPath, []byte("deliberate lab fault\n"), 0600); err != nil {
			panic(err)
		}
		fmt.Println(`{"poison_written":true}`)
		return
	}
	if err := os.Remove(poisonPath); err != nil && !os.IsNotExist(err) {
		panic(err)
	}
	id := make([]byte, 16)
	if _, err := rand.Read(id); err != nil {
		panic(err)
	}
	instance = hex.EncodeToString(id)
	mux := http.NewServeMux()
	for _, path := range []string{"/start", "/live", "/ready"} {
		mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) {
			initialized := time.Since(epoch) >= *warm
			_, markerErr := os.Stat(poisonPath)
			broken := markerErr == nil
			status := http.StatusOK
			if !initialized || (r.URL.Path != "/start" && broken) {
				status = http.StatusServiceUnavailable
			}
			event("probe", map[string]any{"path": r.URL.Path, "status": status, "initialized": initialized, "poisoned": broken, "user_agent": r.UserAgent()})
			w.WriteHeader(status)
			fmt.Fprintf(w, "%d\n", status)
		})
	}
	server := &http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 2 * time.Second}
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
	event("boot", map[string]any{"pid": os.Getpid(), "warm_ms": warm.Milliseconds()})
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			event("server-error", map[string]any{"error": err.Error()})
			os.Exit(2)
		}
	}()
	sig := <-signals
	event("signal", map[string]any{"signal": sig.String()})
	_ = server.Close()
	event("exit", map[string]any{"exit_code": 0})
}
