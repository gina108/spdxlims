package buildinfo

import (
	"fmt"
	"runtime/debug"
	"strings"
)

var (
	Version   = "dev"
	Commit    = "unknown"
	BuildTime = "unknown"
)

type Info struct {
	Version   string `json:"version"`
	Commit    string `json:"commit"`
	BuildTime string `json:"build_time"`
	GoVersion string `json:"go_version,omitempty"`
}

func Current() Info {
	info := Info{
		Version:   valueOrDefault(Version, "dev"),
		Commit:    valueOrDefault(Commit, "unknown"),
		BuildTime: valueOrDefault(BuildTime, "unknown"),
	}
	if build, ok := debug.ReadBuildInfo(); ok {
		info.GoVersion = build.GoVersion
	}
	return info
}

func Summary() string {
	info := Current()
	parts := []string{info.Version}
	if info.Commit != "unknown" {
		parts = append(parts, info.Commit)
	}
	if info.BuildTime != "unknown" {
		parts = append(parts, info.BuildTime)
	}
	return strings.Join(parts, " | ")
}

func (i Info) String() string {
	parts := []string{fmt.Sprintf("version=%s", i.Version), fmt.Sprintf("commit=%s", i.Commit), fmt.Sprintf("build_time=%s", i.BuildTime)}
	if i.GoVersion != "" {
		parts = append(parts, fmt.Sprintf("go=%s", i.GoVersion))
	}
	return strings.Join(parts, " ")
}

func valueOrDefault(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}
