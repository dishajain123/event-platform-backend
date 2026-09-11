"""Screenshot transcription. Topic-to-event mapping follows the user's clarification."""
CATEGORIES = {
    'Corporate 360°': ['Sports', 'Business', 'Networking'],
    'Community 360°': ['Competitions', 'Food', 'Culture', 'Sports', 'Family', 'Youth'],
    'Contribute 360°': ['Give Back', 'Social Impact', 'Community Development'],
    'GO-360° LIVE': ['Music', 'Entertainment', 'Global Experiences'],
}
# key, category, topic, visible name, first day, last day, visible location/details
EVENTS = [
 ('cricket', 'Corporate 360°', 'Sports', 'Corporate Cricket League', 24, 24, 'GSC Ground, Goregaon'),
 ('football', 'Corporate 360°', 'Sports', 'Corporate Football League', 24, 24, 'Ground 2, Goregaon'),
 ('leadership', 'Corporate 360°', 'Business', 'Business Leadership Talk Series', 25, 25, 'The Fern, Goregaon'),
 ('startup', 'Corporate 360°', 'Networking', 'Startup Showcase & Innovation Zone', 26, 26, 'NESCO'),
 ('wellness', 'Corporate 360°', 'Sports', 'Corporate Wellness Run & Fitness Challenge', 27, 27, 'Aarey Trail'),
 ('food', 'Community 360°', 'Food', 'Food & Beverage Festival', 23, 23, 'Goregaon (Main Venue)'),
 ('talent', 'Community 360°', 'Competitions', 'Talent Hunt (Students & Youth)', 24, 24, 'Goregaon'),
 ('culture', 'Community 360°', 'Culture', 'Cultural Performances', 25, 25, 'Dance · Music · Art; Goregaon'),
 ('open-sports', 'Community 360°', 'Sports', 'Open Sports for All', 26, 26, '(5-a-Side, Badminton, TT); Multiple Venues'),
 ('family', 'Community 360°', 'Family', 'Family Fun Zone', 27, 27, 'Kids Activities · Games; Goregaon'),
 ('plantation', 'Contribute 360°', 'Community Development', 'Tree Plantation Drive', 24, 24, 'Aarey, Goregaon'),
 ('blood', 'Contribute 360°', 'Social Impact', 'Blood Donation Camp', 25, 25, 'In association with Hospitals'),
 ('clean', 'Contribute 360°', 'Community Development', 'Clean & Green Goregaon', 26, 26, 'Community Clean-Up'),
 ('education', 'Contribute 360°', 'Give Back', 'Education Support', 27, 27, 'Books for a Brighter Tomorrow'),
 ('ngo', 'Contribute 360°', 'Social Impact', 'NGO Showcase', 23, 27, 'Meet & Support Local NGOs'),
 ('live', 'GO-360° LIVE', 'Music', 'GO-360° LIVE', 29, 29, 'Goregaon Live Arena'),
]
LIVE_DETAILS = {
 'Artist Lineup': 'To be announced',
 'Ticket Information': 'Early Access & Passes',
 'Event Experience': 'Music · Food · Entertainment; Fan Zones · Surprises',
 'Getting There': 'Venue · Parking · Transport',
}
