# Public Release Checklist

- [x] Current-tree secret and privacy scan
- [x] Historical secret and privacy scan
- [x] Commit author email review
- [x] Current-tree proprietary/binary scan
- [x] Historical proprietary/binary scan
- [x] Submodule and license review
- [x] Third-party documentation
- [ ] Root project license decision
- [x] Deterministic tests
- [x] `pip check`
- [x] App launch smoke test
- [ ] Worktree clean
- [x] History rewrite required: YES
- [ ] Safe to switch GitHub visibility: NO

Current blocker: reachable commits expose a potentially personal author and
committer email address. Removing it would require coordinated history
rewriting and a force-push, which has not been authorized.
