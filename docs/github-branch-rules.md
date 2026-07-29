# GitHub Branch Rules

This repository should keep `main` protected with a solo-contributor SaaS workflow:

- require all changes to land through pull requests
- require the `sdk-tests` status check to pass before merge
- require branches to be up to date before merge
- require conversation resolution before merge
- require linear history
- block force pushes and branch deletion
- apply the same rules to admins

No approving review is required while this is a single-contributor repository. GitHub does not count a pull request author's own approval toward required approvals, so setting a one-review requirement would block solo merges.

Apply the rules with:

```bash
scripts/apply_github_branch_rules.sh
```

GitHub currently requires an eligible plan for branch protection on private repositories. If the API returns `HTTP 403` with an upgrade message, either upgrade the GitHub account/organization plan or make the repository public, then rerun the script.
