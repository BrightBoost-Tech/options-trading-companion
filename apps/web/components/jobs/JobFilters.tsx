import React from 'react';
import { Input } from "@/components/ui/input"; // Assuming Input exists, if not I'll use standard input or check
import { Button } from "@/components/ui/button";
import { JobFilters as JobFiltersType } from "@/lib/types";

// Checking if Input component exists, otherwise I'll define a simple one here or use HTML input
// I'll assume standard shadcn-like Input exists as Button existed.
// If not, I'll fix it.

interface JobFiltersProps {
  filters: JobFiltersType;
  onFilterChange: (filters: JobFiltersType) => void;
}

export function JobFilters({ filters, onFilterChange }: JobFiltersProps) {
  const handleStatusChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    onFilterChange({ ...filters, status: e.target.value || undefined });
  };

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onFilterChange({ ...filters, job_name: e.target.value || undefined });
  };

  return (
    <div className="flex flex-col sm:flex-row gap-4 mb-4 items-end">
      <div className="flex flex-col gap-1.5 w-full sm:w-auto">
        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
          Status
        </label>
        <select
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          value={filters.status || ''}
          onChange={handleStatusChange}
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="processing">Processing</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="dead_lettered">Dead Lettered</option>
          <option value="failed_retryable">Failed Retryable</option>
        </select>
      </div>

      <div className="flex flex-col gap-1.5 w-full sm:w-64">
        <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
          Job Name
        </label>
        <input
          type="text"
          placeholder="Filter by job name..."
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          value={filters.job_name || ''}
          onChange={handleNameChange}
        />
      </div>

      <Button
        variant="outline"
        onClick={() => onFilterChange({})}
        disabled={!filters.status && !filters.job_name}
      >
        Clear
      </Button>
    </div>
  );
}
