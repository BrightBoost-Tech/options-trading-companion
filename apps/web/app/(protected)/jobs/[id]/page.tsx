'use client';

import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { JobRun } from '@/lib/types';
import { fetchWithAuth } from '@/lib/api';
import { JobStatusBadge } from '@/components/jobs/JobStatusBadge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ArrowLeft, RefreshCw } from 'lucide-react';

export default function JobDetailsPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [job, setJob] = useState<JobRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryMessage, setRetryMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);

  const loadJob = async () => {
    setLoading(true);
    try {
      const data = await fetchWithAuth<JobRun>(`/jobs/runs/${id}`);
      setJob(data);
      setError(null);
    } catch (err) {
      console.error("Failed to load job details:", err);
      setError("Failed to load job details.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (id) {
      loadJob();
    }
  }, [id]);

  const handleRetry = async () => {
    if (!job) return;

    setRetrying(true);
    setRetryMessage(null);

    try {
      await fetchWithAuth(`/jobs/runs/${job.id}/retry`, {
        method: 'POST',
      });
      setRetryMessage({ type: 'success', text: 'Retry initiated successfully.' });
      // Refresh job details after a short delay to see updated status
      setTimeout(loadJob, 1000);
    } catch (err) {
      console.error("Retry failed:", err);
      setRetryMessage({ type: 'error', text: 'Failed to initiate retry.' });
    } finally {
      setRetrying(false);
    }
  };

  const isRetryable = job && (job.status === 'dead_lettered' || job.status === 'failed_retryable');

  if (loading) {
    return <div className="p-8 text-center text-muted-foreground">Loading job details...</div>;
  }

  if (error || !job) {
    return (
      <div className="p-8 text-center">
        <p className="text-destructive mb-4">{error || "Job not found"}</p>
        <Button variant="outline" onClick={() => router.back()}>
          <ArrowLeft className="mr-2 h-4 w-4" /> Go Back
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h2 className="text-2xl font-bold tracking-tight">{job.job_name}</h2>
            <p className="text-sm text-muted-foreground font-mono">{job.id}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
           <JobStatusBadge status={job.status} />
           {isRetryable && (
             <Button
               variant="outline"
               onClick={handleRetry}
               disabled={retrying}
             >
               <RefreshCw className={`mr-2 h-4 w-4 ${retrying ? 'animate-spin' : ''}`} />
               {retrying ? 'Retrying...' : 'Retry Job'}
             </Button>
           )}
        </div>
      </div>

      {retryMessage && (
        <div className={`p-4 rounded-md ${retryMessage.type === 'success' ? 'bg-green-50 text-green-900 border border-green-200' : 'bg-red-50 text-red-900 border border-red-200'}`}>
          {retryMessage.text}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
             <CardTitle>Execution Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-sm">
               <div className="text-muted-foreground">Status</div>
               <div className="font-medium">{job.status}</div>

               <div className="text-muted-foreground">Attempts</div>
               <div className="font-medium">{job.attempt_count} / {job.max_attempts}</div>

               <div className="text-muted-foreground">Idempotency Key</div>
               <div className="font-mono text-xs break-all">{job.idempotency_key || 'N/A'}</div>

               <div className="text-muted-foreground">Duration</div>
               <div className="font-medium">{job.duration_ms !== undefined && job.duration_ms !== null ? `${job.duration_ms}ms` : '-'}</div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
             <CardTitle>Timestamps</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-sm">
               <div className="text-muted-foreground">Created At</div>
               <div>{new Date(job.created_at).toLocaleString()}</div>

               <div className="text-muted-foreground">Scheduled For</div>
               <div>{new Date(job.scheduled_for).toLocaleString()}</div>

               <div className="text-muted-foreground">Run After</div>
               <div>{new Date(job.run_after).toLocaleString()}</div>

               <div className="text-muted-foreground">Started At</div>
               <div>{job.started_at ? new Date(job.started_at).toLocaleString() : '-'}</div>

               <div className="text-muted-foreground">Finished At</div>
               <div>{job.finished_at ? new Date(job.finished_at).toLocaleString() : '-'}</div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6">
         {job.error && (
            <Card className="border-red-200">
              <CardHeader className="bg-red-50/50">
                <CardTitle className="text-red-900">Error Output</CardTitle>
              </CardHeader>
              <CardContent className="pt-6">
                <pre className="bg-slate-950 text-slate-50 p-4 rounded-md overflow-x-auto text-xs">
                  {JSON.stringify(job.error, null, 2)}
                </pre>
              </CardContent>
            </Card>
         )}

         <Card>
          <CardHeader>
            <CardTitle>Result</CardTitle>
          </CardHeader>
          <CardContent>
            {job.result ? (
               <pre className="bg-slate-100 p-4 rounded-md overflow-x-auto text-xs text-slate-900">
                 {JSON.stringify(job.result, null, 2)}
               </pre>
            ) : (
              <div className="text-muted-foreground italic">No result data available.</div>
            )}
          </CardContent>
         </Card>

         <Card>
          <CardHeader>
            <CardTitle>Payload</CardTitle>
          </CardHeader>
          <CardContent>
            {job.payload ? (
               <pre className="bg-slate-100 p-4 rounded-md overflow-x-auto text-xs text-slate-900">
                 {JSON.stringify(job.payload, null, 2)}
               </pre>
            ) : (
              <div className="text-muted-foreground italic">No payload data available.</div>
            )}
          </CardContent>
         </Card>
      </div>
    </div>
  );
}
