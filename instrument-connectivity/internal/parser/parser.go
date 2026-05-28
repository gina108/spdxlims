package parser

import (
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode"

	"instrument-connectivity/internal/models"
	"instrument-connectivity/internal/util"
)

type Registry struct{}

func NewRegistry() *Registry { return &Registry{} }

func (r *Registry) Parse(protocol models.ProtocolType, profileID, deviceID, rawRef string, transport models.TransportType, payload models.NormalizedPayload) (models.InstrumentMessage, error) {
	switch protocol {
	case models.ProtocolHL7:
		return parseHL7(profileID, deviceID, rawRef, transport, payload)
	case models.ProtocolASTM:
		return parseASTM(profileID, deviceID, rawRef, transport, payload)
	case models.ProtocolCSV:
		return parseCSV(profileID, deviceID, rawRef, transport, payload)
	case models.ProtocolLineText, models.ProtocolFramedText:
		return parseLines(protocol, profileID, deviceID, rawRef, transport, payload), nil
	default:
		return parseRaw(profileID, deviceID, rawRef, transport, payload), nil
	}
}

func baseMessage(protocol models.ProtocolType, profileID, deviceID, rawRef string, transport models.TransportType) models.InstrumentMessage {
	return models.InstrumentMessage{
		MessageID:       util.NewID("msg"),
		SourceDeviceID:  deviceID,
		SourceProfileID: profileID,
		TransportType:   transport,
		ProtocolType:    protocol,
		ReceivedAt:      time.Now().UTC(),
		RawPayloadRef:   rawRef,
		Metadata:        map[string]any{},
	}
}

func parseHL7(profileID, deviceID, rawRef string, transport models.TransportType, payload models.NormalizedPayload) (models.InstrumentMessage, error) {
	msg := baseMessage(models.ProtocolHL7, profileID, deviceID, rawRef, transport)
	segments := splitRecords(payload.NormalizedText)
	setID := 1
	for _, seg := range segments {
		fields := strings.Split(seg, "|")
		if len(fields) == 0 {
			continue
		}
		switch fields[0] {
		case "PID":
			if len(fields) > 3 {
				msg.PatientID = firstComponent(fields[3])
			}
		case "OBR":
			if len(fields) > 3 {
				msg.SampleID = firstComponent(fields[3])
			}
			if len(fields) > 2 {
				msg.AnalyzerRunID = firstComponent(fields[2])
			}
		case "OBX":
			obs := models.Observation{ObservationID: fmt.Sprintf("obx_%d", setID)}
			setID++
			if len(fields) > 3 {
				obs.InstrumentTestCode = firstComponent(fields[3])
				obs.InstrumentTestName = secondComponent(fields[3])
			}
			if obs.InstrumentTestName == "" && len(fields) > 4 {
				obs.InstrumentTestName = strings.TrimSpace(fields[4])
			}
			if len(fields) > 5 {
				obs.ValueRaw = fields[5]
				if v, err := strconv.ParseFloat(strings.ReplaceAll(fields[5], ",", "."), 64); err == nil {
					obs.ValueNumeric = &v
				} else {
					obs.ValueText = fields[5]
				}
			}
			if len(fields) > 6 {
				obs.UnitsRaw = fields[6]
			}
			if len(fields) > 7 {
				obs.ReferenceRange = fields[7]
			}
			if len(fields) > 8 {
				obs.AbnormalFlag = fields[8]
			}
			if len(fields) > 11 {
				obs.ResultStatus = fields[11]
			}
			msg.Observations = append(msg.Observations, obs)
		}
	}
	return msg, nil
}

func parseASTM(profileID, deviceID, rawRef string, transport models.TransportType, payload models.NormalizedPayload) (models.InstrumentMessage, error) {
	msg := baseMessage(models.ProtocolASTM, profileID, deviceID, rawRef, transport)
	cleaned := strings.Map(func(r rune) rune {
		switch r {
		case 0x02, 0x03, 0x04, 0x05, 0x06, 0x15:
			return -1
		default:
			return r
		}
	}, payload.NormalizedText)
	lines := splitRecords(cleaned)
	obsIndex := 1
	for _, line := range lines {
		parts := strings.Split(line, "|")
		if len(parts) == 0 {
			continue
		}
		recordType := strings.TrimSpace(parts[0])
		if strings.HasPrefix(recordType, "P") && len(parts) > 2 {
			msg.PatientID = strings.TrimSpace(parts[2])
		}
		if strings.HasPrefix(recordType, "O") && len(parts) > 3 {
			msg.SampleID = strings.TrimSpace(parts[2])
			msg.AccessionID = strings.TrimSpace(parts[3])
		}
		if strings.HasPrefix(recordType, "R") {
			obs := models.Observation{ObservationID: fmt.Sprintf("r_%d", obsIndex)}
			obsIndex++
			if len(parts) > 2 {
				codeParts := strings.Split(parts[2], "^")
				if len(codeParts) > 0 {
					obs.InstrumentTestCode = strings.TrimSpace(codeParts[len(codeParts)-1])
				}
				if len(codeParts) > 3 {
					obs.InstrumentTestName = strings.TrimSpace(codeParts[3])
				}
			}
			if len(parts) > 3 {
				obs.ValueRaw = strings.TrimSpace(parts[3])
				if v, err := strconv.ParseFloat(strings.ReplaceAll(obs.ValueRaw, ",", "."), 64); err == nil {
					obs.ValueNumeric = &v
				} else {
					obs.ValueText = obs.ValueRaw
				}
			}
			if len(parts) > 4 {
				obs.UnitsRaw = strings.TrimSpace(parts[4])
			}
			if len(parts) > 5 {
				obs.ReferenceRange = strings.TrimSpace(parts[5])
			}
			if len(parts) > 6 {
				obs.AbnormalFlag = strings.TrimSpace(parts[6])
			}
			if len(parts) > 9 {
				obs.ResultStatus = strings.TrimSpace(parts[9])
			}
			msg.Observations = append(msg.Observations, obs)
		}
	}
	return msg, nil
}

func parseCSV(profileID, deviceID, rawRef string, transport models.TransportType, payload models.NormalizedPayload) (models.InstrumentMessage, error) {
	msg := baseMessage(models.ProtocolCSV, profileID, deviceID, rawRef, transport)
	lines := splitRecords(payload.NormalizedText)
	if len(lines) == 0 {
		return msg, nil
	}
	headers := splitDelimited(lines[0])
	for idx, line := range lines[1:] {
		cols := splitDelimited(line)
		row := map[string]string{}
		for i, h := range headers {
			if i < len(cols) {
				row[strings.ToLower(strings.TrimSpace(h))] = strings.TrimSpace(cols[i])
			}
		}
		if msg.SampleID == "" {
			msg.SampleID = firstNonEmpty(row["sample_id"], row["sample"], row["specimen_id"])
		}
		obs := models.Observation{
			ObservationID:      fmt.Sprintf("csv_%d", idx+1),
			InstrumentTestCode: firstNonEmpty(row["test_code"], row["code"], row["analyte"]),
			InstrumentTestName: firstNonEmpty(row["test_name"], row["name"]),
			ValueRaw:           firstNonEmpty(row["value"], row["result"]),
			UnitsRaw:           firstNonEmpty(row["units"], row["unit"]),
			AbnormalFlag:       row["flag"],
			ReferenceRange:     firstNonEmpty(row["reference_range"], row["range"]),
			ResultStatus:       row["status"],
		}
		if obs.InstrumentTestCode == "" && obs.ValueRaw == "" {
			continue
		}
		if v, err := strconv.ParseFloat(strings.ReplaceAll(obs.ValueRaw, ",", "."), 64); err == nil {
			obs.ValueNumeric = &v
		} else {
			obs.ValueText = obs.ValueRaw
		}
		msg.Observations = append(msg.Observations, obs)
	}
	return msg, nil
}

func parseLines(protocol models.ProtocolType, profileID, deviceID, rawRef string, transport models.TransportType, payload models.NormalizedPayload) models.InstrumentMessage {
	msg := baseMessage(protocol, profileID, deviceID, rawRef, transport)
	lines := splitRecords(stripControlRunes(payload.NormalizedText))
	for i, line := range lines {
		if applyLineMetadata(&msg, line) {
			continue
		}
		obs, ok := parseAnalyzerLine(i+1, line)
		if !ok {
			continue
		}
		msg.Observations = append(msg.Observations, obs)
	}
	msg.Metadata["raw_lines"] = lines
	return msg
}

func parseAnalyzerLine(index int, line string) (models.Observation, bool) {
	parts := strings.FieldsFunc(line, func(r rune) bool {
		return r == '|' || r == ',' || r == ';' || r == '\t' || unicode.IsSpace(r)
	})
	if len(parts) < 2 {
		return models.Observation{}, false
	}
	obs := models.Observation{
		ObservationID:      fmt.Sprintf("line_%d", index),
		InstrumentTestCode: parts[0],
		ValueRaw:           strings.TrimSpace(strings.Join(parts[1:], " ")),
	}
	if obs.ValueRaw == "" {
		return models.Observation{}, false
	}
	if unitToken, ok := detectUnitToken(parts[1:]); ok {
		obs.UnitsRaw = unitToken
	}
	if numericValue, ok := firstNumericToken(parts[1:]); ok {
		obs.ValueNumeric = &numericValue
	}
	obs.ValueText = obs.ValueRaw
	return obs, true
}

func applyLineMetadata(msg *models.InstrumentMessage, line string) bool {
	line = strings.TrimSpace(line)
	if line == "" {
		return true
	}
	upper := strings.ToUpper(line)
	switch {
	case strings.HasPrefix(upper, "DATE:"):
		msg.Metadata["instrument_date"] = strings.TrimSpace(line[len("Date:"):])
		return true
	case strings.HasPrefix(upper, "OPERATOR:"):
		msg.Metadata["operator"] = strings.TrimSpace(line[len("Operator:"):])
		return true
	case strings.HasPrefix(upper, "NO."):
		identifier := strings.TrimSpace(line[len("No."):])
		msg.Metadata["instrument_sequence"] = identifier
		msg.AnalyzerRunID = identifier
		return true
	default:
		return false
	}
}

func stripControlRunes(text string) string {
	return strings.Map(func(r rune) rune {
		switch r {
		case 0x02, 0x03, 0x04, 0x05, 0x06, 0x15:
			return -1
		default:
			return r
		}
	}, text)
}

func firstNumericToken(tokens []string) (float64, bool) {
	for _, token := range tokens {
		cleaned := strings.TrimSpace(token)
		if cleaned == "" {
			continue
		}
		if v, err := strconv.ParseFloat(strings.ReplaceAll(cleaned, ",", "."), 64); err == nil {
			return v, true
		}
	}
	return 0, false
}

func detectUnitToken(tokens []string) (string, bool) {
	for i := len(tokens) - 1; i >= 0; i-- {
		token := strings.TrimSpace(tokens[i])
		if token == "" {
			continue
		}
		lower := strings.ToLower(token)
		if lower == "neg" || lower == "pos" || lower == "trace" {
			continue
		}
		if strings.Contains(token, "/") {
			return token, true
		}
	}
	return "", false
}

func parseRaw(profileID, deviceID, rawRef string, transport models.TransportType, payload models.NormalizedPayload) models.InstrumentMessage {
	msg := baseMessage(models.ProtocolUnknown, profileID, deviceID, rawRef, transport)
	msg.Metadata["raw_text_preview"] = payload.NormalizedText
	return msg
}

func splitRecords(text string) []string {
	records := []string{}
	for _, line := range strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			records = append(records, line)
		}
	}
	return records
}

func firstComponent(s string) string {
	parts := strings.Split(s, "^")
	return strings.TrimSpace(parts[0])
}

func secondComponent(s string) string {
	parts := strings.Split(s, "^")
	if len(parts) > 1 {
		return strings.TrimSpace(parts[1])
	}
	return ""
}

func splitDelimited(line string) []string {
	for _, delim := range []string{",", ";", "\t", "|"} {
		if strings.Contains(line, delim) {
			return strings.Split(line, delim)
		}
	}
	return []string{line}
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			return strings.TrimSpace(v)
		}
	}
	return ""
}
