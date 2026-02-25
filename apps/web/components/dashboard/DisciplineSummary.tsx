'use client';

import React, { useEffect, useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { fetchWithAuth } from '@/lib/api';
import { CheckCircle2, AlertTriangle, AlertOctagon } from 'lucide-react';

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
                <CardTitle className="text-sm font-medium text-muted-foreground">Execution Discipline</CardTitle>
            </CardHeader>
            <CardContent role="status" aria-live="polite">
                <div className="animate-pulse h-12 bg-muted rounded"></div>
            </CardContent>
        </Card>
    );

    if (!summary || summary.total_suggestions === 0) {
         return (
            <Card className={className}>
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium text-muted-foreground">Execution Discipline</CardTitle>
                </CardHeader>
                <CardContent>
                    <p className="text-sm text-muted-foreground">No recent activity</p>
                </CardContent>
            </Card>
         );
    }

    // Format rates as percentages
    const disciplinePct = Math.round(summary.disciplined_rate * 100);

    // Color coding
    const color = disciplinePct >= 80 ? 'text-green-600 dark:text-green-400' : disciplinePct >= 50 ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400';
    const indicatorColorClass = disciplinePct >= 80
        ? '[&>div]:bg-green-600 dark:[&>div]:bg-green-500'
        : disciplinePct >= 50
            ? '[&>div]:bg-yellow-600 dark:[&>div]:bg-yellow-500'
            : '[&>div]:bg-red-600 dark:[&>div]:bg-red-500';

    return (
        <Card className={className}>
            <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                    Execution Discipline <span className="text-xs font-normal text-muted-foreground">(Last {summary.window_days} Days)</span>
                </CardTitle>
            </CardHeader>
            <CardContent>
                <div className="flex flex-col gap-2 mb-4">
                    <div className="flex justify-between items-baseline">
                        <div className={`text-2xl font-bold ${color}`}>
                            {disciplinePct}%
                        </div>
                        <div className="text-xs text-muted-foreground">
                            {summary.disciplined_execution} / {summary.total_suggestions} trades
                        </div>
                    </div>

                    {/* Visual Progress Bar with ARIA */}
                    <Progress
                        value={disciplinePct}
                        className={`h-2 ${indicatorColorClass}`}
                        aria-label="Discipline Score"
                    />
                </div>

                <ul className="space-y-2 text-xs text-muted-foreground">
                    {summary.impulse_trades > 0 && (
                        <li className="flex items-center justify-between">
                            <span className="flex items-center gap-1.5">
                                <AlertOctagon className="w-3.5 h-3.5 text-red-500" aria-hidden="true" />
                                Impulse Trades
                            </span>
                            <span className="text-red-500 font-medium">{summary.impulse_trades}</span>
                        </li>
                    )}
                    {summary.size_violations > 0 && (
                        <li className="flex items-center justify-between">
                            <span className="flex items-center gap-1.5">
                                <AlertTriangle className="w-3.5 h-3.5 text-orange-500" aria-hidden="true" />
                                Size Violations
                            </span>
                            <span className="text-orange-500 font-medium">{summary.size_violations}</span>
                        </li>
                    )}
                    {summary.impulse_trades === 0 && summary.size_violations === 0 && (
                        <li className="flex items-center gap-1.5 text-green-600 dark:text-green-400 italic">
                             <CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" />
                             No violations detected
                        </li>
                    )}
                </ul>
            </CardContent>
        </Card>
    );
}
