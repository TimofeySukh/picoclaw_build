package tools

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/sipeed/picoclaw/pkg/hostexec"
)

const defaultRootExecTimeout = 10 * time.Minute

type RootExecTool struct{}

func NewRootExecTool() *RootExecTool {
	return &RootExecTool{}
}

func (t *RootExecTool) Name() string {
	return "root_exec"
}

func (t *RootExecTool) Description() string {
	return "Request root command execution inside the Docker container. Every call requires explicit Allow/Deny approval before it runs."
}

func (t *RootExecTool) Parameters() map[string]any {
	return map[string]any{
		"type": "object",
		"properties": map[string]any{
			"command": map[string]any{
				"type":        "string",
				"description": "The shell command to run as root inside the Docker container.",
			},
			"working_dir": map[string]any{
				"type":        "string",
				"description": "Optional working directory inside the Docker container.",
			},
			"reason": map[string]any{
				"type":        "string",
				"description": "Short reason for the root command, shown in the approval UI.",
			},
			"timeout_seconds": map[string]any{
				"type":        "number",
				"description": "Optional execution timeout once approved. Defaults to 120 seconds.",
			},
		},
		"required": []string{"command"},
	}
}

func (t *RootExecTool) Execute(ctx context.Context, args map[string]any) *ToolResult {
	command := strings.TrimSpace(fmt.Sprint(args["command"]))
	if command == "" {
		return ErrorResult("root_exec requires a non-empty command")
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
		Target:         hostexec.TargetContainerRoot,
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
		return ErrorResult(fmt.Sprintf("failed to create root execution request: %v", err)).WithError(err)
	}

	waitCtx := ctx
	if _, hasDeadline := ctx.Deadline(); !hasDeadline {
		var cancel context.CancelFunc
		waitCtx, cancel = context.WithTimeout(ctx, defaultRootExecTimeout)
		defer cancel()
	}

	finalReq, err := hostexec.Wait(waitCtx, req.ID, time.Second)
	if err != nil {
		return ErrorResult(
			fmt.Sprintf("root execution request %s timed out waiting for approval/result: %v", req.ID, err),
		).WithError(err)
	}

	switch finalReq.Status {
	case hostexec.StatusDenied:
		return ErrorResult(
			fmt.Sprintf("Root command denied by user approval. Request ID: %s", finalReq.ID),
		)
	case hostexec.StatusCompleted:
		return SilentResult(formatHostExecResult(finalReq))
	case hostexec.StatusFailed:
		return ErrorResult(formatHostExecResult(finalReq))
	default:
		return ErrorResult(
			fmt.Sprintf("root execution request %s ended in unexpected status %s", finalReq.ID, finalReq.Status),
		)
	}
}
