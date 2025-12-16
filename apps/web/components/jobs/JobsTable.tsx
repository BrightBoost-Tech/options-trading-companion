import React from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { JobRun } from "@/lib/types";
import { JobStatusBadge } from "./JobStatusBadge";
import { useRouter } from "next/navigation";

interface JobsTableProps {
  jobs: JobRun[];
  isLoading?: boolean;
}

export function JobsTable({ jobs, isLoading }: JobsTableProps) {
  const router = useRouter();

  if (isLoading) {
    return <div className="p-4 text-center text-muted-foreground">Loading jobs...</div>;
  }

  if (jobs.length === 0) {
    return <div className="p-4 text-center text-muted-foreground">No jobs found.</div>;
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Created At</TableHead>
            <TableHead>Job Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Attempts</TableHead>
            <TableHead>Duration (ms)</TableHead>
            <TableHead className="hidden md:table-cell">Idempotency Key</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.map((job) => (
            <TableRow
              key={job.id}
              className="cursor-pointer"
              onClick={() => router.push(`/jobs/${job.id}`)}
            >
              <TableCell className="font-medium whitespace-nowrap">
                {new Date(job.created_at).toLocaleString()}
              </TableCell>
              <TableCell>{job.job_name}</TableCell>
              <TableCell>
                <JobStatusBadge status={job.status} />
              </TableCell>
              <TableCell>
                {job.attempt_count} / {job.max_attempts}
              </TableCell>
              <TableCell>
                {job.duration_ms !== undefined && job.duration_ms !== null ? `${job.duration_ms}ms` : '-'}
              </TableCell>
              <TableCell className="hidden md:table-cell font-mono text-xs text-muted-foreground">
                {job.idempotency_key || '-'}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
