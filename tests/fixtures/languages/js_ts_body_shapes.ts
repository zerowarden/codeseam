export function trimLeft(value: string): string {
  return value.trim();
}

export function trimRight(input: string): string {
  return input.trim();
}

export function localLeft(value: string): string {
  const cleaned = value.trim();
  return cleaned;
}

export function localRight(input: string): string {
  const output = input.trim();
  return output;
}

export function parseValue(value: string): Config {
  return parse(value);
}

export function serializeValue(input: string): Config {
  return serialize(input);
}
