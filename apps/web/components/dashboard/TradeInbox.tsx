'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { fetchWithAuth } from '@/lib/api';
import { Suggestion, InboxResponse, InboxMeta } from '@/lib/types';
import SuggestionCard from './SuggestionCard';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Loader2, RefreshCw, ChevronDown, ChevronUp, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useToast } from '@/components/ui/use-toast';
import { QuantumTooltip } from '@/components/ui/QuantumTooltip';
import { useInboxActions } from '@/hooks/useInboxActions';

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
        stagingIds
    } = useInboxActions(fetchInbox);

    useEffect(() => {
        setLoading(true);
        fetchInbox();
    }, [fetchInbox]);


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
    // If hero is staged, we still show it but marked as staged, until refresh moves it to completed
    const hasHero = !!hero && !isHeroDismissed;

    const visibleQueue = queue.filter(q => !dismissedIds.has(q.id));
    const hasQueue = visibleQueue.length > 0;

    return (
        <div className="max-w-4xl mx-auto pb-10">
            {/* Meta Bar */}
            <InboxMetaBar meta={meta} isLoading={loading} />

            {/* Hero Section */}
            <div className="mb-6">
                <h2 className="text-lg font-semibold mb-3 flex items-center justify-between">
                    Top Opportunity
                    {loading && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />}
                </h2>

                {hasHero ? (
                    <div className="transform transition-all duration-300 hover:scale-[1.01]">
                        <SuggestionCard
                            suggestion={{...hero, staged: hero.staged || stagedIds.has(hero.id)}}
                            onStage={(s) => stageItems([s.id])}
                            onDismiss={(s, r) => dismissItem(s.id, r)}
                            onRefreshQuote={(s) => refreshQuote(s.id)}
                            isStale={isStale(hero)}
                            isStaging={stagingIds.has(hero.id)}
                        />
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
                    <div
                        className="flex items-center justify-between cursor-pointer py-2 hover:bg-muted/50 rounded px-2 transition-colors select-none"
                        onClick={() => setQueueExpanded(!queueExpanded)}
                    >
                        <h3 className="font-medium text-muted-foreground flex items-center gap-2">
                             Pending Queue ({visibleQueue.length})
                        </h3>
                        {queueExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </div>

                    {queueExpanded ? (
                        <div className="space-y-3 mt-2 pl-2 border-l-2 border-muted ml-2 animate-in slide-in-from-top-2 fade-in duration-200">
                             {visibleQueue.map(item => (
                                 <SuggestionCard
                                     key={item.id}
                                     suggestion={{...item, staged: item.staged || stagedIds.has(item.id)}}
                                     onStage={(s) => stageItems([s.id])}
                                     onDismiss={(s, r) => dismissItem(s.id, r)}
                                     onRefreshQuote={(s) => refreshQuote(s.id)}
                                     isStale={isStale(item)}
                                     isStaging={stagingIds.has(item.id)}
                                 />
                             ))}
                        </div>
                    ) : (
                         <div className="text-xs text-muted-foreground pl-4 mt-1">
                             {visibleQueue.map(q => q.symbol).join(', ')}
                         </div>
                    )}
                </div>
            )}

            {/* Completed Section */}
            <CompletedList items={completed} />

        </div>
    );
}
