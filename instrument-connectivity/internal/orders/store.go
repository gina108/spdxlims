package orders

import (
	"strings"
	"sync"
	"time"
)

// PendingTest is a single test the instrument should run on a sample.
type PendingTest struct {
	TestCode string `json:"test_code"`
	TestName string `json:"test_name"`
}

// PendingOrder holds patient and test data pushed by the LIMS before a sample
// arrives, so the Go engine can answer ASTM host query (Q record) requests from
// analyzers.
type PendingOrder struct {
	SampleID    string        `json:"sample_id"`
	PatientID   string        `json:"patient_id"`
	PatientName string        `json:"patient_name"`
	DOB         string        `json:"dob"`
	Sex         string        `json:"sex"`
	DoctorName  string        `json:"doctor_name"`
	Tests       []PendingTest `json:"tests"`
	ProfileID   string        `json:"profile_id"`
	CreatedAt   time.Time     `json:"created_at"`
	ExpiresAt   time.Time     `json:"expires_at"`
}

// Store is a thread-safe in-memory map of sample_id → PendingOrder.
type Store struct {
	mu     sync.RWMutex
	orders map[string]PendingOrder
}

// NewStore returns an empty pending orders store.
func NewStore() *Store {
	return &Store{orders: make(map[string]PendingOrder)}
}

// Put adds or replaces an order. If ExpiresAt is zero it defaults to 24 hours.
func (s *Store) Put(order PendingOrder) {
	if order.ExpiresAt.IsZero() {
		order.ExpiresAt = time.Now().Add(24 * time.Hour)
	}
	if order.CreatedAt.IsZero() {
		order.CreatedAt = time.Now()
	}
	s.mu.Lock()
	s.orders[order.SampleID] = order
	s.mu.Unlock()
}

// Get returns the order for sampleID. Returns false if not found or expired.
func (s *Store) Get(sampleID string) (PendingOrder, bool) {
	s.mu.RLock()
	o, ok := s.orders[sampleID]
	s.mu.RUnlock()
	if !ok {
		return PendingOrder{}, false
	}
	if !o.ExpiresAt.IsZero() && time.Now().After(o.ExpiresAt) {
		return PendingOrder{}, false
	}
	return o, true
}

// Delete removes the order for sampleID.
func (s *Store) Delete(sampleID string) {
	s.mu.Lock()
	delete(s.orders, sampleID)
	s.mu.Unlock()
}

// List returns all non-expired orders.
func (s *Store) List() []PendingOrder {
	s.mu.RLock()
	defer s.mu.RUnlock()
	now := time.Now()
	out := make([]PendingOrder, 0, len(s.orders))
	for _, o := range s.orders {
		if o.ExpiresAt.IsZero() || now.Before(o.ExpiresAt) {
			out = append(out, o)
		}
	}
	return out
}

// FindByPatientID searches for a non-expired pending order by PatientID (MRN).
// Used for Mindray patient monitor QRY^A19 ADT lookups where the monitor queries
// by medical record number rather than by the lab sample/accession ID.
func (s *Store) FindByPatientID(patientID string) (PendingOrder, bool) {
	if patientID == "" {
		return PendingOrder{}, false
	}
	s.mu.RLock()
	defer s.mu.RUnlock()
	now := time.Now()
	pid := strings.ToLower(strings.TrimSpace(patientID))
	for _, o := range s.orders {
		if !o.ExpiresAt.IsZero() && now.After(o.ExpiresAt) {
			continue
		}
		if strings.ToLower(strings.TrimSpace(o.PatientID)) == pid {
			return o, true
		}
	}
	return PendingOrder{}, false
}

// Evict removes all expired orders.
func (s *Store) Evict() {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now()
	for k, o := range s.orders {
		if !o.ExpiresAt.IsZero() && now.After(o.ExpiresAt) {
			delete(s.orders, k)
		}
	}
}
