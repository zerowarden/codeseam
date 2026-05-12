export function parseEncoded(payload: EncodedPayload): ParsedPayload {
  const text = payload.decode("utf8");
  return JSON.parse(text);
}

export class PayloadStore {
  save(payload: EncodedPayload): ParsedPayload {
    const text = payload.decode("utf8");
    return JSON.parse(text);
  }
}
