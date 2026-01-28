'use client';

import React, { useEffect, useRef, memo, useState, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Suggestion, TraceResponse } from '@/lib/types';
import { logEvent } from '@/lib/analytics';
import { fetchWithAuth } from '@/lib/api';
import { QuantumTooltip } from '@/components/ui/QuantumTooltip';
import { X, RefreshCw, Clock, Loader2, ShieldAlert, AlertTriangle, ChevronDown, ChevronUp, Shield, ShieldCheck, ShieldX, Info, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { useToast } from '@/components/ui/use-toast';

// v4: Card mode for context-aware behavior
type CardMode = 'DEFAULT' | 'PAPER_INBOX';

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
    // v4: Mode for context-aware behavior (PAPER_INBOX hides execute buttons)
    mode?: CardMode;
}

// v4: Integrity badge component
const IntegrityBadge = ({ status }: { status: string }) => {
    const config = {
        VERIFIED: { icon: ShieldCheck, color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400 border-green-200 dark:border-green-900', label: 'Verified' },
        TAMPERED: { icon: ShieldX, color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 border-red-200 dark:border-red-900', label: 'Tampered' },
        UNVERIFIED: { icon: Shield, color: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 border-gray-200 dark:border-gray-700', label: 'Unverified' },
    }[status] || { icon: Shield, color: 'bg-gray-100 text-gray-600', label: status };

    const Icon = config.icon;
    return (
        <Badge variant="outline" className={`text-[10px] h-5 px-1.5 ${config.color}`}>
            <Icon className="w-3 h-3 mr-1" />
            {config.label}
        </Badge>
    );
};

// v4-polish: Normalized driver item for schema-tolerant rendering
interface NormalizedDriver {
    label: string;
    detail?: string;
}

/**
 * v4-polish: Normalize drivers_agents to handle multiple schema shapes.
 * Priority: name/agent/model -> label, signal/reason/feature/summary -> detail
 */
function normalizeDriversAgents(driversAgents: any): NormalizedDriver[] {
    if (!driversAgents || !Array.isArray(driversAgents)) return [];

    return driversAgents.slice(0, 5).map((d: any) => {
        if (!d || typeof d !== 'object') {
            return { label: String(d ?? 'Unknown') };
        }

        // Label priority: name > agent > model > first string key
        const label = d.name ?? d.agent ?? d.model ?? d.label ??
            (typeof d === 'string' ? d : Object.keys(d)[0] ?? 'Unknown');

        // Detail priority: signal > reason > feature > summary > score/weight formatting
        let detail = d.signal ?? d.reason ?? d.feature ?? d.summary;
        if (!detail && (d.score !== undefined || d.weight !== undefined)) {
            const score = d.score ?? d.weight;
            detail = `score: ${typeof score === 'number' ? score.toFixed(2) : score}`;
        }

        return { label: String(label), detail: detail ? String(detail) : undefined };
    }).filter((d: NormalizedDriver) => d.label !== 'Unknown' || d.detail);
}

/**
 * v4-polish: Normalize drivers_regime to handle multiple schema shapes.
 * Returns a formatted string for display.
 */
function normalizeRegime(driversRegime: any): string | null {
    if (!driversRegime) return null;

    // If it's a plain string, use directly
    if (typeof driversRegime === 'string') {
        return driversRegime;
    }

    if (typeof driversRegime !== 'object') {
        return String(driversRegime);
    }

    // Standard shape: { regime, context }
    if (driversRegime.regime) {
        const base = String(driversRegime.regime);
        return driversRegime.context ? `${base} — ${driversRegime.context}` : base;
    }

    // Alternative shape: { effective, global, local }
    const parts: string[] = [];
    if (driversRegime.effective !== undefined) parts.push(`effective=${driversRegime.effective}`);
    if (driversRegime.global !== undefined) parts.push(`global=${driversRegime.global}`);
    if (driversRegime.local !== undefined) parts.push(`local=${driversRegime.local}`);

    if (parts.length > 0) {
        return parts.join(' | ');
    }

    // Fallback: stringify first few keys
    const keys = Object.keys(driversRegime).slice(0, 3);
    if (keys.length > 0) {
        return keys.map(k => `${k}=${driversRegime[k]}`).join(', ');
    }

    return null;
}

/**
 * v4-polish: Normalize vetoes to handle multiple schema shapes.
 */
function normalizeVetoes(vetoes: any): NormalizedDriver[] {
    if (!vetoes || !Array.isArray(vetoes)) return [];

    return vetoes.slice(0, 3).map((v: any) => {
        if (!v || typeof v !== 'object') {
            return { label: 'Veto', detail: String(v ?? 'Unknown reason') };
        }

        // Label priority: agent > name > source
        const label = v.agent ?? v.name ?? v.source ?? 'Veto';

        // Detail priority: reason > message > detail
        const detail = v.reason ?? v.message ?? v.detail ?? 'No reason given';

        return { label: String(label), detail: String(detail) };
    });
}

/**
 * v4-polish: Check if attribution has any recognized content
 */
function hasRecognizedAttribution(attribution: any): boolean {
    if (!attribution || typeof attribution !== 'object') return false;

    const normalizedDrivers = normalizeDriversAgents(attribution.drivers_agents);
    const normalizedRegime = normalizeRegime(attribution.drivers_regime);
    const normalizedVetoes = normalizeVetoes(attribution.vetoes);

    return normalizedDrivers.length > 0 || normalizedRegime !== null || normalizedVetoes.length > 0;
}

// v4: Details Drawer component (lazy loads trace data)
const DetailsDrawer = ({ traceId, isExpanded, id }: { traceId?: string; isExpanded: boolean; id: string }) => {
    const [traceData, setTraceData] = useState<TraceResponse | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const hasFetched = useRef(false);

    useEffect(() => {
        if (!isExpanded || !traceId || hasFetched.current) return;

        const fetchTrace = async () => {
            setLoading(true);
            setError(null);
            try {
                const res = await fetchWithAuth(`/observability/trace/${traceId}`);
                setTraceData(res);
            } catch (e: any) {
                if (e?.status === 404) {
                    setError('No v4 trace available');
                } else {
                    setError('Failed to load trace details');
                }
            } finally {
                setLoading(false);
                hasFetched.current = true;
            }
        };
        fetchTrace();
    }, [isExpanded, traceId]);

    if (!isExpanded) return null;

    if (!traceId) {
        return (
            <div id={id} className="mt-3 p-3 bg-muted/30 border border-border rounded-md text-xs text-muted-foreground">
                <Info className="w-4 h-4 inline mr-1" />
                No v4 trace available for this suggestion
            </div>
        );
    }

    if (loading) {
        return (
            <div id={id} className="mt-3 p-3 bg-muted/30 border border-border rounded-md flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading trace details...
            </div>
        );
    }

    if (error) {
        return (
            <div id={id} className="mt-3 p-3 bg-muted/30 border border-border rounded-md text-xs text-muted-foreground">
                <Info className="w-4 h-4 inline mr-1" />
                {error}
            </div>
        );
    }

    if (!traceData) return null;

    const { status, lifecycle } = traceData;
    const attribution = lifecycle?.attribution;
    const auditLog = lifecycle?.audit_log || [];

    // v4-polish: Use normalized helpers for schema tolerance
    const normalizedDrivers = normalizeDriversAgents(attribution?.drivers_agents);
    const normalizedRegime = normalizeRegime(attribution?.drivers_regime);
    const normalizedVetoes = normalizeVetoes(attribution?.vetoes);
    const hasRecognized = hasRecognizedAttribution(attribution);

    return (
        <div id={id} className="mt-3 p-3 bg-muted/20 border border-border rounded-md space-y-3">
            {/* Integrity Badge */}
            <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-muted-foreground">Integrity:</span>
                <IntegrityBadge status={status} />
            </div>

            {/* Top Drivers */}
            {(normalizedDrivers.length > 0 || normalizedVetoes.length > 0) && (
                <div>
                    <span className="text-xs font-medium text-muted-foreground block mb-1">Top Drivers:</span>
                    <div className="space-y-1">
                        {normalizedDrivers.slice(0, 3).map((d, i) => (
                            <div key={i} className="text-xs text-foreground flex items-start gap-1">
                                <span className="text-green-600 dark:text-green-400">+</span>
                                <span>{d.label}{d.detail ? `: ${d.detail}` : ''}</span>
                            </div>
                        ))}
                        {normalizedVetoes.slice(0, 2).map((v, i) => (
                            <div key={`veto-${i}`} className="text-xs text-foreground flex items-start gap-1">
                                <span className="text-red-600 dark:text-red-400">-</span>
                                <span>{v.label}: {v.detail}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Regime Context */}
            {normalizedRegime && (
                <div>
                    <span className="text-xs font-medium text-muted-foreground block mb-1">Regime Context:</span>
                    <div className="text-xs text-foreground">
                        {normalizedRegime}
                    </div>
                </div>
            )}

            {/* Attribution present but unrecognized shape */}
            {attribution && !hasRecognized && (
                <div className="text-xs text-muted-foreground">
                    <span>Attribution present (unrecognized shape)</span>
                    <div className="mt-1 text-[10px] opacity-70">
                        Keys: {Object.keys(attribution).slice(0, 5).join(', ')}
                        {Object.keys(attribution).length > 5 && '...'}
                    </div>
                </div>
            )}

            {/* No attribution fallback */}
            {!attribution && (
                <div className="text-xs text-muted-foreground">
                    No attribution available
                </div>
            )}

            {/* Audit Events (Collapsed) */}
            {auditLog.length > 0 && (
                <details className="text-xs">
                    <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                        Audit Events ({auditLog.length})
                    </summary>
                    <div className="mt-2 space-y-1 pl-2 border-l border-border">
                        {auditLog.slice(0, 10).map((evt, i) => (
                            <div key={i} className="text-muted-foreground">
                                <span className="font-mono">{evt.event}</span>
                                <span className="ml-2 opacity-60">
                                    {new Date(evt.timestamp).toLocaleTimeString()}
                                </span>
                            </div>
                        ))}
                    </div>
                </details>
            )}
        </div>
    );
};

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
    isStaging = false,
    mode = 'DEFAULT'
}: SuggestionCardProps) => {
    const { order_json, score, metrics, iv_regime, iv_rank, delta_impact, theta_impact, staged } = suggestion;
    const { toast } = useToast();
    const [dismissOpen, setDismissOpen] = useState(false);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [detailsExpanded, setDetailsExpanded] = useState(false);
    // Cast to any to access optional agent_summary without changing global type
    const agent_summary = (suggestion as any).agent_summary;
    // v4: Access decision_lineage for constraints
    const decision_lineage = (suggestion as any).decision_lineage;
    const active_constraints = decision_lineage?.active_constraints;
    const hasLoggedView = useRef(false);
    const firstDismissReasonRef = useRef<HTMLButtonElement>(null);
    const displaySymbol = suggestion.display_symbol ?? suggestion.symbol ?? suggestion.ticker ?? '---';
    const detailsId = `details-${suggestion.id}`;

    // v4: Compute confidence percentage (prefer agent_summary.overall_score, fallback to score)
    const confidenceValue = (() => {
        if (agent_summary?.overall_score !== undefined) {
            const val = agent_summary.overall_score;
            // Normalize: if <= 1, treat as 0-1 scale; else assume 0-100
            return val <= 1 ? Math.round(val * 100) : Math.round(val);
        }
        if (score !== undefined) {
            // Score is typically 0-100
            return Math.round(score);
        }
        return null;
    })();

    // PR4: Detect blocked state from quality gate
    const isBlocked = suggestion.status === 'NOT_EXECUTABLE' || !!suggestion.blocked_reason;
    const blockedReason = suggestion.blocked_reason;
    const blockedDetail = suggestion.blocked_detail;
    const marketdataQuality = suggestion.marketdata_quality;
    const effectiveAction = marketdataQuality?.effective_action;
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

    // PR4: Get badge info for effective action
    const getEffectiveActionBadge = (action?: string) => {
        if (!action) return null;
        switch (action) {
            case 'skip_fatal':
                return { label: 'Fatal Quality', color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 border-red-200 dark:border-red-900' };
            case 'skip_policy':
                return { label: 'Blocked by Policy', color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400 border-red-200 dark:border-red-900' };
            case 'defer':
                return { label: 'Deferred', color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400 border-yellow-200 dark:border-yellow-900' };
            case 'downrank':
                return { label: 'Downranked', color: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-400 border-orange-200 dark:border-orange-900' };
            case 'downrank_fallback_to_defer':
                return { label: 'Deferred (Fallback)', color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400 border-yellow-200 dark:border-yellow-900' };
            default:
                return { label: action, color: 'bg-muted text-muted-foreground' };
        }
    };

    // PR4: Parse blocked_detail for display
    const parseBlockedDetail = (detail?: string): Array<{ symbol: string; code: string }> => {
        if (!detail) return [];
        return detail.split('|').map(part => {
            const [symbol, code] = part.split(':');
            return { symbol: symbol || '?', code: code || '?' };
        }).filter(item => item.symbol !== '?' || item.code !== '?');
    };

    // Analytics Wrappers for Actions
    const handleStage = () => {
        if (isStale || isStaging || isBlocked) return; // Guard - PR4: also block if blocked
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

    const handleCopySymbol = async (e: React.MouseEvent | React.KeyboardEvent) => {
        e.stopPropagation();
        try {
            await navigator.clipboard.writeText(displaySymbol);
            toast({
                title: "Copied symbol",
                description: `${displaySymbol} copied to clipboard`,
            });
        } catch (err) {
            // Fallback or silence
        }
    };

    return (
        <Card className={`mb-3 border-l-4 ${
            isBlocked
                ? 'border-l-orange-500 opacity-90'
                : staged
                    ? 'border-l-green-500'
                    : 'border-l-purple-500'
        } hover:shadow-md transition-shadow bg-card border-border`}>
            <CardContent className="p-4 relative">
                {/* PR4: Blocked Banner */}
                {isBlocked && (
                    <div className="mb-3 p-2 bg-orange-50 dark:bg-orange-950/30 border border-orange-200 dark:border-orange-900 rounded-md">
                        <div className="flex items-start gap-2">
                            <ShieldAlert className="w-4 h-4 text-orange-600 dark:text-orange-400 mt-0.5 flex-shrink-0" />
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-xs font-medium text-orange-800 dark:text-orange-300">
                                        Not Executable
                                    </span>
                                    {effectiveAction && getEffectiveActionBadge(effectiveAction) && (
                                        <Badge
                                            variant="outline"
                                            className={`text-[10px] h-4 px-1 ${getEffectiveActionBadge(effectiveAction)!.color}`}
                                        >
                                            {getEffectiveActionBadge(effectiveAction)!.label}
                                        </Badge>
                                    )}
                                </div>
                                {blockedDetail && (
                                    <div className="mt-1 flex flex-wrap gap-1">
                                        {parseBlockedDetail(blockedDetail).map((item, idx) => (
                                            <Badge
                                                key={idx}
                                                variant="outline"
                                                className="text-[9px] h-4 px-1 bg-orange-100/50 dark:bg-orange-900/20 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-800"
                                            >
                                                {item.symbol}: {item.code}
                                            </Badge>
                                        ))}
                                    </div>
                                )}
                                {marketdataQuality?.symbols && marketdataQuality.symbols.length > 0 && !blockedDetail && (
                                    <div className="mt-1 flex flex-wrap gap-1">
                                        {marketdataQuality.symbols.map((sym, idx) => (
                                            <Badge
                                                key={idx}
                                                variant="outline"
                                                className={`text-[9px] h-4 px-1 ${
                                                    sym.code.startsWith('FAIL')
                                                        ? 'bg-red-100/50 dark:bg-red-900/20 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800'
                                                        : sym.code.startsWith('WARN')
                                                            ? 'bg-yellow-100/50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300 border-yellow-200 dark:border-yellow-800'
                                                            : 'bg-muted text-muted-foreground'
                                                }`}
                                            >
                                                {sym.symbol}: {sym.code}
                                                {sym.score !== null && sym.score !== undefined && ` (${sym.score})`}
                                            </Badge>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                )}

                {/* Batch Selection Checkbox - PR4.1: Always render container for consistent alignment */}
                {batchModeEnabled && onToggleSelect && (
                     <div className="absolute top-4 left-[-30px] md:left-[-30px] flex items-center justify-center h-full w-[30px]">
                        {isBlocked ? (
                            // PR4.1: Disabled checkbox placeholder for blocked items (maintains alignment)
                            <Checkbox
                                checked={false}
                                disabled
                                className="opacity-30 cursor-not-allowed"
                                aria-label={`Blocked suggestion ${displaySymbol} cannot be selected`}
                                title="Blocked - cannot be selected"
                            />
                        ) : (
                            <Checkbox
                                checked={isSelected}
                                onChange={() => onToggleSelect(suggestion)}
                                className="checked:bg-purple-600 checked:border-purple-600"
                                aria-label={`Select ${displaySymbol}`}
                                title={`Select ${displaySymbol}`}
                            />
                        )}
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
                            <div
                                className="flex items-center gap-1 group cursor-pointer hover:bg-muted/50 rounded px-1 -ml-1 transition-colors"
                                onClick={handleCopySymbol}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault();
                                        handleCopySymbol(e);
                                    }
                                }}
                                role="button"
                                tabIndex={0}
                                aria-label={`Copy ${displaySymbol} to clipboard`}
                                title="Click to copy symbol"
                            >
                                <span className="font-bold text-lg text-foreground group-hover:underline decoration-dotted underline-offset-4">{displaySymbol}</span>
                                <Copy className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" aria-hidden="true" />
                            </div>
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

                        <div className="flex gap-2 mt-1 flex-wrap">
                             {/* v4: First-class Confidence Badge */}
                             {confidenceValue !== null && (
                                <Badge className="text-[10px] h-5 px-1.5 bg-indigo-50 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300 border-indigo-100 dark:border-indigo-900">
                                    Confidence {confidenceValue}%
                                </Badge>
                             )}

                             {/* IV Context */}
                             {iv_regime && (
                                <Badge className={`text-[10px] px-1 py-0 ${getIVBadgeColor(iv_regime)}`}>
                                    IV: {iv_regime} ({iv_rank?.toFixed(0) || '--'})
                                </Badge>
                             )}

                             {/* Agent Summary VETO indicator */}
                             {agent_summary && (agent_summary.decision === 'VETOED' || agent_summary.vetoed) && (
                                <Badge variant="destructive" className="text-[10px] h-5 px-1.5">
                                    VETOED
                                </Badge>
                             )}

                             {/* Why tooltip */}
                             {agent_summary?.top_reasons?.length > 0 && (
                                <QuantumTooltip
                                    label="Why this trade?"
                                    className="ml-1"
                                    content={agent_summary.top_reasons.map((r: string) => `• ${r}`).join(' ')}
                                />
                             )}
                        </div>

                        {/* v4: Constraints Chips Row */}
                        {active_constraints && active_constraints.length > 0 && (
                            <div className="flex gap-1 mt-1.5 flex-wrap">
                                {active_constraints.slice(0, 5).map((constraint: string, idx: number) => (
                                    <Badge
                                        key={idx}
                                        variant="outline"
                                        className="text-[9px] h-4 px-1 bg-yellow-50 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-400 border-yellow-200 dark:border-yellow-900"
                                    >
                                        {constraint}
                                    </Badge>
                                ))}
                            </div>
                        )}
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

                {/* v4: Details Drawer */}
                <DetailsDrawer traceId={suggestion.trace_id} isExpanded={detailsExpanded} id={detailsId} />

                {/* Footer Actions */}
                <div className="flex justify-end gap-2 mt-3 pt-2 border-t border-border items-center">
                    {/* v4: Details Button */}
                    <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDetailsExpanded(!detailsExpanded)}
                        className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground mr-auto"
                        aria-expanded={detailsExpanded}
                        aria-controls={detailsId}
                    >
                        {detailsExpanded ? <ChevronUp className="w-3 h-3 mr-1" /> : <ChevronDown className="w-3 h-3 mr-1" />}
                        Details
                    </Button>

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
                        disabled={(isStale && !staged) || isStaging || isBlocked}
                        className={`h-7 text-xs px-3 font-medium transition-colors gap-1 ${
                            staged
                                ? 'bg-green-100 text-green-800 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400 dark:hover:bg-green-900/50'
                                : isBlocked
                                    ? 'bg-orange-100 text-orange-600 hover:bg-orange-100 cursor-not-allowed opacity-70 dark:bg-orange-900/30 dark:text-orange-400'
                                    : isStale
                                        ? 'bg-muted text-muted-foreground hover:bg-muted cursor-not-allowed opacity-70'
                                        : 'bg-purple-600 text-white hover:bg-purple-700'
                        }`}
                        aria-label={
                            isBlocked
                                ? `Cannot stage ${displaySymbol} - blocked by quality gate`
                                : staged
                                    ? `Trade for ${displaySymbol} is staged`
                                    : `Stage trade for ${displaySymbol}`
                        }
                    >
                        {isStaging && <Loader2 className="w-3 h-3 animate-spin" />}
                        {isBlocked && <ShieldAlert className="w-3 h-3" />}
                        {staged ? 'Staged' : isBlocked ? 'Blocked' : 'Stage Trade'}
                    </Button>
                </div>
            </CardContent>
        </Card>
    );
};

export default memo(SuggestionCard);
