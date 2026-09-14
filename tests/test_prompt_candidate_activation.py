def test_scheduler_installs_prompt_candidate_policy():
    import app.intraday_engine as intraday_engine
    import app.prompt_candidate_policy as policy
    import app.scheduler  # noqa: F401

    assert intraday_engine.build_candidates is policy.build_prompt_candidates
