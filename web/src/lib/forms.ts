// Convert between list fields and the text inputs that edit them.

/** Splits a textarea into non-empty lines, and back. */
export const lines = {
  parse: (text: string) =>
    text
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean),
  format: (items: string[] | undefined) => (items ?? []).join('\n'),
}

/** Splits a comma-separated input, and back. */
export const commas = {
  parse: (text: string) =>
    text
      .split(',')
      .map((l) => l.trim())
      .filter(Boolean),
  format: (items: string[] | undefined) => (items ?? []).join(', '),
}
