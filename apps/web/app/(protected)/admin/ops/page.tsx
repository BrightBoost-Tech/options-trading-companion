'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { fetchWithAuth } from '@/lib/api';
import {
  OpsDashboardState,
  OpsControlState,
  FreshnessItem,
  PipelineJobState,
  HealthBlock
} from '@/lib/types';
import {
  RefreshCw,
  Pause,
  Play,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Activity,
  Zap
} from 'lucide-react';

export default function OpsPage() {
  const [dashboardState, setDashboardState] = useState<OpsDashboardState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [actionPending, setActionPending] = useState(false);
  const [pauseReason, setPauseReason] = useState('');

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchWithAuth<OpsDashboardState>('/ops/dashboard_state');
        setDashboardState(data);
      } catch (e: any) {
        console.error("Failed to load ops state", e);
        setError(e.message || "Failed to load ops state");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [refreshKey]);

  const handleTogglePause = async () => {
    if (!dashboardState) return;
    setActionPending(true);
    try {
      const newPaused = !dashboardState.control.paused;
      await fetchWithAuth('/ops/pause', {
        method: 'POST',
        body: JSON.stringify({
          paused: newPaused,
          reason: newPaused ? (pauseReason || 'Manual pause from Ops Console') : null
        })
      });
      setPauseReason('');
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      console.error("Failed to toggle pause", e);
      alert(`Failed to toggle pause: ${e.message}`);
    } finally {
      setActionPending(false);
    }
  };

  const handleSetMode = async (mode: string) => {
    setActionPending(true);
    try {
      await fetchWithAuth('/ops/mode', {
        method: 'POST',
        body: JSON.stringify({ mode })
      });
      setRefreshKey(k => k + 1);
    } catch (e: any) {
      console.error("Failed to set mode", e);
      alert(`Failed to set mode: ${e.message}`);
    } finally {
      setActionPending(false);
    }
  };

  const healthStatusColor = (status: string) => {
    switch (status) {
      case 'healthy': return 'bg-green-500';
      case 'paused': return 'bg-yellow-500';
      case 'degraded': return 'bg-orange-500';
      case 'unhealthy': return 'bg-red-500';
      default: return 'bg-slate-500';
    }
  };

  const healthBadgeStyle = (status: string) => {
    switch (status) {
      case 'healthy': return 'bg-green-500/10 text-green-500 border-green-500/30';
      case 'paused': return 'bg-yellow-500/10 text-yellow-500 border-yellow-500/30';
      case 'degraded': return 'bg-orange-500/10 text-orange-500 border-orange-500/30';
      case 'unhealthy': return 'bg-red-500/10 text-red-500 border-red-500/30';
      default: return 'bg-slate-500/10 text-slate-500 border-slate-500/30';
    }
  };

  const freshnessStatusStyle = (status: string) => {
    switch (status) {
      case 'OK': return 'bg-green-500/10 text-green-500';
      case 'WARN': return 'bg-yellow-500/10 text-yellow-500';
      case 'STALE': return 'bg-red-500/10 text-red-500';
      case 'ERROR': return 'bg-red-500/10 text-red-500';
      default: return 'bg-slate-500/10 text-slate-500';
    }
  };

  const pipelineStatusStyle = (status: string) => {
    switch (status) {
      case 'succeeded': return 'bg-green-500/10 text-green-500';
      case 'running': return 'bg-blue-500/10 text-blue-500';
      case 'queued': return 'bg-yellow-500/10 text-yellow-500';
      case 'failed_retryable':
      case 'dead_lettered':
      case 'error': return 'bg-red-500/10 text-red-500';
      case 'never_run': return 'bg-slate-500/10 text-slate-500';
      default: return 'bg-slate-500/10 text-slate-500';
    }
  };

  const modeLabel = (mode: string) => {
    switch (mode) {
      case 'paper': return 'Paper Trading';
      case 'micro_live': return 'Micro Live';
      case 'live': return 'Live Trading';
      default: return mode;
    }
  };

  if (loading) {
    return (
      <div className="container py-8">
        <div className="flex items-center justify-center h-64">
          <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container py-8">
        <Card className="border-red-500/50">
          <CardContent className="pt-6">
            <div className="flex items-center gap-3 text-red-500">
              <XCircle className="h-6 w-6" />
              <span>{error}</span>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => setRefreshKey(k => k + 1)}
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!dashboardState) return null;

  const { control, freshness, pipeline, health } = dashboardState;

  return (
    <div className="container py-8 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Ops Console</h1>
          <p className="text-muted-foreground">Mobile commander for trading operations.</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setRefreshKey(k => k + 1)}
          disabled={actionPending}
        >
          <RefreshCw className={`mr-2 h-4 w-4 ${actionPending ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Health Status Hero */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className={`h-16 w-16 rounded-full ${healthStatusColor(health.status)} flex items-center justify-center`}>
                {health.status === 'healthy' && <CheckCircle2 className="h-8 w-8 text-white" />}
                {health.status === 'paused' && <Pause className="h-8 w-8 text-white" />}
                {health.status === 'degraded' && <AlertTriangle className="h-8 w-8 text-white" />}
                {health.status === 'unhealthy' && <XCircle className="h-8 w-8 text-white" />}
              </div>
              <div>
                <Badge className={`text-lg px-3 py-1 ${healthBadgeStyle(health.status)}`} variant="outline">
                  {health.status.toUpperCase()}
                </Badge>
                <div className="mt-2 text-sm text-muted-foreground">
                  Last updated: {new Date(control.updated_at).toLocaleString()}
                </div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm text-muted-foreground mb-1">Mode</div>
              <Badge variant="outline" className="text-base">
                {modeLabel(control.mode)}
              </Badge>
            </div>
          </div>

          {/* Issues List */}
          {health.issues.length > 0 && (
            <div className="mt-4 p-3 rounded-lg bg-muted/50">
              <div className="text-sm font-medium mb-2">Active Issues:</div>
              <ul className="space-y-1">
                {health.issues.map((issue, i) => (
                  <li key={i} className="text-sm text-muted-foreground flex items-center gap-2">
                    <AlertTriangle className="h-3 w-3 text-yellow-500" />
                    {issue}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Control Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Pause Control */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              {control.paused ? <Pause className="h-5 w-5 text-yellow-500" /> : <Play className="h-5 w-5 text-green-500" />}
              Trading State
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm">
                Status: <span className={control.paused ? 'text-yellow-500 font-medium' : 'text-green-500 font-medium'}>
                  {control.paused ? 'PAUSED' : 'ACTIVE'}
                </span>
              </span>
            </div>
            {control.paused && control.pause_reason && (
              <div className="text-sm text-muted-foreground">
                Reason: {control.pause_reason}
              </div>
            )}
            {!control.paused && (
              <input
                type="text"
                placeholder="Pause reason (optional)"
                value={pauseReason}
                onChange={(e) => setPauseReason(e.target.value)}
                className="w-full px-3 py-2 text-sm border rounded-md bg-background"
              />
            )}
            <Button
              onClick={handleTogglePause}
              disabled={actionPending}
              variant={control.paused ? 'default' : 'destructive'}
              className="w-full"
            >
              {control.paused ? (
                <>
                  <Play className="mr-2 h-4 w-4" /> Resume Trading
                </>
              ) : (
                <>
                  <Pause className="mr-2 h-4 w-4" /> Pause Trading
                </>
              )}
            </Button>
          </CardContent>
        </Card>

        {/* Mode Control */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg flex items-center gap-2">
              <Zap className="h-5 w-5" />
              Operating Mode
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-muted-foreground mb-2">
              Current: <span className="font-medium text-foreground">{modeLabel(control.mode)}</span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {['paper', 'micro_live', 'live'].map((mode) => (
                <Button
                  key={mode}
                  variant={control.mode === mode ? 'default' : 'outline'}
                  size="sm"
                  disabled={actionPending || control.mode === mode}
                  onClick={() => handleSetMode(mode)}
                >
                  {mode === 'paper' && 'Paper'}
                  {mode === 'micro_live' && 'Micro'}
                  {mode === 'live' && 'Live'}
                </Button>
              ))}
            </div>
            {control.mode === 'live' && (
              <div className="text-xs text-red-500 mt-2">
                Warning: Live mode executes real trades.
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Market Data Freshness */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Market Data
          </CardTitle>
          <CardDescription>Real-time quote freshness</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {freshness.map((item) => (
              <div key={item.symbol} className="p-3 rounded-lg border bg-card">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium">{item.symbol}</span>
                  <Badge className={freshnessStatusStyle(item.status)} variant="outline">
                    {item.status}
                  </Badge>
                </div>
                <div className="text-sm text-muted-foreground">
                  {item.freshness_ms !== null ? (
                    <span>{(item.freshness_ms / 1000).toFixed(1)}s ago</span>
                  ) : (
                    <span>Unknown</span>
                  )}
                </div>
                {item.score !== null && (
                  <div className="text-xs text-muted-foreground mt-1">
                    Quality: {item.score}/100
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Pipeline Status */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg flex items-center gap-2">
            <Clock className="h-5 w-5" />
            Pipeline Jobs
          </CardTitle>
          <CardDescription>Scheduled task status</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {Object.entries(pipeline).map(([name, state]) => (
              <div key={name} className="flex items-center justify-between p-3 rounded-lg border bg-card">
                <div>
                  <div className="font-medium text-sm">{name.replace(/_/g, ' ')}</div>
                  {state.finished_at && (
                    <div className="text-xs text-muted-foreground">
                      Last: {new Date(state.finished_at).toLocaleString()}
                    </div>
                  )}
                </div>
                <Badge className={pipelineStatusStyle(state.status)} variant="outline">
                  {state.status}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Component Checks */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Health Checks</CardTitle>
          <CardDescription>Per-component status</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4">
            {Object.entries(health.checks).map(([component, status]) => (
              <div key={component} className="text-center p-3 rounded-lg border bg-card">
                <div className="text-xs text-muted-foreground uppercase mb-1">{component.replace(/_/g, ' ')}</div>
                <Badge
                  className={
                    status === 'ok' || status === 'active' ? 'bg-green-500/10 text-green-500' :
                    status === 'warn' || status === 'running' ? 'bg-yellow-500/10 text-yellow-500' :
                    status === 'paused' ? 'bg-yellow-500/10 text-yellow-500' :
                    'bg-red-500/10 text-red-500'
                  }
                  variant="outline"
                >
                  {status}
                </Badge>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
