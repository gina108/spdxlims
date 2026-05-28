package api

import (
	"encoding/json"
	"net/http"
	"strings"
)

type Service interface {
	ListPrinters() ([]PrinterInfo, error)
	PrintLabel(PrintLabelRequest) (string, error)
}

type Server struct {
	svc Service
}

func New(svc Service) *Server {
	return &Server{svc: svc}
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.health)
	mux.HandleFunc("/api/v1/health", s.health)
	mux.HandleFunc("/printers", s.printers)
	mux.HandleFunc("/api/v1/printers", s.printers)
	mux.HandleFunc("/print/niimbot-label", s.printNIIMBOTLabel)
	mux.HandleFunc("/api/v1/print/niimbot-label", s.printNIIMBOTLabel)
	return mux
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	writeJSON(w, http.StatusOK, HealthResponse{OK: true, Version: "0.1.0"})
}

func (s *Server) printers(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	printers, err := s.svc.ListPrinters()
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, printers)
}

func (s *Server) printNIIMBOTLabel(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req PrintLabelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid json body")
		return
	}
	req.PrinterID = strings.TrimSpace(req.PrinterID)
	req.Content.BarcodeType = strings.TrimSpace(req.Content.BarcodeType)
	req.Content.BarcodeValue = strings.TrimSpace(req.Content.BarcodeValue)
	req.Content.HumanText = strings.TrimSpace(req.Content.HumanText)
	jobID, err := s.svc.PrintLabel(req)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, PrintLabelResponse{OK: true, JobID: jobID})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, ErrorResponse{OK: false, Error: message})
}
