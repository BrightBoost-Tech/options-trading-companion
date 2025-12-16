import React from 'react';
import { Badge } from "@/components/ui/badge";
import { JobRun } from "@/lib/types";

interface JobStatusBadgeProps {
  status: JobRun['status'];
}

export function JobStatusBadge({ status }: JobStatusBadgeProps) {
  let variant: "default" | "secondary" | "destructive" | "outline" = "default";
  let className = "";

  switch (status) {
    case 'completed':
      variant = "default"; // Usually green/primary
      className = "bg-green-100 text-green-800 hover:bg-green-100";
      break;
    case 'processing':
      variant = "secondary";
      className = "bg-blue-100 text-blue-800 hover:bg-blue-100 animate-pulse";
      break;
    case 'pending':
      variant = "outline";
      className = "text-gray-500 border-gray-300";
      break;
    case 'failed':
      variant = "destructive";
      break;
    case 'dead_lettered':
    case 'failed_retryable':
      variant = "destructive";
      className = "bg-red-900 text-red-100 hover:bg-red-900";
      break;
    default:
      variant = "outline";
  }

  return (
    <Badge variant={variant} className={className}>
      {status}
    </Badge>
  );
}
