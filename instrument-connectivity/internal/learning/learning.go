package learning

import (
	"sort"
	"strings"
)

type Suggestion struct {
	DelimiterCandidates []string         `json:"delimiter_candidates"`
	RepeatingColumns    []int            `json:"repeating_columns"`
	FieldSuggestions    map[string][]int `json:"field_suggestions"`
	Notes               []string         `json:"notes"`
}

type Engine struct{}

func New() *Engine { return &Engine{} }

func (e *Engine) Suggest(text string) Suggestion {
	lines := []string{}
	for _, line := range strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			lines = append(lines, line)
		}
	}

	candidates := []string{"|", ",", ";", "\t", "^"}
	scored := map[string]int{}
	for _, delim := range candidates {
		for _, line := range lines {
			scored[delim] += strings.Count(line, delim)
		}
	}
	sort.Slice(candidates, func(i, j int) bool {
		return scored[candidates[i]] > scored[candidates[j]]
	})

	fieldSuggestions := map[string][]int{}
	if len(lines) > 0 {
		parts := splitByCandidate(lines[0], candidates)
		for idx, value := range parts {
			upper := strings.ToUpper(strings.TrimSpace(value))
			switch {
			case strings.Contains(upper, "SAMPLE") || strings.Contains(upper, "SPECIMEN"):
				fieldSuggestions["sample_id"] = append(fieldSuggestions["sample_id"], idx)
			case strings.Contains(upper, "TEST") || strings.Contains(upper, "ANALYTE") || strings.Contains(upper, "CODE"):
				fieldSuggestions["test_code"] = append(fieldSuggestions["test_code"], idx)
			case strings.Contains(upper, "VALUE") || strings.Contains(upper, "RESULT"):
				fieldSuggestions["result_value"] = append(fieldSuggestions["result_value"], idx)
			case strings.Contains(upper, "UNIT"):
				fieldSuggestions["units"] = append(fieldSuggestions["units"], idx)
			case strings.Contains(upper, "TIME") || strings.Contains(upper, "DATE"):
				fieldSuggestions["timestamp"] = append(fieldSuggestions["timestamp"], idx)
			}
		}
	}

	notes := []string{"rule-based learning mode only; confirm suggestions before use"}
	if len(lines) >= 2 {
		notes = append(notes, "multiple lines captured; repeating structure available for manual confirmation")
	}

	return Suggestion{
		DelimiterCandidates: candidates,
		RepeatingColumns:    []int{0, 1, 2},
		FieldSuggestions:    fieldSuggestions,
		Notes:               notes,
	}
}

func splitByCandidate(line string, candidates []string) []string {
	for _, delim := range candidates {
		if strings.Contains(line, delim) {
			return strings.Split(line, delim)
		}
	}
	return []string{line}
}
