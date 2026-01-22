'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { JobsTable } from '@/components/jobs/JobsTable';
import { JobFilters } from '@/components/jobs/JobFilters';
import { JobRun, JobFilters as JobFiltersType } from '@/lib/types';
import { fetchWithAuth, ApiError } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { RequireAuth } from '@/components/RequireAuth';
import { AuthRequired } from '@/components/AuthRequired';

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<JobFiltersType>({});
  const [authMissing, setAuthMissing] = useState(false);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.status) params.append('status', filters.status);
      if (filters.job_name) params.append('job_name', filters.job_name);

      const queryString = params.toString();
      const url = `/jobs/runs${queryString ? `?${queryString}` : ''}`;

      const data = await fetchWithAuth<JobRun[]>(url);

      if (Array.isArray(data)) {
        setJobs(data);
      } else {
        setJobs([]);
        console.error("Expected array from /jobs/runs, got:", data);
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setAuthMissing(true);
        return;
      }
      console.error("Failed to load jobs:", error);
      setJobs([]);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Show auth required UI if authentication is missing
  if (authMissing) {
    return <AuthRequired message="Please log in to view job history." />;
  }

  return (
    <RequireAuth>
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Job Monitor</h2>
        <p className="text-muted-foreground">
          View and manage background job executions.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Job History</CardTitle>
          <CardDescription>
            List of all job runs and their current status.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <JobFilters filters={filters} onFilterChange={setFilters} />
          <JobsTable jobs={jobs} isLoading={loading} />
        </CardContent>
      </Card>
    </div>
    </RequireAuth>
  );
}
