package orderfile

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestFormatOrderLineGrammar(t *testing.T) {
	line := formatOrderLine(OrderRecord{
		OrderNumber: "2006190",
		PatientName: "Rosa Mendoza",
		Date:        "06/22/26",
		Time:        "00:00:00",
		TestCodes:   []string{"GLU L", "CRE L", "URI L"},
	})
	want := "2006190   ;N;Rosa Mendoza        ;            ;   ; ;06/22/26;00:00:00;GLU L ;CRE L ;URI L "
	if line != want {
		t.Fatalf("grammar mismatch:\n got %q\nwant %q", line, want)
	}
	// No status/count fields, and the line must not end with an empty field
	// (which the analyzer would read as a phantom ALB).
	if strings.HasSuffix(line, ";") {
		t.Fatal("line must not end with a trailing empty field")
	}
	if strings.Contains(line, ";OK;") || strings.Contains(line, ";  ; 3;") {
		t.Fatal("line must not contain export-only status/count fields")
	}
}

func TestWriteOrderFileNameWithPatient(t *testing.T) {
	dir := t.TempDir()
	cfg := Config{Directory: dir, FileExtension: ".ANA", WriteOnPush: true}
	path, err := WriteOrder(cfg, OrderRecord{OrderNumber: "2006196", PatientName: "Rosa Mendoza", TestCodes: []string{"GLU L"}})
	if err != nil {
		t.Fatalf("WriteOrder: %v", err)
	}
	if filepath.Base(path) != "2006196 Rosa Mendoza.ANA" {
		t.Fatalf("unexpected filename: %s", filepath.Base(path))
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if !strings.HasSuffix(string(b), "\r\n") {
		t.Fatal("expected CRLF line ending")
	}
}

func TestWriteOrderFileNameNoPatient(t *testing.T) {
	dir := t.TempDir()
	path, err := WriteOrder(Config{Directory: dir, FileExtension: ".ANA"}, OrderRecord{OrderNumber: "2006200", TestCodes: []string{"GLU L"}})
	if err != nil {
		t.Fatalf("WriteOrder: %v", err)
	}
	if filepath.Base(path) != "2006200.ANA" {
		t.Fatalf("expected bare order filename, got %s", filepath.Base(path))
	}
}

func TestWriteOrderSanitizesPatientName(t *testing.T) {
	dir := t.TempDir()
	path, err := WriteOrder(Config{Directory: dir, FileExtension: ".ANA"}, OrderRecord{OrderNumber: "55", PatientName: `Ana/Lu:Garcia*?`, TestCodes: []string{"ALB"}})
	if err != nil {
		t.Fatalf("WriteOrder: %v", err)
	}
	name := filepath.Base(path)
	if strings.ContainsAny(name, invalidFileChars) {
		t.Fatalf("filename retained illegal characters: %s", name)
	}
}

// TestWriteThenArchiveRoundTrip writes an order with a patient name, then
// confirms ArchiveResult finds it by order number alone (prefix match).
func TestWriteThenArchiveRoundTrip(t *testing.T) {
	dir := t.TempDir()
	cfg := Config{Directory: dir, FileExtension: ".ANA", WriteOnPush: true, ArchiveOnResult: true}

	if _, err := WriteOrder(cfg, OrderRecord{OrderNumber: "2006196", PatientName: "Rosa Mendoza", TestCodes: []string{"GLU L"}}); err != nil {
		t.Fatalf("WriteOrder: %v", err)
	}
	dst, err := ArchiveResult(cfg, "2006196")
	if err != nil {
		t.Fatalf("ArchiveResult: %v", err)
	}
	if dst == "" {
		t.Fatal("expected the named order file to be archived by order number")
	}
	if _, err := os.Stat(dst); err != nil {
		t.Fatalf("archived file missing: %v", err)
	}
}

// TestArchiveDoesNotMatchSimilarOrder guards against an order number being a
// prefix of an unrelated order's number.
func TestArchiveDoesNotMatchSimilarOrder(t *testing.T) {
	dir := t.TempDir()
	cfg := Config{Directory: dir, FileExtension: ".ANA", ArchiveOnResult: true}
	if err := os.WriteFile(filepath.Join(dir, "2006196 Rosa.ANA"), []byte("x\r\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	dst, err := ArchiveResult(cfg, "200619")
	if err != nil {
		t.Fatalf("ArchiveResult: %v", err)
	}
	if dst != "" {
		t.Fatalf("order 200619 must not match file for 2006196, got %s", dst)
	}
}
