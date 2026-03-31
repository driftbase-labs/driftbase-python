"""
50 customer support scenarios for the Swiss Airlines agent.

Designed to exercise all 18 tools across realistic customer interactions.
Categories match the tutorial's tool groupings: flights, hotels, cars,
excursions, policy, and mixed (multi-tool) queries.
"""

SCENARIOS = [
    # --- FLIGHT QUERIES (12) ---
    {"query": "Can you show me my current flight bookings?", "category": "flights"},
    {
        "query": "I need to find a flight from Zurich to Paris next Friday.",
        "category": "flights",
    },
    {
        "query": "What flights are available from Geneva to London this weekend?",
        "category": "flights",
    },
    {
        "query": "I'd like to change my flight to an earlier departure. Can you search for alternatives?",
        "category": "flights",
    },
    {"query": "Please cancel my ticket 0005432661234.", "category": "flights"},
    {
        "query": "Find me a business class flight from Basel to Barcelona in the next two weeks.",
        "category": "flights",
    },
    {
        "query": "I want to switch my return flight to a day earlier. My ticket is 0005432661235.",
        "category": "flights",
    },
    {
        "query": "Are there any direct flights from Zurich to New York next month?",
        "category": "flights",
    },
    {
        "query": "What's the cheapest flight from Geneva to Rome next week?",
        "category": "flights",
    },
    {
        "query": "My flight LX 318 — can you confirm the departure time and seat?",
        "category": "flights",
    },
    {
        "query": "I missed my connection. What are my rebooking options?",
        "category": "flights",
    },
    {
        "query": "Search for flights from Zurich to Amsterdam departing tomorrow morning.",
        "category": "flights",
    },
    # --- HOTEL QUERIES (8) ---
    {
        "query": "I need a hotel near Charles de Gaulle airport for one night.",
        "category": "hotels",
    },
    {
        "query": "Find me a luxury hotel in central Paris for 3 nights starting December 20.",
        "category": "hotels",
    },
    {"query": "Can you book hotel 42 for me?", "category": "hotels"},
    {
        "query": "I need to change my hotel dates — push checkout back one day.",
        "category": "hotels",
    },
    {"query": "Please cancel my hotel booking.", "category": "hotels"},
    {
        "query": "What hotels do you recommend near Zurich main station?",
        "category": "hotels",
    },
    {
        "query": "I'm looking for a budget hotel in Geneva with breakfast included.",
        "category": "hotels",
    },
    {
        "query": "Find a hotel with a pool in Barcelona for a family of four.",
        "category": "hotels",
    },
    # --- CAR RENTAL QUERIES (6) ---
    {"query": "I need a rental car at Zurich airport for 5 days.", "category": "cars"},
    {"query": "Search for premium car rentals in Geneva.", "category": "cars"},
    {"query": "Book car rental 15 for me please.", "category": "cars"},
    {"query": "I need to extend my car rental by 2 days.", "category": "cars"},
    {"query": "Cancel my car rental booking.", "category": "cars"},
    {
        "query": "What's available for a one-way rental from Zurich to Milan?",
        "category": "cars",
    },
    # --- EXCURSION QUERIES (6) ---
    {
        "query": "What activities or excursions do you recommend in the Zurich area?",
        "category": "excursions",
    },
    {
        "query": "I'm interested in a chocolate factory tour. What's available?",
        "category": "excursions",
    },
    {"query": "Book excursion 7 for me.", "category": "excursions"},
    {
        "query": "I need to change my excursion booking to a different date.",
        "category": "excursions",
    },
    {"query": "Please cancel my excursion booking.", "category": "excursions"},
    {
        "query": "What outdoor activities are available near Interlaken?",
        "category": "excursions",
    },
    # --- POLICY QUERIES (10) ---
    {"query": "What's the baggage allowance for economy class?", "category": "policy"},
    {
        "query": "What's your refund policy for non-refundable tickets?",
        "category": "policy",
    },
    {"query": "Can I bring my small dog on the flight?", "category": "policy"},
    {
        "query": "What compensation am I entitled to for a 4-hour delay?",
        "category": "policy",
    },
    {"query": "How do I upgrade from economy to business class?", "category": "policy"},
    {"query": "What are the rules for traveling with an infant?", "category": "policy"},
    {
        "query": "Is wifi available on European flights? How much does it cost?",
        "category": "policy",
    },
    {
        "query": "I need wheelchair assistance at the airport. How do I arrange that?",
        "category": "policy",
    },
    {
        "query": "Can I bring my own food on the plane? I have celiac disease.",
        "category": "policy",
    },
    {
        "query": "Do I need a transit visa to connect through Zurich?",
        "category": "policy",
    },
    # --- MIXED / MULTI-TOOL QUERIES (8) ---
    {
        "query": "I'm flying to Paris next week. Can you find me a flight AND a hotel near the Eiffel Tower?",
        "category": "mixed",
    },
    {
        "query": "I want to plan a full trip: flight from Zurich to Barcelona, hotel, and a rental car.",
        "category": "mixed",
    },
    {
        "query": "My flight was delayed 5 hours. What compensation can I get, and can you rebook me on the next available flight?",
        "category": "mixed",
    },
    {
        "query": "Cancel my entire trip — flight, hotel, and car rental. I want refunds for everything.",
        "category": "mixed",
    },
    {
        "query": "I'm arriving in Zurich next Monday. I need a hotel, a rental car, and some activity recommendations.",
        "category": "mixed",
    },
    {
        "query": "What's the baggage policy, and also can you check if there are flights from Zurich to Lisbon next month?",
        "category": "mixed",
    },
    {
        "query": "I want to extend my stay in Paris by 2 days. Can you update my return flight and hotel?",
        "category": "mixed",
    },
    {
        "query": "I need to know the pet policy, and then search for flights that allow pets from Geneva to Berlin.",
        "category": "mixed",
    },
]


def get_scenarios(limit: int | None = None) -> list[dict]:
    """Return scenarios, optionally limited to first N."""
    if limit:
        return SCENARIOS[:limit]
    return SCENARIOS
