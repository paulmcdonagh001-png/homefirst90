# HomeFirst90 Growth Agent — Publishing Setup

Current status:
- Growth Agent drafting: LIVE
- Automatic branded visual previews: LIVE
- Approval queue: LIVE
- Campaign/source tracking: LIVE
- Performance learning: LIVE
- Scheduled GitHub heartbeat workflow: READY, secret connection still required
- Metricool HomeFirst90 brand: EXISTS
- Metricool social networks connected: NONE

## Publishing architecture

The intended flow is:

Growth Agent idea
→ platform-specific draft
→ automatic visual
→ owner approval
→ Metricool schedule/publish
→ tracked HomeFirst90 link
→ tool use / capture / checkout attributed back to source + campaign
→ agent learns which angles to repeat.

## First network priorities

1. Facebook
   - easiest first publishing channel
   - practical moving/budget content
   - can use static generated visuals or calculator screenshots

2. Instagram
   - best once image/carousel production is stable
   - visual post/carousel required

3. Pinterest
   - strong fit for moving, first-home, furnishing and checklist content
   - requires a connected Pinterest account and target board

4. YouTube
   - only once automatic video production is ready
   - do not create a manual video-editing workload

## Safety / control

- Approval remains required.
- No paid ad spend.
- No auto-replies or DMs.
- No posting into communities where self-promotion is prohibited.
- Published posts keep campaign-specific tracked links.
- The draft record stores the publishing channel/status after successful publication.

## Remaining secure setup

### GitHub scheduled heartbeat
Create repository Actions secret:
- Name: HF90_GROWTH_REVIEW_KEY
- Value: the existing private HomeFirst90 Growth Agent review key

The committed workflow then runs Monday / Wednesday / Friday and asks the API to generate one draft only when fewer than 3 drafts are awaiting review.

### Metricool
Connect at least one HomeFirst90 social account under the existing HomeFirst90 Metricool brand. Once a network is connected, the approval-to-publish integration can be activated without rebuilding the Growth Agent.
