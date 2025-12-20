'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchWithAuth, ApiError } from "@/lib/api";

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
                const json = await fetchWithAuth<WeeklySnapshot>('/progress/weekly');
                setData(json);
                setError(false);
            } catch (e: any) {
                // Check for 404 by status if it is an ApiError
                if (e instanceof ApiError && e.status === 404) {
                     // No data yet, handled by null state
                     setData(null);
                } else {
                     console.error('Failed to load weekly progress:', e);
                     setError(true);
                }
            } finally {
                setLoading(false);
            }
        };
        load();
    }, []);

    if (loading) return <div className="animate-pulse h-48 bg-muted rounded-lg"></div>;

    if (error) {
         return (
             <Card className="opacity-75">
                <CardHeader>
                    <CardTitle>Weekly Progress</CardTitle>
                    <CardDescription>Unavailable at the moment.</CardDescription>
                </CardHeader>
            </Card>
        );
    }

    if (!data) {
        return (
            <Card>
                <CardHeader>
                    <CardTitle>Weekly Progress</CardTitle>
                    <CardDescription>Metrics will appear after one week of activity.</CardDescription>
                </CardHeader>
            </Card>
        );
    }

    const { user_metrics, system_metrics, synthesis, dominant_regime } = data;
    const headline = synthesis?.headline || "No data available";

    if (!user_metrics || !system_metrics) {
        return (
             <Card>
                <CardHeader>
                    <CardTitle>Weekly Progress</CardTitle>
                    <CardDescription>Data is incomplete.</CardDescription>
                </CardHeader>
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
                    <Badge className={dominant_regime === 'Neutral' ? 'bg-muted-foreground' : 'bg-purple-600'}>
                        {dominant_regime} Regime
                    </Badge>
                </div>
            </CardHeader>
            <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
                    {/* User Metrics */}
                    <div className="space-y-3">
                        <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Pilot Performance</h4>
                        <div className="flex justify-between items-center">
                            <span className="text-2xl font-bold text-foreground">{user_metrics.overall_score.toFixed(0)}</span>
                            <span className="text-xs text-muted-foreground">Overall Score</span>
                        </div>
                        <div className="space-y-2">
                            {user_metrics.components && Object.entries(user_metrics.components).map(([key, metric]: [string, any]) => (
                                <div key={key} className="flex justify-between text-sm">
                                    <span className="text-muted-foreground">{metric?.label || key}</span>
                                    <span className="font-medium">{metric?.value != null ? (metric.value * 100).toFixed(0) : '--'}%</span>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* System Metrics */}
                    <div className="space-y-3 md:border-l md:pl-6">
                        <h4 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Engine Accuracy</h4>
                        <div className="flex justify-between items-center">
                            <span className="text-2xl font-bold text-purple-900 dark:text-purple-300">{system_metrics.overall_quality.toFixed(0)}</span>
                            <span className="text-xs text-muted-foreground">Quality Score</span>
                        </div>
                         <div className="space-y-2">
                            {system_metrics.components && Object.entries(system_metrics.components).map(([key, metric]: [string, any]) => (
                                <div key={key} className="flex justify-between text-sm">
                                    <span className="text-muted-foreground">{metric?.label || key}</span>
                                    <span className="font-medium">{metric?.value != null ? (metric.value * 100).toFixed(0) : '--'}%</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </CardContent>
        </Card>
    );
}
