// A fictional seller for demos (mirrors backend/samples/seller_profile.json).

import type { Campaign, SellerProfile } from '@/api/types'

export const SAMPLE_PROFILE: SellerProfile = {
  company: {
    name: 'Ledgerly',
    domain: 'ledgerly.example',
    one_liner: 'AI that closes the books faster for finance teams',
  },
  offer: {
    product: 'Ledgerly Close',
    problem_solved:
      'month-end close takes too long because reconciliations and accruals are manual',
    how_it_works: 'matches transactions, drafts accruals and flags anomalies for review',
  },
  icp: {
    industries: ['fintech', 'saas'],
    employee_min: 200,
    employee_max: null,
    regions: ['US', 'UK'],
    exclusions: [],
  },
  personas: [
    {
      id: 'finance_leader',
      title_patterns: ['CFO', 'VP Finance', 'Controller', 'CEO'],
      seniority: 'c_level',
      pains: ['month-end close takes too long', 'finance team spends days on reconciliations'],
      hook_preference: 'company',
    },
  ],
  signal_to_pain: {
    funding_mna: ['more entities and complexity to consolidate'],
    hiring_pattern: ['growing finance team signals manual work'],
    product_launch: ['new revenue streams complicate the close'],
  },
  approved_claims: [
    { id: 'c1', text: 'Ledgerly matches transactions and drafts reconciliations automatically' },
    { id: 'c2', text: 'Teams review exceptions instead of every line' },
  ],
  never_claims: ['guaranteed savings', 'replaces your accountants'],
  tone: { voice: 'plain, warm, specific', max_words: 100, cta_style: 'soft', banned_phrases: [] },
  recency_windows_days: {},
  hook_weights: {},
  footer: "Ledgerly, 1 Example St. Reply 'no thanks' and I won't write again.",
}

export const SAMPLE_CAMPAIGN: Partial<Campaign> = {
  name: 'Close faster',
  objective: 'Book a 20-minute intro call about speeding up month-end close',
  persona_id: 'finance_leader',
  angle: 'growth makes the monthly close slower',
  signal_priorities: { funding_mna: 'high', hiring_pattern: 'high' },
}

export const EMPTY_PROFILE: SellerProfile = {
  company: { name: '', domain: '', one_liner: '' },
  offer: { product: '', problem_solved: '', how_it_works: '' },
  icp: { industries: [], employee_min: null, employee_max: null, regions: [], exclusions: [] },
  personas: [
    {
      id: 'buyer',
      title_patterns: [],
      seniority: 'director',
      pains: [],
      hook_preference: 'company',
    },
  ],
  signal_to_pain: {},
  approved_claims: [],
  never_claims: [],
  tone: { voice: 'plain, warm, specific', max_words: 100, cta_style: 'soft', banned_phrases: [] },
  recency_windows_days: {},
  hook_weights: {},
  footer: '',
}
