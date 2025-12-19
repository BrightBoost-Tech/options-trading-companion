'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { fetchWithAuth } from '@/lib/api';
import { RefreshCw, CheckCircle2, XCircle, Clock, AlertTriangle } from 'lucide-react';

interface JobRun {
  id: string;
  job_name: string;
  idempotency_key: string;
  status: string;
  attempt: number;
  max_attempts: number;
  duration_ms: number | null;
  error: any;
  result: any;
  created_at: string;
}

export default function JobsPage() {
  const [runs, setRuns] = useState<JobRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const data = await fetchWithAuth('/jobs/runs?limit=50');
        if (Array.isArray(data)) {
          setRuns(data);
        }
      } catch (e) {
        console.error("Failed to load jobs", e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [refreshKey]);

  const handleRetry = async (id: string) => {
    try {
      await fetchWithAuth(`/jobs/runs/${id}/retry`, { method: 'POST' });
      // Short delay to let DB update
      setTimeout(() => setRefreshKey(k => k + 1), 500);
    } catch (e) {
      console.error("Retry failed", e);
      alert("Retry failed");
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case 'succeeded': return 'bg-green-500/10 text-green-500 hover:bg-green-500/20';
      case 'failed':
      case 'failed_retryable':
      case 'dead_lettered': return 'bg-red-500/10 text-red-500 hover:bg-red-500/20';
      case 'running': return 'bg-blue-500/10 text-blue-500 hover:bg-blue-500/20';
      case 'queued': return 'bg-yellow-500/10 text-yellow-500 hover:bg-yellow-500/20';
      default: return 'bg-slate-500/10 text-slate-500';
    }
  };

  return (
    <div className="container py-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Job Runs</h1>
          <p className="text-muted-foreground">Monitor internal system tasks and queues.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setRefreshKey(k => k + 1)}>
          <RefreshCw className="mr-2 h-4 w-4" /> Refresh
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="relative w-full overflow-auto">
            <table className="w-full caption-bottom text-sm">
              <thead className="[&_tr]:border-b">
                <tr className="border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted">
                  <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Status</th>
                  <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Job Name</th>
                  <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Idempotency Key</th>
                  <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Created At</th>
                  <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Attempt</th>
                  <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Duration</th>
                  <th className="h-12 px-4 text-right align-middle font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody className="[&_tr:last-child]:border-0">
                {loading && (
                   <tr>
                     <td colSpan={7} className="h-24 text-center">Loading...</td>
                   </tr>
                )}
                {!loading && runs.map((run) => (
                  <>
                  <tr
                    key={run.id}
                    className="border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted cursor-pointer"
                    onClick={() => setExpandedRow(expandedRow === run.id ? null : run.id)}
                  >
                    <td className="p-4 align-middle">
                      <Badge className={statusColor(run.status)} variant="outline">
                        {run.status}
                      </Badge>
                    </td>
                    <td className="p-4 align-middle font-medium">{run.job_name}</td>
                    <td className="p-4 align-middle text-muted-foreground font-mono text-xs">{run.idempotency_key}</td>
                    <td className="p-4 align-middle">{new Date(run.created_at).toLocaleString()}</td>
                    <td className="p-4 align-middle">{run.attempt} / {run.max_attempts}</td>
                    <td className="p-4 align-middle">{run.duration_ms ? `${run.duration_ms}ms` : '-'}</td>
                    <td className="p-4 align-middle text-right">
                      {['dead_lettered', 'failed_retryable'].includes(run.status) && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleRetry(run.id);
                          }}
                        >
                          Retry
                        </Button>
                      )}
                    </td>
                  </tr>
                  {expandedRow === run.id && (
                    <tr className="bg-muted/30">
                      <td colSpan={7} className="p-4">
                        <div className="grid grid-cols-2 gap-4">
                           <div>
                             <h4 className="font-semibold mb-2 text-xs uppercase text-muted-foreground">Result</h4>
                             <pre className="bg-background border rounded p-2 text-xs overflow-auto max-h-[200px]">
                               {JSON.stringify(run.result, null, 2)}
                             </pre>
                           </div>
                           <div>
                             <h4 className="font-semibold mb-2 text-xs uppercase text-red-500">Error</h4>
                             <pre className="bg-background border rounded p-2 text-xs overflow-auto max-h-[200px] text-red-600">
                               {JSON.stringify(run.error, null, 2)}
                             </pre>
                           </div>
                        </div>
                      </td>
                    </tr>
                  )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
