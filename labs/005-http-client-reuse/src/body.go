package main

import (
	"errors"
	"io"
	"net/http"
)

// Keep the response reachable and unconsumed until the explicit cleanup phase.
func badUnclosed(resp *http.Response, held *[]*http.Response) (int64, error) {
	*held = append(*held, resp)
	return 0, nil
}

func closeOnly(resp *http.Response) (int64, error) {
	return 0, resp.Body.Close()
}

func goodDrainClose(resp *http.Response) (int64, error) {
	n, readErr := io.Copy(io.Discard, resp.Body)
	closeErr := resp.Body.Close()
	return n, errors.Join(readErr, closeErr)
}
