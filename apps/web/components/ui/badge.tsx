// apps/web/components/ui/Badge.tsx
import React from 'react';

interface BadgeProps {
  variant?: 'destructive' | 'outline' | 'default' | 'secondary';
  className?: string;
  children: React.ReactNode;
}

export function Badge({ variant = 'default', className = '', children }: BadgeProps) {
  const baseClasses = "px-2.5 py-0.5 rounded-full text-xs font-semibold inline-flex items-center";

  const variants = {
    default: "bg-gray-100 text-gray-800",
    destructive: "bg-red-500 text-white",
    outline: "bg-transparent border border-gray-500 text-gray-400",
    secondary: "bg-gray-200 text-gray-900",
  };

  const variantClass = variants[variant as keyof typeof variants] || variants.default;

  return (
    <span className={`${baseClasses} ${variantClass} ${className}`}>
      {children}
    </span>
  );
}
