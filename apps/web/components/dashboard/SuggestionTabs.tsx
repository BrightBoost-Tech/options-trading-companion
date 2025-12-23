'use client';

import { useState, useRef } from 'react';
import SuggestionCard from './SuggestionCard';
import { Suggestion } from '@/lib/types';
import { Sparkles, Activity, Sun, Clock, FileText } from 'lucide-react';
import WeeklyReportList from '../suggestions/WeeklyReportList';
import { RefreshCw } from 'lucide-react';
import { logEvent } from '@/lib/analytics';

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
  const [stagedIds, setStagedIds] = useState<string[]>([]);
  const tabListRef = useRef<HTMLDivElement>(null);

  // Tabs configuration for cleaner rendering and accessibility
  const tabs = [
    { id: 'morning', label: 'Morning', icon: Sun, count: morningSuggestions.length, color: 'orange' },
    { id: 'midday', label: 'Midday', icon: Clock, count: middaySuggestions.length, color: 'blue' },
    { id: 'rebalance', label: 'Rebalance', icon: Activity, count: optimizerSuggestions.length, color: 'indigo' },
    { id: 'scout', label: 'Scout', icon: Sparkles, count: scoutSuggestions.length, color: 'green' },
    { id: 'journal', label: 'Journal', icon: null, textIcon: '📖', count: journalQueue.length, color: 'purple' },
    { id: 'weekly', label: 'Reports', icon: FileText, count: 0, color: 'slate' },
  ] as const;

  const handleStage = (s: Suggestion) => {
      setStagedIds(prev =>
        prev.includes(s.id) ? prev.filter(id => id !== s.id) : [...prev, s.id]
      );
  };

  const handleModify = (s: Suggestion) => {};
  const handleDismiss = (s: Suggestion, tag: string) => {};

  const handleTabChange = (tabId: typeof activeTab) => {
      setActiveTab(tabId);
      logEvent({
          eventName: 'suggestion_tab_changed',
          category: 'ux',
          properties: { tab: tabId }
      });
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
      // Focus will be handled by the button's auto-focus if we programmed it,
      // but simpler is to rely on aria-activedescendant or manual focus.
      // For tabs, moving focus immediately is standard.
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
          // We construct classes dynamically but safely since the map is small
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

      {/* Tab Content */}
      <div
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        className="p-4 flex-1 overflow-y-auto bg-muted/20 min-h-[400px]"
      >

        {activeTab === 'morning' && (
             morningSuggestions.length === 0 ? (
               <div className="text-center py-10 text-muted-foreground">
                 <p>No morning suggestions.</p>
               </div>
             ) : (
                morningSuggestions.map((s, i) => (
                    <SuggestionCard
                        key={i}
                        suggestion={s}
                        onStage={handleStage}
                        onModify={handleModify}
                        onDismiss={handleDismiss}
                    />
                ))
             )
        )}

        {activeTab === 'midday' && (
             middaySuggestions.length === 0 ? (
                <div className="text-center py-10 text-muted-foreground">
                  <p>No midday suggestions.</p>
                </div>
              ) : (
                 middaySuggestions.map((s, i) => (
                     <SuggestionCard
                        key={i}
                        suggestion={s}
                        onStage={handleStage}
                        onModify={handleModify}
                        onDismiss={handleDismiss}
                    />
                 ))
              )
        )}

        {activeTab === 'weekly' && (
          <WeeklyReportList reports={weeklyReports} />
        )}

        {activeTab === 'rebalance' && (
            optimizerSuggestions.length === 0 ? (
               <div className="text-center py-10 text-muted-foreground">
                 <Activity className="w-10 h-10 mx-auto mb-3 opacity-20" />
                 <p>No rebalance suggestions.</p>
                 <p className="text-xs mt-1">Run the optimizer to generate trades.</p>
               </div>
            ) : (
               optimizerSuggestions.map((s, idx) => (
                    <SuggestionCard
                        key={idx}
                        suggestion={s}
                        onStage={handleStage}
                        onModify={handleModify}
                        onDismiss={handleDismiss}
                    />
               ))
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

            {scoutSuggestions.length === 0 ? (
               <div className="text-center py-10 text-muted-foreground">
                 <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-20" />
                 <p>No scout picks found.</p>
               </div>
            ) : (
               scoutSuggestions.map((opp, idx) => (
                 <SuggestionCard
                    key={idx}
                    suggestion={opp}
                    onStage={handleStage}
                    onModify={handleModify}
                    onDismiss={handleDismiss}
                />
               ))
            )}
          </div>
        )}

        {activeTab === 'journal' && (
          <div className="space-y-4">
            {journalQueue.length === 0 ? (
               <div className="text-center py-10 text-muted-foreground">
                 <p>Journal queue is empty.</p>
                 <p className="text-xs mt-1">Add trades from Scout or Rebalance to track them.</p>
               </div>
            ) : (
               journalQueue.map((item, idx) => (
                 <SuggestionCard
                    key={idx}
                    suggestion={item}
                    onStage={handleStage}
                    onModify={handleModify}
                    onDismiss={handleDismiss}
                />
               ))
            )}
          </div>
        )}

      </div>
    </div>
  );
}
