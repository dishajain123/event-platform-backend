# GO-360° screenshot source transcription

Source: the five-phone GO-360° Goregaon promotional screenshot supplied by the user.
This is the source transcription. The user subsequently clarified that topic labels such as Sports, Business and Networking are sub-categories; see go360_data.py and README.md for the implemented mapping.
No event names below should receive a DEMO prefix in the new dataset.

Overall date: **23–29 December 2027**. Location: **Multiple Venues, Goregaon**.
Main category names use the spelling/case shown on the category screens.

| Main category | Visible event/initiative name | December 2027 dates | Visible venue/details |
|---|---|---|---|
| Corporate 360° | Corporate Cricket League | 24 | GSC Ground, Goregaon |
| Corporate 360° | Corporate Football League | 24 | Ground 2, Goregaon |
| Corporate 360° | Business Leadership Talk Series | 25 | The Fern, Goregaon |
| Corporate 360° | Startup Showcase & Innovation Zone | 26 | NESCO |
| Corporate 360° | Corporate Wellness Run & Fitness Challenge | 27 | Aarey Trail |
| Community 360° | Food & Beverage Festival | 23 | Goregaon (Main Venue) |
| Community 360° | Talent Hunt (Students & Youth) | 24 | Goregaon |
| Community 360° | Cultural Performances | 25 | Dance · Music · Art; Goregaon |
| Community 360° | Open Sports for All | 26 | (5-a-Side, Badminton, TT); Multiple Venues |
| Community 360° | Family Fun Zone | 27 | Kids Activities · Games; Goregaon |
| Contribute 360° | Tree Plantation Drive | 24 | Aarey, Goregaon |
| Contribute 360° | Blood Donation Camp | 25 | In association with Hospitals |
| Contribute 360° | Clean & Green Goregaon | 26 | Community Clean-Up |
| Contribute 360° | Education Support | 27 | Books for a Brighter Tomorrow |
| Contribute 360° | NGO Showcase | 23–27 | Meet & Support Local NGOs |
| GO-360° LIVE | GO-360° LIVE | 29 | Goregaon Live Arena |

## Navigation and descriptive text (not automatically taxonomy)

- Corporate 360° tagline: Business · Sports · Networking · Leadership.
  Tabs: Schedule, Sports, Business, Networking. Section: Event Schedule.
- Community 360° tagline: Culture · Food · Sports · Family · Youth.
  Tabs: Schedule, Competitions, Food, Culture. Section: Event Schedule.
- Contribute 360° tagline: Give Back · Social Impact · Community Development.
  Tabs: Initiatives, Volunteer, Donate, Partner. Section: Ongoing Initiatives.
- GO-360° LIVE tagline: Music · Entertainment · Global Experiences.
  Tabs: Lineup, Tickets, Experience, Info. Grand Finale – 29 December 2027.
  Detail rows:
  - Artist Lineup — To be announced
  - Ticket Information — Early Access & Passes
  - Event Experience — Music · Food · Entertainment; Fan Zones · Surprises
  - Getting There — Venue · Parking · Transport

## Information not supplied by this screenshot

Explicit sub-category records and event → sub-category assignments are not shown.
Tabs mix all-events navigation, topics and actions; treating every tab as a
sub-category would invent a hierarchy. The LIVE detail rows do not show separate
events. Start/end times, database status enums, fees, capacities, eligibility
rules and operational dummy records are not specified either.

## Existing database inspection

The configured database contains four active categories with manually generated
UUIDs: CORPORATE 360°, COMMUNITY 360°, CONTRIBUTE 360°, G360° LIVE. Corporate has
active Business, Networking (with trailing whitespace), and Sports sub-categories.
The three old deterministic DEMO events and their original categories are already
soft-deleted. These facts do not establish seed ownership of the manually created
categories; a reset must preserve unowned records and their references.

The former `seed_platform reset` implementation truncated every mapped table.
That implementation was not run on this mixed database. It has now been replaced with ownership-aware
reset logic in scripts/seed/ownership.py.
