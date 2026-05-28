package classifier

import (
	"testing"

	"instrument-connectivity/internal/models"
)

func TestClassifyHL7(t *testing.T) {
	payload := []byte(`MSH|^~\&|A|B|C|D|202603211200||ORU^R01|1|P|2.3
PID|1||123
OBR|1||S1
OBX|1|NM|GLU^Glucose||100|mg/dL`)
	result := New().Classify(payload)
	if result.Selected != models.ProtocolHL7 {
		t.Fatalf("expected HL7, got %s", result.Selected)
	}
}

func TestClassifyASTM(t *testing.T) {
	payload := []byte{0x05, 0x02}
	payload = append(payload, []byte("1H|\\^&||\r\nP|1|PAT1\r\nR|1|^^^GLU|100|mg/dl|70-110|N|||F\r\nL|1|N")...)
	payload = append(payload, 0x03, 0x04)
	result := New().Classify(payload)
	if result.Selected != models.ProtocolASTM {
		t.Fatalf("expected ASTM, got %s", result.Selected)
	}
}
