# Conversation colour refinement

Use distinct roles: cyan user input, warm gold Bishop replies, grey system/progress, amber approvals and coral errors. Sanitize model text before adding trusted colour sequences. Colour only TTY output; respect NO_COLOR and --no-color. Keep typed input cyan through the prompt, resetting after input/EOF/errors; zero-width readline markers preserve editing geometry. Verify role distinctions, plain output, sanitization and an actual interactive PTY.
