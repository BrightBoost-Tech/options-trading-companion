'use client';

import * as React from 'react';
import { Moon, Sun } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

export function ThemeToggle() {
  const [theme, setTheme] = React.useState<'light' | 'dark'>('dark');
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    // Read from DOM on mount to sync state
    const isDark = document.documentElement.classList.contains('dark');
    setTheme(isDark ? 'dark' : 'light');
    setMounted(true);
  }, []);

  const toggleTheme = () => {
    const newTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);

    if (newTheme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }

    try {
      localStorage.theme = newTheme;
    } catch (e) {
      // Ignore if local storage is blocked
    }
  };

  const label = mounted
    ? (theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode')
    : 'Toggle theme';

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            aria-label={label}
          >
            {mounted && theme === 'dark' ? (
              <Sun className="h-5 w-5" />
            ) : mounted && theme === 'light' ? (
              <Moon className="h-5 w-5" />
            ) : (
              // Fallback for SSR
              <Sun className="h-5 w-5 opacity-0" />
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent className="whitespace-nowrap">
          <p>{label}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
