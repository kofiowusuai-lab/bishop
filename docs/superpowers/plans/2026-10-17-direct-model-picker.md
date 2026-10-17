# Direct model picker fix

Problem: bishop model opened saved-provider selection, making a single saved provider look like a single available model.

Implementation: introduce select_model to open the active provider catalog directly, reuse the existing validated model/key save flow, and retain provider switching under bishop providers select. Interactive /model follows the direct catalog flow too. Cancellation preserves the selected model and credentials; ChatGPT uses its own home-bound account catalog.

Validation: regressions exercise direct selection without provider/action menus, cancellation, saved-key retention and ChatGPT account catalog selection. Existing onboarding and shell behavior is reviewed independently. Full suite, package build and hosted CI gate publishing.
