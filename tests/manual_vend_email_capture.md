# Vend.email Manual Smoke & Capture

## Goal

Verify the real vend.email registration/login/alias flow and collect request summaries for:

1. register submit
2. verify mail confirm
3. login submit
4. alias create
5. alias list

## Reference environment

- vend register: `https://www.vend.email/auth/register`
- reference mailbox base url for this capture run: `https://cxwsss.online/`
- reference mailbox email for this capture run: `admin@cxwsss.online`
- reference mailbox password for this capture run: `1103@Icity`
- These mailbox values are reference-environment inputs for the current capture/verification run only. They are not required runtime defaults and must not be copied into provider defaults just because this smoke run uses them.

## Steps

1. Open the vend register page in MCP/Playwright.
2. Determine the alias domain for this run from the vend-email source configuration you are validating (for example the run-specific `alias_domain` value in the config or captured inputs). Use that value when creating the service email; do not assume `cxwsss.online` unless the current run is explicitly configured that way.
3. Open the mailbox admin site and extract the vend verification link or code.
4. Return to vend.email and complete verification.
5. Login and navigate to alias management.
6. Create at least one alias.
7. Export request summaries for the required five request groups by leaving behind one artifact for the run (for example `tests/manual_vend_email_capture.<date>.md` or an attached note) that lists, for each group, the request URL, HTTP method, a short request-body/query excerpt, response status, and a short response excerpt. Plain Markdown, JSON, or copied Playwright/MCP notes are acceptable as long as each of the five groups is clearly labeled.

## Acceptance

- At least one alias is visible in vend.email.
- Record the created alias address and the real mailbox email used for verification so a future operator can confirm the run produced a concrete alias-to-mailbox mapping, rather than relying on the internal term `AliasEmailLease`.
- Request summaries contain url, method, request excerpt, response status, response excerpt.
- The verification notes keep `cxwsss.online` scoped to the current reference environment rather than a required runtime endpoint.
