package parser

import (
	"testing"

	"instrument-connectivity/internal/models"
)

func TestParseASTM(t *testing.T) {
	payload := models.NormalizedPayload{NormalizedText: "H|\\^&|||Analyzer\nP|1|PAT001\nO|1|SAMPLE42|ACC42||^^^GLU\nR|1|^^^GLU|108|mg/dl|70-110|N|||F\nL|1|N"}
	msg, err := NewRegistry().Parse(models.ProtocolASTM, "generic-astm", "dev1", "raw", models.TransportSerial, payload)
	if err != nil {
		t.Fatal(err)
	}
	if msg.SampleID != "SAMPLE42" {
		t.Fatalf("expected sample id SAMPLE42, got %q", msg.SampleID)
	}
	if len(msg.Observations) != 1 || msg.Observations[0].InstrumentTestCode != "GLU" {
		t.Fatalf("unexpected observations: %#v", msg.Observations)
	}
}

func TestParseHL7(t *testing.T) {
	payload := models.NormalizedPayload{NormalizedText: "MSH|^~\\&|AN|LAB|LIS|LAB|20260321||ORU^R01|1|P|2.3\nPID|1||PAT123\nOBR|1|RUN1|SAMPLE1|GLU^Glucose\nOBX|1|NM|GLU^Glucose||108|mg/dL|70-110|N|||F"}
	msg, err := NewRegistry().Parse(models.ProtocolHL7, "generic-hl7", "dev1", "raw", models.TransportTCPClient, payload)
	if err != nil {
		t.Fatal(err)
	}
	if msg.PatientID != "PAT123" {
		t.Fatalf("expected patient PAT123, got %q", msg.PatientID)
	}
	if len(msg.Observations) != 1 || msg.Observations[0].InstrumentTestCode != "GLU" {
		t.Fatalf("unexpected observations: %#v", msg.Observations)
	}
}

func TestParseFramedUrinalysisLines(t *testing.T) {
	payload := models.NormalizedPayload{NormalizedText: "\x02 Date:2026-05-02 15:58\r\n Operator: 100\r\n No.000004\r\n LEU       -              neg\r\n URO       -       0.2  mg/dL\r\n PRO      +-       15   mg/dL\r\n pH           6.0\r\n SG         1.015\r\n\x03"}
	msg, err := NewRegistry().Parse(models.ProtocolLineText, "urinalysis-com6", "COM6", "raw", models.TransportSerial, payload)
	if err != nil {
		t.Fatal(err)
	}
	if msg.SampleID != "" {
		t.Fatalf("expected no sample id from urinalysis sequence, got %q", msg.SampleID)
	}
	if msg.AccessionID != "" {
		t.Fatalf("expected no accession id from urinalysis sequence, got %q", msg.AccessionID)
	}
	if msg.AnalyzerRunID != "000004" {
		t.Fatalf("expected analyzer run id 000004, got %q", msg.AnalyzerRunID)
	}
	if len(msg.Observations) != 5 {
		t.Fatalf("expected 5 observations, got %d (%#v)", len(msg.Observations), msg.Observations)
	}
	if msg.Observations[0].InstrumentTestCode != "LEU" || msg.Observations[0].ValueRaw != "- neg" {
		t.Fatalf("unexpected LEU observation: %#v", msg.Observations[0])
	}
	if msg.Observations[1].InstrumentTestCode != "URO" || msg.Observations[1].UnitsRaw != "mg/dL" {
		t.Fatalf("unexpected URO observation: %#v", msg.Observations[1])
	}
	if msg.Observations[1].ValueNumeric == nil || *msg.Observations[1].ValueNumeric != 0.2 {
		t.Fatalf("expected URO numeric value 0.2, got %#v", msg.Observations[1].ValueNumeric)
	}
	if msg.Observations[2].InstrumentTestCode != "PRO" || msg.Observations[2].ValueNumeric == nil || *msg.Observations[2].ValueNumeric != 15 {
		t.Fatalf("unexpected PRO observation: %#v", msg.Observations[2])
	}
	if msg.Observations[3].InstrumentTestCode != "pH" || msg.Observations[3].ValueNumeric == nil || *msg.Observations[3].ValueNumeric != 6.0 {
		t.Fatalf("unexpected pH observation: %#v", msg.Observations[3])
	}
	if msg.Observations[4].InstrumentTestCode != "SG" || msg.Observations[4].ValueNumeric == nil || *msg.Observations[4].ValueNumeric != 1.015 {
		t.Fatalf("unexpected SG observation: %#v", msg.Observations[4])
	}
}
