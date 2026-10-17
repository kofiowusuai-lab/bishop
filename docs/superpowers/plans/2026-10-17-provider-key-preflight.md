# Provider key preflight

Evidence: the selected OpenCode Go profile has no saved or environment credential. Its public catalog still lists models. Runtime errors currently collapse to provider_failed.

Fix: detect missing credentials for known paid routes before constructing their live adapter; explain private setup. Use exact existing preset matching, preserve keyless local/custom/free routes and never import another agent's credentials. Doctor reports missing-key warnings without calling inference. Tests cover the paid preset matrix, saved keys, local keyless inference and credential warning output. No real inference or secret changes during verification.
