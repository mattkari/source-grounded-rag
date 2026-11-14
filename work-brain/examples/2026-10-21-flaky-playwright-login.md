# flaky playwright login

Playwright login test fails ~1 in 10 on CI only. Cause: SSO redirect finishes after page.waitForLoadState('load').
Fix: wait for the dashboard locator instead: page.locator("[data-test=dashboard]").waitFor(). No more flakes in 50 runs.
Related to the Karate work: same SIT environment, mornings are worst because of the batch job at 08:00.
