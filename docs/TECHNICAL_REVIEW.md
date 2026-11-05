# Guide for a prospective technical cofounder

Run the README walkthrough and `tools/check_repo.py`. Read `interaction.js`, `fixture_service.py` and their tests before evaluating optional camera work. This is evidence of a narrow software interaction; the complete historical product is not built.

## Useful review questions

1. Are selection, cancellation, input loss and confirmation represented clearly enough to extend?
2. Which guards should be shared across transports? Which differences matter before real integrations?
3. For the first user/task, is webcam gaze useful to test, or should a supported dedicated tracker be used?
4. How should viewport mapping, drift, head motion and accidental selections be measured?
5. What should be simplified before involving real users?

## First engineering milestone

Agree one target task and one device. Run a bounded real-input experiment with these same synthetic messages and a mouse/keyboard baseline. Record calibration failures as well as successes, selection errors, accidental drafts, completion time, cancellations, tracking loss and perceived effort. Keep explicit confirmation and no real message delivery. Define acceptance thresholds with the intended user before measuring; the existing calibration rejection gate is not a proven usability threshold.

Deliver reproducible setup, a test protocol, failure logs, measured results and a recommendation to continue, change hardware or stop that approach. See `CAMERA_VALIDATION.txt` and `FIRST_USER_TEST_PLAN.txt`. Formative testing does not establish clinical efficacy, demand or production readiness.

## Limits to discuss

- No physical camera/glasses validation, live AI, SMS/email, Maps or released SDK.
- One unauthenticated local coordinate producer; shared relay to UI tabs.
- No production deployment, authentication, persistence or integration security design.
- Browser and Python fixtures are distinct implementations with different simulated timing and acknowledgement metadata.
- Windows/macOS start scripts are supplied but execution here is Linux; platform checks remain to be run.
- Contributor assignments, current commitments and company/equity records require owner confirmation.

The founder can use the interaction to explain product intent, user hypotheses, requirements and QA observations. Judge the code directly; this recovery does not establish individual authorship of every historical module.
