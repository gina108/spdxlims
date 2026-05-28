package transport

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	seriallib "go.bug.st/serial"

	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/profile"
)

const (
	astmENQ byte = 0x05
	astmACK byte = 0x06
	astmNAK byte = 0x15
	astmEOT byte = 0x04
	astmSTX byte = 0x02
	astmETX byte = 0x03
	astmETB byte = 0x17
	astmCR  byte = 0x0D
	astmLF  byte = 0x0A
)

type PayloadHandler func(raw []byte, deviceID string, transportType models.TransportType) error
type ErrorHandler func(error, map[string]any)
type StateHandler func(state string, meta map[string]any)

type Worker interface {
	Stop() error
}

type nopWorker struct{}

func (nopWorker) Stop() error { return nil }

type loopWorker struct {
	cancel context.CancelFunc
	done   chan struct{}
}

func (w *loopWorker) Stop() error {
	w.cancel()
	<-w.done
	return nil
}

type sessionProcessor struct {
	mode             string
	buffer           []byte
	frame            []byte
	awaitingChecksum bool
	checksumBuf      []byte
}

func newSessionProcessor(mode string) *sessionProcessor {
	return &sessionProcessor{
		mode:        strings.ToLower(strings.TrimSpace(mode)),
		buffer:      make([]byte, 0, 8192),
		frame:       make([]byte, 0, 4096),
		checksumBuf: make([]byte, 0, 2),
	}
}

func (sp *sessionProcessor) consume(chunk []byte, writer io.Writer, meta map[string]any, flush func([]byte) error, onError ErrorHandler, onState StateHandler) error {
	if sp.mode != "astm" {
		sp.buffer = append(sp.buffer, chunk...)
		return nil
	}

	for _, b := range chunk {
		if sp.awaitingChecksum && sp.handleChecksumByte(b, writer, meta, onError, onState) {
			continue
		}

		switch b {
		case astmENQ:
			sp.resetFrame()
			if onState != nil {
				onState("handshake", mergeMeta(meta, map[string]any{"event": "enq"}))
			}
			if writer != nil {
				if _, err := writer.Write([]byte{astmACK}); err != nil {
					onError(err, mergeMeta(meta, map[string]any{"stage": "astm_send_ack"}))
				}
			}
		case astmACK:
		case astmNAK:
			if onState != nil {
				onState("nak_received", mergeMeta(meta, map[string]any{"event": "nak"}))
			}
			onError(errors.New("received ASTM NAK"), mergeMeta(meta, map[string]any{"stage": "astm_receive_nak"}))
		case astmSTX:
			sp.frame = sp.frame[:0]
			sp.frame = append(sp.frame, b)
		case astmEOT:
			if sp.awaitingChecksum && len(sp.checksumBuf) == 0 && len(sp.frame) > 0 {
				sp.acceptFrame()
			}
			if err := sp.flush(flush); err != nil {
				return err
			}
			sp.resetFrame()
			if onState != nil {
				onState("idle", mergeMeta(meta, map[string]any{"event": "eot"}))
			}
		case astmETX, astmETB:
			if len(sp.frame) == 0 {
				sp.frame = append(sp.frame, astmSTX)
			}
			sp.frame = append(sp.frame, b)
			sp.awaitingChecksum = true
			sp.checksumBuf = sp.checksumBuf[:0]
		default:
			if len(sp.frame) > 0 {
				sp.frame = append(sp.frame, b)
			} else {
				sp.buffer = append(sp.buffer, b)
			}
		}
	}

	return nil
}

func (sp *sessionProcessor) handleChecksumByte(b byte, writer io.Writer, meta map[string]any, onError ErrorHandler, onState StateHandler) bool {
	if isHexByte(b) && len(sp.checksumBuf) < 2 {
		sp.checksumBuf = append(sp.checksumBuf, b)
		if len(sp.checksumBuf) == 2 {
			valid, expected, actual := sp.validateChecksum()
			if valid {
				sp.acceptFrame()
				if onState != nil {
					onState("frame_valid", mergeMeta(meta, map[string]any{"checksum": actual}))
				}
				if writer != nil {
					if _, err := writer.Write([]byte{astmACK}); err != nil {
						onError(err, mergeMeta(meta, map[string]any{"stage": "astm_send_ack"}))
					}
				}
			} else {
				sp.rejectFrame()
				if onState != nil {
					onState("checksum_error", mergeMeta(meta, map[string]any{"expected": expected, "actual": actual}))
				}
				onError(fmt.Errorf("invalid ASTM checksum: expected %s got %s", expected, actual), mergeMeta(meta, map[string]any{"stage": "astm_checksum"}))
				if writer != nil {
					if _, err := writer.Write([]byte{astmNAK}); err != nil {
						onError(err, mergeMeta(meta, map[string]any{"stage": "astm_send_nak"}))
					}
				}
			}
		}
		return true
	}

	if (b == astmCR || b == astmLF) && len(sp.checksumBuf) > 0 {
		return true
	}

	return false
}

func (sp *sessionProcessor) validateChecksum() (bool, string, string) {
	if len(sp.frame) < 2 || len(sp.checksumBuf) != 2 {
		return false, "", string(sp.checksumBuf)
	}
	expected := strings.ToUpper(string(sp.checksumBuf))
	sum := 0
	for _, b := range sp.frame[1:] {
		sum += int(b)
	}
	actual := strings.ToUpper(fmt.Sprintf("%02X", sum%256))
	return expected == actual, expected, actual
}

func (sp *sessionProcessor) acceptFrame() {
	if len(sp.frame) == 0 {
		sp.resetFrame()
		return
	}
	payload := sp.frame
	if payload[0] == astmSTX {
		payload = payload[1:]
	}
	sp.buffer = append(sp.buffer, payload...)
	sp.resetFrame()
}

func (sp *sessionProcessor) rejectFrame() { sp.resetFrame() }

func (sp *sessionProcessor) resetFrame() {
	sp.frame = sp.frame[:0]
	sp.awaitingChecksum = false
	sp.checksumBuf = sp.checksumBuf[:0]
}

func (sp *sessionProcessor) flush(flush func([]byte) error) error {
	if len(sp.buffer) == 0 {
		return nil
	}
	payload := append([]byte(nil), sp.buffer...)
	sp.buffer = sp.buffer[:0]
	return flush(payload)
}

func StartProfileWorker(p profile.Profile, handler PayloadHandler, onError ErrorHandler, onState StateHandler) (Worker, error) {
	switch strings.ToLower(strings.TrimSpace(p.Transport.Type)) {
	case "file_drop":
		return startFileDropWorker(p, handler, onError, onState)
	case "tcp_server":
		return startTCPServerWorker(p, handler, onError, onState)
	case "tcp_client":
		return startTCPClientWorker(p, handler, onError, onState)
	case "serial":
		return startSerialWorker(p, handler, onError, onState)
	case "", "replay":
		return nopWorker{}, nil
	default:
		return nil, fmt.Errorf("unsupported transport type %q", p.Transport.Type)
	}
}

func startFileDropWorker(p profile.Profile, handler PayloadHandler, onError ErrorHandler, onState StateHandler) (Worker, error) {
	watcher, err := NewFileWatcher()
	if err != nil {
		return nil, err
	}
	directories := p.Transport.WatchDirectories
	if len(directories) == 0 {
		directories = []string{"incoming"}
	}
	for _, dir := range directories {
		cleaned := NormalizeWatchedPath(dir)
		if err := os.MkdirAll(cleaned, 0o755); err != nil {
			_ = watcher.Close()
			return nil, err
		}
		if err := watcher.Add(cleaned); err != nil {
			_ = watcher.Close()
			return nil, err
		}
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	recent := map[string]time.Time{}
	var mu sync.Mutex

	go func() {
		defer close(done)
		defer watcher.Close()
		ticker := time.NewTicker(30 * time.Second)
		defer ticker.Stop()
		if onState != nil {
			onState("watching", nil)
		}
		for {
			select {
			case <-ctx.Done():
				if onState != nil {
					onState("stopped", nil)
				}
				return
			case event, ok := <-watcher.Events():
				if !ok {
					return
				}
				if event.Op&(1|2|8|16) == 0 {
					continue
				}
				if info, err := os.Stat(event.Name); err == nil && info.IsDir() {
					continue
				}
				mu.Lock()
				if last, ok := recent[event.Name]; ok && time.Since(last) < time.Second {
					mu.Unlock()
					continue
				}
				recent[event.Name] = time.Now()
				mu.Unlock()
				if onState != nil {
					onState("processing", map[string]any{"path": event.Name})
				}
				raw, err := os.ReadFile(event.Name)
				if err != nil {
					onError(err, map[string]any{"stage": "file_drop_read", "path": event.Name})
					if onState != nil {
						onState("error", map[string]any{"path": event.Name})
					}
					continue
				}
				if len(raw) == 0 {
					continue
				}
				if err := handler(raw, filepath.Base(event.Name), models.TransportFileDrop); err != nil {
					onError(err, map[string]any{"stage": "file_drop_process", "path": event.Name})
					if onState != nil {
						onState("error", map[string]any{"path": event.Name})
					}
				} else if onState != nil {
					onState("active", map[string]any{"path": event.Name})
				}
			case err, ok := <-watcher.Errors():
				if !ok {
					return
				}
				onError(err, map[string]any{"stage": "file_drop_watch"})
				if onState != nil {
					onState("error", nil)
				}
			case <-ticker.C:
				mu.Lock()
				for key, ts := range recent {
					if time.Since(ts) > time.Minute {
						delete(recent, key)
					}
				}
				mu.Unlock()
			}
		}
	}()

	return &loopWorker{cancel: cancel, done: done}, nil
}

func startTCPServerWorker(p profile.Profile, handler PayloadHandler, onError ErrorHandler, onState StateHandler) (Worker, error) {
	address := strings.TrimSpace(p.Transport.ListenAddress)
	if address == "" {
		return nil, errors.New("tcp_server transport requires listen_address")
	}
	listener, err := net.Listen("tcp", address)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	sessionMode := selectSessionMode(p)

	go func() {
		defer close(done)
		defer listener.Close()
		tcpListener, _ := listener.(*net.TCPListener)
		if onState != nil {
			onState("listening", map[string]any{"address": address})
		}
		for {
			if tcpListener != nil {
				_ = tcpListener.SetDeadline(time.Now().Add(time.Second))
			}
			conn, err := listener.Accept()
			if err != nil {
				if ne, ok := err.(net.Error); ok && ne.Timeout() {
					select {
					case <-ctx.Done():
						if onState != nil {
							onState("stopped", nil)
						}
						return
					default:
						continue
					}
				}
				select {
				case <-ctx.Done():
					if onState != nil {
						onState("stopped", nil)
					}
					return
				default:
					onError(err, map[string]any{"stage": "tcp_server_accept", "address": address})
					if onState != nil {
						onState("retrying", map[string]any{"address": address})
					}
					time.Sleep(time.Second)
					continue
				}
			}
			if onState != nil {
				onState("connected", map[string]any{"device_id": conn.RemoteAddr().String()})
			}
			go handleConnection(ctx, conn, models.TransportTCPServer, sessionMode, handler, onError, onState)
		}
	}()

	return &loopWorker{cancel: func() { cancel(); _ = listener.Close() }, done: done}, nil
}

func startTCPClientWorker(p profile.Profile, handler PayloadHandler, onError ErrorHandler, onState StateHandler) (Worker, error) {
	address := strings.TrimSpace(p.Transport.RemoteAddress)
	if address == "" {
		return nil, errors.New("tcp_client transport requires remote_address")
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	sessionMode := selectSessionMode(p)

	go func() {
		defer close(done)
		backoff := time.Second
		if onState != nil {
			onState("starting", map[string]any{"address": address})
		}
		for {
			select {
			case <-ctx.Done():
				if onState != nil {
					onState("stopped", nil)
				}
				return
			default:
			}
			conn, err := net.DialTimeout("tcp", address, 5*time.Second)
			if err != nil {
				onError(err, map[string]any{"stage": "tcp_client_connect", "address": address})
				if onState != nil {
					onState("retrying", map[string]any{"address": address})
				}
				sleepWithContext(ctx, backoff)
				if backoff < 15*time.Second {
					backoff *= 2
				}
				continue
			}
			backoff = time.Second
			if onState != nil {
				onState("connected", map[string]any{"address": address})
			}
			handleConnection(ctx, conn, models.TransportTCPClient, sessionMode, handler, onError, onState)
			sleepWithContext(ctx, time.Second)
		}
	}()

	return &loopWorker{cancel: cancel, done: done}, nil
}

func startSerialWorker(p profile.Profile, handler PayloadHandler, onError ErrorHandler, onState StateHandler) (Worker, error) {
	portName := strings.TrimSpace(p.Transport.SerialPort)
	if portName == "" {
		return nil, errors.New("serial transport requires serial_port")
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	sessionMode := selectSessionMode(p)

	go func() {
		defer close(done)
		backoff := time.Second
		if onState != nil {
			onState("starting", map[string]any{"port": portName})
		}
		for {
			select {
			case <-ctx.Done():
				if onState != nil {
					onState("stopped", nil)
				}
				return
			default:
			}
			mode, candidate := selectSerialMode(p)
			port, err := seriallib.Open(portName, mode)
			if err != nil {
				onError(err, map[string]any{"stage": "serial_open", "port": portName, "candidate": candidate})
				if onState != nil {
					onState("retrying", map[string]any{"port": portName})
				}
				sleepWithContext(ctx, backoff)
				if backoff < 15*time.Second {
					backoff *= 2
				}
				continue
			}
			backoff = time.Second
			_ = port.SetReadTimeout(2 * time.Second)
			if onState != nil {
				onState("connected", map[string]any{"port": portName, "candidate": candidate})
			}
			readSerialLoop(ctx, port, portName, sessionMode, handler, onError, onState, candidate)
			sleepWithContext(ctx, time.Second)
		}
	}()

	return &loopWorker{cancel: cancel, done: done}, nil
}

func readSerialLoop(ctx context.Context, port seriallib.Port, portName, sessionMode string, handler PayloadHandler, onError ErrorHandler, onState StateHandler, candidate SerialCandidate) {
	defer port.Close()
	processor := newSessionProcessor(sessionMode)
	chunk := make([]byte, 4096)
	meta := map[string]any{"port": portName, "candidate": candidate}
	for {
		n, err := port.Read(chunk)
		if n > 0 {
			consumeErr := processor.consume(chunk[:n], port, meta, func(payload []byte) error {
				if onState != nil {
					onState("processing", meta)
				}
				return handler(payload, portName, models.TransportSerial)
			}, onError, onState)
			if consumeErr != nil {
				onError(consumeErr, mergeMeta(meta, map[string]any{"stage": "serial_process"}))
				if onState != nil {
					onState("error", meta)
				}
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				_ = processor.flush(func(payload []byte) error {
					return handler(payload, portName, models.TransportSerial)
				})
				return
			}
			onError(err, mergeMeta(meta, map[string]any{"stage": "serial_read"}))
			if onState != nil {
				onState("retrying", meta)
			}
			return
		}
		if n == 0 {
			if flushErr := processor.flush(func(payload []byte) error {
				return handler(payload, portName, models.TransportSerial)
			}); flushErr != nil {
				onError(flushErr, mergeMeta(meta, map[string]any{"stage": "serial_process"}))
			} else if onState != nil {
				onState("idle", meta)
			}
		}
		select {
		case <-ctx.Done():
			return
		default:
		}
	}
}

func selectSerialMode(p profile.Profile) (*seriallib.Mode, SerialCandidate) {
	selected := SerialCandidate{BaudRate: fallbackInt(p.Transport.BaudRate, 9600), DataBits: fallbackInt(p.Transport.DataBits, 8), Parity: fallbackString(strings.ToUpper(strings.TrimSpace(p.Transport.Parity)), "N"), StopBits: fallbackInt(p.Transport.StopBits, 1), Reason: "profile transport settings"}
	if p.Transport.BaudRate == 0 || p.Transport.DataBits == 0 || strings.TrimSpace(p.Transport.Parity) == "" || p.Transport.StopBits == 0 {
		candidates := ScoreSerialCandidates(p)
		if len(candidates) > 0 {
			selected = candidates[0]
			selected.Reason = "best scored serial candidate"
		}
	}
	mode := &seriallib.Mode{BaudRate: selected.BaudRate, DataBits: selected.DataBits, Parity: toSerialParity(selected.Parity), StopBits: toSerialStopBits(selected.StopBits)}
	return mode, selected
}

func toSerialParity(parity string) seriallib.Parity {
	switch strings.ToUpper(strings.TrimSpace(parity)) {
	case "E":
		return seriallib.EvenParity
	case "O":
		return seriallib.OddParity
	default:
		return seriallib.NoParity
	}
}

func toSerialStopBits(stopBits int) seriallib.StopBits {
	if stopBits == 2 {
		return seriallib.TwoStopBits
	}
	return seriallib.OneStopBit
}

func fallbackInt(value, fallback int) int {
	if value != 0 {
		return value
	}
	return fallback
}
func fallbackString(value, fallback string) string {
	if value != "" {
		return value
	}
	return fallback
}

func handleConnection(ctx context.Context, conn net.Conn, transportType models.TransportType, sessionMode string, handler PayloadHandler, onError ErrorHandler, onState StateHandler) {
	defer conn.Close()
	deviceID := conn.RemoteAddr().String()
	processor := newSessionProcessor(sessionMode)
	chunk := make([]byte, 4096)
	meta := map[string]any{"device_id": deviceID}
	for {
		_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
		n, err := conn.Read(chunk)
		if n > 0 {
			consumeErr := processor.consume(chunk[:n], conn, meta, func(payload []byte) error {
				if onState != nil {
					onState("processing", meta)
				}
				return handler(payload, deviceID, transportType)
			}, onError, onState)
			if consumeErr != nil {
				onError(consumeErr, mergeMeta(meta, map[string]any{"stage": "connection_process"}))
				if onState != nil {
					onState("error", meta)
				}
			}
		}
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				if flushErr := processor.flush(func(payload []byte) error {
					return handler(payload, deviceID, transportType)
				}); flushErr != nil {
					onError(flushErr, mergeMeta(meta, map[string]any{"stage": "connection_process"}))
				} else if onState != nil {
					onState("idle", meta)
				}
				select {
				case <-ctx.Done():
					return
				default:
					continue
				}
			}
			if errors.Is(err, io.EOF) {
				_ = processor.flush(func(payload []byte) error {
					return handler(payload, deviceID, transportType)
				})
				if onState != nil {
					onState("disconnected", meta)
				}
				return
			}
			onError(err, mergeMeta(meta, map[string]any{"stage": "connection_read"}))
			if onState != nil {
				onState("retrying", meta)
			}
			return
		}
		select {
		case <-ctx.Done():
			return
		default:
		}
	}
}

func selectSessionMode(p profile.Profile) string {
	if mode := strings.ToLower(strings.TrimSpace(p.Transport.SessionMode)); mode != "" {
		return mode
	}
	if strings.EqualFold(p.ProtocolHint, "astm") || strings.EqualFold(p.Parsing.Strategy, "astm") {
		return "astm"
	}
	return ""
}

func mergeMeta(base, extra map[string]any) map[string]any {
	merged := map[string]any{}
	for k, v := range base {
		merged[k] = v
	}
	for k, v := range extra {
		merged[k] = v
	}
	return merged
}

func isHexByte(b byte) bool { return bytes.ContainsAny([]byte{b}, "0123456789ABCDEFabcdef") }

func sleepWithContext(ctx context.Context, duration time.Duration) {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
	case <-timer.C:
	}
}

func buildASTMFrame(body string) []byte {
	frame := append([]byte{astmSTX}, []byte(body)...)
	frame = append(frame, astmETX)
	sum := 0
	for _, b := range frame[1:] {
		sum += int(b)
	}
	checksum := strings.ToUpper(fmt.Sprintf("%02X", sum%256))
	out := append([]byte{}, frame...)
	out = append(out, []byte(checksum)...)
	out = append(out, astmCR, astmLF)
	return out
}
