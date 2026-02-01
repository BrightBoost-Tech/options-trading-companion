'use client';

import React from 'react';
import { Sun } from 'lucide-react';
import { Suggestion } from '@/lib/types';
import SuggestionCard from '../dashboard/SuggestionCard';
import { EmptyState } from '@/components/ui/empty-state';

interface MiddayEntriesListProps {
  suggestions: Suggestion[];
}

export default function MiddayEntriesList({ suggestions }: MiddayEntriesListProps) {
  if (suggestions.length === 0) {
      return (
        <EmptyState
          icon={Sun}
          title="No midday suggestions"
          description="Midday opportunities will appear here as market conditions evolve."
        />
      );
  }

  return (
    <div className="space-y-4">
      {suggestions.map((s, i) => (
         <SuggestionCard
            key={s.id || i}
            suggestion={s}
        />
      ))}
    </div>
  );
}
