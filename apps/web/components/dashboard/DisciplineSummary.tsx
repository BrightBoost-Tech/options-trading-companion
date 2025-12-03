'use client';

import React, { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { fetchWithAuth } from '@/lib/api';

interface DriftSummary {
    window_days: number;
    total_suggestions: number;
    disciplined_execution: number;
    impulse_trades: number;
    size_violations: number;
    disciplined_rate: number;
    impulse_rate: number;
    size_violation_rate: number;
}

export default function DisciplineSummary({ className }: { className?: string }) {
    const [summary, setSummary] = useState<DriftSummary | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const load = async () => {
            try {
                const data = await fetchWithAuth('/journal/drift-summary');
                if (data && typeof data === 'object') {
                    setSummary(data as DriftSummary);
                }
            } catch (err) {
                console.error("Failed to load drift summary", err);
            } finally {
                setLoading(false);
            }
        };
        load();
    }, []);

    if (loading) return (
        <Card className={className}>
            <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-gray-500">Execution Discipline</CardTitle>
            </CardHeader>
            <CardContent>
                <div className="animate-pulse h-12 bg-gray-100 rounded"></div>
            </CardContent>
        </Card>
    );

    if (!summary || summary.total_suggestions === 0) {
         return (
            <Card className={className}>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-gray-500">Execution Discipline</CardTitle>
                </CardHeader>
                <CardContent>
                    <p className="text-sm text-gray-400">No recent activity</p>
                </CardContent>
            </Card>
         );
    }

    // Format rates as percentages
    const disciplinePct = Math.round(summary.disciplined_rate * 100);
    const impulsePct = Math.round(summary.impulse_rate * 100);

    // Color coding
    const color = disciplinePct >= 80 ? 'text-green-600' : disciplinePct >= 50 ? 'text-yellow-600' : 'text-red-600';

    return (
        <Card className={className}>
            <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-gray-500">
                    Execution Discipline <span className="text-xs font-normal text-gray-400">(Last {summary.window_days} Days)</span>
                </CardTitle>
            </CardHeader>
            <CardContent>
                <div className="flex justify-between items-baseline mb-2">
                    <div className={`text-2xl font-bold ${color}`}>
                        {disciplinePct}%
                    </div>
                    <div className="text-xs text-gray-500">
                        {summary.disciplined_execution} / {summary.total_suggestions} trades
                    </div>
                </div>

                <div className="space-y-1 text-xs text-gray-600">
                    {summary.impulse_trades > 0 && (
                        <div className="flex justify-between">
                            <span>Impulse Trades:</span>
                            <span className="text-red-500 font-medium">{summary.impulse_trades}</span>
                        </div>
                    )}
                    {summary.size_violations > 0 && (
                        <div className="flex justify-between">
                            <span>Size Violations:</span>
                            <span className="text-orange-500 font-medium">{summary.size_violations}</span>
                        </div>
                    )}
                    {summary.impulse_trades === 0 && summary.size_violations === 0 && (
                        <p className="text-green-600 italic">No violations detected</p>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}
