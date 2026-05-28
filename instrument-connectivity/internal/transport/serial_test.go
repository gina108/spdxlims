package transport

import (
	"bytes"
	"testing"

	"instrument-connectivity/internal/profile"
)

func TestScoreSerialCandidates(t *testing.T) {
	prof := profile.Profile{Transport: profile.TransportSettings{BaudRate: 9600, DataBits: 8, Parity: "N", StopBits: 1}}
	candidates := ScoreSerialCandidates(prof)
	if len(candidates) == 0 {
		t.Fatal("expected candidates")
	}
	best := candidates[0]
	if best.BaudRate != 9600 || best.DataBits != 8 || best.Parity != "N" || best.StopBits != 1 {
		t.Fatalf("unexpected best candidate: %#v", best)
	}
}

func TestASTMSessionProcessorValidChecksum(t *testing.T) {
	processor := newSessionProcessor("astm")
	var writes bytes.Buffer
	flushed := [][]byte{}
	frame := append([]byte{astmENQ}, buildASTMFrame("1H|\\^&|||Analyzer\r")...)
	frame = append(frame, astmEOT)

	err := processor.consume(frame, &writes, map[string]any{}, func(payload []byte) error {
		flushed = append(flushed, append([]byte(nil), payload...))
		return nil
	}, func(error, map[string]any) {}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(flushed) != 1 {
		t.Fatalf("expected one flushed ASTM payload, got %d", len(flushed))
	}
	if !bytes.Contains(flushed[0], []byte("H|\\^&|||Analyzer")) {
		t.Fatalf("unexpected ASTM payload: %q", string(flushed[0]))
	}
	if writes.Len() < 2 {
		t.Fatalf("expected ACK writes, got %d bytes", writes.Len())
	}
}

func TestASTMSessionProcessorLegacyNoChecksum(t *testing.T) {
	processor := newSessionProcessor("astm")
	flushed := [][]byte{}
	legacy := []byte{astmENQ, astmSTX}
	legacy = append(legacy, []byte("1H|\\^&|||Analyzer\r")...)
	legacy = append(legacy, astmETX, astmEOT)

	err := processor.consume(legacy, &bytes.Buffer{}, map[string]any{}, func(payload []byte) error {
		flushed = append(flushed, append([]byte(nil), payload...))
		return nil
	}, func(error, map[string]any) {}, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(flushed) != 1 {
		t.Fatalf("expected legacy ASTM payload to flush once, got %d", len(flushed))
	}
}
