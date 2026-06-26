package pipeline

import (
    "strings"

    "instrument-connectivity/internal/classifier"
    "instrument-connectivity/internal/mapping"
    "instrument-connectivity/internal/models"
    "instrument-connectivity/internal/normalize"
    "instrument-connectivity/internal/parser"
    "instrument-connectivity/internal/profile"
)

type Processor struct {
    classifier *classifier.Classifier
    parsers *parser.Registry
    mapper *mapping.Engine
}
func New() *Processor { return &Processor{classifier: classifier.New(), parsers: parser.NewRegistry(), mapper: mapping.New()} }
func (p *Processor) Process(raw []byte, transport models.TransportType, deviceID string, prof profile.Profile, rawRef string) (models.ParseResult, error) {
    normalized := normalize.Decode(raw)
    cls := p.classifier.Classify(raw)
    // Profile parsing.strategy beats the classifier; protocol_hint is fallback for unknown.
    if strategy := strings.TrimSpace(prof.Parsing.Strategy); strategy != "" {
        cls.Selected = models.ProtocolType(strategy)
    } else if prof.ProtocolHint != "" && cls.Selected == models.ProtocolUnknown {
        cls.Selected = models.ProtocolType(prof.ProtocolHint)
    }
    msg, err := p.parsers.Parse(cls.Selected, prof.ID, deviceID, rawRef, transport, normalized)
    if err != nil { return models.ParseResult{}, err }
    msg, trace := p.mapper.Apply(msg, prof)
    return models.ParseResult{Classification: cls, Payload: normalized, Message: msg, MappingTrace: trace}, nil
}
