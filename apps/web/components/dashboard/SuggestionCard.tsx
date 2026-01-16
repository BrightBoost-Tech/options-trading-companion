'use client';

import React, { useEffect, useRef, memo, useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Suggestion } from '@/lib/types';
import { logEvent } from '@/lib/analytics';
import { QuantumTooltip } from '@/components/ui/QuantumTooltip';
import { X, RefreshCw, Clock, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';

interface SuggestionCardProps {
    suggestion: Suggestion;
    onStage?: (suggestion: Suggestion) => void;
    onModify?: (suggestion: Suggestion) => void;
    onDismiss?: (suggestion: Suggestion, tag: string) => void;
    onRefreshQuote?: (suggestion: Suggestion) => void;

    isStale?: boolean;
    batchModeEnabled?: boolean;
    isSelected?: boolean;
    onToggleSelect?: (suggestion: Suggestion) => void;
    isStaging?: boolean;
}

const SuggestionCard = ({
    suggestion,
    onStage,
    onModify,
    onDismiss,
    onRefreshQuote,
    isStale = false,
    batchModeEnabled = false,
    isSelected = false,
    onToggleSelect,
    isStaging = false
}: SuggestionCardProps) => {
    const { order_json, score, metrics, iv_regime, iv_rank, delta_impact, theta_impact, staged } = suggestion;
    const [dismissOpen, setDismissOpen] = useState(false);
    const [isRefreshing, setIsRefreshing] = useState(false);
    // Cast to any to access optional agent_summary without changing global type
    const agent_summary = (suggestion as any).agent_summary;
    const hasLoggedView = useRef(false);
    const firstDismissReasonRef = useRef<HTMLButtonElement>(null);
    const displaySymbol = suggestion.display_symbol ?? suggestion.symbol ?? suggestion.ticker ?? '---';
    const exitPrice = typeof order_json?.limit_price === 'number'
        ? order_json.limit_price
        : order_json?.limit_price !== undefined
            ? Number(order_json.limit_price)
            : undefined;
    const histStats = suggestion.historical_stats;
    const winRatePct = typeof histStats?.win_rate === 'number' ? histStats.win_rate * 100 : undefined;
    const avgPnl = typeof histStats?.avg_pnl === 'number' ? histStats.avg_pnl : undefined;
    const sampleSize = histStats?.sample_size ?? 0;

    // Analytics: Log View on Mount (or IntersectionObserver for strictly viewport)
    // For simplicity, we log on mount if not already logged.
    useEffect(() => {
        if (!hasLoggedView.current) {
            logEvent({
                eventName: "suggestion_viewed",
                category: "ux",
                properties: {
                    suggestion_id: suggestion.id,
                    symbol: suggestion.symbol,
                    strategy: suggestion.strategy,
                    window: suggestion.window,
                    iv_regime,
                    score
                }
            });
            hasLoggedView.current = true;
        }
    }, [suggestion.id, suggestion.symbol, suggestion.strategy, suggestion.window, iv_regime, score]);

    // Focus management for dismiss actions
    useEffect(() => {
        if (dismissOpen) {
            // Small timeout to allow render to complete and element to be mounted
            const timer = setTimeout(() => {
                firstDismissReasonRef.current?.focus();
            }, 0);
            return () => clearTimeout(timer);
        }
    }, [dismissOpen]);

    // Payoff Diagram Helper (Simple V-shape or hockey stick)
    const renderPayoffDiagram = () => {
        return (
            <svg
                viewBox="0 0 100 40"
                className="w-full h-full text-green-500 opacity-20"
                role="img"
                aria-label="Payoff diagram preview"
            >
                <path d="M0,40 L40,40 L60,10 L100,10" fill="none" stroke="currentColor" strokeWidth="2" />
                <line x1="0" y1="40" x2="100" y2="40" stroke="currentColor" className="text-muted-foreground/50" strokeWidth="1" strokeDasharray="2,2" />
            </svg>
        );
    };

    const getIVBadgeColor = (regime?: string) => {
        if (!regime) return 'bg-muted text-foreground';
        const r = regime.toLowerCase();
        if (r.includes('elevated') || r.includes('high')) return 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400';
        if (r.includes('suppressed') || r.includes('low')) return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400';
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400';
    };

    // Analytics Wrappers for Actions
    const handleStage = () => {
        if (isStale || isStaging) return; // Guard
        logEvent({
            eventName: "suggestion_staged",
            category: "ux",
            properties: {
                suggestion_id: suggestion.id,
                symbol: suggestion.symbol,
                window: suggestion.window,
                strategy: suggestion.strategy,
                iv_regime: suggestion.iv_regime,
                trace_id: suggestion.trace_id ?? null,
            }
        });
        onStage && onStage(suggestion);
    };

    const handleModify = () => {
        logEvent({
            eventName: "suggestion_modify_clicked",
            category: "ux",
            properties: { suggestion_id: suggestion.id, symbol: suggestion.symbol }
        });
        onModify && onModify(suggestion);
    };

    const handleDismiss = (reason: string) => {
        logEvent({
            eventName: "suggestion_dismissed",
            category: "ux",
            properties: {
                suggestion_id: suggestion.id,
                symbol: suggestion.symbol,
                reason: reason
            }
        });
        onDismiss && onDismiss(suggestion, reason);
        setDismissOpen(false);
    };

    const handleRefresh = async (e: React.MouseEvent) => {
        e.stopPropagation();
        if (isRefreshing || !onRefreshQuote) return;
        setIsRefreshing(true);
        try {
             await onRefreshQuote(suggestion);
        } finally {
             setIsRefreshing(false);
        }
    };

    return (
        <Card className={`mb-3 border-l-4 ${staged ? 'border-l-green-500' : 'border-l-purple-500'} hover:shadow-md transition-shadow bg-card border-border`}>
            <CardContent className="p-4 relative">
                {/* Batch Selection Checkbox */}
                {batchModeEnabled && onToggleSelect && (
                     <div className="absolute top-4 left-[-30px] md:left-[-30px] flex items-center justify-center h-full w-[30px]">
                        <Checkbox
                            checked={isSelected}
                            onChange={() => onToggleSelect(suggestion)}
                            className="checked:bg-purple-600 checked:border-purple-600"
                            aria-label={`Select ${displaySymbol}`}
                            title={`Select ${displaySymbol}`}
                        />
                     </div>
                )}

                {/* Header */}
                <div className="flex justify-between items-start mb-2">
                    <div>
                        <div className="flex items-center gap-2">
                            {batchModeEnabled && onToggleSelect && (
                                <Checkbox
                                    checked={isSelected}
                                    onChange={() => onToggleSelect(suggestion)}
                                    className="mr-2 md:hidden checked:bg-purple-600 checked:border-purple-600"
                                    aria-label={`Select ${displaySymbol}`}
                                />
                            )}
                            <span className="font-bold text-lg text-foreground">{displaySymbol}</span>
                            <span className="text-sm font-medium text-muted-foreground">{suggestion.strategy}</span>
                            {suggestion.expiration && (
                                <span className="text-xs text-muted-foreground border border-border px-1 rounded">{suggestion.expiration}</span>
                            )}
                        </div>

                        {/* Rationale / Historical Stats (Morning Suggestions) */}
                        {suggestion.window === 'morning_limit' && (
                            <div className="mt-1 mb-1 space-y-0.5">
                                {exitPrice !== undefined && !Number.isNaN(exitPrice) && (
                                    <p className="text-xs text-foreground font-medium">
                                        Exit @ ${exitPrice.toFixed(2)}
                                    </p>
                                )}
                                {suggestion.rationale && (
                                    <p className="text-xs text-muted-foreground italic">
                                        {suggestion.rationale}
                                    </p>
                                )}
                                {histStats && (
                                    <div className="text-[10px] text-muted-foreground">
                                        <div className="font-semibold text-muted-foreground">Historical stats</div>
                                        <p>
                                            {sampleSize} exits |
                                            Win Rate: {winRatePct !== undefined ? winRatePct.toFixed(0) : '--'}% |
                                            Avg P&L: ${avgPnl !== undefined ? avgPnl.toFixed(2) : '--'}
                                        </p>
                                    </div>
                                )}
                            </div>
                        )}

                        <div className="flex gap-2 mt-1">
                             {/* IV Context */}
                             {iv_regime && (
                                <Badge className={`text-[10px] px-1 py-0 ${getIVBadgeColor(iv_regime)}`}>
                                    IV: {iv_regime} ({iv_rank?.toFixed(0) || '--'})
                                </Badge>
                             )}
                             {/* Score/Conviction */}
                             {score !== undefined && (
                                <Badge className="text-[10px] bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300 px-1 py-0">
                                    Score: {score.toFixed(0)}
                                </Badge>
                             )}

                             {/* Agent Summary Chip */}
                             {agent_summary && (
                                <>
                                    {(agent_summary.decision === 'VETOED' || agent_summary.vetoed) ? (
                                        <Badge variant="destructive" className="text-[10px] h-5 px-1.5 ml-1">
                                            VETOED
                                        </Badge>
                                    ) : (typeof agent_summary.overall_score === 'number') && (
                                        <Badge variant="secondary" className="text-[10px] h-5 px-1.5 bg-indigo-50 text-indigo-700 border-indigo-100 hover:bg-indigo-100 ml-1">
                                            Confidence {Math.round(agent_summary.overall_score <= 1.0 ? agent_summary.overall_score * 100 : agent_summary.overall_score)}%
                                        </Badge>
                                    )}
                                    <QuantumTooltip
                                        label="Why this trade?"
                                        className="ml-1"
                                        content={
                                            (agent_summary.top_reasons?.length)
                                                ? agent_summary.top_reasons.map((r: string) => `• ${r}`).join(' ')
                                                : "Suggested based on your positions, volatility regime, and risk model. Always confirm it fits your own plan."
                                        }
                                    />
                                </>
                             )}
                        </div>
                    </div>
                    <div className="text-right">
                        <div className="font-bold text-green-600 dark:text-green-400 text-sm">EV: ${metrics?.ev?.toFixed(2) || '--'}</div>
                        <div className="text-xs text-muted-foreground">Win Rate: {(metrics?.win_rate || 0) * 100}%</div>
                    </div>
                </div>

                {/* Body - Legs & Risk */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 my-3 text-sm">
                    {/* Legs */}
                    <div className="col-span-2 space-y-1">
                        {order_json?.legs?.map((leg, idx) => {
                            const rawAction = leg.action ?? "";
                            const actionLabel = rawAction.toUpperCase();
                            const actionClass =
                                rawAction === "buy"
                                    ? "text-green-600 dark:text-green-400"
                                    : rawAction === "sell"
                                    ? "text-red-600 dark:text-red-400"
                                    : "text-muted-foreground";

                            const qty = typeof leg.quantity === "number" ? leg.quantity : 0;
                            const typeLabel =
                                leg.type === "call" ? "C" :
                                leg.type === "put"  ? "P"  :
                                "";
                            const strike = leg.strike ?? "";

                            // Prefer friendly display symbol if available (especially for full ticker)
                            // But for legs we often just want Qty Type Strike
                            const legDisplay = leg.display_symbol ?? `${qty > 0 ? "+" : ""}${qty} ${typeLabel} ${strike}`;

                            return (
                                <div key={idx} className="flex justify-between border-b border-border last:border-0 py-1">
                                    <span className="text-muted-foreground text-xs truncate max-w-[200px]" title={leg.display_symbol}>
                                        {leg.display_symbol ?? `${qty > 0 ? "+" : ""}${qty} ${typeLabel} ${strike}`}
                                    </span>
                                    <span className={`text-xs font-mono ${actionClass}`}>
                                        {actionLabel}
                                    </span>
                                </div>
                            );
                        })}
                    </div>

                    {/* Payoff & Impact */}
                    <div className="relative border border-border rounded bg-muted/30 p-2 flex flex-col justify-between">
                         <div className="h-8 w-full">
                            {renderPayoffDiagram()}
                         </div>
                         <div className="flex justify-between text-xs mt-2 text-muted-foreground font-mono">
                            <span>Δ {delta_impact ? (delta_impact > 0 ? '+' : '') + delta_impact.toFixed(1) : '--'}</span>
                            <span>Θ {theta_impact ? (theta_impact > 0 ? '+' : '') + theta_impact.toFixed(1) : '--'}</span>
                         </div>
                    </div>
                </div>

                {/* Risk Metadata Row */}
                {suggestion.sizing_metadata && (
                    <div className="mb-3 p-2 bg-muted/30 border border-border rounded text-xs text-muted-foreground flex flex-wrap items-center gap-2">
                        {/* Compact metrics */}
                        <span>
                            Max loss: ${suggestion.sizing_metadata.max_loss_total?.toFixed(2) ?? '--'}
                        </span>
                        <span className="text-muted-foreground/50">•</span>
                        <span>
                            Collateral: ${suggestion.sizing_metadata.capital_required?.toFixed(2) ?? '--'}
                        </span>
                        <span className="text-muted-foreground/50">•</span>
                        <span>
                            Risk mult: {suggestion.sizing_metadata.risk_multiplier?.toFixed(2) ?? '--'}
                        </span>

                        {/* Clamp Reason Badge */}
                        {(suggestion.sizing_metadata.clamped_by || suggestion.sizing_metadata.clamp_reason) && (
                            <Badge variant="outline" className="ml-auto text-[10px] bg-red-50 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-900/50">
                                {suggestion.sizing_metadata.clamp_reason ?? suggestion.sizing_metadata.clamped_by}
                            </Badge>
                        )}
                    </div>
                )}

                {/* Footer Actions */}
                <div className="flex justify-end gap-2 mt-3 pt-2 border-t border-border items-center">
                    {/* Stale Warning / Refresh */}
                    {isStale && !staged && (
                        <div className="flex items-center gap-2 mr-auto">
                            <span className="text-xs text-orange-600 dark:text-orange-400 flex items-center gap-1">
                                <Clock className="w-3 h-3" aria-hidden="true" />
                                Stale
                            </span>
                            <Button
                                variant="outline"
                                size="sm"
                                className="h-6 text-[10px] px-2"
                                onClick={handleRefresh}
                                disabled={isRefreshing}
                            >
                                <RefreshCw className={`w-3 h-3 mr-1 ${isRefreshing ? 'animate-spin' : ''}`} />
                                Refresh Quote
                            </Button>
                        </div>
                    )}

                    {/* Dismiss Popover/Buttons */}
                    <div className="relative group">
                         {dismissOpen ? (
                             <div className="flex items-center gap-1.5 animate-in fade-in zoom-in duration-200 origin-right">
                                 <Button
                                    ref={firstDismissReasonRef}
                                    variant="outline"
                                    onClick={() => handleDismiss('too_risky')}
                                    className="h-7 px-3 text-xs font-medium bg-red-100 text-red-700 hover:bg-red-200 hover:text-red-800 dark:bg-red-900/30 dark:text-red-400 dark:hover:bg-red-900/50 border-red-200 dark:border-red-900"
                                    aria-label={`Dismiss ${displaySymbol} as too risky`}
                                 >
                                     Too Risky
                                 </Button>
                                 <Button
                                    variant="outline"
                                    onClick={() => handleDismiss('bad_price')}
                                    className="h-7 px-3 text-xs font-medium bg-yellow-100 text-yellow-700 hover:bg-yellow-200 hover:text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400 dark:hover:bg-yellow-900/50 border-yellow-200 dark:border-yellow-900"
                                    aria-label={`Dismiss ${displaySymbol} due to bad price`}
                                 >
                                     Bad Price
                                 </Button>
                                 <Button
                                    variant="outline"
                                    onClick={() => handleDismiss('wrong_timing')}
                                    className="h-7 px-3 text-xs font-medium bg-slate-100 text-slate-700 hover:bg-slate-200 hover:text-slate-800 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700 border-slate-200 dark:border-slate-700"
                                    aria-label={`Dismiss ${displaySymbol} due to wrong timing`}
                                 >
                                     Timing
                                 </Button>
                                 <Button
                                    variant="ghost"
                                    onClick={() => setDismissOpen(false)}
                                    className="h-7 w-7 p-0 rounded-md text-muted-foreground hover:text-foreground"
                                    aria-label="Cancel dismiss"
                                 >
                                     <X className="w-4 h-4" />
                                 </Button>
                             </div>
                         ) : (
                             <Button
                                 variant="ghost"
                                 onClick={() => setDismissOpen(true)}
                                 className="h-7 px-3 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50"
                                 aria-label={`Dismiss suggestion for ${displaySymbol}`}
                             >
                                 Dismiss
                             </Button>
                         )}
                    </div>

                    <Button
                        variant="outline"
                        onClick={handleModify}
                        className="h-7 px-3 text-xs bg-card border-border hover:bg-muted/50"
                        aria-label={`Modify trade parameters for ${displaySymbol}`}
                    >
                        Modify
                    </Button>

                    <Button
                        onClick={handleStage}
                        disabled={(isStale && !staged) || isStaging}
                        className={`h-7 text-xs px-3 font-medium transition-colors gap-1 ${
                            staged
                                ? 'bg-green-100 text-green-800 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400 dark:hover:bg-green-900/50'
                                : isStale
                                    ? 'bg-muted text-muted-foreground hover:bg-muted cursor-not-allowed opacity-70'
                                    : 'bg-purple-600 text-white hover:bg-purple-700'
                        }`}
                        aria-label={staged ? `Trade for ${displaySymbol} is staged` : `Stage trade for ${displaySymbol}`}
                    >
                        {isStaging && <Loader2 className="w-3 h-3 animate-spin" />}
                        {staged ? 'Staged' : 'Stage Trade'}
                    </Button>
                </div>
            </CardContent>
        </Card>
    );
};

export default memo(SuggestionCard);
