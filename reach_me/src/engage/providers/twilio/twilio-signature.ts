import { createHmac, timingSafeEqual } from 'node:crypto';

export function verifyTwilioSignature(
  params: Record<string, string | string[] | undefined>,
  url: string,
  signature: string | undefined,
  authToken: string,
): boolean {
  if (!signature) {
    return false;
  }

  const sortedKeys = Object.keys(params).sort();
  let data = url;
  for (const key of sortedKeys) {
    const value = params[key];
    if (value === undefined) {
      continue;
    }

    if (Array.isArray(value)) {
      for (const entry of value) {
        data += key + entry;
      }
    } else {
      data += key + value;
    }
  }

  const expected = createHmac('sha1', authToken).update(data).digest('base64');

  if (expected.length !== signature.length) {
    return false;
  }

  return timingSafeEqual(
    Buffer.from(expected, 'utf8'),
    Buffer.from(signature, 'utf8'),
  );
}
