# HomeFirst90 Launch Checklist

This is the master launch checklist. A phase is only marked complete when the completion criteria are live and verified.

## Phase 1 — Fix conversion before traffic 🟡

- [x] Clear free-before-the-keys vs paid-from-moving-day proposition
- [x] HomeFirst90 Complete priced at £12.99 one-off
- [x] Complete page shows concrete post-move dashboard/value
- [x] Stripe checkout, 14-day money-back wording, privacy/terms/methodology live
- [x] Replace confusing "My Home: Not saved" wording with clearer save/dashboard wording
- [x] Add contextual Complete hand-off after every major free-tool result
- [ ] Collect genuine early-user feedback/testimonials (never fabricate social proof)
  - [x] Controlled Founding Tester access for up to 20 people
  - [x] Structured feedback form with explicit permission-to-quote control
  - [x] Tester/feedback progress shown in internal funnel dashboard
- [x] Final mobile conversion QA — homepage, tools, My Home, Complete and Stripe checkout verified on mobile-style flow

**Phase completion gate:** no broken conversion path; every free tool has a natural next step; trust is credible; mobile purchase journey verified.

## Phase 2 — Build capture 🟡

- [x] Email + moving-date capture built
- [x] Consent recorded
- [x] Unsubscribe flow built
- [x] Lead storage in persistent Postgres
- [x] Reminder emails designed for 14 days before, 3 days before and moving day
- [x] Daily Render reminder cron configured
- [x] Live API reports move reminders enabled
- [ ] Verify first real scheduled cron run/send end-to-end

**Phase completion gate:** a real captured lead can be stored, unsubscribed, and receives the correctly timed reminder sequence.

## Phase 3 — SEO content engine 🟡

- [x] Core search-led calculator/tool pages live
- [x] Long-tail pages for first-home/setup/furnishing searches live
- [x] robots.txt and sitemap.xml live
- [x] Canonical/meta descriptions on core pages
- [x] Build the 30-page priority keyword/content roadmap
- [x] Publish/upgrade the first priority cluster with strong internal links to the relevant tool
- [ ] Verify indexing/performance and use actual query data to choose the next cluster
  - 29 Sep 2026 check: no HomeFirst90 pages yet returned in Google-style site search; recheck after crawl/indexing

**Phase completion gate:** repeatable keyword → useful page → relevant tool → capture path exists, with performance measured and the content backlog prioritised by evidence.

## Phase 4 — Measure funnel ✅

Required funnel:
1. Visitors
2. Tool starts
3. Tool completions
4. Homes saved
5. Emails/moves captured
6. Complete page views
7. Checkout starts
8. Purchases

Current:
- [x] Page-view event storage
- [x] Tool-run event storage
- [x] Checkout-click event storage
- [x] Confirmed-purchase event from Stripe webhook
- [x] Move/email capture event storage
- [x] Separate tool-completion event
- [x] Separate home-saved event
- [x] Funnel summary endpoint/dashboard
- [x] Conversion rates between stages
- [x] Source breakdown so SEO/social/referral performance can be compared

**Phase completion gate: COMPLETE.** One view now shows the full funnel, conversion rates and visitor-source breakdown. New tool-completion/home-saved events record from 29 September 2026 onward.
