'use client';

import React from 'react';
import { Sunrise } from 'lucide-react';
import { Suggestion } from '@/lib/types';
import SuggestionCard from '../dashboard/SuggestionCard';
import { EmptyState } from '@/components/ui/empty-state';

interface MorningOrdersListProps {
  suggestions: Suggestion[];
}

export default function MorningOrdersList({ suggestions }: MorningOrdersListProps) {
  if (suggestions.length === 0) {
    return (
      <EmptyState
        icon={Sunrise}
        title="No morning suggestions"
        description="Check back before the market opens for new trade ideas."
      />
    );
  }

  return (
    <div className="space-y-4">
      {suggestions.map((s, i) => (
         <SuggestionCard
            key={s.id || i}
            suggestion={s}
            // Add default handlers if needed
        />
      ))}
    </div>
  );
}
