// Approved drafts leave Lede by hand: the rep copies them or opens them in their own Gmail or
// LinkedIn and presses send there. Lede itself never sends anything.

import { authHeaders } from '@/api/client'
import type { Draft, ProspectInput } from '@/api/types'

/** The body as it should be sent: the draft plus the seller's footer. */
export function emailBody(draft: Draft, footer: string): string {
  return footer.trim() ? `${draft.body}\n\n${footer.trim()}` : draft.body
}

/** Gmail's compose window with the subject and body filled in; the rep adds the address. */
export function gmailComposeUrl(draft: Draft, footer: string): string {
  // encodeURIComponent, not URLSearchParams: Gmail can leave a "+" in the body as a literal plus.
  const su = encodeURIComponent(draft.subject)
  const body = encodeURIComponent(emailBody(draft, footer))
  return `https://mail.google.com/mail/?view=cm&fs=1&su=${su}&body=${body}`
}

/** The person's LinkedIn profile if we have it, otherwise a people search for them. */
export function linkedinUrl(prospect: ProspectInput): string {
  if (prospect.linkedin_url?.startsWith('https://')) return prospect.linkedin_url
  const keywords = [prospect.person_name, prospect.company_name].filter(Boolean).join(' ')
  return `https://www.linkedin.com/search/results/people/?${new URLSearchParams({ keywords })}`
}

/** Download the approved drafts as a spreadsheet (the endpoint needs the access code). */
export async function downloadApproved(campaignId?: string): Promise<void> {
  const query = campaignId ? `?${new URLSearchParams({ campaign_id: campaignId })}` : ''
  const res = await fetch(`/api/export${query}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(`The download failed (${res.status}).`)
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), {
    href: url,
    download: 'approved-drafts.csv',
  })
  a.click()
  URL.revokeObjectURL(url)
}
