// apps/web/components/ui/Badge.tsx
import React from 'react';

interface BadgeProps {
  variant: 'destructive' | 'outline';
  children: React.ReactNode;
}

export function Badge({ variant, children }: BadgeProps) {
  const baseClasses = "px-2.5 py-0.5 rounded-full text-xs font-semibold";
  const variants = {
    destructive: "bg-red-500 text-white",
    outline: "bg-transparent border border-gray-500 text-gray-400",
  };

  return (
    <span className={`${baseClasses} ${variants[variant]}`}>
      {children}
    </span>
  );
}
