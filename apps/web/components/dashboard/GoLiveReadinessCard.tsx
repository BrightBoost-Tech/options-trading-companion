'use client';

import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchWithAuth } from "@/lib/api";
import { Loader2, CheckCircle, XCircle, Play, History, FileText, AlertTriangle } from 'lucide-react';
import { QuantumTooltip } from "@/components/ui/QuantumTooltip";

interface ValidationState {
    paper_window_start: string;
    paper_window_end: string;
    paper_consecutive_passes: number;
    paper_ready: boolean;
    historical_last_run_at: string | null;
    historical_last_result: {
        passed?: boolean;
        return_pct?: number;
    };
    overall_ready: boolean;
    // v4-L1: Paper forward checkpoint fields
    paper_checkpoint_target?: number;
    paper_checkpoint_last_run_at?: string | null;
    paper_fail_fast_triggered?: boolean;
    paper_fail_fast_reason?: string | null;
    paper_window_days?: number;
}

interface JournalEntry {
    id: string;
    created_at: string;
    title: string;
    summary: string;
    details_json: any;
}

export function GoLiveReadinessCard() {
    const [status, setStatus] = useState<ValidationState | null>(null);
    const [journal, setJournal] = useState<JournalEntry[]>([]);
    const [loading, setLoading] = useState(true);
    const [runningPaper, setRunningPaper] = useState(false);
    const [runningHistorical, setRunningHistorical] = useState(false);

    const loadData = async () => {
        try {
            const statusData = await fetchWithAuth<any>('/validation/status');
            setStatus(statusData.state);

            const journalData = await fetchWithAuth<any>('/validation/journal?limit=5');
            setJournal(journalData.entries || []);
        } catch (err) {
            console.error('Failed to load validation status:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadData();
    }, []);

    const runPaperEval = async () => {
        setRunningPaper(true);
        try {
            await fetchWithAuth('/validation/run', {
                method: 'POST',
                body: JSON.stringify({ mode: 'paper' })
            });
            await loadData();
        } catch (err) {
            console.error('Failed to run paper eval:', err);
        } finally {
            setRunningPaper(false);
        }
    };

    const runHistoricalSuite = async () => {
        setRunningHistorical(true);
        try {
            await fetchWithAuth('/validation/run', {
                method: 'POST',
                body: JSON.stringify({
                    mode: 'historical',
                    historical: {
                        window_days: 90,
                        symbol: "SPY",
                        concurrent_runs: 3,
                        stride_days: 90,
                        goal_return_pct: 10,
                        autotune: true,
                        max_trials: 12,
                    }
                })
            });
            // Since historical is async/queued, we might just refresh state to show it started or just wait a bit.
            // For UX, we just refresh.
            await loadData();
        } catch (err) {
            console.error('Failed to run historical suite:', err);
        } finally {
            setRunningHistorical(false);
        }
    };

    if (loading) {
        return <div className="animate-pulse h-64 bg-muted rounded-lg"></div>;
    }

    if (!status) {
        return (
            <Card>
                <CardHeader>
                    <CardTitle>Go-Live Readiness</CardTitle>
                    <CardDescription>Setup incomplete.</CardDescription>
                </CardHeader>
            </Card>
        );
    }

    // v4-L1: Use dynamic checkpoint target from state
    const paperTarget = status.paper_checkpoint_target ?? 10;
    const paperStreak = status.paper_consecutive_passes ?? 0;
    const paperProgress = Math.min((paperStreak / paperTarget) * 100, 100);
    const failFastTriggered = status.paper_fail_fast_triggered ?? false;

    // Calculate days remaining in current paper window
    const now = new Date();
    const windowEnd = new Date(status.paper_window_end);
    const daysRemaining = Math.max(0, Math.ceil((windowEnd.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)));

    const histPassed = status.historical_last_result?.passed;
    const histDate = status.historical_last_run_at ? new Date(status.historical_last_run_at).toLocaleDateString() : 'Never';

    return (
        <Card className="border-l-4 border-l-blue-600">
            <CardHeader className="pb-2">
                <div className="flex justify-between items-start">
                    <div>
                        <CardTitle className="flex items-center gap-2">
                            Go-Live Readiness
                            <QuantumTooltip content="Tracks your progress towards live trading authorization based on paper trading streaks and historical validation." />
                        </CardTitle>
                        <CardDescription>System Validation Level 3</CardDescription>
                    </div>
                    <Badge variant={status.overall_ready ? "default" : "outline"} className={status.overall_ready ? "bg-green-600 hover:bg-green-700" : ""}>
                        {status.overall_ready ? (
                            <div className="flex items-center gap-1"><CheckCircle className="w-3 h-3" /> READY FOR LIVE</div>
                        ) : (
                            <div className="flex items-center gap-1"><History className="w-3 h-3" /> IN PROGRESS</div>
                        )}
                    </Badge>
                </div>
            </CardHeader>
            <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">

                    {/* Paper Readiness */}
                    <div className="space-y-4">
                        <div className="flex items-center justify-between">
                            <h3 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                                <FileText className="w-4 h-4" /> Paper Forward-Test
                            </h3>
                            <Badge variant={status.paper_ready ? "default" : "secondary"}>
                                Streak: {paperStreak}/{paperTarget}
                            </Badge>
                        </div>

                        {/* v4-L1: Fail-fast banner */}
                        {failFastTriggered && (
                            <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg p-3 flex items-start gap-2">
                                <AlertTriangle className="w-4 h-4 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
                                <div className="text-sm">
                                    <p className="font-medium text-red-800 dark:text-red-200">Window Reset Triggered</p>
                                    <p className="text-red-600 dark:text-red-400 text-xs mt-0.5">
                                        {status.paper_fail_fast_reason || "Performance threshold breached"}
                                    </p>
                                    {status.paper_checkpoint_last_run_at && (
                                        <p className="text-red-500 dark:text-red-500 text-xs mt-1">
                                            Last checkpoint: {new Date(status.paper_checkpoint_last_run_at).toLocaleString()}
                                        </p>
                                    )}
                                </div>
                            </div>
                        )}

                        <div className="bg-muted/50 p-4 rounded-lg space-y-3">
                            <div className="flex justify-between text-sm">
                                <span className="text-muted-foreground">Window ends:</span>
                                <span className="font-medium">{windowEnd.toLocaleDateString()} ({daysRemaining} days)</span>
                            </div>
                            <div className="w-full bg-secondary h-2 rounded-full overflow-hidden">
                                <div className="bg-blue-500 h-full transition-all" style={{ width: `${paperProgress}%` }}></div>
                            </div>
                            <div className="flex justify-between text-xs text-muted-foreground">
                                <span>Streak: {paperStreak} / {paperTarget} checkpoints</span>
                                <span>{paperProgress.toFixed(0)}%</span>
                            </div>
                            <div className="flex justify-end pt-2">
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={runPaperEval}
                                    disabled={runningPaper}
                                    className="h-7 text-xs"
                                >
                                    {runningPaper ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Play className="w-3 h-3 mr-1" />}
                                    Run Checkpoint
                                </Button>
                            </div>
                        </div>
                    </div>

                    {/* Historical Readiness */}
                    <div className="space-y-4 md:border-l md:pl-6">
                        <div className="flex items-center justify-between">
                            <h3 className="font-semibold text-sm uppercase tracking-wider text-muted-foreground flex items-center gap-2">
                                <History className="w-4 h-4" /> Historical Validation
                            </h3>
                            {status.historical_last_run_at ? (
                                <Badge variant={histPassed ? "default" : "destructive"} className={histPassed ? "bg-green-600/20 text-green-700 dark:text-green-300 hover:bg-green-600/30" : ""}>
                                    {histPassed ? "PASSED" : "FAILED"}
                                </Badge>
                            ) : (
                                <Badge variant="outline">PENDING</Badge>
                            )}
                        </div>

                        <div className="bg-muted/50 p-4 rounded-lg space-y-3">
                            <div className="flex justify-between text-sm">
                                <span className="text-muted-foreground">Last Run:</span>
                                <span className="font-medium">{histDate}</span>
                            </div>
                            {status.historical_last_result?.return_pct !== undefined && (
                                <div className="flex justify-between text-sm">
                                    <span className="text-muted-foreground">Return:</span>
                                    <span className={`font-mono font-bold ${status.historical_last_result.return_pct >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                        {status.historical_last_result.return_pct.toFixed(2)}%
                                    </span>
                                </div>
                            )}
                             <div className="flex justify-end pt-2">
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={runHistoricalSuite}
                                    disabled={runningHistorical}
                                    className="h-7 text-xs"
                                >
                                    {runningHistorical ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Play className="w-3 h-3 mr-1" />}
                                    Run Suite (90d)
                                </Button>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Recent Journal */}
                <div className="mt-6 pt-6 border-t">
                     <h4 className="text-sm font-semibold mb-3">Recent Validation Events</h4>
                     <div className="space-y-2">
                        {journal.length === 0 ? (
                            <p className="text-xs text-muted-foreground italic">No validation events recorded.</p>
                        ) : (
                            journal.map((entry) => (
                                <div key={entry.id} className="flex items-center justify-between text-xs p-2 hover:bg-muted/50 rounded transition-colors border border-transparent hover:border-border">
                                    <div className="flex items-center gap-2">
                                        {entry.title.includes("Passed") ? (
                                            <CheckCircle className="w-3 h-3 text-green-500" />
                                        ) : entry.title.includes("Failed") ? (
                                            <XCircle className="w-3 h-3 text-red-500" />
                                        ) : (
                                            <div className="w-3 h-3 rounded-full bg-gray-300" />
                                        )}
                                        <span className="font-medium">{entry.title}</span>
                                    </div>
                                    <div className="text-muted-foreground">
                                        {new Date(entry.created_at).toLocaleDateString()}
                                    </div>
                                </div>
                            ))
                        )}
                     </div>
                </div>
            </CardContent>
        </Card>
    );
}
