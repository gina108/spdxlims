package mapping

import (
    "fmt"
    "regexp"
    "strconv"
    "strings"

    "instrument-connectivity/internal/models"
    "instrument-connectivity/internal/profile"
)

type Engine struct{}
func New() *Engine { return &Engine{} }

func (e *Engine) Apply(msg models.InstrumentMessage, p profile.Profile) (models.InstrumentMessage, []string) {
    trace := []string{}
    filtered := []models.Observation{}
    for _, obs := range msg.Observations {
        if shouldIgnore(obs, p.Mapping.QCFilterPatterns) { trace = append(trace, "filtered observation "+obs.ObservationID+" by QC rule"); continue }
        normCode := strings.TrimSpace(obs.InstrumentTestCode)
        for canonical, aliases := range p.Mapping.TestCodeAliases {
            for _, alias := range aliases {
                if strings.EqualFold(alias, normCode) { normCode = canonical; trace = append(trace, "aliased "+obs.InstrumentTestCode+" -> "+canonical); break }
            }
        }

        var componentRules []profile.TestMapping
        var plainRules []profile.TestMapping
        for _, rule := range p.Mapping.TestMappings {
            if !matches(rule, normCode) { continue }
            if rule.ComponentIndex != nil { componentRules = append(componentRules, rule) } else { plainRules = append(plainRules, rule) }
        }

        if len(componentRules) > 0 {
            valueComponents := strings.Split(obs.ValueRaw, "^")
            unitComponents := strings.Split(obs.UnitsRaw, "^")
            for _, rule := range componentRules {
                idx := *rule.ComponentIndex
                expanded := obs
                expanded.ObservationID = fmt.Sprintf("%s_c%d", obs.ObservationID, idx)
                expanded.InstrumentTestCode = fmt.Sprintf("%s_%d", normCode, idx)
                expanded.InstrumentTestName = rule.CanonicalAssay
                expanded.MappedLISTestID = rule.LISTestID
                expanded.ValueNumeric = nil
                expanded.ValueText = ""
                if idx < len(valueComponents) {
                    raw := strings.TrimSpace(valueComponents[idx])
                    expanded.ValueRaw = raw
                    if v, err := strconv.ParseFloat(strings.ReplaceAll(raw, ",", "."), 64); err == nil { expanded.ValueNumeric = &v } else { expanded.ValueText = raw }
                }
                if idx < len(unitComponents) { expanded.UnitsRaw = strings.TrimSpace(unitComponents[idx]) }
                expanded.UnitsNormalized = normalizeUnit(expanded.UnitsRaw, rule.NormalizedUnits, p.Mapping.UnitNormalization)
                trace = append(trace, fmt.Sprintf("expanded %s[%d] -> %s", normCode, idx, rule.LISTestID))
                filtered = append(filtered, expanded)
            }
        } else {
            mapped := false
            for _, rule := range plainRules {
                obs.MappedLISTestID = rule.LISTestID
                if obs.InstrumentTestName == "" { obs.InstrumentTestName = rule.CanonicalAssay }
                mapped = true
                trace = append(trace, "mapped "+normCode+" -> "+rule.LISTestID)
                if obs.UnitsRaw != "" { obs.UnitsNormalized = normalizeUnit(obs.UnitsRaw, rule.NormalizedUnits, p.Mapping.UnitNormalization) }
                break
            }
            if !mapped { trace = append(trace, "unmapped observation "+obs.InstrumentTestCode) }
            if obs.UnitsNormalized == "" && obs.UnitsRaw != "" { obs.UnitsNormalized = normalizeUnit(obs.UnitsRaw, "", p.Mapping.UnitNormalization) }
            filtered = append(filtered, obs)
        }
    }
    msg.Observations = filtered
    return msg, trace
}

func matches(rule profile.TestMapping, code string) bool {
    switch strings.ToLower(rule.MatchType) {
    case "regex":
        re, err := regexp.Compile(rule.Pattern)
        return err == nil && re.MatchString(code)
    case "contains":
        return strings.Contains(strings.ToUpper(code), strings.ToUpper(rule.Pattern))
    default:
        return strings.EqualFold(rule.Pattern, code)
    }
}
func normalizeUnit(raw, explicit string, mapping map[string]string) string { if explicit != "" { return explicit }; for from, to := range mapping { if strings.EqualFold(strings.TrimSpace(from), strings.TrimSpace(raw)) { return to } }; return strings.TrimSpace(raw) }
func shouldIgnore(obs models.Observation, patterns []string) bool { combined := strings.ToUpper(obs.InstrumentTestCode + " " + obs.InstrumentTestName + " " + obs.ValueRaw); for _, pattern := range patterns { if strings.Contains(combined, strings.ToUpper(pattern)) { return true } }; return false }
