package main

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func get(t *testing.T, path string) *httptest.ResponseRecorder {
	t.Helper()
	recorder := httptest.NewRecorder()
	routes().ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
	return recorder
}

func TestHealth(t *testing.T) {
	response := get(t, "/health")
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), `"ok"`) {
		t.Fatalf("GET /health = %d %s", response.Code, response.Body)
	}
}

func TestHello(t *testing.T) {
	if body := get(t, "/api/hello?name=quoll").Body.String(); !strings.Contains(body, "Hello, quoll!") {
		t.Fatalf("GET /api/hello = %s", body)
	}
	if body := get(t, "/api/hello").Body.String(); !strings.Contains(body, "Hello, world!") {
		t.Fatalf("GET /api/hello = %s", body)
	}
}

func TestServeUntilCancelled(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- serve(ctx, listener) }()

	response, err := http.Get("http://" + listener.Addr().String() + "/health")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(response.Body)
	_ = response.Body.Close()
	if !strings.Contains(string(body), `"ok"`) {
		t.Fatalf("GET /health = %s", body)
	}
	cancel()
	if err := <-done; err != nil {
		t.Fatalf("serve = %v", err)
	}
}

func TestRunNeedsAnAddress(t *testing.T) {
	if err := run(context.Background(), "not-an-address"); err == nil {
		t.Fatal("run accepted an invalid address")
	}
}

func TestEnvOr(t *testing.T) {
	t.Setenv("QUOLL_TEST", "")
	if got := envOr("QUOLL_TEST", "8080"); got != "8080" {
		t.Fatalf("envOr = %s", got)
	}
	t.Setenv("QUOLL_TEST", "9000")
	if got := envOr("QUOLL_TEST", "8080"); got != "9000" {
		t.Fatalf("envOr = %s", got)
	}
}

func TestServeFailsOnAClosedListener(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	_ = listener.Close()
	if err := serve(context.Background(), listener); err == nil {
		t.Fatal("serve succeeded on a closed listener")
	}
}

func TestWriteJSONReportsEncodingErrors(t *testing.T) {
	recorder := httptest.NewRecorder()
	writeJSON(recorder, make(chan int)) // a channel can't be encoded: logged, nothing written
	if recorder.Body.Len() != 0 {
		t.Fatalf("body = %s", recorder.Body)
	}
}

func TestRunStopsWithItsContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := run(ctx, "127.0.0.1:0"); err != nil {
		t.Fatalf("run = %v", err)
	}
}
