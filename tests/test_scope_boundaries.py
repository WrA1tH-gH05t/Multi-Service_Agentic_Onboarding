"""
test_scope_boundaries.py - Test Suite for DocIntake Project Scope Guardrails and Boundary Enforcement.

Verifies that:
1. Out-of-scope requests (e.g. gym plans, recipes, coding, trivia, medical advice) are strictly blocked.
2. Zero-trust fallback ensures queries with no DocIntake domain grounding are blocked.
3. In-scope queries (available services, catalog services, documents, status, architecture, policies) pass.
4. Ambiguous onboarding queries return NEEDS_CLARIFICATION.
5. Mixed-intent queries are flagged for DocIntake-only answering.
6. Post-generation output guardrail intercepts out-of-scope leakage (e.g. workout routines).
"""

import pytest
from services.scope_classifier import ScopeClassifier, OUT_OF_SCOPE_RESPONSE, is_out_of_scope_reply


class TestScopeBoundaries:
    """Tests verifying strict project scope enforcement."""

    # 1. The exact user case: "give me a gym plan"
    def test_gym_plan_strictly_out_of_scope(self):
        cat, reason, special = ScopeClassifier.classify("give me a gym plan")
        assert cat == "OUT_OF_SCOPE"
        assert special == OUT_OF_SCOPE_RESPONSE

    # 2. Fitness, Workout, and Diet variations
    @pytest.mark.parametrize("query", [
        "give me a workout routine",
        "workout plan for chest and triceps",
        "how many pushups should i do daily",
        "create a 4-day split routine for bodybuilding",
        "keto diet meal plan for weight loss",
        "how much protein should i eat per day",
        "exercises to relieve lower back pain",
    ])
    def test_fitness_and_health_queries_out_of_scope(self, query):
        cat, reason, special = ScopeClassifier.classify(query)
        assert cat == "OUT_OF_SCOPE"
        assert special == OUT_OF_SCOPE_RESPONSE

    # 3. Other diverse out-of-scope categories that must be blocked
    @pytest.mark.parametrize("query", [
        # Cooking / food
        "how to bake chocolate chip cookies",
        "recipe for chicken alfredo pasta",
        # Coding & general tech outside DocIntake
        "write a python script to web scrape a site",
        "how do i implement a binary search tree in java",
        "debug my react frontend code",
        # Math & academics
        "solve the equation 3x + 15 = 45",
        "explain the theory of general relativity",
        "what is photosynthesis",
        # Entertainment & sports
        "tell me a funny joke",
        "write a poem about the sunrise",
        "who won the 2022 fifa world cup",
        "what movies are in theaters right now",
        # Home & automotive repair
        "how to change the oil in a toyota camry",
        "how to fix a leaking sink pipe",
        # Travel & real estate
        "best hotels to stay in paris",
        "is it a good time to buy real estate in london",
        # Career
        "write a cover letter for a software engineer role",
        "how to ask my boss for a raise",
    ])
    def test_other_out_of_scope_categories_blocked(self, query):
        cat, reason, special = ScopeClassifier.classify(query)
        assert cat == "OUT_OF_SCOPE"
        assert special == OUT_OF_SCOPE_RESPONSE

    # 4. Zero-Trust Fallback: Arbitrary ungrounded queries must be blocked
    @pytest.mark.parametrize("query", [
        "what is the meaning of life",
        "can you suggest a good laptop to buy",
        "tell me something interesting",
        "recommend a book for weekend reading",
        "how tall is mount everest",
    ])
    def test_zero_trust_unanchored_queries_blocked(self, query):
        cat, reason, special = ScopeClassifier.classify(query)
        assert cat == "OUT_OF_SCOPE"
        assert special == OUT_OF_SCOPE_RESPONSE

    # 5. In-Scope queries that MUST pass
    @pytest.mark.parametrize("query", [
        # Basic greetings & identity
        "hello",
        "hi Lynx",
        "good morning",
        "who are you?",
        "what can you do?",
        "what is docintake?",
        "thank you very much",
        # Available services
        "What is Basic Registration?",
        "How long does Premium Cross-Border take?",
        "What are the requirements for mobility rental?",
        "I want to register for vehicle rental",
        # Coming-soon services in catalogue
        "Can I open a bank account?",
        "Do you provide SIM card registration?",
        "How does loan application work?",
        "I need a tenancy agreement verification",
        # Document requirements & rules
        "Can I use an expired passport?",
        "What documents do I need to upload?",
        "How do I submit my proof of address?",
        "What is the maximum file size for PDF upload?",
        # Application tracking
        "Where can I check my application status?",
        "What happens if my application needs human review?",
        # DocIntake technical architecture
        "What database does DocIntake use?",
        "How does DocIntake process uploaded PDFs?",
        "Does DocIntake use FastAPI and PostgreSQL?",
        # Policies
        "What is your privacy policy?",
        "Where can I read the terms and conditions?",
    ])
    def test_in_scope_queries_pass(self, query):
        cat, reason, special = ScopeClassifier.classify(query)
        assert cat == "IN_SCOPE"

    # 6. Ambiguous onboarding queries requiring clarification
    @pytest.mark.parametrize("query", [
        "I want to apply",
        "help me apply",
        "i need help",
        "can you help me with my documents",
        "how does this work",
    ])
    def test_ambiguous_queries_trigger_clarification(self, query):
        cat, reason, special = ScopeClassifier.classify(query)
        assert cat == "NEEDS_CLARIFICATION"

    # 7. Mixed-intent queries
    def test_mixed_intent_flagged(self):
        cat, reason, special = ScopeClassifier.classify(
            "How does DocIntake store documents, and give me a gym plan"
        )
        assert cat == "IN_SCOPE"
        assert special == "MIXED_INTENT"

    # 8. Post-generation output guardrail
    def test_output_guardrail_catches_workout_plan(self):
        sample_workout_reply = (
            "I can help you with a basic gym plan. Here's a simple 4-day split routine:\n"
            "**Day 1: Lower Body**\n"
            "- Squats: 3 sets of 12 reps\n"
            "- Deadlifts: 3 sets of 10 reps\n"
            "- Lunges: 3 sets of 12 reps each leg\n"
            "**Day 2: Upper Body**\n"
            "- Bench Press: 3 sets of 8 reps\n"
            "- Dumbbell Rows: 3 sets of 12 reps\n"
            "Remember to warm up before each workout."
        )
        assert is_out_of_scope_reply(sample_workout_reply) is True

    def test_output_guardrail_catches_recipe(self):
        sample_recipe = (
            "Here is the recipe: Ingredients: 2 cups flour, 1 cup sugar. "
            "Preheat the oven to 350F and bake for 25 minutes."
        )
        assert is_out_of_scope_reply(sample_recipe) is True

    def test_output_guardrail_allows_legitimate_reply(self):
        docintake_reply = (
            "Basic Registration is an onboarding service requiring a National ID card "
            "and proof of address. Processing takes 1-2 business days."
        )
        assert is_out_of_scope_reply(docintake_reply) is False
