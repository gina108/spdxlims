package discovery

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"go.bug.st/serial/enumerator"

	"instrument-connectivity/internal/models"
)

type Service struct{}

type NetworkScanOptions struct {
	CIDRs       []string
	Ports       []int
	Timeout     time.Duration
	Concurrency int
	HostLimit   int
}

type NetworkScanResult struct {
	Devices        []models.NetworkDevice
	CIDRs          []string
	Ports          []int
	CandidateHosts int
	HostLimit      int
	Duration       time.Duration
}

func New() *Service { return &Service{} }

func (s *Service) ScanSerialPorts() ([]models.DeviceFingerprint, error) {
	ports, err := enumerator.GetDetailedPortsList()
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	out := make([]models.DeviceFingerprint, 0, len(ports))
	for _, port := range ports {
		fp := models.DeviceFingerprint{PortName: port.Name, PortPath: port.Name, FirstSeen: now, LastSeen: now, StabilityScore: stabilityScore(port.Name, port.IsUSB)}
		if port.IsUSB {
			fp.USBVID = port.VID
			fp.USBPID = port.PID
			fp.SerialNumber = port.SerialNumber
			fp.Product = port.Product
		}
		out = append(out, fp)
	}
	return out, nil
}

func (s *Service) ScanNetwork(opts NetworkScanOptions) (NetworkScanResult, error) {
	started := time.Now()
	cidrs := opts.CIDRs
	if len(cidrs) == 0 {
		detected, err := localPrivateCIDRs()
		if err != nil {
			return NetworkScanResult{}, err
		}
		cidrs = detected
	}
	ports := normalizePorts(opts.Ports)
	if len(ports) == 0 {
		ports = []int{5000, 3001, 4000, 8080, 9100}
	}
	timeout := opts.Timeout
	if timeout <= 0 {
		timeout = 250 * time.Millisecond
	}
	concurrency := opts.Concurrency
	if concurrency <= 0 {
		concurrency = 24
	}
	hostLimit := opts.HostLimit
	if hostLimit <= 0 {
		hostLimit = 64
	}

	candidates := enumerateCandidates(cidrs, hostLimit)
	result := NetworkScanResult{CIDRs: cidrs, Ports: ports, CandidateHosts: len(candidates), HostLimit: hostLimit}
	if len(candidates) == 0 {
		result.Devices = []models.NetworkDevice{}
		result.Duration = time.Since(started)
		return result, nil
	}

	jobs := make(chan networkCandidate)
	results := make(chan models.NetworkDevice, len(candidates))
	var wg sync.WaitGroup

	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for candidate := range jobs {
				if device, ok := probeCandidate(candidate, ports, timeout); ok {
					results <- device
				}
			}
		}()
	}

	for _, candidate := range candidates {
		jobs <- candidate
	}
	close(jobs)
	wg.Wait()
	close(results)

	devices := make([]models.NetworkDevice, 0, len(results))
	seen := map[string]struct{}{}
	for device := range results {
		if _, exists := seen[device.DeviceID]; exists {
			continue
		}
		seen[device.DeviceID] = struct{}{}
		devices = append(devices, device)
	}
	for _, device := range arpNeighborDevices(cidrs) {
		if _, exists := seen[device.DeviceID]; exists {
			continue
		}
		seen[device.DeviceID] = struct{}{}
		devices = append(devices, device)
	}
	sort.Slice(devices, func(i, j int) bool {
		if devices[i].IP == devices[j].IP {
			return len(devices[i].OpenPorts) > len(devices[j].OpenPorts)
		}
		return devices[i].IP < devices[j].IP
	})
	result.Devices = devices
	result.Duration = time.Since(started)
	return result, nil
}

func CandidateCountForCIDRs(cidrs []string, hostLimit int) int {
	return len(enumerateCandidates(cidrs, hostLimit))
}

func arpNeighborDevices(cidrs []string) []models.NetworkDevice {
	raw, err := exec.Command("arp", "-a").Output()
	if err != nil {
		return nil
	}
	return parseARPNeighborDevices(string(raw), cidrs, time.Now().UTC())
}

func parseARPNeighborDevices(raw string, cidrs []string, now time.Time) []models.NetworkDevice {
	nets := parseCIDRNets(cidrs)
	if len(nets) == 0 {
		return nil
	}
	devices := []models.NetworkDevice{}
	seen := map[string]struct{}{}
	for _, line := range strings.Split(raw, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 3 {
			continue
		}
		ip := net.ParseIP(fields[0])
		if ip == nil || ip.To4() == nil || !cidrContains(nets, ip) {
			continue
		}
		mac := strings.TrimSpace(fields[1])
		entryType := strings.ToLower(strings.TrimSpace(fields[2]))
		if mac == "" || mac == "ff-ff-ff-ff-ff-ff" || entryType == "estático" || entryType == "estatico" || entryType == "static" || strings.HasPrefix(ip.String(), "224.") || ip.String() == "255.255.255.255" {
			continue
		}
		deviceID := "net:" + ip.String()
		if _, exists := seen[deviceID]; exists {
			continue
		}
		seen[deviceID] = struct{}{}
		cidr := matchingCIDR(nets, ip)
		devices = append(devices, models.NetworkDevice{
			DeviceID:        deviceID,
			Host:            reverseLookup(ip.String()),
			IP:              ip.String(),
			CIDR:            cidr,
			InterfaceName:   interfaceForCIDR(cidr),
			MAC:             mac,
			Reachability:    "arp_seen",
			FirstSeen:       now,
			LastSeen:        now,
			SeenCount:       1,
			LastSeenStatus:  "online",
			StabilityScore:  0.42,
			LikelyProtocols: []string{"reachable_network_candidate"},
			Metadata:        map[string]any{"detection": "arp_cache", "probe_strategy": "arp_neighbor"},
		})
	}
	return devices
}

func parseCIDRNets(cidrs []string) []*net.IPNet {
	nets := []*net.IPNet{}
	for _, rawCIDR := range cidrs {
		_, ipNet, err := net.ParseCIDR(strings.TrimSpace(rawCIDR))
		if err == nil && ipNet != nil && ipNet.IP.To4() != nil {
			nets = append(nets, ipNet)
		}
	}
	return nets
}

func cidrContains(nets []*net.IPNet, ip net.IP) bool {
	return matchingCIDR(nets, ip) != ""
}

func matchingCIDR(nets []*net.IPNet, ip net.IP) string {
	for _, ipNet := range nets {
		if ipNet.Contains(ip) {
			return ipNet.String()
		}
	}
	return ""
}

func (s *Service) ProbeTCP(address string, timeout time.Duration) bool {
	conn, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

func (s *Service) ScanWatchedDirectory(path string) (bool, error) {
	info, err := os.Stat(path)
	if err != nil {
		return false, err
	}
	return info.IsDir(), nil
}

type networkCandidate struct {
	ip            string
	cidr          string
	interfaceName string
}

type probeOutcome struct {
	banner          string
	bannerProtocol  string
	likelyProtocols []string
	strategy        string
}

func probeCandidate(candidate networkCandidate, ports []int, timeout time.Duration) (models.NetworkDevice, bool) {
	now := time.Now().UTC()
	openPorts := make([]int, 0, len(ports))
	var bestLatency time.Duration
	for _, port := range ports {
		address := net.JoinHostPort(candidate.ip, fmt.Sprintf("%d", port))
		started := time.Now()
		conn, err := net.DialTimeout("tcp", address, timeout)
		if err != nil {
			continue
		}
		latency := time.Since(started)
		if bestLatency == 0 || latency < bestLatency {
			bestLatency = latency
		}
		openPorts = append(openPorts, port)
		_ = conn.Close()
	}
	if len(openPorts) == 0 {
		return models.NetworkDevice{}, false
	}
	outcome := probeService(candidate.ip, openPorts, timeout)
	return models.NetworkDevice{
		DeviceID:        fmt.Sprintf("net:%s", candidate.ip),
		Host:            reverseLookup(candidate.ip),
		IP:              candidate.ip,
		CIDR:            candidate.cidr,
		InterfaceName:   candidate.interfaceName,
		OpenPorts:       openPorts,
		Reachability:    "tcp_open",
		ProbeLatencyMS:  bestLatency.Milliseconds(),
		Banner:          outcome.banner,
		BannerProtocol:  outcome.bannerProtocol,
		LikelyProtocols: outcome.likelyProtocols,
		FirstSeen:       now,
		LastSeen:        now,
		SeenCount:       1,
		LastSeenStatus:  "online",
		StabilityScore:  networkStabilityScore(openPorts, 1),
		Metadata:        map[string]any{"detection": "tcp_port_probe", "probe_strategy": outcome.strategy},
	}, true
}

func localPrivateCIDRs() ([]string, error) {
	interfaces, err := net.Interfaces()
	if err != nil {
		return nil, err
	}
	cidrs := []string{}
	seen := map[string]struct{}{}
	for _, iface := range interfaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, addr := range addrs {
			ip, ipNet, err := net.ParseCIDR(addr.String())
			if err != nil || ip == nil || ip.To4() == nil || !ip.IsPrivate() {
				continue
			}
			cidr := ipNet.String()
			if _, exists := seen[cidr]; exists {
				continue
			}
			seen[cidr] = struct{}{}
			cidrs = append(cidrs, cidr)
		}
	}
	sort.Strings(cidrs)
	return cidrs, nil
}

func enumerateCandidates(cidrs []string, hostLimit int) []networkCandidate {
	candidates := []networkCandidate{}
	for _, rawCIDR := range cidrs {
		_, ipNet, err := net.ParseCIDR(strings.TrimSpace(rawCIDR))
		if err != nil || ipNet == nil {
			continue
		}
		networkIP := ipNet.IP.To4()
		if networkIP == nil {
			continue
		}
		maskSize, bits := ipNet.Mask.Size()
		if bits != 32 || maskSize < 24 {
			continue
		}
		current := append(net.IP(nil), networkIP...)
		count := 0
		incrementIPv4(current)
		for ipNet.Contains(current) {
			candidateIP := current.String()
			if candidateIP != networkIP.String() {
				candidates = append(candidates, networkCandidate{ip: candidateIP, cidr: ipNet.String(), interfaceName: interfaceForCIDR(ipNet.String())})
				count++
			}
			if count >= hostLimit {
				break
			}
			incrementIPv4(current)
		}
	}
	return candidates
}

func interfaceForCIDR(targetCIDR string) string {
	interfaces, err := net.Interfaces()
	if err != nil {
		return ""
	}
	for _, iface := range interfaces {
		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}
		for _, addr := range addrs {
			if addr.String() == targetCIDR {
				return iface.Name
			}
		}
	}
	return ""
}

func incrementIPv4(ip net.IP) {
	for i := len(ip) - 1; i >= 0; i-- {
		ip[i]++
		if ip[i] != 0 {
			return
		}
	}
}

func normalizePorts(ports []int) []int {
	seen := map[int]struct{}{}
	cleaned := []int{}
	for _, port := range ports {
		if port <= 0 || port > 65535 {
			continue
		}
		if _, exists := seen[port]; exists {
			continue
		}
		seen[port] = struct{}{}
		cleaned = append(cleaned, port)
	}
	sort.Ints(cleaned)
	return cleaned
}

func reverseLookup(ip string) string {
	names, err := net.LookupAddr(ip)
	if err != nil || len(names) == 0 {
		return ""
	}
	return strings.TrimSuffix(names[0], ".")
}

func probeService(ip string, openPorts []int, timeout time.Duration) probeOutcome {
	likely := inferLikelyProtocols(openPorts, "")
	banner, bannerProtocol := probeBanner(ip, openPorts, timeout)
	if banner != "" {
		return probeOutcome{
			banner:          banner,
			bannerProtocol:  bannerProtocol,
			likelyProtocols: inferLikelyProtocols(openPorts, bannerProtocol),
			strategy:        "passive_banner",
		}
	}
	banner, bannerProtocol = probeHTTPBanner(ip, openPorts, timeout)
	if banner != "" {
		return probeOutcome{
			banner:          banner,
			bannerProtocol:  bannerProtocol,
			likelyProtocols: inferLikelyProtocols(openPorts, bannerProtocol),
			strategy:        "http_head",
		}
	}
	banner, bannerProtocol = probeCRLFGreeting(ip, openPorts, timeout)
	if banner != "" {
		return probeOutcome{
			banner:          banner,
			bannerProtocol:  bannerProtocol,
			likelyProtocols: inferLikelyProtocols(openPorts, bannerProtocol),
			strategy:        "crlf_probe",
		}
	}
	return probeOutcome{likelyProtocols: likely, strategy: "port_hints"}
}

func stabilityScore(portName string, usb bool) float64 {
	score := 0.45
	if usb {
		score += 0.25
	}
	if filepath.Base(portName) != "" {
		score += 0.15
	}
	return score
}

func probeBanner(ip string, openPorts []int, timeout time.Duration) (string, string) {
	for _, port := range openPorts {
		address := net.JoinHostPort(ip, fmt.Sprintf("%d", port))
		conn, err := net.DialTimeout("tcp", address, timeout)
		if err != nil {
			continue
		}
		_ = conn.SetReadDeadline(time.Now().Add(timeout))
		buffer := make([]byte, 256)
		n, err := conn.Read(buffer)
		_ = conn.Close()
		if err != nil || n <= 0 {
			continue
		}
		banner := strings.TrimSpace(string(buffer[:n]))
		if banner == "" {
			continue
		}
		return banner, inferBannerProtocol(banner)
	}
	return "", ""
}

func probeHTTPBanner(ip string, openPorts []int, timeout time.Duration) (string, string) {
	for _, port := range openPorts {
		if !isHTTPProbePort(port) {
			continue
		}
		banner, protocol := probeHTTPBannerAddress(net.JoinHostPort(ip, fmt.Sprintf("%d", port)), timeout)
		if banner == "" {
			continue
		}
		return banner, protocol
	}
	return "", ""
}

func probeHTTPBannerAddress(address string, timeout time.Duration) (string, string) {
	conn, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		return "", ""
	}
	_ = conn.SetDeadline(time.Now().Add(timeout))
	_, _ = conn.Write([]byte("HEAD / HTTP/1.0\r\nHost: instrument-probe\r\n\r\n"))
	buffer := make([]byte, 256)
	n, err := conn.Read(buffer)
	_ = conn.Close()
	if err != nil || n <= 0 {
		return "", ""
	}
	banner := strings.TrimSpace(string(buffer[:n]))
	if banner == "" {
		return "", ""
	}
	return firstBannerLine(banner), inferBannerProtocol(banner)
}

func isHTTPProbePort(port int) bool {
	switch port {
	case 80, 8080, 8000, 8888, 8081:
		return true
	default:
		return false
	}
}

func firstBannerLine(banner string) string {
	banner = strings.ReplaceAll(banner, "\r", "\n")
	parts := strings.Split(banner, "\n")
	for _, part := range parts {
		trimmed := strings.TrimSpace(part)
		if trimmed != "" {
			return trimmed
		}
	}
	return ""
}

func probeCRLFGreeting(ip string, openPorts []int, timeout time.Duration) (string, string) {
	for _, port := range openPorts {
		if !isCRLFProbePort(port) {
			continue
		}
		banner, protocol := probeCRLFGreetingAddress(net.JoinHostPort(ip, fmt.Sprintf("%d", port)), timeout)
		if banner != "" {
			return banner, protocol
		}
	}
	return "", ""
}

func probeCRLFGreetingAddress(address string, timeout time.Duration) (string, string) {
	conn, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		return "", ""
	}
	_ = conn.SetDeadline(time.Now().Add(timeout))
	_, _ = conn.Write([]byte("\r\n"))
	buffer := make([]byte, 256)
	n, err := conn.Read(buffer)
	_ = conn.Close()
	if err != nil || n <= 0 {
		return "", ""
	}
	banner := strings.TrimSpace(string(buffer[:n]))
	if banner == "" {
		return "", ""
	}
	return firstBannerLine(banner), inferBannerProtocol(banner)
}

func isCRLFProbePort(port int) bool {
	switch port {
	case 21, 23:
		return true
	default:
		return false
	}
}

func inferBannerProtocol(banner string) string {
	upper := strings.ToUpper(strings.TrimSpace(banner))
	switch {
	case strings.Contains(upper, "MSH|"):
		return "hl7_v2"
	case strings.HasPrefix(upper, "H|") || strings.Contains(upper, "\nP|") || strings.Contains(upper, "\nO|"):
		return "astm"
	case strings.Contains(upper, "FTP"):
		return "ftp"
	case strings.HasPrefix(upper, "SSH-"):
		return "ssh"
	case strings.HasPrefix(upper, "HTTP/"):
		return "http"
	case strings.HasPrefix(upper, "220 "):
		return "smtp_like"
	case strings.Contains(upper, "TELNET"):
		return "telnet_like"
	default:
		return "unknown_banner"
	}
}

func inferLikelyProtocols(openPorts []int, bannerProtocol string) []string {
	seen := map[string]struct{}{}
	if bannerProtocol != "" && bannerProtocol != "unknown_banner" {
		seen[bannerProtocol] = struct{}{}
	}
	for _, port := range openPorts {
		switch port {
		case 2575, 3001, 4000, 5000:
			seen["hl7_mllp_candidate"] = struct{}{}
		case 80, 8000, 8080, 8081, 8888:
			seen["http_admin_candidate"] = struct{}{}
		case 9100:
			seen["raw_socket_candidate"] = struct{}{}
		case 21:
			seen["ftp_admin_candidate"] = struct{}{}
		case 23:
			seen["telnet_admin_candidate"] = struct{}{}
		}
	}
	out := make([]string, 0, len(seen))
	for protocol := range seen {
		out = append(out, protocol)
	}
	sort.Strings(out)
	return out
}

func networkStabilityScore(openPorts []int, seenCount int) float64 {
	score := 0.35
	if len(openPorts) > 0 {
		score += 0.25
	}
	if len(openPorts) > 1 {
		score += 0.1
	}
	if seenCount > 1 {
		score += 0.05
	}
	if seenCount > 5 {
		score += 0.1
	}
	if score > 1 {
		return 1
	}
	return score
}
