package mapping

import (
    "testing"

    "instrument-connectivity/internal/models"
    "instrument-connectivity/internal/profile"
)

func semiquantRule(entries map[string]profile.SemiquantEntry) profile.TestMapping {
    return profile.TestMapping{MatchType: "exact", Pattern: "GLU", LISTestID: "LIS-GLU", SemiquantMap: entries}
}

func TestSemiquantMergeQualifier(t *testing.T) {
    engine := New()
    val := func(v float64) *float64 { return &v }
    cases := []struct {
        name    string
        raw     string
        wantTxt string
        wantNum *float64
    }{
        {"neg two tokens", "- neg", "Negativo", nil},
        {"3+ single token", "3+ 1000 mg/dL", "1000", val(1000)},
        {"2+ single token", "2+ 500 mg/dL", "500", val(500)},
        {"numeric stays separate", "- 0.2", "", nil}, // no key for bare "-", blanked
        {"trace single token", "+-", "Trazas", val(100)},
    }
    rule := semiquantRule(map[string]profile.SemiquantEntry{
        "-neg": {Display: "Negativo"},
        "+-":   {Display: "Trazas", Value: val(100)},
        "1+":   {Display: "250", Value: val(250)},
        "2+":   {Display: "500", Value: val(500)},
        "3+":   {Display: "1000", Value: val(1000)},
    })
    prof := profile.Profile{Mapping: profile.MappingSettings{TestMappings: []profile.TestMapping{rule}}}
    for _, tc := range cases {
        t.Run(tc.name, func(t *testing.T) {
            msg := models.InstrumentMessage{Observations: []models.Observation{{ObservationID: "1", InstrumentTestCode: "GLU", ValueRaw: tc.raw, ValueText: tc.raw}}}
            out, _ := engine.Apply(msg, prof)
            obs := out.Observations[0]
            if obs.ValueText != tc.wantTxt {
                t.Fatalf("raw %q: want text %q, got %q", tc.raw, tc.wantTxt, obs.ValueText)
            }
            if tc.wantNum == nil && obs.ValueNumeric != nil {
                t.Fatalf("raw %q: want no numeric, got %v", tc.raw, *obs.ValueNumeric)
            }
            if tc.wantNum != nil {
                if obs.ValueNumeric == nil { t.Fatalf("raw %q: want numeric %v, got nil", tc.raw, *tc.wantNum) }
                if *obs.ValueNumeric != *tc.wantNum { t.Fatalf("raw %q: want numeric %v, got %v", tc.raw, *tc.wantNum, *obs.ValueNumeric) }
            }
        })
    }
}

func TestMappingEngine(t *testing.T) {
    engine := New()
    msg := models.InstrumentMessage{Observations: []models.Observation{{ObservationID: "1", InstrumentTestCode: "GLU", UnitsRaw: "mg/dl", ValueRaw: "108"}}}
    prof := profile.Profile{Mapping: profile.MappingSettings{TestMappings: []profile.TestMapping{{MatchType: "exact", Pattern: "GLU", CanonicalAssay: "Glucose", LISTestID: "LIS-GLU", NormalizedUnits: "mg/dL"}}, UnitNormalization: map[string]string{"mg/dl": "mg/dL"}}}
    out, trace := engine.Apply(msg, prof)
    if out.Observations[0].MappedLISTestID != "LIS-GLU" { t.Fatalf("expected LIS mapping") }
    if out.Observations[0].UnitsNormalized != "mg/dL" { t.Fatalf("expected normalized units") }
    if len(trace) == 0 { t.Fatalf("expected mapping trace") }
}
