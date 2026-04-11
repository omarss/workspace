/**
 * Parse and validate a numeric CLI option.
 * Throws a clear error if the value is not a valid positive integer.
 */
export function parsePositiveInt(value: string, optionName: string): number {
  const parsed = parseInt(value, 10);
  if (Number.isNaN(parsed) || parsed <= 0) {
    throw new Error(
      `Invalid value for ${optionName}: "${value}". Expected a positive integer.`,
    );
  }
  return parsed;
}

/**
 * Parse and validate a non-negative integer CLI option.
 */
export function parseNonNegativeInt(value: string, optionName: string): number {
  const parsed = parseInt(value, 10);
  if (Number.isNaN(parsed) || parsed < 0) {
    throw new Error(
      `Invalid value for ${optionName}: "${value}". Expected a non-negative integer.`,
    );
  }
  return parsed;
}
