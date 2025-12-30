'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { fetchWithAuth } from '@/lib/api';
import { Suggestion, InboxResponse, InboxMeta } from '@/lib/types';
import SuggestionCard from './SuggestionCard';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, RefreshCw, ChevronDown, ChevronUp, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useToast } from '@/components/ui/use-toast';
import { cn } from '@/lib/utils';
import { QuantumTooltip } from '@/components/ui/QuantumTooltip';

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
                        // Read-only mode implied by lack of handlers,
                        // but SuggestionCard renders actions if not disabled.
                        // We can pass empty handlers or rely on status styling.
                        // Ideally SuggestionCard should have a 'readOnly' prop but it doesn't.
                        // However, we can just NOT pass handlers.
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
    const { toast } = useToast();

    // -- Actions --

    const fetchInbox = useCallback(async () => {
        setLoading(true);
        setError(null);
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

    useEffect(() => {
        fetchInbox();
    }, [fetchInbox]);

    const handleRefreshQuote = async (s: Suggestion) => {
        try {
            const res = await fetchWithAuth(`/suggestions/${s.id}/refresh-quote`, {
                method: 'POST'
            });
            if (res.quote) {
                 toast({ title: "Quote Refreshed", description: `Latest price for ${s.symbol}` });
                 // Optimistically update? Or just re-fetch inbox?
                 // Re-fetching inbox is safer to get re-ranked data.
                 fetchInbox();
            }
        } catch (e) {
            toast({ title: "Refresh Failed", description: "Could not fetch new quote.", variant: "destructive" });
        }
    };

    const handleDismiss = async (s: Suggestion, reason: string) => {
        try {
             // Optimistic Update
             if (data) {
                 const isHero = data.hero?.id === s.id;
                 const newQueue = data.queue.filter(i => i.id !== s.id);
                 let newHero = isHero ? null : data.hero;

                 // If hero dismissed, promote top of queue?
                 // The backend re-ranks, but for immediate UI feedback we might just remove it.
                 // Let's just remove it and wait for re-fetch or let user manually refresh if they want new rank.
                 // Better UX: Remove locally, then background fetch.

                 setData({
                     ...data,
                     hero: newHero,
                     queue: newQueue
                 });
             }

             await fetchWithAuth(`/suggestions/${s.id}/dismiss`, {
                 method: 'POST',
                 body: JSON.stringify({ reason })
             });

             toast({ title: "Dismissed", description: "Suggestion removed." });
             fetchInbox(); // Sync with backend for new hero/ranking
        } catch (e) {
             toast({ title: "Error", description: "Failed to dismiss suggestion", variant: "destructive" });
             fetchInbox(); // Revert on error
        }
    };

    const handleStage = async (s: Suggestion) => {
        try {
            // Check for batch endpoint usage as singular
            // Reuse logic from SuggestionTabs: /inbox/stage-batch with list
            const res = await fetchWithAuth('/inbox/stage-batch', {
                method: 'POST',
                body: JSON.stringify({ suggestion_ids: [s.id] })
            });

            if (res.staged_count > 0 || (res.staged && res.staged.length > 0)) {
                toast({ title: "Staged", description: "Trade moved to execution queue." });
                fetchInbox();
            } else {
                throw new Error("Stage failed");
            }
        } catch (e) {
             toast({ title: "Error", description: "Failed to stage trade.", variant: "destructive" });
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
                <Button onClick={fetchInbox} variant="outline" className="gap-2">
                    <RefreshCw className="w-4 h-4" /> Try Again
                </Button>
            </div>
        );
    }

    if (!data) return null;

    const { hero, queue, completed, meta } = data;
    const hasHero = !!hero;
    const hasQueue = queue && queue.length > 0;

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
                            suggestion={hero}
                            onStage={handleStage}
                            onDismiss={handleDismiss}
                            onRefreshQuote={handleRefreshQuote}
                            isStale={hero.is_stale} // Use backend staleness if available
                            // Hero is expanded/prominent by default structure of SuggestionCard
                        />
                    </div>
                ) : (
                    <Card className="border-dashed border-2 bg-muted/10">
                        <CardContent className="py-10 text-center text-muted-foreground">
                            <p>No high-priority suggestions right now.</p>
                            <Button variant="link" onClick={fetchInbox} className="mt-2">Check Again</Button>
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
                             Pending Queue ({queue.length})
                        </h3>
                        {queueExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </div>

                    {queueExpanded ? (
                        <div className="space-y-3 mt-2 pl-2 border-l-2 border-muted ml-2 animate-in slide-in-from-top-2 fade-in duration-200">
                             {queue.map(item => (
                                 <SuggestionCard
                                     key={item.id}
                                     suggestion={item}
                                     onStage={handleStage}
                                     onDismiss={handleDismiss}
                                     onRefreshQuote={handleRefreshQuote}
                                     isStale={item.is_stale}
                                 />
                             ))}
                        </div>
                    ) : (
                         <div className="text-xs text-muted-foreground pl-4 mt-1">
                             {queue.map(q => q.symbol).join(', ')}
                         </div>
                    )}
                </div>
            )}

            {/* Completed Section */}
            <CompletedList items={completed} />

        </div>
    );
}
