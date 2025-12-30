'use client';

import { useState, useRef, useEffect } from 'react';
import SuggestionCard from './SuggestionCard';
import { Suggestion } from '@/lib/types';
import { Sparkles, Activity, Sun, Clock, FileText, CheckSquare, Loader2 } from 'lucide-react';
import WeeklyReportList from '../suggestions/WeeklyReportList';
import { RefreshCw } from 'lucide-react';
import { logEvent } from '@/lib/analytics';
import { Button } from '@/components/ui/button';
import { fetchWithAuth } from '@/lib/api';
import { useToast } from '@/components/ui/use-toast';

interface SuggestionTabsProps {
  optimizerSuggestions: Suggestion[];
  scoutSuggestions: Suggestion[];
  journalQueue: Suggestion[];
  morningSuggestions: Suggestion[];
  middaySuggestions: Suggestion[];
  weeklyReports: any[];
  onRefreshScout: () => void;
  scoutLoading: boolean;
  onRefreshJournal: () => void;
}

// Helper for mapping dismiss reasons (legacy support if Card sends labels)
const CANONICAL_REASONS: Record<string, string> = {
  "Risky": "too_risky",
  "Too Risky": "too_risky",
  "Price": "bad_price",
  "Bad Price": "bad_price",
  "Timing": "wrong_timing",
  "Wrong Timing": "wrong_timing"
};

export default function SuggestionTabs({
  optimizerSuggestions,
  scoutSuggestions,
  journalQueue,
  morningSuggestions,
  middaySuggestions,
  weeklyReports,
  onRefreshScout,
  scoutLoading,
  onRefreshJournal
}: SuggestionTabsProps) {
  const [activeTab, setActiveTab] = useState<'morning' | 'midday' | 'rebalance' | 'scout' | 'journal' | 'weekly'>('morning');
  const [stagedIds, setStagedIds] = useState<string[]>([]); // Locally staged, visually distinct
  const [dismissedIds, setDismissedIds] = useState<string[]>([]); // Locally dismissed for optimistic UI
  const [selectedIds, setSelectedIds] = useState<string[]>([]); // Batch selection
  const [isBatchLoading, setIsBatchLoading] = useState(false);
  const [stagingIds, setStagingIds] = useState<string[]>([]); // Track which specific IDs are currently staging
  const [refreshedAtMap, setRefreshedAtMap] = useState<Record<string, number>>({}); // id -> timestamp (ms)
  const tabListRef = useRef<HTMLDivElement>(null);
  const { toast } = useToast();

  // Tabs configuration for cleaner rendering and accessibility
  const tabs = [
    { id: 'morning', label: 'Morning', icon: Sun, count: morningSuggestions.filter(s => !dismissedIds.includes(s.id)).length, color: 'orange' },
    { id: 'midday', label: 'Midday', icon: Clock, count: middaySuggestions.filter(s => !dismissedIds.includes(s.id)).length, color: 'blue' },
    { id: 'rebalance', label: 'Rebalance', icon: Activity, count: optimizerSuggestions.filter(s => !dismissedIds.includes(s.id)).length, color: 'indigo' },
    { id: 'scout', label: 'Scout', icon: Sparkles, count: scoutSuggestions.filter(s => !dismissedIds.includes(s.id)).length, color: 'green' },
    { id: 'journal', label: 'Journal', icon: null, textIcon: '📖', count: journalQueue.filter(s => !dismissedIds.includes(s.id)).length, color: 'purple' },
    { id: 'weekly', label: 'Reports', icon: FileText, count: 0, color: 'slate' },
  ] as const;

  const executeBatchStage = async (idsToStage: string[]) => {
      if (idsToStage.length === 0) return;

      const isBatchUI = idsToStage.length > 1;
      if (isBatchUI) setIsBatchLoading(true);
      else setStagingIds(prev => [...prev, ...idsToStage]);

      try {
          const res = await fetchWithAuth('/inbox/stage-batch', {
              method: 'POST',
              body: JSON.stringify({ suggestion_ids: idsToStage })
          });

          // Support new staged[] / failed[] and legacy staged_count / failed_ids
          // staged[] might be strings OR objects { id, order_id }
          const rawStaged = res.staged || [];
          const successfulIds: string[] = [];

          rawStaged.forEach((item: any) => {
              if (typeof item === 'string') {
                  successfulIds.push(item);
              } else if (item && typeof item === 'object') {
                  if (item.id) {
                      successfulIds.push(item.id);
                      if (!item.order_id) {
                          console.warn(`[BatchStage] Staged item ${item.id} missing order_id`);
                      }
                  }
              }
          });

          const failedItems: any[] = res.failed || [];
          const failedIds: string[] = res.failed_ids || failedItems.map((f: any) => f.id) || [];

          // Fallback if staged[] is missing but staged_count indicates success
          if (successfulIds.length === 0 && res.staged_count > 0 && failedIds.length === 0) {
              // Assume all succeeded if no specific failures returned
              successfulIds.push(...idsToStage);
          }

          if (successfulIds.length > 0) {
               setStagedIds(prev => Array.from(new Set([...prev, ...successfulIds])));

               if (isBatchUI || successfulIds.length > 1) {
                   toast({
                       title: "Staged",
                       description: `Successfully staged ${successfulIds.length} suggestions.`
                   });
               } else {
                   toast({ title: "Staged", description: "Suggestion moved to staged queue." });
               }

               // Clear selection if it matches the batch
               if (isBatchUI) setSelectedIds([]);
          }

          if (failedIds.length > 0) {
               toast({
                   title: "Partial Failure",
                   description: `Failed to stage ${failedIds.length} items.`,
                   variant: "destructive"
               });
          }
      } catch (e) {
          toast({ title: "Error", description: "Stage request failed", variant: "destructive" });
      } finally {
          if (isBatchUI) setIsBatchLoading(false);
          else setStagingIds(prev => prev.filter(id => !idsToStage.includes(id)));
      }
  };

  const handleStage = (s: Suggestion) => {
      if (stagingIds.includes(s.id)) return; // Prevent double click
      executeBatchStage([s.id]);
  };

  const handleBatchStage = () => {
      executeBatchStage(selectedIds);
  };

  const handleModify = (s: Suggestion) => {};

  const handleDismiss = async (s: Suggestion, reasonLabel: string) => {
      const reason = CANONICAL_REASONS[reasonLabel] || reasonLabel;

      // Optimistic UI update
      setDismissedIds(prev => [...prev, s.id]);

      try {
          await fetchWithAuth(`/suggestions/${s.id}/dismiss`, {
              method: 'POST',
              body: JSON.stringify({ reason }),
          });
          toast({ title: "Dismissed", description: `Suggestion dismissed.` });
      } catch (e) {
          // Rollback on error
          setDismissedIds(prev => prev.filter(id => id !== s.id));
          toast({ title: "Error", description: "Failed to dismiss suggestion", variant: "destructive" });
      }
  };

  const handleTabChange = (tabId: typeof activeTab) => {
      setActiveTab(tabId);
      setSelectedIds([]); // Clear selection on tab change
      logEvent({
          eventName: 'suggestion_tab_changed',
          category: 'ux',
          properties: { tab: tabId }
      });
  };

  const handleToggleSelect = (s: Suggestion) => {
      setSelectedIds(prev =>
          prev.includes(s.id) ? prev.filter(id => id !== s.id) : [...prev, s.id]
      );
  };

  const handleRefreshQuote = async (s: Suggestion) => {
      try {
          const res = await fetchWithAuth(`/suggestions/${s.id}/refresh-quote`, {
              method: 'POST'
          });
          if (res.refreshed_at) {
               setRefreshedAtMap(prev => ({
                   ...prev,
                   [s.id]: new Date(res.refreshed_at).getTime()
               }));
               toast({ title: "Quote Refreshed", description: "Latest market data fetched." });
          }
      } catch (e) {
          toast({ title: "Refresh Failed", description: "Could not fetch new quote.", variant: "destructive" });
      }
  };

  // Helper to determine if a suggestion is stale
  const checkIsStale = (s: Suggestion) => {
      if (s.staged) return false;
      const refreshedTime = refreshedAtMap[s.id];
      const now = Date.now();

      // 1. Check local refresh within 5 minutes
      if (refreshedTime && (now - refreshedTime < 5 * 60 * 1000)) {
          return false;
      }

      // 2. Check server-provided flag
      if (s.is_stale === true) {
          return true;
      }

      // 3. Fallback: Creation time > 5 mins (if is_stale is undefined/null)
      if (s.is_stale === undefined) {
          const createdTime = s.created_at ? new Date(s.created_at).getTime() : 0;
          if (now - createdTime > 5 * 60 * 1000) {
              return true;
          }
      }
      return false;
  };

  const renderCard = (s: Suggestion, idx: number) => {
      if (dismissedIds.includes(s.id)) return null;

      return (
          <SuggestionCard
            key={s.id || idx}
            suggestion={{...s, staged: s.staged || stagedIds.includes(s.id)}}
            onStage={handleStage}
            onModify={handleModify}
            onDismiss={handleDismiss}
            onRefreshQuote={handleRefreshQuote}
            isStale={checkIsStale(s)}
            batchModeEnabled={true}
            isSelected={selectedIds.includes(s.id)}
            onToggleSelect={handleToggleSelect}
            isStaging={stagingIds.includes(s.id)}
          />
      );
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const currentIndex = tabs.findIndex(t => t.id === activeTab);
      let nextIndex;
      if (e.key === 'ArrowRight') {
        nextIndex = (currentIndex + 1) % tabs.length;
      } else {
        nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
      }
      const nextTab = tabs[nextIndex];
      handleTabChange(nextTab.id);
      const buttons = tabListRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
      buttons?.[nextIndex]?.focus();
    }
  };

  return (
    <div className="bg-card rounded-lg shadow overflow-hidden h-full flex flex-col border border-border">
      {/* Tabs Header */}
      <div
        ref={tabListRef}
        role="tablist"
        aria-label="Trading Opportunities"
        className="flex border-b border-border overflow-x-auto no-scrollbar bg-muted/20"
        onKeyDown={handleKeyDown}
      >
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          const Icon = tab.icon;
          // Colors map: orange, blue, indigo, green, purple, slate
          let activeClass = '';
          let badgeClass = '';

          if (tab.color === 'orange') {
             activeClass = 'border-orange-500 text-orange-600 dark:text-orange-400 bg-orange-50/50 dark:bg-orange-900/10';
             badgeClass = 'bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400';
          } else if (tab.color === 'blue') {
             activeClass = 'border-blue-500 text-blue-600 dark:text-blue-400 bg-blue-50/50 dark:bg-blue-900/10';
             badgeClass = 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400';
          } else if (tab.color === 'indigo') {
             activeClass = 'border-indigo-500 text-indigo-600 dark:text-indigo-400 bg-indigo-50/50 dark:bg-indigo-900/10';
             badgeClass = 'bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400';
          } else if (tab.color === 'green') {
             activeClass = 'border-green-500 text-green-600 dark:text-green-400 bg-green-50/50 dark:bg-green-900/10';
             badgeClass = 'bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400';
          } else if (tab.color === 'purple') {
             activeClass = 'border-purple-500 text-purple-600 dark:text-purple-400 bg-purple-50/50 dark:bg-purple-900/10';
             badgeClass = 'bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400';
          } else { // slate
             activeClass = 'border-slate-500 text-slate-600 dark:text-slate-400 bg-slate-50/50 dark:bg-slate-900/10';
          }

          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${tab.id}`}
              id={`tab-${tab.id}`}
              tabIndex={isActive ? 0 : -1}
              onClick={() => handleTabChange(tab.id)}
              className={`flex-1 py-4 px-2 min-w-[120px] text-sm font-medium text-center border-b-2 transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring ${
                isActive
                  ? activeClass
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/50'
              }`}
            >
              <div className="flex items-center justify-center gap-2">
                {Icon ? <Icon className="w-4 h-4" /> : <span>{tab.textIcon}</span>}
                {tab.label}
                {tab.count > 0 && (
                  <span className={`${badgeClass} py-0.5 px-2 rounded-full text-xs`}>
                    {tab.count}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Batch Action Bar */}
      {selectedIds.length > 0 && (
          <div className="bg-purple-50 dark:bg-purple-900/20 border-b border-purple-100 dark:border-purple-800 p-2 flex justify-between items-center animate-in slide-in-from-top-2">
              <span className="text-xs font-medium text-purple-700 dark:text-purple-300 ml-2">
                  {selectedIds.length} selected
              </span>
              <div className="flex gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs"
                    onClick={() => setSelectedIds([])}
                  >
                      Cancel
                  </Button>
                  <Button
                    size="sm"
                    className="h-7 text-xs bg-purple-600 hover:bg-purple-700 text-white gap-1"
                    onClick={handleBatchStage}
                    disabled={isBatchLoading}
                  >
                      {isBatchLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckSquare className="w-3 h-3" />}
                      Stage Selected
                  </Button>
              </div>
          </div>
      )}

      {/* Tab Content */}
      <div
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        className="p-4 flex-1 overflow-y-auto bg-muted/20 min-h-[400px]"
      >

        {activeTab === 'morning' && (
             morningSuggestions.filter(s => !dismissedIds.includes(s.id)).length === 0 ? (
               <div className="text-center py-10 text-muted-foreground">
                 <p>No morning suggestions.</p>
               </div>
             ) : (
                morningSuggestions.map((s, i) => renderCard(s, i))
             )
        )}

        {activeTab === 'midday' && (
             middaySuggestions.filter(s => !dismissedIds.includes(s.id)).length === 0 ? (
                <div className="text-center py-10 text-muted-foreground">
                  <p>No midday suggestions.</p>
                </div>
              ) : (
                 middaySuggestions.map((s, i) => renderCard(s, i))
              )
        )}

        {activeTab === 'weekly' && (
          <WeeklyReportList reports={weeklyReports} />
        )}

        {activeTab === 'rebalance' && (
            optimizerSuggestions.filter(s => !dismissedIds.includes(s.id)).length === 0 ? (
               <div className="text-center py-10 text-muted-foreground">
                 <Activity className="w-10 h-10 mx-auto mb-3 opacity-20" />
                 <p>No rebalance suggestions.</p>
                 <p className="text-xs mt-1">Run the optimizer to generate trades.</p>
               </div>
            ) : (
               optimizerSuggestions.map((s, idx) => renderCard(s, idx))
            )
        )}

        {activeTab === 'scout' && (
          <div className="space-y-4">
            <div className="flex justify-end mb-2">
                <button
                  onClick={onRefreshScout}
                  disabled={scoutLoading}
                  className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1 hover:underline disabled:opacity-50"
                >
                  <RefreshCw className={`w-3 h-3 ${scoutLoading ? 'animate-spin' : ''}`} />
                  Refresh
                </button>
            </div>

            {scoutSuggestions.filter(s => !dismissedIds.includes(s.id)).length === 0 ? (
               <div className="text-center py-10 text-muted-foreground">
                 <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-20" />
                 <p>No scout picks found.</p>
               </div>
            ) : (
               scoutSuggestions.map((opp, idx) => renderCard(opp, idx))
            )}
          </div>
        )}

        {activeTab === 'journal' && (
          <div className="space-y-4">
            {journalQueue.filter(s => !dismissedIds.includes(s.id)).length === 0 ? (
               <div className="text-center py-10 text-muted-foreground">
                 <p>Journal queue is empty.</p>
                 <p className="text-xs mt-1">Add trades from Scout or Rebalance to track them.</p>
               </div>
            ) : (
               journalQueue.map((item, idx) => renderCard(item, idx))
            )}
          </div>
        )}

      </div>
    </div>
  );
}
