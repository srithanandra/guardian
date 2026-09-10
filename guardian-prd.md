# Guardian — Product Requirements Document

**Tagline:** A remote escort for the transit riders America's maps were never built for.

**Author:** King Andra
**Date:** September 10, 2026
**Version:** 0.1 (Draft)
**Status:** Draft — for hackathon team review
**Target audience:** Hackathon teammates, mentors, and judges

---

## 1. Problem Statement

Most people who can afford to never have to think about public transit reliability. If a flight is delayed, there's another one. If a route is confusing, Google Maps sorts it out in two taps. For a large share of Americans, the bus is not a backup option — it is the only option, and it is frequently late, rerouted, or simply doesn't show up.

The deeper problem isn't the schedule. It's who the system was built for. Public transit is designed around the median rider: someone who reads the signage, speaks the local language fluently, and can recover from a missed stop by improvising. The moment a rider falls outside that median — because of age, disability, language, or a condition like autism or ADHD that makes an unexpected disruption genuinely disorienting — the system has no idea they exist as an individual. Two people can be standing on the same platform, both technically "inside the system," and only one of them has any real safety net if something goes wrong.

That's the insight behind Guardian: **the problem isn't navigation, it's supervision.** These riders don't need a better map. They need something actively watching over the entire trip, and a real person to call in the moment something goes wrong — the way a companion or escort would.

## 2. Proposed Solution

Guardian is a voice-first companion app that stays with a rider for the length of a single bus trip: it gives simple, spoken, step-by-step instructions; watches their real position against the expected route in real time; and escalates — first with a gentle nudge, then a check-in, then a live call to a real human — if the rider drifts off course and doesn't recover on their own.

**Guardian is not:**
- A general-purpose maps or trip-planning app
- A diagnostic or medical tool that identifies or labels a rider's condition
- A replacement for 911 or emergency services
- A permanent tracking or surveillance product — it is active only during a declared trip

**Core differentiator:** every other transit tool optimizes the route. Guardian optimizes the response when the route goes wrong. It trades a passive turn-by-turn map for an active escalation chain that ends with a human, not a notification.

> **Design principle: Guardian escalates urgency, not authority.** The app never decides a rider is "lost" on its own judgment — it follows a pre-agreed escalation plan the rider or their caregiver set up in advance, and it always hands off to a real person rather than trying to resolve the situation itself.

## 3. Target Users

| Persona | Who they are | What they need | How they use Guardian |
|---|---|---|---|
| **The Rider** (Primary) | An elderly adult, a person with a physical or cognitive disability, or a neurodivergent adult (e.g., autism, ADHD) who takes the bus regularly, often on a familiar handful of routes | To complete a trip without needing to read, interpret, or recover from an unfamiliar situation alone | Opens the app before boarding, follows spoken instructions, can press one button for help at any time |
| **The Setup Companion** (Secondary) | A family member, home aide, or case worker who supports the rider but isn't physically present on every trip | Confidence that the rider is safe without having to personally track them | Configures the trip, the rider's care profile, and emergency contacts before departure; receives Tier 2 check-in alerts |
| **The Responder** (Tertiary) | A dispatcher at a partnered elder- or disability-assistance nonprofit | Actionable, specific information the moment a rider needs real intervention, not raw location noise | Receives Tier 3 escalation calls with the rider's location, profile, and last-known status |

*(Assumption: Guardian's care profile — age, disability, or condition — is entered voluntarily by the rider or their Setup Companion, not inferred by the AI from behavior. This is a deliberate privacy and dignity choice; confirm with team before build.)*

## 4. Core Features

**F1 — Radically Simple UI**
- One primary action visible per screen; no nested menus
- Large icons and touch targets over text wherever possible
- Voice output for every instruction, not just text on screen
- No transit jargon ("Route 42 outbound") — instructions describe what to physically do ("Stand up, the bus is stopping now")
- Acceptance criteria: a first-time rider persona can complete a scripted trip without needing to read more than one short sentence per screen

**F2 — Pre-Trip Setup & Permissions**
- Rider or Setup Companion selects a destination and confirms the expected route before departure
- Location, microphone, and notification permissions are requested and must be explicitly accepted before the trip can start — no silent background access
- Care profile (name, emergency contacts, relevant needs) and the nonprofit contact are configured here, not mid-trip
- Acceptance criteria: trip cannot begin until all required permissions are granted and at least one emergency contact is set

**F3 — Real-Time Route Monitoring**
- Pulls live vehicle position and scheduled stop times from a GTFS transit feed (511 SF Bay or OC Bus)
- Compares the rider's live GPS position against the expected route corridor and timing
- Flags a deviation when the rider falls outside an agreed distance/time buffer *(assumption: exact buffer, e.g. 300m or 2 missed stops, is tunable — confirm with team)*
- Acceptance criteria: a simulated off-route rider is detected within the defined buffer during a live demo

**F4 — Multilingual Voice Guidance**
- Whisper handles speech-to-text for rider responses in multiple languages
- An LLM converts raw GTFS/route data into short, plain-language spoken instructions, and interprets the rider's spoken replies (e.g., "yes," "I'm lost," "help")
- Acceptance criteria: the same trip can be run in at least two languages using the same underlying route logic

**F5 — Tiered Escalation**
- See escalation table below. Each tier is a deliberate, explicit step — never a silent skip from "on route" straight to "call the nonprofit."
- Acceptance criteria: all three tiers are demonstrable in sequence during the demo

**F6 — Live Escort Mode**
- Continuous, low-frequency voice check-ins during the trip ("Doing okay? Two stops to go.")
- A single always-visible "Help" button that jumps straight to Tier 3, bypassing the automatic tiers, for a rider who knows they need help immediately
- Acceptance criteria: pressing Help at any point in the trip triggers the Tier 3 flow within a few seconds

**F7 — Nonprofit Contact Integration**
- A default, pre-vetted elder- or disability-assistance nonprofit is set as the fallback Tier 3 contact
- Escalation call/message includes rider name, last-known location, destination, and relevant care-profile notes
- Acceptance criteria: a Tier 3 event produces a call or SMS containing all four pieces of information above

### Escalation Tiers

| Tier | Trigger | Action |
|---|---|---|
| **1 — Gentle Redirect** | Rider drifts from the expected route/stop by a small buffer | App speaks a simple correction ("Get off at the next stop and cross the street") |
| **2 — Check-In** | Deviation continues after Tier 1, or rider misses the expected arrival window | App initiates a voice check-in with the rider; if there's no response, the Setup Companion is notified |
| **3 — Escalate to Organization** | No response to Tier 2 within a set time, or the rider presses Help directly | Partnered nonprofit dispatcher is contacted with rider location, profile, and last-known status |

## 5. Out of Scope (v0.1)

- Diagnosing, labeling, or inferring a rider's disability or condition from behavior
- Replacing 911 or other emergency dispatch services
- Full accessibility (ADA/WCAG) certification
- Ticketing, fare payment, or trip-cost features
- Support for cities beyond the demo transit feed (511 SF Bay / OC Bus)
- Long-term tracking, trip history, or analytics dashboards
- A production integration with a real nonprofit's dispatch system *(the hackathon demo will use a mocked or simulated version of this — see Build Plan)*

## 6. Technical Architecture

- **Frontend:** React, single-action screens, large touch targets, minimal on-screen text, voice-first interaction pattern *(assumption: designed for a phone screen — confirm target device with team)*
- **Speech:** Whisper for multilingual speech-to-text on rider responses
- **AI/Routing Layer:** An LLM converts GTFS route data into plain-language spoken instructions and interprets rider responses into one of a small set of states (on track, confused, needs help)
- **Transit Data:** 511 SF Bay API or OC Bus GTFS feed for live vehicle position, scheduled stops, and route shape
- **Backend:** A deviation-detection service comparing live GPS to the expected route corridor, plus an escalation state machine implementing the tier table above
- **Escalation Channel:** Phone/SMS bridge (e.g., Twilio) to reach the Setup Companion and nonprofit dispatcher *(assumption: for the hackathon demo, the nonprofit contact is a mocked number, not a live partner integration)*

## 7. Success Criteria

**Qualitative**
- A rider persona can complete a full simulated trip using only voice and large single-tap actions, without reading more than one short sentence per screen
- A judge unfamiliar with the problem understands what Guardian does within two minutes of watching the demo

**Quantitative**
- Deviation is detected within the agreed buffer (e.g., under 2 minutes or 300 meters off the expected route) *(assumption: exact thresholds — confirm with team)*
- Full end-to-end demo (setup → ride → deviation → escalation call) completes in under 5 minutes

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| False positives trigger unnecessary escalations | Add a confirmation buffer at Tier 1 before moving to Tier 2; tune distance/time thresholds during testing |
| Live GTFS data is unreliable or missing for the demo transit agency | Prepare a pre-recorded or simulated GTFS feed as a fallback for the live demo |
| No real nonprofit partner is integrated in time | Mock the Tier 3 call/SMS with a real phone number the team controls, and say so plainly in the demo |
| Handling care-profile data (age, disability, condition) raises privacy concerns | Keep the profile minimal, rider/caregiver-entered only, stored only for the active trip, and never inferred by the AI |
| Scope is too large for the hackathon window | Narrow the live demo to one scripted route on one transit feed; treat multi-city support as a stated future direction, not a build target |
| Voice/LLM responses feel robotic or confusing to the exact users Guardian is meant to help | User-test the actual spoken scripts with a non-technical tester before the demo, not just with the team |

## 9. Open Questions

- Who is responsible if Guardian escalates incorrectly, or fails to escalate when it should have? (Not a build blocker for the hackathon, but worth naming out loud to judges.)
- What exactly defines "outside a certain range of route" — a fixed distance, a time buffer, or a count of missed stops? Needs one concrete definition before F3 can be built.
- Will the hackathon demo use a real nonprofit's contact info (with their prior consent) or a fully mocked one?
- Should the rider's care profile ever be required, or should Guardian work generically for any rider who wants a safety net, with the profile as an optional add-on?

---

## 10. Build Plan (Hackathon Mode)

*(Assumption: this plan assumes a roughly 24-hour hackathon format. Adjust the hour blocks if your event's timeline differs.)*

### Team Roles

| Role | Responsibility |
|---|---|
| Frontend/UX | Builds the simplified React UI: setup flow, live trip screen, Help button |
| AI/Voice Engineer | Wires up Whisper for speech input and prompts the LLM to generate plain-language instructions and interpret rider responses |
| Backend/Data Engineer | Integrates the GTFS feed, builds the deviation-detection logic and the escalation state machine |
| Demo/Pitch Lead | Owns the demo script, sets up the mocked nonprofit call, and rehearses the judge-facing pitch |

### Milestone Timeline

| Hours | Milestone |
|---|---|
| 0–2 | Finalize scope: one city, one scripted route, one rider persona. Lock the escalation buffer definitions. |
| 2–8 | Build core pieces in parallel: UI skeleton, GTFS pull, Whisper integration |
| 8–14 | Connect the pieces: live trip screen driven by real route data and voice output |
| 14–20 | Build and test the escalation flow end-to-end, including the mocked Tier 3 call |
| 20–23 | Rehearse the demo script at least twice, fix the rough edges |
| 23–24 | Buffer time and submission |

### Demo Script

1. **Set up a trip (30 sec):** Show the permission screen, select a rider profile, choose a real bus route on the live map.
2. **Normal ride (30 sec):** Voice calmly narrates progress ("Riding the 55 toward Downtown, three stops to go").
3. **Injected deviation (60 sec):** Simulate the rider getting off at the wrong stop. Show the Tier 1 spoken redirect.
4. **Escalation (60 sec):** Simulate no response to the Tier 1 nudge. Show the Tier 2 check-in fail, then the Tier 3 call to the nonprofit dispatcher — let the judges hear the phone actually ring.
5. **Close (30 sec):** State the thesis directly: this replaces a static map with an active companion, for the riders a map alone was never enough for.

### Minimum Viable Demo vs. Full Demo

| | Minimum Viable Demo | Full Demo |
|---|---|---|
| Route data | One hardcoded route, real GTFS shape | Live GTFS feed, selectable routes |
| Voice | Pre-scripted TTS instructions | LLM-generated instructions in 2+ languages via Whisper |
| Deviation detection | Manually triggered for the demo | Detected automatically from live/simulated GPS |
| Escalation | Tier 3 only, triggered by the Help button | All three tiers, triggered automatically |
| Nonprofit contact | Mocked phone number the team controls | Same, clearly labeled as mocked to judges |

---

**Want me to expand any section, adjust the escalation thresholds, or write the actual pitch deck version of this for judges?**
