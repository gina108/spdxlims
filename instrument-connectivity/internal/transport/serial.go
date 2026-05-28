package transport

import (
    "sort"

    "instrument-connectivity/internal/profile"
)

type SerialCandidate struct {
    BaudRate int `json:"baud_rate"`
    DataBits int `json:"data_bits"`
    Parity string `json:"parity"`
    StopBits int `json:"stop_bits"`
    Score float64 `json:"score"`
    Reason string `json:"reason"`
}

func CommonSerialCandidates() []SerialCandidate {
    return []SerialCandidate{{BaudRate: 9600, DataBits: 8, Parity: "N", StopBits: 1}, {BaudRate: 19200, DataBits: 8, Parity: "N", StopBits: 1}, {BaudRate: 38400, DataBits: 8, Parity: "N", StopBits: 1}, {BaudRate: 9600, DataBits: 7, Parity: "E", StopBits: 1}}
}
func ScoreSerialCandidates(p profile.Profile) []SerialCandidate {
    candidates := CommonSerialCandidates()
    for i := range candidates {
        score := 0.3
        reason := "default common serial profile"
        if p.Transport.BaudRate == candidates[i].BaudRate { score += 0.35; reason = "matches profile baud" }
        if p.Transport.DataBits != 0 && p.Transport.DataBits == candidates[i].DataBits { score += 0.15 }
        if p.Transport.Parity != "" && p.Transport.Parity == candidates[i].Parity { score += 0.15 }
        if p.Transport.StopBits != 0 && p.Transport.StopBits == candidates[i].StopBits { score += 0.05 }
        if candidates[i].BaudRate == 9600 && candidates[i].DataBits == 8 && candidates[i].Parity == "N" && candidates[i].StopBits == 1 { score += 0.1 }
        candidates[i].Score = score
        candidates[i].Reason = reason
    }
    sort.Slice(candidates, func(i, j int) bool { return candidates[i].Score > candidates[j].Score })
    return candidates
}
