"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { AlertCircle, CheckCircle2, ShieldAlert, Activity, Database, Zap, ServerCrash } from "lucide-react"
import { fetchWithAuth } from "@/lib/api"
import { Skeleton } from "@/components/ui/skeleton"

interface ProviderMetrics {
  state: "CLOSED" | "HALF_OPEN" | "OPEN"
  failures: number
  rate_limits: number
}

interface CacheStats {
  total_entries: number
  active_entries: number
}

interface SystemHealthResponse {
  status: "Normal" | "Conservative" | "Data-Limited"
  provider_health?: {
    polygon?: ProviderMetrics
  }
  cache_stats?: CacheStats
  veto_rate_7d: number
  veto_rate_30d: number
  active_constraints: Array<{ constraint: string; count: number }>
  not_executable_pct: number
  partial_outcomes_pct: number
}

export function SystemHealthPanel() {
  const [data, setData] = useState<SystemHealthResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function fetchHealth() {
      try {
        const response = await fetchWithAuth("/system/health")
        if (response) {
          setData(response)
        }
      } catch (err) {
        console.error("Failed to fetch system health:", err)
        setError("Failed to load health metrics")
      } finally {
        setLoading(false)
      }
    }

    fetchHealth()
  }, [])

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>System Health</CardTitle>
          <CardDescription>Diagnostic metrics</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        </CardContent>
      </Card>
    )
  }

  if (error || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            System Health
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">
            {error || "No data available"}
          </div>
        </CardContent>
      </Card>
    )
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case "Normal":
        return "bg-green-500/10 text-green-500 hover:bg-green-500/20"
      case "Conservative":
        return "bg-blue-500/10 text-blue-500 hover:bg-blue-500/20"
      case "Data-Limited":
        return "bg-yellow-500/10 text-yellow-500 hover:bg-yellow-500/20"
      default:
        return "bg-gray-500/10 text-gray-500"
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "Normal":
        return <CheckCircle2 className="h-4 w-4 mr-1" />
      case "Conservative":
        return <ShieldAlert className="h-4 w-4 mr-1" />
      case "Data-Limited":
        return <Database className="h-4 w-4 mr-1" />
      default:
        return <Activity className="h-4 w-4 mr-1" />
    }
  }

  const getReasonLine = () => {
    if (data.status !== "Data-Limited") return null;

    const polygonState = data.provider_health?.polygon?.state;
    if (polygonState === "OPEN") {
      return (
        <div className="mt-1 flex items-center gap-1 text-xs text-red-500 font-medium">
          <ServerCrash className="h-3 w-3" />
          Provider Breaker Open
        </div>
      );
    }

    // Fallback reason if provider is fine but we are still data limited
    return (
      <div className="mt-1 flex items-center gap-1 text-xs text-yellow-600 font-medium">
        <Database className="h-3 w-3" />
        Universe Scarcity
      </div>
    );
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-medium flex items-center gap-2">
            <Activity className="h-5 w-5 text-muted-foreground" />
            System Health
          </CardTitle>
          <div className="flex flex-col items-end">
            <Badge className={getStatusColor(data.status)} variant="outline">
              {getStatusIcon(data.status)}
              {data.status}
            </Badge>
            {getReasonLine()}
          </div>
        </div>
        <CardDescription>
          Diagnostic metrics for system behavior (30d window)
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">

        {/* Provider & Cache Details - New Section */}
        {(data.provider_health?.polygon || data.cache_stats) && (
          <div className="grid grid-cols-2 gap-2 p-2 bg-muted/30 rounded-lg text-xs">
             {/* Polygon Status */}
             {data.provider_health?.polygon && (
               <div className="space-y-1">
                 <div className="flex items-center gap-1 text-muted-foreground font-medium">
                   <Zap className="h-3 w-3" /> Polygon
                 </div>
                 <div className="flex flex-col gap-0.5 ml-1">
                   <span className={data.provider_health.polygon.state === 'OPEN' ? "text-red-500 font-bold" : "text-green-600"}>
                     {data.provider_health.polygon.state}
                   </span>
                   <span className="text-muted-foreground opacity-80">
                      {data.provider_health.polygon.rate_limits} RL / {data.provider_health.polygon.failures} Err
                   </span>
                 </div>
               </div>
             )}

             {/* Cache Stats */}
             {data.cache_stats && (
               <div className="space-y-1">
                 <div className="flex items-center gap-1 text-muted-foreground font-medium">
                   <Database className="h-3 w-3" /> Cache
                 </div>
                 <div className="flex flex-col gap-0.5 ml-1">
                   <span>
                     {data.cache_stats.active_entries} <span className="text-muted-foreground">/ {data.cache_stats.total_entries}</span>
                   </span>
                   <span className="text-muted-foreground opacity-80">
                     Entries Active
                   </span>
                 </div>
               </div>
             )}
          </div>
        )}

        {/* Veto Rate Stats */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Veto Rate (7d / 30d)</span>
            <span className="font-medium">
              {data.veto_rate_7d.toFixed(1)}% / {data.veto_rate_30d.toFixed(1)}%
            </span>
          </div>
          <Progress value={data.veto_rate_30d} className="h-2" aria-label="30-day Veto Rate" />
        </div>

        {/* Outcome Quality */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground block">Not Executable</span>
            <div className="text-2xl font-bold flex items-baseline">
              {data.not_executable_pct.toFixed(1)}
              <span className="text-sm font-normal text-muted-foreground ml-1">%</span>
            </div>
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground block">Partial Fills</span>
            <div className="text-2xl font-bold flex items-baseline">
              {data.partial_outcomes_pct.toFixed(1)}
              <span className="text-sm font-normal text-muted-foreground ml-1">%</span>
            </div>
          </div>
        </div>

        {/* Active Constraints */}
        <div className="space-y-3">
          <span className="text-sm font-medium block flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-muted-foreground" />
            Active Constraints
          </span>
          {data.active_constraints.length > 0 ? (
            <div className="space-y-2">
              {data.active_constraints.slice(0, 3).map((c, i) => (
                <div key={i} className="flex justify-between items-center text-sm">
                  <span className="text-muted-foreground truncate max-w-[180px]" title={c.constraint}>
                    {c.constraint}
                  </span>
                  <Badge variant="secondary" className="text-xs h-5">
                    x{c.count}
                  </Badge>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground italic">
              No active constraints recorded
            </div>
          )}
        </div>

      </CardContent>
    </Card>
  )
}
