# karate parallel runs

Karate suite was slow (40 min). Switched runner to Runner.path("classpath:features").parallel(6). Now 9 min on GitLab runner.
Gotcha: features that share the same test customer collide in parallel. Tag them @serial and run them in a separate job.
Decision: max 6 threads, because the SIT payments stub rate-limits above ~8 concurrent calls.
