'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchWithAuth } from "@/lib/api";

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
                const json = await fetchWithAuth<WeeklySnapshot>('/api/progress/weekly');
                setData(json);
            } catch (e: any) {
                // Check for 404 by message if possible, or just treat as error/empty
                // Current fetchWithAuth throws generic error with status code in message
                if (e.message && e.message.includes('404')) {
                     // No data yet, handled by null state
                } else {
                     console.error(e);
                     setError(true);
                }
            } finally {
                setLoading(false);
            }
        };
        load();
    }, []);

    if (loading) return <div className="animate-pulse h-48 bg-gray-100 rounded-lg"></div>;

    if (error) return null; // Hide on error for minimal intrusion

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

    return (
        <Card className="bg-gradient-to-br from-white to-gray-50 border-l-4 border-l-blue-500">
            <CardHeader className="pb-2">
                <div className="flex justify-between items-start">
                    <div>
                        <CardTitle className="flex items-center gap-2">
                            Weekly Progress <Badge variant="outline">{data.week_id}</Badge>
                        </CardTitle>
                        <CardDescription>{synthesis.headline}</CardDescription>
                    </div>
                    <Badge className={dominant_regime === 'Neutral' ? 'bg-gray-500' : 'bg-purple-600'}>
                        {dominant_regime} Regime
                    </Badge>
                </div>
            </CardHeader>
            <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
                    {/* User Metrics */}
                    <div className="space-y-3">
                        <h4 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">Pilot Performance</h4>
                        <div className="flex justify-between items-center">
                            <span className="text-2xl font-bold text-gray-900">{user_metrics.overall_score.toFixed(0)}</span>
                            <span className="text-xs text-gray-500">Overall Score</span>
                        </div>
                        <div className="space-y-2">
                            {Object.entries(user_metrics.components).map(([key, metric]: [string, any]) => (
                                <div key={key} className="flex justify-between text-sm">
                                    <span className="text-gray-600">{metric.label}</span>
                                    <span className="font-medium">{(metric.value * 100).toFixed(0)}%</span>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* System Metrics */}
                    <div className="space-y-3 md:border-l md:pl-6">
                        <h4 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">Engine Accuracy</h4>
                        <div className="flex justify-between items-center">
                            <span className="text-2xl font-bold text-purple-900">{system_metrics.overall_quality.toFixed(0)}</span>
                            <span className="text-xs text-gray-500">Quality Score</span>
                        </div>
                         <div className="space-y-2">
                            {Object.entries(system_metrics.components).map(([key, metric]: [string, any]) => (
                                <div key={key} className="flex justify-between text-sm">
                                    <span className="text-gray-600">{metric.label}</span>
                                    <span className="font-medium">{(metric.value * 100).toFixed(0)}%</span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </CardContent>
        </Card>
    );
}
