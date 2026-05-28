package mapping

import (
    "testing"

    "instrument-connectivity/internal/models"
    "instrument-connectivity/internal/profile"
)

func TestMappingEngine(t *testing.T) {
    engine := New()
    msg := models.InstrumentMessage{Observations: []models.Observation{{ObservationID: "1", InstrumentTestCode: "GLU", UnitsRaw: "mg/dl", ValueRaw: "108"}}}
    prof := profile.Profile{Mapping: profile.MappingSettings{TestMappings: []profile.TestMapping{{MatchType: "exact", Pattern: "GLU", CanonicalAssay: "Glucose", LISTestID: "LIS-GLU", NormalizedUnits: "mg/dL"}}, UnitNormalization: map[string]string{"mg/dl": "mg/dL"}}}
    out, trace := engine.Apply(msg, prof)
    if out.Observations[0].MappedLISTestID != "LIS-GLU" { t.Fatalf("expected LIS mapping") }
    if out.Observations[0].UnitsNormalized != "mg/dL" { t.Fatalf("expected normalized units") }
    if len(trace) == 0 { t.Fatalf("expected mapping trace") }
}
