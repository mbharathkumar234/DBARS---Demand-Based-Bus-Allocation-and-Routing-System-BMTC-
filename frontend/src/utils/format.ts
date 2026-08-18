// cleanly rounds a decimal (like 0.45) into a readable string (like "45%")
export function percent(value?: number) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

// trims down timestamps so they don't look super messy in the UI
export function timeLabel(value: string) {
  return value.slice(0, 5);
}
