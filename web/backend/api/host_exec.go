package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/sipeed/picoclaw/pkg/hostexec"
)

type hostExecDecisionRequest struct {
	DecidedBy string `json:"decided_by"`
}

type hostExecListResponse struct {
	Requests []hostexec.Request `json:"requests"`
}

func (h *Handler) registerHostExecRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/host-exec/requests", h.handleListHostExecRequests)
	mux.HandleFunc("POST /api/host-exec/requests/{id}/approve", h.handleApproveHostExecRequest)
	mux.HandleFunc("POST /api/host-exec/requests/{id}/deny", h.handleDenyHostExecRequest)
}

func (h *Handler) handleListHostExecRequests(w http.ResponseWriter, r *http.Request) {
	requests, err := hostexec.List()
	if err != nil {
		http.Error(w, fmt.Sprintf("Failed to load host execution requests: %v", err), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(hostExecListResponse{Requests: requests})
}

func (h *Handler) handleApproveHostExecRequest(w http.ResponseWriter, r *http.Request) {
	h.handleHostExecDecision(w, r, true)
}

func (h *Handler) handleDenyHostExecRequest(w http.ResponseWriter, r *http.Request) {
	h.handleHostExecDecision(w, r, false)
}

func (h *Handler) handleHostExecDecision(w http.ResponseWriter, r *http.Request, approved bool) {
	id := strings.TrimSpace(r.PathValue("id"))
	if id == "" {
		http.Error(w, "Missing request id", http.StatusBadRequest)
		return
	}

	var req hostExecDecisionRequest
	_ = json.NewDecoder(r.Body).Decode(&req)

	updated, err := hostexec.Decide(id, approved, req.DecidedBy)
	if err != nil {
		http.Error(w, fmt.Sprintf("Failed to update request: %v", err), http.StatusBadRequest)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(updated)
}
