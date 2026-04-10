package tools

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/sipeed/picoclaw/pkg/hostexec"
)

const defaultHostExecTimeout = 10 * time.Minute

type HostExecTool struct{}

func NewHostExecTool() *HostExecTool {
	return &HostExecTool{}
}

func (t *HostExecTool) Name() string {
	return "host_exec"
}

func (t *HostExecTool) Description() string {
	return "Request command execution on the host machine outside Docker. Every call requires explicit Allow/Deny approval in the launcher UI before it runs."
}

func (t *HostExecTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"command": map[string]any{
				"type":        "string",
				"description": "The shell command to run on the host machine.",
			},
			"working_dir": map[string]any{
				"type":        "string",
				"description": "Optional working directory on the host machine.",
			},
			"reason": map[string]any{
				"type":        "string",
				"description": "Short reason for the host command, shown in the approval UI.",
			},
			"timeout_seconds": map[string]any{
				"type":        "number",
				"description": "Optional execution timeout once approved. Defaults to 120 seconds on the host bridge.",
			},
		},
		"required": []string{"command"},
	}
}

func (t *HostExecTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	command := strings.TrimSpace(fmt.Sprint(args["command"]))
	if command == "" {
		return ErrorResult("host_exec requires a non-empty command")
	}

	workingDir := optionalStringArg(args, "working_dir")
	reason := optionalStringArg(args, "reason")
	timeoutSeconds := 120
	if raw, ok := args["timeout_seconds"]; ok {
		if n, ok := asInt(raw); ok && n > 0 {
			timeoutSeconds = n
		}
	}

	req := &hostexec.Request{
		Target:         hostexec.TargetHost,
		Command:        command,
		WorkingDir:     workingDir,
		Reason:         reason,
		Source:         ToolChannel(ctx),
		SessionKey:     ToolChatID(ctx),
		ChatID:         ToolChatID(ctx),
		Status:         hostexec.StatusPending,
		TimeoutSeconds: timeoutSeconds,
	}
	if err := hostexec.Create(req); err != nil {
		return ErrorResult(fmt.Sprintf("failed to create host execution request: %v", err)).WithError(err)
	}

	waitCtx := ctx
	if _, hasDeadline := ctx.Deadline(); !hasDeadline {
		var cancel context.CancelFunc
		waitCtx, cancel = context.WithTimeout(ctx, defaultHostExecTimeout)
		defer cancel()
	}

	finalReq, err := hostexec.Wait(waitCtx, req.ID, time.Second)
	if err != nil {
		return ErrorResult(
			fmt.Sprintf("host execution request %s timed out waiting for approval/result: %v", req.ID, err),
		).WithError(err)
	}

	switch finalReq.Status {
	case hostexec.StatusDenied:
		return ErrorResult(
			fmt.Sprintf("Host command denied by user approval. Request ID: %s", finalReq.ID),
		)
	case hostexec.StatusCompleted:
		return SilentResult(formatHostExecResult(finalReq))
	case hostexec.StatusFailed:
		return ErrorResult(formatHostExecResult(finalReq))
	default:
		return ErrorResult(
			fmt.Sprintf("host execution request %s ended in unexpected status %s", finalReq.ID, finalReq.Status),
		)
	}
}

func formatHostExecResult(req *hostexec.Request) string {
	parts := []string{
		fmt.Sprintf("Host command request %s finished with status %s.", req.ID, req.Status),
		fmt.Sprintf("Command: %s", req.Command),
	}
	if req.Target != "" {
		parts = append(parts, fmt.Sprintf("Target: %s", req.Target))
	}
	if req.WorkingDir != "" {
		parts = append(parts, fmt.Sprintf("Working directory: %s", req.WorkingDir))
	}
	if req.ExitCode != nil {
		parts = append(parts, fmt.Sprintf("Exit code: %d", *req.ExitCode))
	}
	if req.Stdout != "" {
		parts = append(parts, "STDOUT:\n"+req.Stdout)
	}
	if req.Stderr != "" {
		parts = append(parts, "STDERR:\n"+req.Stderr)
	}
	if req.Error != "" {
		parts = append(parts, "ERROR:\n"+req.Error)
	}
	return strings.Join(parts, "\n\n")
}

func asInt(v any) (int, bool) {
	switch n := v.(type) {
	case int:
		return n, true
	case int64:
		return int(n), true
	case float64:
		return int(n), true
	default:
		return 0, false
	}
}

func optionalStringArg(args map[string]any, key string) string {
	value, ok := args[key]
	if !ok || value == nil {
		return ""
	}
	return strings.TrimSpace(fmt.Sprint(value))
}
