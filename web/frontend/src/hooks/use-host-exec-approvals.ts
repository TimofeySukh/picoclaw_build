import { useEffect, useState } from "react"

import {
  approveHostExecRequest,
  denyHostExecRequest,
  listHostExecRequests,
  type HostExecRequest,
} from "@/api/host-exec"

const POLL_MS = 2000

export function useHostExecApprovals() {
  const [requests, setRequests] = useState<HostExecRequest[]>([])
  const [loading, setLoading] = useState(false)

  const refresh = async () => {
    try {
      setLoading(true)
      const next = await listHostExecRequests()
      setRequests(next)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    const handle = window.setInterval(() => {
      void refresh()
    }, POLL_MS)
    return () => window.clearInterval(handle)
  }, [])

  const approve = async (id: string) => {
    await approveHostExecRequest(id)
    await refresh()
  }

  const deny = async (id: string) => {
    await denyHostExecRequest(id)
    await refresh()
  }

  return {
    requests,
    pendingRequests: requests.filter((request) => request.status === "pending"),
    loading,
    refresh,
    approve,
    deny,
  }
}
