import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format a UTC ISO string to a locale-aware relative or absolute string.
 */
export function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * Format duration in milliseconds to a human-readable string.
 */
export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

/**
 * Truncate a string to a max length and append ellipsis.
 */
export function truncate(str: string, maxLength = 80): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength) + "…";
}

/**
 * Return a CSS class name appropriate for a sandbox status badge.
 */
export function sandboxStatusClass(status: string): string {
  switch (status) {
    case "running":
    case "completed":
      return "status-success";
    case "creating":
    case "executing":
      return "status-info";
    case "failed":
    case "timed_out":
    case "error":
      return "status-danger";
    case "expired":
    case "destroying":
    case "destroyed":
      return "status-muted";
    default:
      return "status-muted";
  }
}

/**
 * Format bytes into a human-readable string (e.g. 64 KB, 256 MB).
 */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${Math.round(bytes / Math.pow(1024, i))} ${units[i]}`;
}
