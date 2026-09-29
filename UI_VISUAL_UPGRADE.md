# HomeFirst90 UI Visual Upgrade

Purpose: make HomeFirst90 easier to understand at a glance, more engaging on mobile and more like a real planning product without adding decorative clutter.

## Design rules

1. Every visual must explain real user data.
2. Doughnut charts are for part-to-whole cost breakdowns.
3. Circular rings are for progress, completion, priority counts or a clearly labelled countdown.
4. No invented readiness or financial-health scores.
5. The user must still be able to understand the result from text alone.
6. Charts must redraw from the same source data as the calculator.
7. Keep visual styling consistent across the site.
8. Mobile first: charts stack and legends remain readable at 320px.
9. Avoid gratuitous animation.
10. The visual should always lead toward a useful next action.

## Phase A — Core free calculators ✅

### Moving Out Budget
- [x] Doughnut chart
- [x] Uses actual calculated deposit, rent-before-move, moving, setup, other and reserve values
- [x] Total displayed in chart centre
- [x] Existing numerical breakdown remains underneath

### Household Bills
- [x] Doughnut chart
- [x] Uses actual editable monthly bill values
- [x] Largest categories shown individually; smaller categories may be combined visually as Other
- [x] Exact numerical list remains underneath

### Setup Cost
- [x] Doughnut chart
- [x] Groups the actual personalised setup rows by room/category
- [x] Setup total displayed in the centre
- [x] Existing Need now / Buy soon / Can wait figures remain visible

## Phase B — Product/dashboard value ✅

### My Home
- [x] Overall planning-completion ring
- [x] Transparent formula: four saved planning steps, each worth one quarter
- [x] Setup plan status
- [x] Moving-out cash status
- [x] Monthly bills status
- [x] Move date / pre-move plan status
- [x] One contextual Next best planning step
- [x] No arbitrary readiness score

### Complete
- [x] Home progress ring
- [x] Tasks-completed ring
- [x] Purchases-bought ring
- [x] Recorded-spend-vs-plan ring
- [x] Rings redraw immediately when tasks or purchases change
- [x] Explain how Home progress is calculated

## Phase C — Priority and timing ✅

### What To Buy First
- [x] Need now item ring
- [x] Buy soon item ring
- [x] Can wait item ring
- [x] Setup-budget-used-now ring

### Pre-move Planner
- [x] Moving countdown ring
- [x] Four milestone blocks: 4 weeks / 2 weeks / 1 week / day before
- [x] Current/upcoming/reached state is date-driven

## Additional engagement improvements

### High-value next
- [x] Next-best-step card on My Home
- [ ] Add small contextual milestone messages when a user completes all four free planning steps
- [ ] Create shareable result cards for selected free tools, designed to encourage organic referrals without exposing private data
- [ ] Add a simple Print / Save summary option to the major planning tools
- [ ] Add lightweight expand/collapse for long detailed breakdowns on small screens
- [ ] Consider an optional "What changed?" comparison when a saved budget is recalculated
- [ ] Add a small "You have planned £X / identified Y items / mapped Z actions" summary on My Home once enough data exists

### Avoid
- fake gamification points
- daily streaks
- confetti everywhere
- arbitrary scores
- excessive animations
- charts that duplicate information without improving comprehension
- red/green financial judgements that imply professional advice

## Measurement

Compare after genuine traffic starts:
- tool completion rate
- home-save rate
- move/email capture
- My Home visits
- Complete-page visits
- checkout starts
- purchases

Do not judge the upgrade only by page views or time on page.
