package transport

import (
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/profile"
)

type observedPayload struct {
	payload   []byte
	deviceID  string
	transport models.TransportType
}

func TestFileDropWorkerProcessesNewFile(t *testing.T) {
	watchDir := t.TempDir()
	payloads := make(chan observedPayload, 2)
	states := &stateLog{}

	worker, err := startFileDropWorker(
		profile.Profile{Transport: profile.TransportSettings{Type: "file_drop", WatchDirectories: []string{watchDir}}},
		func(raw []byte, deviceID string, transportType models.TransportType) error {
			payloads <- observedPayload{payload: append([]byte(nil), raw...), deviceID: deviceID, transport: transportType}
			return nil
		},
		func(err error, detail map[string]any) { t.Fatalf("unexpected error: %v detail=%v", err, detail) },
		states.record,
	)
	if err != nil {
		t.Fatalf("startFileDropWorker() error = %v", err)
	}
	defer worker.Stop()

	filePath := filepath.Join(watchDir, "sample-result.hl7")
	if err := os.WriteFile(filePath, []byte("MSH|^~\\&|LAB|LIS"), 0o644); err != nil {
		t.Fatalf("WriteFile() error = %v", err)
	}

	got := waitForPayload(t, payloads)
	if string(got.payload) != "MSH|^~\\&|LAB|LIS" {
		t.Fatalf("payload = %q, want %q", string(got.payload), "MSH|^~\\&|LAB|LIS")
	}
	if got.transport != models.TransportFileDrop {
		t.Fatalf("transport = %q, want %q", got.transport, models.TransportFileDrop)
	}
	if got.deviceID != "sample-result.hl7" {
		t.Fatalf("deviceID = %q, want %q", got.deviceID, "sample-result.hl7")
	}
	states.waitFor(t, "watching")
	states.waitFor(t, "processing")
	states.waitFor(t, "active")
}

func TestTCPServerWorkerProcessesInboundPayload(t *testing.T) {
	address := reserveLocalAddress(t)
	payloads := make(chan observedPayload, 2)
	states := &stateLog{}
	stateCh := make(chan string, 10)

	worker, err := startTCPServerWorker(
		profile.Profile{Transport: profile.TransportSettings{Type: "tcp_server", ListenAddress: address}},
		func(raw []byte, deviceID string, transportType models.TransportType) error {
			payloads <- observedPayload{payload: append([]byte(nil), raw...), deviceID: deviceID, transport: transportType}
			return nil
		},
		func(err error, detail map[string]any) { t.Fatalf("unexpected error: %v detail=%v", err, detail) },
		func(state string, meta map[string]any) {
			states.record(state, meta)
			select {
			case stateCh <- state:
			default:
			}
		},
		nil,
	)
	if err != nil {
		t.Fatalf("startTCPServerWorker() error = %v", err)
	}
	defer worker.Stop()

	waitForStateName(t, stateCh, "listening")

	conn, err := net.DialTimeout("tcp", address, 5*time.Second)
	if err != nil {
		t.Fatalf("DialTimeout() error = %v", err)
	}
	if _, err := conn.Write([]byte("OBX|1|NM|GLU^Glucose||102|mg/dL")); err != nil {
		conn.Close()
		t.Fatalf("Write() error = %v", err)
	}
	_ = conn.Close()

	got := waitForPayload(t, payloads)
	if string(got.payload) != "OBX|1|NM|GLU^Glucose||102|mg/dL" {
		t.Fatalf("payload = %q, want expected TCP payload", string(got.payload))
	}
	if got.transport != models.TransportTCPServer {
		t.Fatalf("transport = %q, want %q", got.transport, models.TransportTCPServer)
	}
	if !strings.Contains(got.deviceID, ":") {
		t.Fatalf("deviceID = %q, expected remote address", got.deviceID)
	}
	states.waitFor(t, "connected")
	states.waitFor(t, "disconnected")
}

func waitForPayload(t *testing.T, payloads <-chan observedPayload) observedPayload {
	t.Helper()
	select {
	case got := <-payloads:
		return got
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for payload")
		return observedPayload{}
	}
}

func reserveLocalAddress(t *testing.T) string {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("Listen() error = %v", err)
	}
	defer listener.Close()
	return listener.Addr().String()
}

type stateLog struct {
	mu     sync.Mutex
	states []string
}

func (s *stateLog) record(state string, _ map[string]any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.states = append(s.states, state)
}

func (s *stateLog) waitFor(t *testing.T, want string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		for _, state := range s.states {
			if state == want {
				s.mu.Unlock()
				return
			}
		}
		s.mu.Unlock()
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for state %q; got %v", want, s.snapshot())
}

func (s *stateLog) snapshot() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]string, len(s.states))
	copy(out, s.states)
	return out
}

func waitForStateName(t *testing.T, states <-chan string, want string) {
	t.Helper()
	deadline := time.After(5 * time.Second)
	for {
		select {
		case state := <-states:
			if state == want {
				return
			}
		case <-deadline:
			t.Fatalf("timed out waiting for state %q", want)
		}
	}
}
