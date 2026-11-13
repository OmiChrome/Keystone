# 5-minute demo script (Round 1 video)

**One line:** *Keystone is the procurement specialist bench Amber calls. Every answer cites the page it came from, and when it isn't sure, it says so.*

| Time | Screen | Say / show |
|---|---|---|
| 0:00 | Overview | The user is a procurement manager on a data-center job. The problem: a 480 V switchgear package with three bids, one submittal and a schedule. Missing one exclusion or one late switchboard costs weeks. |
| 0:25 | Package pipeline → Run | One click chains bid leveling, then spec compliance, then the schedule. Point at the live log: every model call, which model answered it, and cache hits. |
| 0:55 | Bid leveling result | Helix has the lowest stated bid ($991.5k). It excludes the SPD, the arc-flash study, spares and seismic certification, and its line items add up to $13k more than its stated total. Leveled, **Voltara wins at $1,068,250**. The margin is 1.8%, so Keystone **hands the call to a human**. Click a "source" chip: the quote is highlighted in the PDF. |
| 1:50 | Spec compliance | 20 requirements: 8 deviations and 2 missing. Open 2.3.E: the submittal says 6,400 mm, and **code converts it to 252 in, over the 240 in limit**. A second model family (Gemma) agrees. Show "Draft vendor email": it's ready to send once approved. |
| 2:50 | Schedule risk | P(finish by the target date) = **18%**. The #1 driver is not the switchgear but the **generators**: they cause about 97 days of expected delay (a counterfactual over 5,000 scenarios). Each action is tied to a number. Market sources are linked. |
| 3:40 | Lead time | Honest ranges: the switchgear quote is below the market P10, so it's treated sceptically. Show the back-test card on 4,124 real shipments. |
| 4:10 | Connect via MCP | Amber connects over stdio or HTTP and gets 10 tools in the same JSON envelope. Show the JSON. |
| 4:35 | Close | Accuracy on labelled data: 20/20 on the dev project. On the **held-out** chiller project, the first run scored 15/16 and the one miss was routed to a human. Cost is about a cent per package. The models are open-weight, so it can run privately. |

Tip: record the demo from the cached run (`KEYSTONE_CACHE=1`) so the shared endpoint's load can't stall it. Mention that the run is cached.

## Pitch deck outline (8–10 slides)

1. Title and one-liner
2. The user and the problem: bids cover different scope, and submittal checks take days. Missing items cost weeks on data-center timelines.
3. What Keystone is: specialists Amber calls over MCP, sharing one contract (`keystone/1.0`)
4. Live result: the low-bid trap (the scope matrix)
5. Live result: compliance with unit conversion and a second model's opinion
6. Live result: which PO actually delays the job (counterfactual Monte Carlo)
7. Trust architecture: verified quotes, rule checks, a second model, grounded narratives, human hand-off
8. Accuracy, cost and speed (`eval/REPORT.md`), including the held-out miss and the fix
9. Data provenance and private deployment
10. What's next: OCR and vision for drawings, a vendor pre-qualification agent, PO-history-trained lead times
