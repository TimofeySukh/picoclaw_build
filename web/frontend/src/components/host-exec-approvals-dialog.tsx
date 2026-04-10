import { IconShieldCheck } from "@tabler/icons-react"
import { useState } from "react"

import { useHostExecApprovals } from "@/hooks/use-host-exec-approvals"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"

export function HostExecApprovalsDialog() {
  const [open, setOpen] = useState(false)
  const { pendingRequests, approve, deny, loading } = useHostExecApprovals()

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant={pendingRequests.length > 0 ? "default" : "outline"}
          size="sm"
          className="h-8 gap-2"
        >
          <IconShieldCheck className="size-4" />
          <span className="text-xs font-semibold">
            Host Approval{pendingRequests.length > 0 ? ` (${pendingRequests.length})` : ""}
          </span>
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Host Command Approval</DialogTitle>
          <DialogDescription>
            Commands that leave Docker must be approved here before the host bridge runs them.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-3 overflow-y-auto">
          {pendingRequests.length === 0 ? (
            <div className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
              {loading ? "Checking for pending approvals..." : "No pending host command approvals."}
            </div>
          ) : (
            pendingRequests.map((request) => (
              <div key={request.id} className="rounded-xl border p-4">
                <div className="mb-2 text-xs text-muted-foreground">
                  Request {request.id}
                </div>
                <pre className="bg-muted overflow-x-auto rounded-md p-3 text-xs whitespace-pre-wrap">
                  {request.command}
                </pre>
                {request.working_dir && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    Working directory: {request.working_dir}
                  </div>
                )}
                {request.reason && (
                  <div className="mt-2 text-sm">{request.reason}</div>
                )}
                <div className="mt-4 flex gap-2">
                  <Button size="sm" onClick={() => void approve(request.id)}>
                    Allow
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={() => void deny(request.id)}
                  >
                    Deny
                  </Button>
                </div>
              </div>
            ))
          )}
        </div>

        <DialogFooter showCloseButton />
      </DialogContent>
    </Dialog>
  )
}
