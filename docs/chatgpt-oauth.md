# Continue with ChatGPT

Bishop implements the official public-client **Sign in with ChatGPT** flow directly. Bishop owns its agent loop; it does not launch Codex, read another application's credentials, borrow another application's client ID, or call ChatGPT backend endpoints.

First sign-in dynamically registers Bishop with OpenAI. A browser consent screen authorizes the account and returns Bishop's issued client ID. The callback listens only on `127.0.0.1` at `/auth/callback`, with a fresh random port. PKCE, state, nonce, issuer, audience, expiration and the ID-token signature are verified before credentials are saved. Returning sign-in keeps the saved account/client mapping. To connect a different account use a separate Bishop home; the current version deliberately rejects replacement by a different subject.

Credentials live in `HOME/auth/chatgpt.json`, written atomically with owner-only permissions. The stable host identifier survives logout. Token refresh is serialized across processes and persists rotating refresh tokens. Logout attempts remote revocation, clears local tokens, and reports whether revocation was confirmed. If revocation fails, disconnect Bishop in ChatGPT Settings.

OAuth inference uses `https://api.openai.com/v1/responses`, with `store:false` and `stream:true`. Bishop requires `response.completed` before accepting an answer; partial output or failed/incomplete streams are errors. Function calls and their results are mapped to Bishop's existing approval-aware loop. OAuth tokens can only be sent to the exact public OpenAI Responses endpoint. Tests replace the network opener; production does not allow loopback OAuth inference destinations. Encrypted reasoning continuation items and server-issued function IDs are retained in private run state and replayed across tool results.

Account eligibility, available models, plan authorization and limits are controlled by OpenAI. A successful browser login does not guarantee inference availability. Choose a model available to the signed-in account. No live sign-in or inference is performed by the offline tests.

Sources:

- [Registration and sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Accounts and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
- [ID-token verification](https://developers.openai.com/siwc/website)
