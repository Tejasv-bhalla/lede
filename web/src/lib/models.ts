// Plain names for the models behind a run ("groq:openai/gpt-oss-120b" → "gpt-oss-120b, free via Groq").

const PROVIDER_LABEL: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  gemini: 'Gemini',
  groq: 'Groq',
  openrouter: 'OpenRouter',
  mistral: 'Mistral',
  custom: 'custom endpoint',
}

export function writerLabel(name: string): string {
  const yours = name.startsWith('yours:')
  const [provider, ...rest] = (yours ? name.slice('yours:'.length) : name).split(':')
  const model = rest.join(':').split('/').pop() || provider
  const via = PROVIDER_LABEL[provider] ?? provider
  if (provider === 'claude_code') return `${model}, via Claude Code on this computer`
  return yours ? `${model}, with your ${via} key` : `${model}, free via ${via}`
}
