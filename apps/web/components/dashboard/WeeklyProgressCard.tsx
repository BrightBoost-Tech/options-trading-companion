"use client";

import { useState, useEffect } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { EmptyState } from "@/components/ui/empty-state";
import { fetchWithAuth, ApiError } from "@/lib/api";
import { BarChart3, AlertCircle } from "lucide-react";

interface WeeklySnapshot {
  week_id: string;
  dominant_regime: string;
  user_metrics: {
    overall_score: number;
    components: {
      adherence_ratio: { value: number; label: string };
      risk_compliance: { value: number; label: string };
      execution_efficiency: { value: number; label: string };
    };
  };
  system_metrics: {
    overall_quality: number;
    components: {
      win_rate_high_confidence: { value: number; label: string };
      regime_stability: { value: number; label: string };
    };
  };
  synthesis: {
    headline: string;
    action_items: string[];
  };
}

export function WeeklyProgressCard() {
  const [data, setData] = useState<WeeklySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        // fetchWithAuth now returns parsed JSON and throws on error
        // It automatically prepends API_URL if path starts with '/'
        const json = await fetchWithAuth<WeeklySnapshot>("/progress/weekly");
        setData(json);
        setError(false);
      } catch (e: any) {
        // Check for 404 or 4xx by status if it is an ApiError
        // Only treat >=500 as "system errors" that show the red card.
        // 404 means "no data yet".
        if (e instanceof ApiError && e.status < 500) {
          // No data available (or bad request), treat as empty state
          setData(null);
          setError(false);
        } else {
          console.error("Failed to load weekly progress:", e);
          setError(true);
        }
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  if (loading)
    return <div className="animate-pulse h-48 bg-muted rounded-lg"></div>;

  if (error) {
    return (
      <Card className="opacity-75">
        <CardContent className="pt-6">
          <EmptyState
            icon={AlertCircle}
            title="Weekly Progress"
            description="Unavailable at the moment."
          />
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={BarChart3}
            title="Weekly Progress"
            description="Metrics will appear after one week of activity."
          />
        </CardContent>
      </Card>
    );
  }

  const { user_metrics, system_metrics, synthesis, dominant_regime } = data;
  const headline = synthesis?.headline || "No data available";

  if (!user_metrics || !system_metrics) {
    return (
      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={BarChart3}
            title="Weekly Progress"
            description="Data is incomplete."
          />
        </CardContent>
      </Card>
    );
  }

  const overallScore =
    typeof user_metrics.overall_score === "number"
      ? user_metrics.overall_score
      : null;
  const qualityScore =
    typeof system_metrics.overall_quality === "number"
      ? system_metrics.overall_quality
      : null;

  // If both scores are null/missing and components are empty, show empty state
  const hasUserComponents =
    user_metrics.components && Object.keys(user_metrics.components).length > 0;
  const hasSystemComponents =
    system_metrics.components &&
    Object.keys(system_metrics.components).length > 0;

  if (
    overallScore === null &&
    qualityScore === null &&
    !hasUserComponents &&
    !hasSystemComponents
  ) {
    return (
      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={BarChart3}
            title="Weekly Progress"
            description="Metrics will appear after one week of activity."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-gradient-to-br from-card to-background border-l-4 border-l-blue-500">
      <CardHeader className="pb-2">
        <div className="flex justify-between items-start">
          <div>
            <CardTitle className="flex items-center gap-2">
              Weekly Progress <Badge variant="outline">{data.week_id}</Badge>
            </CardTitle>
            <CardDescription>{headline}</CardDescription>
          </div>
          <Badge
            className={
              dominant_regime === "Neutral"
                ? "bg-muted-foreground"
                : "bg-purple-600"
            }
          >
            {dominant_regime} Regime
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
          {/* User Metrics */}
          <div className="space-y-3">
            <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Pilot Performance
            </h4>
            <div className="flex justify-between items-center">
              <span className="text-2xl font-bold text-foreground">
                {overallScore !== null ? overallScore.toFixed(0) : "--"}
              </span>
              <span className="text-xs text-muted-foreground">
                Overall Score
              </span>
            </div>
            <div className="space-y-4">
              {user_metrics.components &&
                Object.entries(user_metrics.components).map(
                  ([key, metric]: [string, any]) => (
                    <div key={key} className="space-y-1.5">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">
                          {metric?.label || key}
                        </span>
                        <span className="font-medium">
                          {metric?.value != null
                            ? (metric.value * 100).toFixed(0)
                            : "--"}
                          %
                        </span>
                      </div>
                      <Progress
                        value={metric?.value != null ? metric.value * 100 : 0}
                        className="h-2"
                        aria-label={metric?.label || key}
                      />
                    </div>
                  ),
                )}
            </div>
          </div>

          {/* System Metrics */}
          <div className="space-y-3 md:border-l md:pl-6">
            <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Engine Accuracy
            </h4>
            <div className="flex justify-between items-center">
              <span className="text-2xl font-bold text-purple-900 dark:text-purple-300">
                {qualityScore !== null ? qualityScore.toFixed(0) : "--"}
              </span>
              <span className="text-xs text-muted-foreground">
                Quality Score
              </span>
            </div>
            <div className="space-y-4">
              {system_metrics.components &&
                Object.entries(system_metrics.components).map(
                  ([key, metric]: [string, any]) => (
                    <div key={key} className="space-y-1.5">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">
                          {metric?.label || key}
                        </span>
                        <span className="font-medium">
                          {metric?.value != null
                            ? (metric.value * 100).toFixed(0)
                            : "--"}
                          %
                        </span>
                      </div>
                      <Progress
                        value={metric?.value != null ? metric.value * 100 : 0}
                        className="h-2"
                        aria-label={metric?.label || key}
                      />
                    </div>
                  ),
                )}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
