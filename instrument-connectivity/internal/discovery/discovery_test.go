package discovery

import (
	"net"
	"testing"
	"time"
)

func TestNormalizePorts(t *testing.T) {
	ports := normalizePorts([]int{5000, 0, 8080, 5000, 65536, 3001})
	expected := []int{3001, 5000, 8080}
	if len(ports) != len(expected) {
		t.Fatalf("expected %d ports, got %d", len(expected), len(ports))
	}
	for i, port := range expected {
		if ports[i] != port {
			t.Fatalf("expected port %d at index %d, got %d", port, i, ports[i])
		}
	}
}

func TestEnumerateCandidatesSkipsWideSubnetsAndRespectsLimit(t *testing.T) {
	candidates := enumerateCandidates([]string{"192.168.1.0/24", "10.0.0.0/16", "bad-cidr"}, 3)
	if len(candidates) != 3 {
		t.Fatalf("expected 3 candidates from /24 with limit, got %d", len(candidates))
	}
	if candidates[0].cidr != "192.168.1.0/24" {
		t.Fatalf("unexpected cidr: %#v", candidates[0])
	}
}

func TestCandidateCountForCIDRsUsesHostLimit(t *testing.T) {
	if got := CandidateCountForCIDRs([]string{"10.0.0.0/24"}, 254); got != 254 {
		t.Fatalf("candidate count = %d, want 254", got)
	}
}

func TestParseARPNeighborDevicesIncludesReachableCandidates(t *testing.T) {
	raw := `
Interfaz: 10.0.0.10 --- 0x7
  Direccion de Internet          Direccion fisica      Tipo
  10.0.0.2              ca-a4-0d-4a-02-0a     dinamico
  10.0.0.3              10-0c-29-52-f8-0f     dinamico
  10.0.0.255            ff-ff-ff-ff-ff-ff     estatico
  192.168.100.1         44-22-7c-45-34-d1     dinamico
`
	devices := parseARPNeighborDevices(raw, []string{"10.0.0.0/24"}, time.Date(2026, 5, 29, 20, 0, 0, 0, time.UTC))
	if len(devices) != 2 {
		t.Fatalf("len(devices) = %d, want 2: %#v", len(devices), devices)
	}
	if devices[1].IP != "10.0.0.3" || devices[1].Reachability != "arp_seen" || devices[1].MAC != "10-0c-29-52-f8-0f" {
		t.Fatalf("unexpected second device: %#v", devices[1])
	}
}

func TestInferBannerProtocol(t *testing.T) {
	cases := map[string]string{
		"SSH-2.0-OpenSSH_9.0":           "ssh",
		"HTTP/1.1 200 OK":               "http",
		"MSH|^~\\&|LAB":                 "hl7_v2",
		"H|\\^&|||Analyzer":             "astm",
		"220-Welcome to instrument FTP": "ftp",
		"220 instrument ready":          "smtp_like",
		"welcome":                       "unknown_banner",
	}
	for banner, want := range cases {
		if got := inferBannerProtocol(banner); got != want {
			t.Fatalf("inferBannerProtocol(%q) = %q, want %q", banner, got, want)
		}
	}
}

func TestProbeBannerReadsImmediateBanner(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("Listen() error = %v", err)
	}
	defer listener.Close()
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		_, _ = conn.Write([]byte("SSH-2.0-TestBanner\r\n"))
	}()
	port := listener.Addr().(*net.TCPAddr).Port
	banner, protocol := probeBanner("127.0.0.1", []int{port}, 500*time.Millisecond)
	if protocol != "ssh" {
		t.Fatalf("protocol = %q, want ssh", protocol)
	}
	if banner == "" {
		t.Fatal("expected non-empty banner")
	}
}

func TestProbeHTTPBannerSendsSafeHeadRequest(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("Listen() error = %v", err)
	}
	defer listener.Close()
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		buffer := make([]byte, 256)
		n, _ := conn.Read(buffer)
		if n == 0 {
			return
		}
		_, _ = conn.Write([]byte("HTTP/1.1 200 OK\r\nServer: TestProbe\r\n\r\n"))
	}()
	banner, protocol := probeHTTPBannerAddress(listener.Addr().String(), 500*time.Millisecond)
	if protocol != "http" {
		t.Fatalf("protocol = %q, want http", protocol)
	}
	if banner != "HTTP/1.1 200 OK" {
		t.Fatalf("banner = %q, want first HTTP line", banner)
	}
}

func TestInferLikelyProtocolsAddsPortHints(t *testing.T) {
	got := inferLikelyProtocols([]int{21, 23, 2575, 8080, 9100}, "")
	want := map[string]bool{"hl7_mllp_candidate": true, "http_admin_candidate": true, "raw_socket_candidate": true, "ftp_admin_candidate": true, "telnet_admin_candidate": true}
	for _, protocol := range got {
		delete(want, protocol)
	}
	if len(want) != 0 {
		t.Fatalf("missing protocol hints: %#v from %#v", want, got)
	}
}

func TestProbeCRLFGreetingReadsLineOrientedBanner(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("Listen() error = %v", err)
	}
	defer listener.Close()
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		buffer := make([]byte, 16)
		_, _ = conn.Read(buffer)
		_, _ = conn.Write([]byte("220 FTP instrument ready\r\n"))
	}()
	banner, protocol := probeCRLFGreetingAddress(listener.Addr().String(), 500*time.Millisecond)
	if banner == "" {
		t.Fatal("expected a banner")
	}
	if protocol != "ftp" {
		t.Fatalf("protocol = %q, want ftp", protocol)
	}
}
