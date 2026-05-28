package api

type HealthResponse struct {
	OK      bool   `json:"ok"`
	Version string `json:"version"`
}

type PrinterInfo struct {
	ID         string `json:"id"`
	Model      string `json:"model"`
	Connection string `json:"connection"`
	Status     string `json:"status"`
}

type LabelSize struct {
	WidthMM  int `json:"width_mm"`
	HeightMM int `json:"height_mm"`
}

type LabelContent struct {
	BarcodeType  string   `json:"barcode_type"`
	BarcodeValue string   `json:"barcode_value"`
	HumanText    string   `json:"human_text"`
	TextLines    []string `json:"text_lines"`
	ShowBarcode bool     `json:"show_barcode"`
}

type PrintLabelRequest struct {
	PrinterID string       `json:"printer_id"`
	Label     LabelSize    `json:"label"`
	Content   LabelContent `json:"content"`
	Copies    int          `json:"copies"`
}

type PrintLabelResponse struct {
	OK    bool   `json:"ok"`
	JobID string `json:"job_id"`
}

type ErrorResponse struct {
	OK    bool   `json:"ok"`
	Error string `json:"error"`
}
