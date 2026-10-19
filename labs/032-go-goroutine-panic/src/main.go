package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime"
	"runtime/debug"
)

type result struct {
	Value int    `json:"value"`
	Error string `json:"error"`
}

func emit(event string, fields map[string]any) {
	fields["event"] = event
	if err := json.NewEncoder(os.Stdout).Encode(fields); err != nil {
		panic(err)
	}
}

//go:noinline
func job(fail bool) int {
	emit("job_before", map[string]any{"fail": fail})
	if fail {
		panic("lab032-job-fault")
	}
	emit("job_after", map[string]any{"value": 42})
	return 42
}
func safeJob(fail bool) (r result) {
	defer func() {
		if v := recover(); v != nil {
			r.Error = fmt.Sprintf("worker panic: %v", v)
			emit("worker_recovered", map[string]any{"panic": fmt.Sprint(v), "stack": string(debug.Stack())})
		}
	}()
	r.Value = job(fail)
	return
}
func main() {
	mode := flag.String("case", "parent-only", "parent-only/worker-recover/normal")
	flag.Parse()
	if *mode != "parent-only" && *mode != "worker-recover" && *mode != "normal" {
		os.Exit(64)
	}
	emit("start", map[string]any{"case": *mode, "pid": os.Getpid(), "go": runtime.Version(), "os": runtime.GOOS, "arch": runtime.GOARCH})
	defer func() {
		v := recover()
		emit("parent_defer", map[string]any{"panic": v})
	}()
	results := make(chan result, 1)
	done := make(chan struct{})
	emit("parent_ready", map[string]any{})
	go func() {
		defer close(done)
		defer emit("worker_defer", map[string]any{})
		emit("worker_enter", map[string]any{})
		var r result
		if *mode == "parent-only" {
			r.Value = job(true)
		} else {
			r = safeJob(*mode == "worker-recover")
		}
		emit("worker_result", map[string]any{"value": r.Value, "error": r.Error})
		results <- r
	}()
	r := <-results
	<-done
	emit("completed", map[string]any{"value": r.Value, "error": r.Error, "worker_joined": true, "business_success": r.Error == ""})
}
