/**
 * Redaction rules for sensitive data in logs and artifacts.
 *
 * Default redaction targets:
 * - Passwords and passcodes
 * - Session cookies and tokens
 * - Email verification codes
 * - Payment card numbers
 * - Personal data (when privacy mode is enabled)
 */

/**
 * Redaction configuration.
 */
export interface RedactConfig {
  /** Enable privacy mode — redacts personal data fields */
  privacyMode?: boolean;
  /** Additional custom patterns to redact */
  customPatterns?: RedactPattern[];
  /** Replacement string (default: "[REDACTED]") */
  replacement?: string;
}

export interface RedactPattern {
  /** Human-readable name for the pattern */
  name: string;
  /** Regex pattern to match */
  pattern: RegExp;
}

const REDACT_PLACEHOLDER = "[REDACTED]";

/**
 * Default sensitive field names — values of these fields are always redacted.
 */
const SENSITIVE_FIELD_NAMES = new Set([
  "password",
  "passcode",
  "secret",
  "token",
  "access_token",
  "refresh_token",
  "api_key",
  "apikey",
  "authorization",
  "cookie",
  "session_id",
  "sessionid",
  "csrf",
  "otp",
  "verification_code",
  "pin",
]);

/**
 * Patterns that match sensitive content inline.
 */
const DEFAULT_PATTERNS: RedactPattern[] = [
  {
    name: "credit_card",
    pattern: /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/g,
  },
  {
    name: "bearer_token",
    pattern: /Bearer\s+\S+/gi,
  },
  {
    name: "jwt",
    pattern: /eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,
  },
];

/**
 * Privacy-mode patterns (only applied when privacyMode is enabled).
 */
const PRIVACY_PATTERNS: RedactPattern[] = [
  {
    name: "email",
    pattern: /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
  },
  {
    name: "phone",
    pattern: /\+?\d{1,4}[\s-]?\(?\d{1,4}\)?[\s-]?\d{1,4}[\s-]?\d{1,9}/g,
  },
  {
    name: "ssn",
    pattern: /\b\d{3}-\d{2}-\d{4}\b/g,
  },
];

/**
 * Redact sensitive data from a plain string.
 */
export function redactString(
  input: string,
  config: RedactConfig = {},
): string {
  const replacement = config.replacement ?? REDACT_PLACEHOLDER;
  let result = input;

  // Apply default patterns
  for (const p of DEFAULT_PATTERNS) {
    result = result.replace(p.pattern, replacement);
  }

  // Apply privacy patterns if enabled
  if (config.privacyMode === true) {
    for (const p of PRIVACY_PATTERNS) {
      result = result.replace(p.pattern, replacement);
    }
  }

  // Apply custom patterns
  if (config.customPatterns !== undefined) {
    for (const p of config.customPatterns) {
      result = result.replace(p.pattern, replacement);
    }
  }

  return result;
}

/**
 * Redact sensitive fields from a JSON-serializable object.
 * Returns a deep copy with sensitive values replaced.
 */
export function redactObject<T>(
  obj: T,
  config: RedactConfig = {},
): T {
  const replacement = config.replacement ?? REDACT_PLACEHOLDER;
  return deepRedact(obj, config, replacement) as T;
}

function deepRedact(
  value: unknown,
  config: RedactConfig,
  replacement: string,
): unknown {
  if (value === null || value === undefined) return value;

  if (typeof value === "string") {
    return redactString(value, config);
  }

  if (Array.isArray(value)) {
    return value.map((item) => deepRedact(item, config, replacement));
  }

  if (typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(value as Record<string, unknown>)) {
      if (SENSITIVE_FIELD_NAMES.has(key.toLowerCase())) {
        result[key] = replacement;
      } else {
        result[key] = deepRedact(val, config, replacement);
      }
    }
    return result;
  }

  return value;
}

/**
 * Check if a field name is considered sensitive.
 */
export function isSensitiveField(fieldName: string): boolean {
  return SENSITIVE_FIELD_NAMES.has(fieldName.toLowerCase());
}
