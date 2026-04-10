package hostexec

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/sipeed/picoclaw/pkg/config"
	"github.com/sipeed/picoclaw/pkg/fileutil"
)

type Status string
type Target string

const (
	StatusPending   Status = "pending"
	StatusApproved  Status = "approved"
	StatusDenied    Status = "denied"
	StatusRunning   Status = "running"
	StatusCompleted Status = "completed"
	StatusFailed    Status = "failed"

	TargetHost          Target = "host"
	TargetContainerRoot Target = "container_root"
)

type Request struct {
	ID             string `json:"id"`
	Target         Target `json:"target,omitempty"`
	Command        string `json:"command"`
	WorkingDir     string `json:"working_dir,omitempty"`
	Reason         string `json:"reason,omitempty"`
	Source         string `json:"source,omitempty"`
	SessionKey     string `json:"session_key,omitempty"`
	ChatID         string `json:"chat_id,omitempty"`
	Status         Status `json:"status"`
	CreatedAt      string `json:"created_at"`
	UpdatedAt      string `json:"updated_at"`
	DecisionAt     string `json:"decision_at,omitempty"`
	DecidedBy      string `json:"decided_by,omitempty"`
	TimeoutSeconds int    `json:"timeout_seconds,omitempty"`
	ExitCode       *int   `json:"exit_code,omitempty"`
	Stdout         string `json:"stdout,omitempty"`
	Stderr         string `json:"stderr,omitempty"`
	Error          string `json:"error,omitempty"`
	CompletedAt    string `json:"completed_at,omitempty"`
}

func Dir() string {
	return filepath.Join(config.GetHome(), "hostexec", "requests")
}

func PathForID(id string) string {
	return filepath.Join(Dir(), id+".json")
}

func NewID() (string, error) {
	buf := make([]byte, 8)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}

func Create(req *Request) error {
	if strings.TrimSpace(req.ID) == "" {
		id, err := NewID()
		if err != nil {
			return err
		}
		req.ID = id
	}
	now := time.Now().UTC().Format(time.RFC3339)
	req.CreatedAt = now
	req.UpdatedAt = now
	if req.Status == "" {
		req.Status = StatusPending
	}
	return save(req)
}

func Get(id string) (*Request, error) {
	data, err := os.ReadFile(PathForID(id))
	if err != nil {
		return nil, err
	}
	var req Request
	if err := json.Unmarshal(data, &req); err != nil {
		return nil, err
	}
	return &req, nil
}

func List(statuses ...Status) ([]Request, error) {
	entries, err := os.ReadDir(Dir())
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}

	var filter []Status
	if len(statuses) > 0 {
		filter = append(filter, statuses...)
	}

	requests := make([]Request, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".json") {
			continue
		}
		req, err := Get(strings.TrimSuffix(entry.Name(), ".json"))
		if err != nil {
			continue
		}
		if len(filter) > 0 && !slices.Contains(filter, req.Status) {
			continue
		}
		requests = append(requests, *req)
	}

	sort.Slice(requests, func(i, j int) bool {
		return requests[i].CreatedAt > requests[j].CreatedAt
	})
	return requests, nil
}

func Decide(id string, approved bool, decidedBy string) (*Request, error) {
	req, err := Get(id)
	if err != nil {
		return nil, err
	}
	if req.Status != StatusPending {
		return nil, fmt.Errorf("request %s is already %s", id, req.Status)
	}
	if approved {
		req.Status = StatusApproved
	} else {
		req.Status = StatusDenied
	}
	req.DecisionAt = time.Now().UTC().Format(time.RFC3339)
	req.DecidedBy = strings.TrimSpace(decidedBy)
	req.UpdatedAt = req.DecisionAt
	return req, saveAndReturn(req)
}

func MarkRunning(id string) (*Request, error) {
	req, err := Get(id)
	if err != nil {
		return nil, err
	}
	if req.Status != StatusApproved {
		return nil, fmt.Errorf("request %s is not approved", id)
	}
	req.Status = StatusRunning
	req.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	return req, saveAndReturn(req)
}

func Complete(
	id string,
	exitCode int,
	stdout string,
	stderr string,
	runErr error,
) (*Request, error) {
	req, err := Get(id)
	if err != nil {
		return nil, err
	}
	req.ExitCode = &exitCode
	req.Stdout = stdout
	req.Stderr = stderr
	req.CompletedAt = time.Now().UTC().Format(time.RFC3339)
	req.UpdatedAt = req.CompletedAt
	if runErr != nil || exitCode != 0 {
		req.Status = StatusFailed
		if runErr != nil {
			req.Error = runErr.Error()
		}
	} else {
		req.Status = StatusCompleted
		req.Error = ""
	}
	return req, saveAndReturn(req)
}

func Wait(ctx context.Context, id string, pollInterval time.Duration) (*Request, error) {
	if pollInterval <= 0 {
		pollInterval = time.Second
	}

	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		req, err := Get(id)
		if err == nil {
			switch req.Status {
			case StatusCompleted, StatusFailed, StatusDenied:
				return req, nil
			}
		}

		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-ticker.C:
		}
	}
}

func saveAndReturn(req *Request) error {
	return save(req)
}

func save(req *Request) error {
	if err := os.MkdirAll(Dir(), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(req, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return fileutil.WriteFileAtomic(PathForID(req.ID), data, 0o600)
}
