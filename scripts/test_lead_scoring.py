import asyncio
from dotenv import load_dotenv

load_dotenv()

from agent.services.lead_observer import heuristic_extract, llm_extract_fields
from agent.services.summarizer import generate_call_summary
from agent.state import CallState


async def main():
    # Case 1: Full BANT turn (deterministic heuristic)
    s1 = CallState(room_name="test-1")
    text = "Hi Aria, my name is Zaheed. I'm a final-year CS engineer looking to join the Voice AI Fellowship next month. I'm comfortable with monthly EMI."
    s1.append_turn("user", text)
    s1.merge_extracted_fields(heuristic_extract(text))
    print(f"Case 1 (Heuristic BANT): {s1.lead_score}/100 ({s1.lead_tier}) | role={s1.current_role} | course={s1.target_course} | tl={s1.timeline} | bg={s1.budget_comfort}")
    assert s1.lead_score >= 85 and s1.lead_tier == "Hot", f"Expected Hot >=85, got {s1.lead_score}"

    # Case 2: Direct-to-booking (previously capped at 25/100 Cold!)
    s2 = CallState(room_name="test-2")
    s2.lead_name = "Zaheed"
    s2.lead_email = "zaheed@example.com"
    s2.booking_status = "Confirmed"
    score, tier = s2.compute_lead_score()
    print(f"Case 2 (Direct Booking): {score}/100 ({tier})")
    assert score >= 80 and tier == "Hot", f"Expected Hot >=80 on confirmed booking, got {score}"

    # Case 3: Partial / Warm lead
    s3 = CallState(room_name="test-3")
    s3.merge_extracted_fields({"lead_name": "Rohan", "current_role": "Software Engineer", "target_course": "Cloud & DevOps"})
    print(f"Case 3 (Partial Lead):   {s3.lead_score}/100 ({s3.lead_tier})")
    assert 40 <= s3.lead_score < 70 and s3.lead_tier == "Warm", f"Expected Warm, got {s3.lead_score}"

    # Case 4: Live LLM Observer extraction (OpenAI) + Summarizer backfill
    s4 = CallState(room_name="test-4")
    s4.append_turn("user", "Hey, I am Priya, working as a backend developer. Interested in your Cloud and DevOps bootcamp starting next batch, and no-cost EMI works great. My email is priya@test.com.")
    extracted = await llm_extract_fields(s4)
    s4.merge_extracted_fields(extracted)
    print(f"Case 4 (Live LLM):       {s4.lead_score}/100 ({s4.lead_tier}) | extracted={extracted}")
    assert s4.lead_score >= 85 and s4.lead_tier == "Hot", f"Expected Hot >=85 from LLM, got {s4.lead_score}"

    # Case 5: Live LLM Observer extraction under OpenAI Outage (Groq Failover)
    s5 = CallState(room_name="test-5", openai_killed=True)
    s5.append_turn("user", "I'm Kabir, a college student wanting the Full-Stack GenAI cohort this month, monthly installments are fine.")
    extracted_groq = await llm_extract_fields(s5)
    s5.merge_extracted_fields(extracted_groq)
    await generate_call_summary(s5)
    print(f"Case 5 (Groq Failover):  {s5.lead_score}/100 ({s5.lead_tier}) | summary={s5.summary[:80]}...")
    assert s5.lead_score >= 70 and s5.lead_tier == "Hot", f"Expected Hot >=70 on Groq failover, got {s5.lead_score}"

    print("\nALL 5 LEAD SCORING TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
