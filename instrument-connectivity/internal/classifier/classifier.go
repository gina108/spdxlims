package classifier

import (
    "bytes"
    "strings"
    "unicode"

    "instrument-connectivity/internal/models"
)

type Classifier struct{}

func New() *Classifier { return &Classifier{} }

func (c *Classifier) Classify(payload []byte) models.ClassificationResult {
    printable := printableRatio(payload)
    text := strings.ReplaceAll(string(payload), "\x00", "")
    upper := strings.ToUpper(text)
    delimCounts := map[string]int{"|": strings.Count(text, "|"), ",": strings.Count(text, ","), ";": strings.Count(text, ";"), "\t": strings.Count(text, "\t"), "^": strings.Count(text, "^")}
    scores := []models.ClassificationScore{
        scoreHL7(upper, payload, printable),
        scoreASTM(upper, payload, printable),
        scoreCSV(text, printable, delimCounts),
        scoreLine(text, printable),
        scoreFramed(text, payload, printable),
        scoreBinary(payload, printable),
    }
    selected := models.ProtocolUnknown
    best := -1.0
    for _, s := range scores {
        if s.Score > best { best = s.Score; selected = s.Protocol }
    }
    framing := "none"
    if bytes.Contains(payload, []byte{0x02}) && bytes.Contains(payload, []byte{0x03}) { framing = "stx_etx" }
    if bytes.Contains(payload, []byte{0x05}) || bytes.Contains(payload, []byte{0x06}) || bytes.Contains(payload, []byte{0x15}) || bytes.Contains(payload, []byte{0x04}) {
        framing = strings.TrimSpace(framing + " enq_ack_flow")
    }
    return models.ClassificationResult{Selected: selected, Scores: scores, Framing: framing, Printable: printable, Delimiters: delimCounts}
}

func scoreHL7(text string, payload []byte, printable float64) models.ClassificationScore {
    score := 0.0
    reasons := []string{}
    signals := map[string]float64{}
    if strings.Contains(text, "MSH|") { score += 0.55; reasons = append(reasons, "contains MSH segment"); signals["msh"] = 1 }
    for _, seg := range []string{"PID|", "OBR|", "OBX|"} {
        if strings.Contains(text, seg) { score += 0.12; reasons = append(reasons, "contains "+seg) }
    }
    if bytes.Contains(payload, []byte{'\r'}) { score += 0.08; signals["cr"] = 1 }
    if printable > 0.85 { score += 0.05 }
    return models.ClassificationScore{Protocol: models.ProtocolHL7, Score: clamp(score), Reasons: reasons, Signals: signals}
}

func scoreASTM(text string, payload []byte, printable float64) models.ClassificationScore {
    score := 0.0
    reasons := []string{}
    signals := map[string]float64{}
    for _, marker := range []string{"H|", "P|", "O|", "R|", "L|"} {
        if strings.Contains(text, marker) { score += 0.12; reasons = append(reasons, "contains "+marker) }
    }
    if bytes.Contains(payload, []byte{0x02}) && bytes.Contains(payload, []byte{0x03}) { score += 0.22; reasons = append(reasons, "contains STX/ETX framing"); signals["stx_etx"] = 1 }
    if bytes.Contains(payload, []byte{0x05}) || bytes.Contains(payload, []byte{0x06}) || bytes.Contains(payload, []byte{0x15}) || bytes.Contains(payload, []byte{0x04}) { score += 0.2; reasons = append(reasons, "contains ASTM session control characters"); signals["session_ctrl"] = 1 }
    if printable > 0.75 { score += 0.05 }
    return models.ClassificationScore{Protocol: models.ProtocolASTM, Score: clamp(score), Reasons: reasons, Signals: signals}
}

func scoreCSV(text string, printable float64, delims map[string]int) models.ClassificationScore {
    score := 0.0
    reasons := []string{}
    if printable > 0.9 { score += 0.1 }
    if delims[","] >= 3 { score += 0.45; reasons = append(reasons, "frequent comma delimiters") }
    if delims[";"] >= 3 || delims["\t"] >= 3 { score += 0.25; reasons = append(reasons, "frequent delimited fields") }
    if strings.Count(text, "\n") >= 1 { score += 0.1 }
    return models.ClassificationScore{Protocol: models.ProtocolCSV, Score: clamp(score), Reasons: reasons}
}

func scoreLine(text string, printable float64) models.ClassificationScore {
    score := 0.0
    reasons := []string{}
    if printable > 0.95 { score += 0.35; reasons = append(reasons, "mostly printable text") }
    if strings.Count(text, "\n") > 0 || strings.Count(text, "\r") > 0 { score += 0.2; reasons = append(reasons, "line boundaries detected") }
    return models.ClassificationScore{Protocol: models.ProtocolLineText, Score: clamp(score), Reasons: reasons}
}

func scoreFramed(text string, payload []byte, printable float64) models.ClassificationScore {
    score := 0.0
    reasons := []string{}
    if bytes.Contains(payload, []byte{0x02}) || bytes.Contains(payload, []byte{0x03}) { score += 0.25; reasons = append(reasons, "frame markers present") }
    if printable > 0.65 && printable < 0.95 { score += 0.15 }
    if strings.Count(text, "|") > 2 && !strings.Contains(text, "MSH|") { score += 0.12 }
    return models.ClassificationScore{Protocol: models.ProtocolFramedText, Score: clamp(score), Reasons: reasons}
}

func scoreBinary(payload []byte, printable float64) models.ClassificationScore {
    score := 0.0
    reasons := []string{}
    if printable < 0.55 { score += 0.7; reasons = append(reasons, "low printable ratio") }
    if bytes.Count(payload, []byte{0x00}) > 0 { score += 0.15; reasons = append(reasons, "contains null bytes") }
    return models.ClassificationScore{Protocol: models.ProtocolBinary, Score: clamp(score), Reasons: reasons}
}

func printableRatio(payload []byte) float64 {
    if len(payload) == 0 { return 1 }
    printable := 0
    for _, b := range payload {
        r := rune(b)
        if unicode.IsPrint(r) || b == '\n' || b == '\r' || b == '\t' { printable++ }
    }
    return float64(printable) / float64(len(payload))
}

func clamp(v float64) float64 {
    if v < 0 { return 0 }
    if v > 1 { return 1 }
    return v
}
