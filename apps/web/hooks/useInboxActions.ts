import { useState, useCallback } from 'react';
import { fetchWithAuth } from '@/lib/api';
import { useToast } from '@/components/ui/use-toast';
import { Suggestion } from '@/lib/types';

export function useInboxActions(onActionComplete?: () => void) {
  const [stagedIds, setStagedIds] = useState<Set<string>>(new Set());
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());
  const [refreshedAtMap, setRefreshedAtMap] = useState<Record<string, number>>({});
  const [isBatchLoading, setIsBatchLoading] = useState(false);
  const [stagingIds, setStagingIds] = useState<Set<string>>(new Set()); // For individual loaders
  const { toast } = useToast();

  const isStale = useCallback((suggestion: Suggestion) => {
    // If explicitly staged locally or by server, not stale for action purposes (or handled differently)
    if (suggestion.staged || stagedIds.has(suggestion.id)) return false;

    const refreshedTime = refreshedAtMap[suggestion.id];
    const now = Date.now();

    // 1. Check local refresh within 5 minutes
    if (refreshedTime && (now - refreshedTime < 5 * 60 * 1000)) {
        return false;
    }

    // 2. Check server-provided flag
    if (suggestion.is_stale === true) {
        return true;
    }

    // 3. Fallback: Creation time > 5 mins (if is_stale is undefined)
    if (suggestion.is_stale === undefined) {
        const createdTime = suggestion.created_at ? new Date(suggestion.created_at).getTime() : 0;
        if (now - createdTime > 5 * 60 * 1000) {
            return true;
        }
    }
    return false;
  }, [refreshedAtMap, stagedIds]);

  const stageItems = useCallback(async (ids: string[]) => {
    if (ids.length === 0) return;

    // Optimistic / Loading State
    const isBatch = ids.length > 1;
    if (isBatch) {
        setIsBatchLoading(true);
    } else {
        setStagingIds(prev => new Set([...prev, ...ids]));
    }

    // Optimistic update for UI feedback immediately?
    // We defer adding to stagedIds until at least partial success confirmation
    // to avoid stuck "Staged" state on network error,
    // but individual loaders (stagingIds) show progress.

    try {
        const res = await fetchWithAuth('/inbox/stage-batch', {
            method: 'POST',
            body: JSON.stringify({ suggestion_ids: ids })
        });

        // Parse response
        const successfulIds: string[] = [];
        const rawStaged = res.staged || [];

        rawStaged.forEach((item: any) => {
            if (typeof item === 'string') successfulIds.push(item);
            else if (item?.id) successfulIds.push(item.id);
        });

        // Fallback for legacy backend response
        if (successfulIds.length === 0 && res.staged_count > 0 && (!res.failed_ids || res.failed_ids.length === 0)) {
            successfulIds.push(...ids);
        }

        const failedIds: string[] = res.failed_ids || (res.failed || []).map((f: any) => f.id) || [];

        // Update state
        if (successfulIds.length > 0) {
            setStagedIds(prev => {
                const next = new Set(prev);
                successfulIds.forEach(id => next.add(id));
                return next;
            });

            const message = isBatch
                ? `Successfully staged ${successfulIds.length} suggestions.`
                : "Suggestion moved to staged queue.";
            toast({ title: "Staged", description: message });
        }

        if (failedIds.length > 0) {
            toast({
                title: "Partial Failure",
                description: `Failed to stage ${failedIds.length} items.`,
                variant: "destructive"
            });
        }

        onActionComplete?.();
        return successfulIds.length > 0;

    } catch (e) {
        console.error(e);
        toast({ title: "Error", description: "Stage request failed", variant: "destructive" });
        return false;
    } finally {
        if (isBatch) setIsBatchLoading(false);
        else setStagingIds(prev => {
            const next = new Set(prev);
            ids.forEach(id => next.delete(id));
            return next;
        });
    }
  }, [toast, onActionComplete]);

  const dismissItem = useCallback(async (id: string, reason: string) => {
      // Optimistic Update
      setDismissedIds(prev => new Set([...prev, id]));

      try {
          await fetchWithAuth(`/suggestions/${id}/dismiss`, {
              method: 'POST',
              body: JSON.stringify({ reason })
          });
          toast({ title: "Dismissed", description: "Suggestion dismissed." });
          onActionComplete?.();
      } catch (e) {
          console.error(e);
          // Rollback
          setDismissedIds(prev => {
              const next = new Set(prev);
              next.delete(id);
              return next;
          });
          toast({ title: "Error", description: "Failed to dismiss suggestion", variant: "destructive" });
      }
  }, [toast, onActionComplete]);

  const refreshQuote = useCallback(async (id: string, symbol?: string) => {
      try {
          const res = await fetchWithAuth(`/suggestions/${id}/refresh-quote`, {
              method: 'POST'
          });

          if (res.refreshed_at) {
              setRefreshedAtMap(prev => ({
                  ...prev,
                  [id]: new Date(res.refreshed_at).getTime()
              }));
              toast({
                  title: "Quote Refreshed",
                  description: `Latest market data fetched${symbol ? ` for ${symbol}` : ''}.`
              });
              onActionComplete?.(); // Optional: trigger reload of inbox to get new ranking/ev
              return true;
          }
      } catch (e) {
          console.error(e);
          toast({ title: "Refresh Failed", description: "Could not fetch new quote.", variant: "destructive" });
      }
      return false;
  }, [toast, onActionComplete]);

  return {
      stagedIds,
      dismissedIds,
      isBatchLoading,
      stagingIds,
      stageItems,
      dismissItem,
      refreshQuote,
      isStale,
      // Helper to clear optimistic states if needed (e.g. after full re-fetch)
      resetOptimisticState: () => {
          setStagedIds(new Set());
          setDismissedIds(new Set());
      }
  };
}
