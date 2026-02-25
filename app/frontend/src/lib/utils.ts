import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Platform detection utility
export function isMac(): boolean {
  return typeof navigator !== 'undefined' && navigator.platform.toUpperCase().indexOf('MAC') >= 0;
}

// Keyboard shortcut formatting utility
export function formatKeyboardShortcut(key: string): string {
  const modifierKey = isMac() ? '⌘' : 'Ctrl';
  return `${modifierKey}${key.toUpperCase()}`;
}

// Provider color utility for consistent styling across components
export function getProviderColor(provider: string): string {
  return 'bg-gray-600/20 text-primary border-gray-600/40';
  // switch (provider.toLowerCase()) {
  //   case 'anthropic':
  //     return 'bg-orange-600/20 text-orange-300 border-orange-600/40';
  //   case 'google':
  //     return 'bg-green-600/20 text-green-300 border-green-600/40';
  //   case 'groq':
  //     return 'bg-red-600/20 text-red-300 border-red-600/40';
  //   case 'deepseek':
  //     return 'bg-blue-600/20 text-blue-300 border-blue-600/40';
  //   case 'openai':
  //     return 'bg-gray-900/60 text-gray-200 border-gray-700/60';
  //   case 'ollama':
  //     return 'bg-white/90 text-gray-800 border-gray-300';
  //   default:
  //     return 'bg-gray-600/20 text-gray-300 border-gray-600/40';
  // }
}

/**
 * Parse ticker string to array, supporting both English and Chinese commas
 * Handles formats like: "AAPL,NVDA,TSLA" or "600158，300118" (Chinese comma)
 */
export function parseTickers(tickerString: string): string[] {
  if (!tickerString || typeof tickerString !== 'string') {
    return [];
  }
  // Replace Chinese comma with English comma, then split
  return tickerString
    .replace(/，/g, ',')
    .split(',')
    .map(t => t.trim())
    .filter(t => t.length > 0);
}
