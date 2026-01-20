'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { fetchWithAuth } from '@/lib/api';
import { Suggestion, InboxResponse, InboxMeta } from '@/lib/types';
import SuggestionCard from './SuggestionCard';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Loader2, RefreshCw, ChevronDown, ChevronUp, AlertCircle, CheckCircle2, Wand2, Filter, ShieldAlert } from 'lucide-react';
import { useToast } from '@/components/ui/use-toast';
import { QuantumTooltip } from '@/components/ui/QuantumTooltip';
import { useInboxActions } from '@/hooks/useInboxActions';

// --- Helpers ---
const displaySymbol = (s: Suggestion | { symbol?: string, ticker?: string }) => s.symbol ?? s.ticker ?? "Symbol";

// PR4: Check if suggestion is blocked by quality gate
const isBlocked = (s: Suggestion): boolean => {
    return s.status === 'NOT_EXECUTABLE' || !!s.blocked_reason;
};

// PR4: Filter types for inbox view
type InboxFilter = 'all' | 'executable' | 'blocked';

// --- Sub-components ---

const InboxMetaBar = ({ meta, isLoading }: { meta?: InboxMeta, isLoading: boolean }) => {
  if (!meta && isLoading) {
    return (
      <div className="flex justify-between items-center p-4 bg-muted/20 rounded-lg animate-pulse mb-4">
        <div className="h-4 w-24 bg-muted rounded"></div>
        <div className="h-4 w-24 bg-muted rounded"></div>
        <div className="h-4 w-24 bg-muted rounded"></div>
      </div>
    );
  }

  if (!meta) return null;

  return (
    <div className="grid grid-cols-3 gap-2 mb-4">
      <Card className="bg-card border-border shadow-sm">
        <CardContent className="p-3 flex flex-col items-center justify-center text-center">
            <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider">EV Available</span>
            <div className="text-lg font-bold text-green-600 dark:text-green-400">
               ${meta.total_ev_available > 0 ? meta.total_ev_available.toFixed(2) : '0.00'}
            </div>
        </CardContent>
      </Card>

      <Card className="bg-card border-border shadow-sm">
        <CardContent className="p-3 flex flex-col items-center justify-center text-center">
            <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider flex items-center gap-1">
               Capital <QuantumTooltip content="Deployable capital based on current risk model and cash" />
            </span>
            <div className="text-lg font-bold text-foreground">
               ${meta.deployable_capital.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </div>
        </CardContent>
      </Card>

      <Card className="bg-card border-border shadow-sm">
        <CardContent className="p-3 flex flex-col items-center justify-center text-center">
             <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider">Stale Threshold</span>
             <div className="text-lg font-bold text-foreground">
                {Math.round(meta.stale_after_seconds / 60)}m
             </div>
        </CardContent>
      </Card>
    </div>
  );
};

const CompletedList = ({ items }: { items: Suggestion[] }) => {
    if (!items || items.length === 0) return null;

    return (
        <div className="mt-8">
            <h3 className="text-sm font-medium text-muted-foreground mb-3 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4" />
                Completed Today ({items.length})
            </h3>
            <div className="space-y-2 opacity-75">
                {items.map(item => (
                    <SuggestionCard
                        key={item.id}
                        suggestion={item}
                        isStale={false}
                    />
                ))}
            </div>
        </div>
    );
};

// --- Main Component ---

export default function TradeInbox() {
    const [data, setData] = useState<InboxResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [queueExpanded, setQueueExpanded] = useState(false);

    // Selection / Batch Mode State
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const [isAutoSelecting, setIsAutoSelecting] = useState(false);
    const { toast } = useToast();

    // PR4: Filter state
    const [filter, setFilter] = useState<InboxFilter>('all');

    // -- Actions Hook --
    const fetchInbox = useCallback(async () => {
        // Don't set loading true if we already have data (background refresh)
        // But here we might want to if it's a full refresh requested by user
        // For now, let's keep it simple.
        try {
            const res = await fetchWithAuth('/inbox');
            if (res) {
                setData(res);
            } else {
                setError("No data received");
            }
        } catch (err: any) {
            console.error("Inbox Fetch Error:", err);
            setError(err.message || "Failed to load inbox");
        } finally {
            setLoading(false);
        }
    }, []);

    const {
        stageItems,
        dismissItem,
        refreshQuote,
        isStale,
        dismissedIds,
        stagedIds,
        stagingIds,
        isBatchLoading: isStagingBatch
    } = useInboxActions(fetchInbox);

    useEffect(() => {
        setLoading(true);
        fetchInbox();
    }, [fetchInbox]);

    // -- Handlers --

    const handleToggleSelect = useCallback((s: Suggestion) => {
        // PR4: Prevent selecting blocked suggestions for staging
        if (isBlocked(s)) {
            toast({
                variant: "destructive",
                title: "Cannot Select",
                description: "Blocked suggestions cannot be staged. Resolve the quality issue first."
            });
            return;
        }

        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(s.id)) next.delete(s.id);
            else next.add(s.id);
            return next;
        });
    }, [toast]);

    const handleAutoSelect = async () => {
        if (!data) return;
        setIsAutoSelecting(true);

        // PR4: Only include executable (non-blocked) suggestions in auto-select
        const allCandidates: Suggestion[] = [];
        if (data.hero && !dismissedIds.has(data.hero.id) && !isBlocked(data.hero)) {
            allCandidates.push(data.hero);
        }
        if (data.queue) {
            allCandidates.push(...data.queue.filter(q => !dismissedIds.has(q.id) && !isBlocked(q)));
        }

        if (allCandidates.length === 0) {
            setIsAutoSelecting(false);
            toast({
                description: "No executable suggestions available for auto-select.",
            });
            return;
        }

        try {
            // Map to CandidateTrade schema
            const candidates = allCandidates.map(s => ({
                id: s.id,
                symbol: displaySymbol(s),
                side: 'buy', // Default to buy for simplicity
                qty_max: 1, // Default to 1 unit selection
                ev_per_unit: s.metrics?.ev ?? (s.score ? s.score / 10.0 : 0.0), // Fallback EV proxy
                premium_per_unit: s.order_json?.price ?? 0.0,
                delta: s.delta_impact ?? 0.0,
                gamma: 0.0, // Assuming unavailable if not present
                vega: s.vega_impact ?? 0.0,
                tail_risk_contribution: 0.0
            }));

            const payload = {
                candidates,
                constraints: {
                    max_cash: data.meta.deployable_capital || 5000,
                    max_vega: 99999,
                    max_delta_abs: 99999,
                    max_gamma: 99999
                },
                parameters: {
                    mode: 'hybrid',
                    trial_mode: process.env.NEXT_PUBLIC_QCI_TRIAL_MODE === "1",
                    num_samples: 20,
                    lambda_tail: 1.0,
                    lambda_cash: 1.0,
                    lambda_vega: 1.0,
                    lambda_delta: 1.0,
                    lambda_gamma: 1.0,
                    max_candidates_for_dirac: 40,
                    max_dirac_calls: 2,
                    dirac_timeout_s: 10
                }
            };

            const res = await fetchWithAuth('/optimize/discrete', {
                method: 'POST',
                body: JSON.stringify(payload)
            });

            if (res && res.selected_trades) {
                const newSelectedIds = new Set<string>();
                res.selected_trades.forEach((t: any) => newSelectedIds.add(t.id));
                setSelectedIds(newSelectedIds);

                if (newSelectedIds.size === 0) {
                     toast({
                        description: "No batch found under current constraints.",
                     });
                } else {
                     toast({
                        title: "Auto-Selected Best Batch",
                        description: `Selected ${newSelectedIds.size} optimal trades.`,
                     });
                }
            }
        } catch (e) {
            console.error("Auto-select failed", e);
            toast({
                variant: "destructive",
                title: "Auto-Select Failed",
                description: "Couldn't auto-select. Try again."
            });
        } finally {
            setIsAutoSelecting(false);
        }
    };

    const handleStageSelected = async () => {
        const ids = Array.from(selectedIds);
        // stageItems handles batch staging in the hook
        const success = await stageItems(ids);
        if (success) {
            setSelectedIds(new Set()); // Clear selection on success
        }
    };


    // -- Render --

    if (loading && !data) {
        return (
            <div className="space-y-4 animate-pulse">
                <div className="flex gap-4">
                     <div className="h-20 bg-muted rounded w-1/3"></div>
                     <div className="h-20 bg-muted rounded w-1/3"></div>
                     <div className="h-20 bg-muted rounded w-1/3"></div>
                </div>
                <div className="h-64 bg-muted rounded"></div>
                <div className="h-10 bg-muted rounded"></div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-8 text-center border rounded-lg bg-muted/20">
                <AlertCircle className="w-10 h-10 mx-auto text-destructive mb-3" />
                <h3 className="font-medium text-lg">Unable to load Inbox</h3>
                <p className="text-muted-foreground mb-4">{error}</p>
                <Button onClick={() => { setLoading(true); fetchInbox(); }} variant="outline" className="gap-2">
                    <RefreshCw className="w-4 h-4" /> Try Again
                </Button>
            </div>
        );
    }

    if (!data) return null;

    const { hero, queue, completed, meta } = data;

    // Filter out dismissed items optimistically
    const isHeroDismissed = hero && dismissedIds.has(hero.id);

    // PR4: Apply filter to hero and queue
    const applyFilter = (s: Suggestion): boolean => {
        if (filter === 'all') return true;
        if (filter === 'executable') return !isBlocked(s);
        if (filter === 'blocked') return isBlocked(s);
        return true;
    };

    const hasHero = !!hero && !isHeroDismissed && applyFilter(hero);
    const visibleQueue = queue.filter(q => !dismissedIds.has(q.id) && applyFilter(q));
    const hasQueue = visibleQueue.length > 0;

    // PR4: Count blocked vs executable for filter badges
    const allActive = [hero, ...queue].filter((s): s is Suggestion => !!s && !dismissedIds.has(s.id));
    const blockedCount = allActive.filter(isBlocked).length;
    const executableCount = allActive.filter(s => !isBlocked(s)).length;

    // Only executable (non-blocked) items can be selected for staging/auto-select
    const totalCandidates = executableCount;
    const isSelectionEnabled = totalCandidates > 0;

    return (
        <div className="max-w-4xl mx-auto pb-10">
            {/* Meta Bar */}
            <InboxMetaBar meta={meta} isLoading={loading} />

            {/* Action Bar */}
            <div className="flex justify-between items-center mb-6">
                 <div className="flex gap-2">
                    <Button
                        onClick={handleAutoSelect}
                        disabled={isAutoSelecting || !isSelectionEnabled}
                        className="gap-2 bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white shadow-sm transition-all"
                    >
                        {isAutoSelecting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
                        {isAutoSelecting ? "Selecting..." : "Auto-Select Best Batch"}
                    </Button>

                    {selectedIds.size > 0 && (
                        <Button
                            onClick={handleStageSelected}
                            disabled={isStagingBatch}
                            variant="secondary"
                            className="gap-2 animate-in fade-in slide-in-from-left-2 duration-200"
                        >
                            {isStagingBatch && <Loader2 className="w-4 h-4 animate-spin" />}
                            Stage Selected ({selectedIds.size})
                        </Button>
                    )}
                 </div>

                 {/* PR4: Filter Controls */}
                 <div className="flex items-center gap-1">
                    <Filter className="w-4 h-4 text-muted-foreground mr-1" />
                    <Button
                        variant={filter === 'all' ? 'secondary' : 'ghost'}
                        size="sm"
                        onClick={() => setFilter('all')}
                        className="h-7 px-2 text-xs"
                    >
                        All ({allActive.length})
                    </Button>
                    <Button
                        variant={filter === 'executable' ? 'secondary' : 'ghost'}
                        size="sm"
                        onClick={() => setFilter('executable')}
                        className="h-7 px-2 text-xs"
                    >
                        Executable ({executableCount})
                    </Button>
                    {blockedCount > 0 && (
                        <Button
                            variant={filter === 'blocked' ? 'secondary' : 'ghost'}
                            size="sm"
                            onClick={() => setFilter('blocked')}
                            className="h-7 px-2 text-xs text-orange-600 dark:text-orange-400"
                        >
                            <ShieldAlert className="w-3 h-3 mr-1" />
                            Blocked ({blockedCount})
                        </Button>
                    )}
                 </div>
            </div>

            {/* Hero Section */}
            <div className="mb-6">
                <h2 className="text-lg font-semibold mb-3 flex items-center justify-between">
                    Top Opportunity
                    {loading && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
                </h2>

                {hasHero ? (
                    <div className="transform transition-all duration-300 hover:scale-[1.01]">
                        <div className="flex gap-3">
                            <div className="pt-8">
                                <Checkbox
                                    checked={selectedIds.has(hero.id)}
                                    onChange={() => handleToggleSelect(hero)}
                                    className="checked:bg-purple-600 checked:border-purple-600"
                                    aria-label={`Select ${displaySymbol(hero)} for batch action`}
                                />
                            </div>
                            <div className="flex-1">
                                <SuggestionCard
                                    suggestion={{...hero, staged: hero.staged || stagedIds.has(hero.id)}}
                                    onStage={(s) => stageItems([s.id])}
                                    onDismiss={(s, r) => dismissItem(s.id, r)}
                                    onRefreshQuote={(s) => refreshQuote(s.id, displaySymbol(s))}
                                    isStale={isStale(hero)}
                                    isStaging={stagingIds.has(hero.id)}
                                />
                            </div>
                        </div>
                    </div>
                ) : (
                    <Card className="border-dashed border-2 bg-muted/10">
                        <CardContent className="py-10 text-center text-muted-foreground">
                            <p>No high-priority suggestions right now.</p>
                            <Button variant="link" onClick={() => { setLoading(true); fetchInbox(); }} className="mt-2">Check Again</Button>
                        </CardContent>
                    </Card>
                )}
            </div>

            {/* Queue Section */}
            {hasQueue && (
                <div className="mb-6">
                    <button
                        type="button"
                        className="w-full flex items-center justify-between py-2 hover:bg-muted/50 rounded px-2 transition-colors select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => setQueueExpanded(!queueExpanded)}
                        aria-expanded={queueExpanded}
                        aria-controls="pending-queue-list"
                    >
                        <span className="font-medium text-muted-foreground flex items-center gap-2">
                             Pending Queue ({visibleQueue.length})
                        </span>
                        {queueExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </button>

                    {queueExpanded ? (
                        <div
                            id="pending-queue-list"
                            className="space-y-3 mt-2 pl-2 border-l-2 border-muted ml-2 animate-in slide-in-from-top-2 fade-in duration-200"
                        >
                             {visibleQueue.map(item => (
                                 <div key={item.id} className="flex gap-3">
                                     <div className="pt-8">
                                        <Checkbox
                                            checked={selectedIds.has(item.id)}
                                            onChange={() => handleToggleSelect(item)}
                                            className="checked:bg-purple-600 checked:border-purple-600"
                                            aria-label={`Select ${displaySymbol(item)} for batch action`}
                                        />
                                     </div>
                                     <div className="flex-1">
                                         <SuggestionCard
                                             suggestion={{...item, staged: item.staged || stagedIds.has(item.id)}}
                                             onStage={(s) => stageItems([s.id])}
                                             onDismiss={(s, r) => dismissItem(s.id, r)}
                                             onRefreshQuote={(s) => refreshQuote(s.id, displaySymbol(s))}
                                             isStale={isStale(item)}
                                             isStaging={stagingIds.has(item.id)}
                                         />
                                     </div>
                                 </div>
                             ))}
                        </div>
                    ) : (
                         <div className="text-xs text-muted-foreground pl-4 mt-1">
                             {visibleQueue.map(q => displaySymbol(q)).join(', ')}
                         </div>
                    )}
                </div>
            )}

            {/* Completed Section */}
            <CompletedList items={completed} />

        </div>
    );
}
