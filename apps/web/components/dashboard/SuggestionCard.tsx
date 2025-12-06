'use client';

import React, { useEffect, useRef } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Suggestion } from '@/lib/types';
import { logEvent } from '@/lib/analytics';

interface SuggestionCardProps {
    suggestion: Suggestion;
    onStage?: (suggestion: Suggestion) => void;
    onModify?: (suggestion: Suggestion) => void;
    onDismiss?: (suggestion: Suggestion, tag: string) => void;
}

export default function SuggestionCard({ suggestion, onStage, onModify, onDismiss }: SuggestionCardProps) {
    const { order_json, score, metrics, iv_regime, iv_rank, delta_impact, theta_impact, staged } = suggestion;
    const hasLoggedView = useRef(false);

    // Analytics: Log View on Mount (or IntersectionObserver for strictly viewport)
    // For simplicity, we log on mount if not already logged.
    useEffect(() => {
        if (!hasLoggedView.current) {
            logEvent("suggestion_viewed", "ux", {
                suggestion_id: suggestion.id,
                symbol: suggestion.symbol,
                strategy: suggestion.strategy,
                window: suggestion.window,
                iv_regime,
                score
            });
            hasLoggedView.current = true;
        }
    }, [suggestion.id, suggestion.symbol, suggestion.strategy, suggestion.window, iv_regime, score]);

    // Payoff Diagram Helper (Simple V-shape or hockey stick)
    const renderPayoffDiagram = () => {
        return (
            <svg viewBox="0 0 100 40" className="w-full h-full text-green-500 opacity-20">
                <path d="M0,40 L40,40 L60,10 L100,10" fill="none" stroke="currentColor" strokeWidth="2" />
                <line x1="0" y1="40" x2="100" y2="40" stroke="#ccc" strokeWidth="1" strokeDasharray="2,2" />
            </svg>
        );
    };

    const getIVBadgeColor = (regime?: string) => {
        if (!regime) return 'bg-gray-100 text-gray-800';
        const r = regime.toLowerCase();
        if (r.includes('elevated') || r.includes('high')) return 'bg-orange-100 text-orange-800';
        if (r.includes('suppressed') || r.includes('low')) return 'bg-blue-100 text-blue-800';
        return 'bg-green-100 text-green-800';
    };

    // Analytics Wrappers for Actions
    const handleStage = () => {
        logEvent("suggestion_staged", "ux", { suggestion_id: suggestion.id, symbol: suggestion.symbol });
        onStage && onStage(suggestion);
    };

    const handleModify = () => {
        logEvent("suggestion_expanded", "ux", { suggestion_id: suggestion.id, symbol: suggestion.symbol }); // Treating 'Modify' as expanding details/edit
        onModify && onModify(suggestion);
    };

    const handleDismiss = () => {
        logEvent("suggestion_dismissed", "ux", { suggestion_id: suggestion.id, symbol: suggestion.symbol, reason: 'skipped' });
        onDismiss && onDismiss(suggestion, 'skipped');
    };

    return (
        <Card className="mb-3 border-l-4 border-l-purple-500 hover:shadow-md transition-shadow">
            <CardContent className="p-4">
                {/* Header */}
                <div className="flex justify-between items-start mb-2">
                    <div>
                        <div className="flex items-center gap-2">
                            <span className="font-bold text-lg">{suggestion.symbol}</span>
                            <span className="text-sm font-medium text-gray-600">{suggestion.strategy}</span>
                            {suggestion.expiration && (
                                <span className="text-xs text-gray-400 border px-1 rounded">{suggestion.expiration}</span>
                            )}
                        </div>
                        <div className="flex gap-2 mt-1">
                             {/* IV Context */}
                             {iv_regime && (
                                <Badge className={`text-[10px] px-1 py-0 ${getIVBadgeColor(iv_regime)}`}>
                                    IV: {iv_regime} ({iv_rank?.toFixed(0) || '--'})
                                </Badge>
                             )}
                             {/* Score/Conviction */}
                             {score !== undefined && (
                                <Badge className="text-[10px] bg-purple-100 text-purple-800 px-1 py-0">
                                    Score: {score.toFixed(0)}
                                </Badge>
                             )}
                        </div>
                    </div>
                    <div className="text-right">
                        <div className="font-bold text-green-600 text-sm">EV: ${metrics?.ev?.toFixed(2) || '--'}</div>
                        <div className="text-xs text-gray-500">Win Rate: {(metrics?.win_rate || 0) * 100}%</div>
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
                                    ? "text-green-600"
                                    : rawAction === "sell"
                                    ? "text-red-600"
                                    : "text-gray-500";

                            const qty = typeof leg.quantity === "number" ? leg.quantity : 0;
                            const typeLabel =
                                leg.type === "call" ? "C" :
                                leg.type === "put"  ? "P"  :
                                "";
                            const strike = leg.strike ?? "";

                            return (
                                <div key={idx} className="flex justify-between border-b border-gray-100 last:border-0 py-1">
                                    <span className="text-gray-600">
                                        {qty > 0 ? "+" : ""}{qty} {typeLabel} {strike}
                                    </span>
                                    <span className={`text-xs font-mono ${actionClass}`}>
                                        {actionLabel}
                                    </span>
                                </div>
                            );
                        })}
                    </div>

                    {/* Payoff & Impact */}
                    <div className="relative border rounded bg-gray-50 p-2 flex flex-col justify-between">
                         <div className="h-8 w-full">
                            {renderPayoffDiagram()}
                         </div>
                         <div className="flex justify-between text-xs mt-2 text-gray-500 font-mono">
                            <span>Δ {delta_impact ? (delta_impact > 0 ? '+' : '') + delta_impact.toFixed(1) : '--'}</span>
                            <span>Θ {theta_impact ? (theta_impact > 0 ? '+' : '') + theta_impact.toFixed(1) : '--'}</span>
                         </div>
                    </div>
                </div>

                {/* Footer Actions */}
                <div className="flex justify-end gap-2 mt-3 pt-2 border-t border-gray-100">
                    <button
                        onClick={handleDismiss}
                        className="text-xs text-gray-400 hover:text-gray-600 px-2 py-1"
                    >
                        Dismiss
                    </button>
                    <button
                        onClick={handleModify}
                        className="text-xs bg-white border border-gray-300 text-gray-700 px-3 py-1 rounded hover:bg-gray-50"
                    >
                        Modify
                    </button>
                    <button
                        onClick={handleStage}
                        className={`text-xs px-3 py-1 rounded font-medium ${staged ? 'bg-green-100 text-green-800' : 'bg-purple-600 text-white hover:bg-purple-700'}`}
                    >
                        {staged ? 'Staged' : 'Stage Trade'}
                    </button>
                </div>
            </CardContent>
        </Card>
    );
}
