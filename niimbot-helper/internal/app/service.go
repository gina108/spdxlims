package app

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"

	"niimbot-helper/internal/api"
)

type Service interface {
	ListPrinters() ([]api.PrinterInfo, error)
	PrintLabel(api.PrintLabelRequest) (string, error)
}

type BridgeService struct {
	mu         sync.Mutex
	pythonArgs []string
	scriptPath string
}

type bridgePrinter struct {
	ID         string `json:"id"`
	Model      string `json:"model"`
	Connection string `json:"connection"`
	Status     string `json:"status"`
}

func NewBridgeService() *BridgeService {
	scriptPath := filepath.Join("scripts", "niimbot_bridge.py")
	if exePath, err := os.Executable(); err == nil {
		exeDir := filepath.Dir(exePath)
		candidate := filepath.Join(exeDir, "scripts", "niimbot_bridge.py")
		if _, statErr := os.Stat(candidate); statErr == nil {
			scriptPath = candidate
		}
	}
	return &BridgeService{
		pythonArgs: []string{"-3.13"},
		scriptPath: scriptPath,
	}
}

func (s *BridgeService) ListPrinters() ([]api.PrinterInfo, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	output, err := s.runBridge("list-printers", nil)
	if err != nil {
		return nil, err
	}

	var printers []bridgePrinter
	if err := json.Unmarshal(output, &printers); err != nil {
		return nil, fmt.Errorf("invalid bridge printer response: %w", err)
	}

	result := make([]api.PrinterInfo, 0, len(printers))
	for _, printer := range printers {
		result = append(result, api.PrinterInfo{
			ID:         printer.ID,
			Model:      printer.Model,
			Connection: printer.Connection,
			Status:     printer.Status,
		})
	}
	return result, nil
}

func (s *BridgeService) PrintLabel(req api.PrintLabelRequest) (string, error) {
	if strings.TrimSpace(req.PrinterID) == "" {
		return "", fmt.Errorf("printer_id is required")
	}
	if strings.TrimSpace(req.Content.BarcodeValue) == "" {
		return "", fmt.Errorf("content.barcode_value is required")
	}
	if req.Label.WidthMM <= 0 || req.Label.HeightMM <= 0 {
		return "", fmt.Errorf("label width_mm and height_mm must be greater than zero")
	}
	if req.Copies <= 0 {
		req.Copies = 1
	}

	payload, err := json.Marshal(req)
	if err != nil {
		return "", fmt.Errorf("marshal print request: %w", err)
	}
	if _, err := s.runBridge("print-label", payload); err != nil {
		return "", err
	}
	return nextJobID(), nil
}

func (s *BridgeService) runBridge(command string, input []byte) ([]byte, error) {
	args := append([]string{}, s.pythonArgs...)
	args = append(args, s.scriptPath, command)
	cmd := exec.Command("py", args...)
	cmd.Dir = "."
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if len(input) > 0 {
		cmd.Stdin = bytes.NewReader(input)
	}
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		message := strings.TrimSpace(stderr.String())
		if message == "" {
			message = err.Error()
		}
		return nil, fmt.Errorf("bridge command failed: %s", message)
	}
	return bytes.TrimSpace(stdout.Bytes()), nil
}

func nextJobID() string {
	buf := make([]byte, 6)
	if _, err := rand.Read(buf); err != nil {
		return "job_fallback"
	}
	return "job_" + hex.EncodeToString(buf)
}
