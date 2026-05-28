package normalize

import (
    "strings"
    "unicode/utf8"

    "instrument-connectivity/internal/models"
)

func Decode(payload []byte) models.NormalizedPayload {
    decoded, enc := decode(payload)
    normalized := normalizeText(decoded)
    return models.NormalizedPayload{RawBytes: payload, DecodedText: decoded, NormalizedText: normalized, Encoding: enc}
}

func decode(payload []byte) (string, string) {
    if isASCII(payload) { return string(payload), "ascii" }
    if utf8.Valid(payload) { return string(payload), "utf-8" }
    return bytesToLatin1(payload), "windows-1252-fallback"
}

func normalizeText(text string) string {
    text = strings.ReplaceAll(text, "\r\n", "\n")
    text = strings.ReplaceAll(text, "\r", "\n")
    text = strings.ReplaceAll(text, "\x00", "")
    lines := strings.Split(text, "\n")
    for i, line := range lines { lines[i] = strings.TrimSpace(line) }
    return strings.TrimSpace(strings.Join(lines, "\n"))
}

func isASCII(payload []byte) bool {
    for _, b := range payload { if b > 127 { return false } }
    return true
}

func bytesToLatin1(payload []byte) string {
    runes := make([]rune, len(payload))
    for i, b := range payload { runes[i] = rune(b) }
    return string(runes)
}
