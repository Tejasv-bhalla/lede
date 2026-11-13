import { friendly } from '@/lib/status'

/** One problem in plain words; technical detail stays one click away. */
export function Problem({ problem }: { problem: string }) {
  const { text, detail } = friendly(problem)
  return (
    <li>
      {text}
      {detail && (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer select-none">Technical detail</summary>
          <p className="mt-1 break-words">{detail}</p>
        </details>
      )}
    </li>
  )
}
