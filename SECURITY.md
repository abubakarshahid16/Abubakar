# Security policy

Nabaa processes client engineering documentation. The security posture is
therefore about **containment** first and vulnerabilities second: the worst
outcome for this project is not a crash, it is a page of a client's
specification leaving the machine it was uploaded to.

## The boundary

**Client document content never leaves the machine it was uploaded to.**

| Allowed to cross the network | Never crosses the network |
|---|---|
| Model weights, pip and npm packages | Document text, extracted pages, chunks |
| GitHub, CI, documentation | Questions asked of the corpus |
| Telemetry that carries no document content | Answers, citations, quoted passages |

This is **not** an air-gapped system. It is a **locally-inferencing system on a
networked machine**, and the distinction is stated rather than glossed because
a reader who assumes air-gap will make decisions this project does not support.

### How the boundary is enforced

| Mechanism | Where |
|---|---|
| Server binds loopback only, never `0.0.0.0` | `backend/app/config.py` |
| CORS restricted to the local dev origin | `backend/app/main.py` |
| `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` after setup | startup |
| All inference local — embeddings, reranking, generation | no hosted APIs |
| A CI job fails the build if client data appears in a commit | `.github/workflows` |
| Secret scanning on every push | `.gitleaks.toml` |

There is no hosted inference API, no cloud OCR, and no hosted vector database
anywhere in the dependency tree. Removing one would be a breaking change to
the product's central claim, not an implementation detail.

## Reporting a vulnerability

Open a private security advisory on the repository, or contact the maintainer
directly. Please do not open a public issue for a vulnerability that could
expose document content.

Include what you did, what happened, and what you expected. A reproduction is
worth more than a description; a reproduction that does not require client
documents is worth more still.

Expect an acknowledgement within a few working days. If a report is valid and
concerns the containment boundary above, it takes priority over feature work.

## Scope

**In scope**

- Anything that causes document content to leave the machine
- Anything that exposes the API beyond loopback
- Path traversal, or writing outside the configured upload directory
- Denial of service through the upload path
- Retrieved document text being treated as instructions to the model
- A previous answer being treated as evidence for the next one

**Out of scope**

- An attacker who already has interactive access to the machine. The threat
  model assumes the operator is trusted; the system protects documents from
  the network, not from their owner.
- The Ollama instance on localhost, which is a separate program with its own
  security posture.
- Findings that depend on running the server bound to a non-loopback address,
  which the configuration does not do and the code comments forbid.

## Known limitations that are not vulnerabilities

Documented in `docs/limitations.md` and recorded honestly rather than hidden.
Of note for a security reader:

- Retrieved PDF text is treated as **untrusted data**, never as instructions.
  This is a design rule, and a report demonstrating a case where it does not
  hold is in scope.
- Answers can be wrong. The system cites a page for every claim and refuses
  when evidence is weak, but a refusal is a mitigation, not a guarantee.
- **Custody of `AUTH_SECRET` is the authentication boundary.** Bearer tokens are
  HMAC-signed with that key and carry a user id, so anyone holding the key can
  mint a valid session for any user without knowing a password. This is how
  signed tokens work and it is correct by design — there is no session table to
  consult, which is what lets the backend stay stateless — but it means the file
  holding the key is as sensitive as every password in the system combined.
  `backend/.env` is gitignored and must stay that way; a leaked key is a full
  authentication bypass and the remedy is to replace the key, which invalidates
  every issued token. A report that the key is recoverable from a log, a
  response body, a screenshot or a committed file is in scope.
