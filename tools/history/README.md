# Historical release tooling

Files in this directory are retained only to reproduce or audit previously
published releases. They are version-specific and are not current release
builders.

- `build_v0_1_0_beta_2_package.ps1` reconstructs the historical
  `v0.1.0-beta.2` package boundary from its exact validated binary inputs.

Current source releases are published from the validated Git tag/source tree;
the no-Conda portable distribution remains deliberately deferred.
