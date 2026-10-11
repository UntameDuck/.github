# UntameDuck Contribution Ocean — event-driven updates

The public organization profile at [UntameDuck](https://github.com/UntameDuck) renders transparent light and dark SVGs from `profile/assets/`.

## How it works

1. An UntameDuck repository receives a push on **its default branch** (`main` or `master`).
2. Its `.github/workflows/notify-contributions.yml` workflow sends a GitHub `repository_dispatch` event (`organization-commit`) to `UntameDuck/.github`.
3. The central `.github/workflows/update-contributions.yml` rebuilds both SVGs using only UntameDuck public repository default-branch commits; .github is excluded.
4. The fallback daily schedule stays enabled at **00:13 KST**, and manual runs remain available.

**A cross-repository credential is required before step 2 can send events.** Until it is configured, the notifier logs a warning and exits successfully. The daily fallback remains operational.

## One-time credential setup (organization owner)

1. Create a **fine-grained personal access token** at https://github.com/settings/personal-access-tokens/new. Choose resource owner `UntameDuck` (if offered), repository access **Only select repositories → `.github`**, and repository permission **Contents: Read and write**. No other repository write permission is needed. Organization token approval may be required. Give the token a limited lifetime and plan to rotate it.
2. Visit https://github.com/organizations/UntameDuck/settings/secrets/actions → **New organization secret**. Name it exactly `UNTAMEDUCK_PROFILE_DISPATCH_TOKEN`; paste the token. Under **Repository access**, select the 12 nonempty project repositories with installed notifier workflows, rather than `.github`. (Alternatively, allow all repositories if new repositories should inherit the secret automatically, while weighing the larger exposure.)
3. Test using **Actions → Notify UntameDuck Contribution Ocean → Run workflow** in one of those project repositories, choosing its default branch.
4. Confirm that the notifier log has no `Missing organization secret` warning and that the central workflow in https://github.com/UntameDuck/.github/actions reports a new `repository_dispatch` run. SVG changes are committed only if the generated content differs.
5. If the sender gets 401/403/404, recheck that the token belongs to/has access to the UntameDuck organization, is approved if necessary, has **Contents: write on `.github`**, and has not expired.

Never commit the token to any repository or paste it into an issue, log, or README.

## Newly created repositories

To enable immediate refresh in a new repository, install the organization workflow template **Notify UntameDuck Contribution Ocean** in its Actions tab. It corresponds to `workflow-templates/notify-contributions.yml` here. Ensure the new repository has access to the organization secret; if using selected-repository access, add that repository. An initially empty repository such as `Alphase` needs initialization before installing the workflow.

Repositories without the notifier are **still included** in the daily aggregated public-commit graph once they contain a default-branch commit, but they cannot cause immediate event-triggered refresh.

## What is counted

- Public repositories owned by UntameDuck, except `.github`, forks, archived, disabled and empty repositories.
- All human committers' commits reachable through each repository's **default branch** in the last 365 days, grouped by the KST date of the commit's committer timestamp.
- Bot accounts are excluded. Other branches count once merged/reachable from the default branch.
- The chart may take some time to update visually due to GitHub's image caching and workflow queueing.

See `scripts/generate_contributions.py` for the exact aggregation rules.
