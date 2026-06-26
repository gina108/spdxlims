package mapping

import (
    "fmt"
    "regexp"
    "sort"
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

        obs = normalizeValue(obs, p.Mapping.ValueNormalization, &trace)

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
                applyRule := rule
                expanded = applySemiquant(expanded, applyRule, &trace)
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
                obs = applySemiquant(obs, rule, &trace)
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

func normalizeValue(obs models.Observation, mapping map[string]string, trace *[]string) models.Observation {
    if len(mapping) == 0 || obs.ValueText == "" {
        return obs
    }
    for from, to := range mapping {
        if strings.EqualFold(strings.TrimSpace(obs.ValueText), strings.TrimSpace(from)) {
            *trace = append(*trace, fmt.Sprintf("value normalized: %q -> %q", obs.ValueText, to))
            obs.ValueText = to
            obs.ValueRaw = to
            obs.ValueNumeric = nil
            return obs
        }
    }
    return obs
}

func applySemiquant(obs models.Observation, rule profile.TestMapping, trace *[]string) models.Observation {
    if len(rule.SemiquantMap) == 0 {
        return obs
    }
    tokens := strings.Fields(obs.ValueRaw)
    if len(tokens) == 0 {
        return obs
    }
    qualifier := tokens[0]
    // "- neg", "- 3+", "+ pos" arrive as two tokens; merge them when the first
    // is a lone operator and the second token is not a pure number (e.g. "neg",
    // "3+", "1+" are qualifiers; "1000", "0.2" are numeric values and stay separate).
    if (qualifier == "-" || qualifier == "+") && len(tokens) > 1 {
        next := tokens[1]
        if _, err := strconv.ParseFloat(next, 64); err != nil {
            qualifier += next
        }
    }

    keys := make([]string, 0, len(rule.SemiquantMap))
    for k := range rule.SemiquantMap {
        keys = append(keys, k)
    }
    sort.Slice(keys, func(i, j int) bool { return len(keys[i]) > len(keys[j]) })

    for _, k := range keys {
        if strings.HasPrefix(strings.ToLower(qualifier), strings.ToLower(k)) {
            entry := rule.SemiquantMap[k]
            obs.ValueText = entry.Display
            obs.ValueRaw = entry.Display
            if entry.Value != nil {
                v := *entry.Value
                obs.ValueNumeric = &v
            } else {
                obs.ValueNumeric = nil
            }
            *trace = append(*trace, fmt.Sprintf("semiquant %s %q -> %q", rule.LISTestID, qualifier, entry.Display))
            return obs
        }
    }

    // semiquant_map defined but no match — blank for manual entry
    *trace = append(*trace, fmt.Sprintf("semiquant %s %q unmatched — blanked for manual entry", rule.LISTestID, qualifier))
    obs.ValueText = ""
    obs.ValueRaw = ""
    obs.ValueNumeric = nil
    obs.UnitsRaw = ""
    obs.UnitsNormalized = ""
    return obs
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
