import { launcherFetch } from "@/api/http"

export type HostExecRequest = {
  id: string
  command: string
  working_dir?: string
  reason?: string
  source?: string
  status: string
  created_at: string
  updated_at: string
  decision_at?: string
  decided_by?: string
  completed_at?: string
  stdout?: string
  stderr?: string
  error?: string
  exit_code?: number
}

export async function listHostExecRequests(): Promise<HostExecRequest[]> {
  const res = await launcherFetch("/api/host-exec/requests")
  if (!res.ok) {
    throw new Error("Failed to load host execution requests")
  }
  const data = (await res.json()) as { requests?: HostExecRequest[] }
  return data.requests ?? []
}

async function decideHostExecRequest(id: string, action: "approve" | "deny") {
  const res = await launcherFetch(`/api/host-exec/requests/${id}/${action}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
    },
    body: JSON.stringify({ decided_by: "launcher-ui" }),
  })
  if (!res.ok) {
    throw new Error(`Failed to ${action} host execution request`)
  }
}

export async function approveHostExecRequest(id: string) {
  await decideHostExecRequest(id, "approve")
}

export async function denyHostExecRequest(id: string) {
  await decideHostExecRequest(id, "deny")
}
